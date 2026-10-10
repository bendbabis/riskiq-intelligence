"""SQL-backed state and artifacts. SQLite local; PostgreSQL via SQLAlchemy optional.
Audit entries are HMAC-chained, not a claim of WORM or regulator certification.
"""
import json
import gzip
import hashlib
import hmac
import time
import uuid
from contextlib import contextmanager
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Integer, Text, Float,
                        LargeBinary, Boolean, ForeignKey, UniqueConstraint, select, insert, update, delete, event)
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from .config import Settings

metadata=MetaData()
tenants=Table("tenants",metadata,Column("id",String(40),primary_key=True),Column("counter",Integer,nullable=False,default=0))
users=Table("users",metadata,Column("id",String(36),primary_key=True),Column("tenant",String(40),ForeignKey("tenants.id"),nullable=False),
    Column("email",String(200),nullable=False),Column("password",Text,nullable=False),Column("role",String(20),nullable=False),
    Column("active",Boolean,nullable=False,default=True),UniqueConstraint("tenant","email"))
sessions=Table("sessions",metadata,Column("id",String(64),primary_key=True),Column("user_id",String(36),ForeignKey("users.id"),nullable=False),
    Column("csrf",String(64),nullable=False),Column("expires",Float,nullable=False))
resources=Table("resources",metadata,Column("id",String(36),primary_key=True),Column("tenant",String(40),ForeignKey("tenants.id"),nullable=False,index=True),
    Column("kind",String(30),nullable=False,index=True),Column("name",String(150),nullable=False),Column("owner",String(36),nullable=False),
    Column("created",Float,nullable=False),Column("body",Text,nullable=False),Column("blob",LargeBinary),Column("digest",String(64),nullable=False))
runs=Table("runs",metadata,Column("id",String(36),primary_key=True),Column("tenant",String(40),ForeignKey("tenants.id"),nullable=False,index=True),
    Column("owner",String(36),nullable=False),Column("name",String(150),nullable=False),Column("created",Float,nullable=False),
    Column("updated",Float,nullable=False),Column("status",String(40),nullable=False,index=True),Column("step",Integer,nullable=False),
    Column("lease_until",Float,nullable=False,default=0),Column("lease_token",String(36)),Column("spec",Text,nullable=False),Column("result",Text,nullable=False),
    Column("error",Text),Column("idempotency",String(100),nullable=False),Column("request_hash",String(64),nullable=False),
    UniqueConstraint("tenant","idempotency"))
audit=Table("audit_events",metadata,Column("tenant",String(40),ForeignKey("tenants.id"),primary_key=True),Column("seq",Integer,primary_key=True),
    Column("created",Float,nullable=False),Column("actor",String(100),nullable=False),Column("action",String(80),nullable=False),
    Column("resource_id",String(80),nullable=False),Column("detail",Text,nullable=False),Column("previous",String(64),nullable=False),Column("digest",String(64),nullable=False))
login_attempts=Table("login_attempts",metadata,Column("key",String(64),primary_key=True),Column("count",Integer,nullable=False),Column("since",Float,nullable=False))

ph=PasswordHasher(time_cost=2,memory_cost=19456,parallelism=1)
DUMMY_HASH=ph.hash("not-a-real-account-password")

def dumps(obj): return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def digest(obj): return hashlib.sha256(dumps(obj).encode()).hexdigest()
def uid(): return str(uuid.uuid4())
def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()

class Store:
    def __init__(self,settings:Settings):
        self.settings=settings
        kw={"check_same_thread":False,"timeout":30} if settings.database_url.startswith("sqlite") else {}
        self.engine=create_engine(settings.database_url,connect_args=kw,pool_pre_ping=True)
        if settings.database_url.startswith("sqlite"):
            @event.listens_for(self.engine,"connect")
            def pragmas(dbapi,record):
                cur=dbapi.cursor(); cur.execute("PRAGMA foreign_keys=ON"); cur.execute("PRAGMA journal_mode=WAL"); cur.close()
        metadata.create_all(self.engine)
    @contextmanager
    def tx(self):
        with self.engine.connect() as c:
            if self.engine.dialect.name=="sqlite": c.exec_driver_sql("BEGIN IMMEDIATE")
            else: c.begin()
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback(); raise
    def log(self,c,tenant,actor,action,rid,detail):
        # UPDATE locks the tenant row, serialising sequence assignment across workers.
        c.execute(update(tenants).where(tenants.c.id==tenant).values(counter=tenants.c.counter+1))
        seq=c.execute(select(tenants.c.counter).where(tenants.c.id==tenant)).scalar_one()
        prev=c.execute(select(audit.c.digest).where(audit.c.tenant==tenant).order_by(audit.c.seq.desc()).limit(1)).scalar_one_or_none() or "0"*64
        rec={"tenant":tenant,"seq":seq,"created":time.time(),"actor":actor,"action":action,"resource_id":rid,"detail":dumps(detail),"previous":prev}
        rec["digest"]=hmac.new(self.settings.audit_key.encode(),dumps(rec).encode(),hashlib.sha256).hexdigest()
        c.execute(insert(audit).values(**rec))
    def bootstrap(self,tenant,email,password,role="admin",actor=None):
        if len(password)<12: raise ValueError("Password must contain at least 12 characters")
        with self.tx() as c:
            if not c.execute(select(tenants).where(tenants.c.id==tenant)).first(): c.execute(insert(tenants).values(id=tenant,counter=0))
            if c.execute(select(users).where(users.c.tenant==tenant,users.c.email==email.lower())).first():
                raise ValueError("User already exists; bootstrap never resets a password")
            user={"id":uid(),"tenant":tenant,"email":email.lower(),"password":ph.hash(password),"role":role,"active":True}
            c.execute(insert(users).values(**user)); self.log(c,tenant,actor or "local-bootstrap", "user.created",user["id"],{"role":role})
            return {k:v for k,v in user.items() if k!="password"}
    def reset_password(self,tenant,email,password):
        """Local machine administrator operation; revokes every existing session."""
        if not 12<=len(password)<=256: raise ValueError("Password must contain 12 to 256 characters")
        with self.tx() as c:
            row=c.execute(select(users).where(users.c.tenant==tenant,users.c.email==email.lower())).mappings().first()
            if not row: raise KeyError("User not found")
            c.execute(update(users).where(users.c.id==row["id"]).values(password=ph.hash(password)))
            c.execute(delete(sessions).where(sessions.c.user_id==row["id"]))
            self.log(c,tenant,"local-administrator","user.password_reset",row["id"],{"sessions_revoked":True})
    def user(self,c,user_id):
        row=c.execute(select(users).where(users.c.id==user_id,users.c.active.is_(True))).mappings().first()
        if not row: raise PermissionError("Inactive user")
        return dict(row)
    def put(self,c,tenant,owner,kind,name,body,blob=None):
        rid=uid(); rec={"id":rid,"tenant":tenant,"kind":kind,"owner":owner,"name":name,"created":time.time(),"body":dumps(body),
                       "blob":gzip.compress(blob,mtime=0) if blob is not None else None,"digest":hashlib.sha256(blob).hexdigest() if blob is not None else digest(body)}
        c.execute(insert(resources).values(**rec)); self.log(c,tenant,owner,kind+".created",rid,{"digest":rec["digest"]})
        return rid
    def get(self,c,tenant,rid,kind=None,with_blob=False):
        q=select(resources).where(resources.c.tenant==tenant,resources.c.id==rid)
        if kind: q=q.where(resources.c.kind==kind)
        row=c.execute(q).mappings().first()
        if not row: raise KeyError("Resource not found")
        out=dict(row); raw=out.pop("blob"); out["body"]=json.loads(out["body"])
        if with_blob: out["blob"]=gzip.decompress(raw) if raw is not None else None
        return out
    def list(self,c,tenant,kind):
        cols=[col for col in resources.c if col.name!="blob"]
        rows=c.execute(select(*cols).where(resources.c.tenant==tenant,resources.c.kind==kind).order_by(resources.c.created.desc()).limit(200)).mappings()
        return [{**dict(r),"body":json.loads(r["body"])} for r in rows]
    def run(self,c,tenant,rid):
        row=c.execute(select(runs).where(runs.c.tenant==tenant,runs.c.id==rid)).mappings().first()
        if not row: raise KeyError("Run not found")
        return {**dict(row),"spec":json.loads(row["spec"]),"result":json.loads(row["result"])}
    def audit_entries(self,c,tenant):
        return [dict(r) for r in c.execute(select(audit).where(audit.c.tenant==tenant).order_by(audit.c.seq)).mappings()]
    def verify_audit(self,c,tenant):
        prev="0"*64; rows=self.audit_entries(c,tenant)
        for seq,row in enumerate(rows,1):
            expected=row.pop("digest"); valid=hmac.compare_digest(expected,hmac.new(self.settings.audit_key.encode(),dumps(row).encode(),hashlib.sha256).hexdigest())
            if not valid or row["previous"]!=prev or row["seq"]!=seq: return {"valid":False,"at_sequence":seq}
            prev=expected
        counter=c.execute(select(tenants.c.counter).where(tenants.c.id==tenant)).scalar_one()
        return {"valid":counter==len(rows),"events":len(rows),"head":prev,"limitation":"DB administrator with the HMAC key can rewrite history; export head externally for independent anchoring"}
