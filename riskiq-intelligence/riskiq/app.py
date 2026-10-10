"""Same-origin web application + API, with real local identities and tenant checks."""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import hmac
import io
import json
import secrets
import time

import pandas as pd
from fastapi import FastAPI,Depends,Request,Response,HTTPException,UploadFile,File,Form
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select,insert,update,delete
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .store import Store,users,sessions,runs,resources,login_attempts,ph,DUMMY_HASH,token_hash,uid,dumps,digest
from .schemas import (Login,UserCreate,RunCreate,Approval,Note,MonitorRequest,CopilotRequest,
                     DemoCreate,ImportRemote,Transform,QuoteRequest)
from .core.data import (read_csv_bytes,frame_bytes,synthetic,quality,select_coverage,transform,
                        MAX_BYTES,MAX_ROWS)
from .core.scoring import quote
from .workflow import AGENTS,Worker,create_run,approve,deploy,monitor
from .adapters import load_sources,PROVIDERS,Adapter
from .copilot import answer

STATIC=Path(__file__).parent/"static"

class BodyLimit:
    """Bound the entire request before multipart/form parsing, including chunked bodies."""
    def __init__(self,app,limit=MAX_BYTES+1024*1024): self.app=app; self.limit=limit
    async def __call__(self,scope,receive,send):
        if scope["type"]!="http": return await self.app(scope,receive,send)
        if scope["method"] in ("GET","HEAD","OPTIONS"): return await self.app(scope,receive,send)
        chunks=[]; total=0
        while True:
            msg=await receive()
            if msg["type"]=="http.disconnect": return
            chunk=msg.get("body",b""); total+=len(chunk)
            if total>self.limit:
                return await JSONResponse({"detail":"Request exceeds 16 MiB"},413)(scope,receive,send)
            chunks.append(chunk)
            if not msg.get("more_body",False): break
        sent=False
        async def replay():
            nonlocal sent
            if not sent: sent=True; return {"type":"http.request","body":b"".join(chunks),"more_body":False}
            return await receive()
        await self.app(scope,replay,send)


def create_app(settings:Settings|None=None,start_worker=True)->FastAPI:
    settings=settings or Settings.load(); store=Store(settings)
    worker=Worker(store)
    @asynccontextmanager
    async def lifespan(app):
        if start_worker and settings.embedded_worker: worker.start()
        yield
        worker.stop(); store.engine.dispose()
    app=FastAPI(title="RiskIQ Intelligence",version="0.1.0",lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store; app.state.settings=settings
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def security(request,call_next):
        origin=request.headers.get("origin")
        expected=settings.public_url
        if request.method not in ("GET","HEAD","OPTIONS") and origin and origin!=expected:
            return JSONResponse({"detail":"Origin not allowed"},403)
        # Host pinning reduces DNS-rebinding exposure in local mode.
        host=request.headers.get("host","")
        allowed={urlparse(settings.public_url).netloc}
        if settings.mode=="local": allowed.update({"127.0.0.1:8080","localhost:8080","testserver"})
        if host not in allowed and request.url.path!="/health":
            return JSONResponse({"detail":"Host not allowed; configure RISKIQ_PUBLIC_URL"},400)
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"]="no-store"
        if settings.cookie_secure: response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request,exc): return JSONResponse({"detail":str(exc)},422)
    @app.exception_handler(KeyError)
    async def not_found(request,exc): return JSONResponse({"detail":"Resource not found"},404)
    @app.exception_handler(PermissionError)
    async def forbidden(request,exc): return JSONResponse({"detail":str(exc)},403)
    @app.exception_handler(IntegrityError)
    async def conflict(request,exc): return JSONResponse({"detail":"Conflicting record; reload and retry"},409)

    def current(request:Request):
        token=request.cookies.get("riskiq_session","")
        if not token: raise HTTPException(401,"Login required")
        with store.tx() as c:
            row=c.execute(select(sessions).where(sessions.c.id==token_hash(token),sessions.c.expires>time.time())).mappings().first()
            if not row: raise HTTPException(401,"Session expired")
            try: user=store.user(c,row["user_id"])
            except PermissionError: raise HTTPException(401,"User suspended")
            if request.method not in ("GET","HEAD","OPTIONS"):
                if not hmac.compare_digest(request.headers.get("X-CSRF-Token",""),row["csrf"]):
                    raise HTTPException(403,"CSRF token missing or invalid")
            return {k:v for k,v in user.items() if k!="password"}|{"csrf":row["csrf"]}
    def roles(*allowed):
        def dep(user=Depends(current)):
            if user["role"] not in allowed: raise HTTPException(403,"Role does not permit this action")
            return user
        return dep
    editor=roles("admin","analyst")
    reviewer=roles("admin","approver")
    admin=roles("admin")

    @app.get("/")
    def index(): return FileResponse(STATIC/"index.html")
    app.mount("/static",StaticFiles(directory=STATIC),name="static")
    @app.get("/health")
    def health(): return {"status":"ok","version":"0.1.0"}
    @app.get("/api/openapi.json")
    def api_schema(user=Depends(current)): return app.openapi()

    @app.post("/api/auth/login")
    def login(req:Login,response:Response,request:Request):
        # Persisted IP + tenant/email rate limits, independent of caller-controlled forwarding headers.
        ip=request.client.host if request.client else "unknown"
        key=token_hash(ip+"|"+req.tenant+"|"+req.email.lower())
        ipkey=token_hash("ip|"+ip)
        with store.tx() as c:
            for k,max_attempts in ((key,10),(ipkey,60)):
                rec=c.execute(select(login_attempts).where(login_attempts.c.key==k)).mappings().first()
                count=rec["count"] if rec and rec["since"]>time.time()-900 else 0
                if count>=max_attempts: raise HTTPException(429,"Too many login attempts; retry after 15 minutes")
                if rec: c.execute(update(login_attempts).where(login_attempts.c.key==k).values(count=count+1,since=rec["since"] if count else time.time()))
                else: c.execute(insert(login_attempts).values(key=k,count=1,since=time.time()))
        with store.tx() as c:
            row=c.execute(select(users).where(users.c.tenant==req.tenant,users.c.email==req.email.lower())).mappings().first()
            try: ok=ph.verify(row["password"] if row else DUMMY_HASH,req.password)
            except Exception: ok=False
            if not row or not ok or not row["active"]:
                raise HTTPException(401,"Invalid credentials")
            old=request.cookies.get("riskiq_session","")
            if old: c.execute(delete(sessions).where(sessions.c.id==token_hash(old)))
            token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
            c.execute(insert(sessions).values(id=token_hash(token),user_id=row["id"],csrf=csrf,expires=time.time()+8*3600))
            c.execute(delete(login_attempts).where(login_attempts.c.key==key))
            store.log(c,row["tenant"],row["id"],"session.login",row["id"],{})
        response.set_cookie("riskiq_session",token,httponly=True,secure=settings.cookie_secure,samesite="strict",max_age=8*3600,path="/")
        return {"email":row["email"],"role":row["role"],"tenant":row["tenant"],"csrf":csrf}
    @app.get("/api/auth/me")
    def me(user=Depends(current)): return user
    @app.post("/api/auth/logout")
    def logout(request:Request,response:Response,user=Depends(current)):
        with store.tx() as c:
            c.execute(delete(sessions).where(sessions.c.id==token_hash(request.cookies.get("riskiq_session",""))))
            store.log(c,user["tenant"],user["id"],"session.logout",user["id"],{})
        response.delete_cookie("riskiq_session",path="/")
        return {"logged_out":True}
    @app.get("/api/users")
    def list_users(user=Depends(admin)):
        with store.tx() as c:
            return [dict(x) for x in c.execute(select(users.c.id,users.c.email,users.c.role,users.c.active).where(users.c.tenant==user["tenant"])).mappings()]
    @app.post("/api/users")
    def add_user(req:UserCreate,user=Depends(admin)):
        return store.bootstrap(user["tenant"],req.email,req.password,req.role,actor=user["id"])
    @app.post("/api/users/{user_id}/suspend")
    def suspend(user_id:str,user=Depends(admin)):
        if user_id==user["id"]: raise ValueError("Cannot suspend your own account")
        with store.tx() as c:
            if c.execute(update(users).where(users.c.id==user_id,users.c.tenant==user["tenant"]).values(active=False)).rowcount!=1: raise KeyError()
            c.execute(delete(sessions).where(sessions.c.user_id==user_id)); store.log(c,user["tenant"],user["id"],"user.suspended",user_id,{})
        return {"suspended":True}

    def save_dataset(user,df,name,provenance):
        raw=frame_bytes(df)
        if len(raw)>MAX_BYTES: raise ValueError("Normalised dataset exceeds 15 MiB")
        body={"rows":len(df),"columns":[{"name":str(c),"dtype":str(df[c].dtype),"missing":int(df[c].isna().sum())} for c in df],"provenance":provenance,"schema_version":1}
        with store.tx() as c:
            rid=store.put(c,user["tenant"],user["id"],"dataset",name,body,raw)
            return store.get(c,user["tenant"],rid,"dataset")
    @app.get("/api/datasets")
    def datasets(user=Depends(current)):
        with store.tx() as c: return store.list(c,user["tenant"],"dataset")
    @app.post("/api/datasets/synthetic")
    def demo(req:DemoCreate,user=Depends(editor)):
        df=synthetic(**req.model_dump()); return save_dataset(user,df,f"SYNTHETIC • RC • {req.n:,} risks",{"type":"synthetic","generator":req.model_dump()})
    @app.post("/api/datasets/upload")
    def upload(file:UploadFile=File(...),name:str=Form(...),separator:str=Form("auto"),decimal:str=Form("."),encoding:str=Form("utf-8-sig"),user=Depends(editor)):
        if not 1<=len(name)<=120: raise ValueError("Name length must be 1–120")
        if not (file.filename or "").lower().endswith(".csv"): raise ValueError("This release accepts CSV only; convert Excel/Parquet using your platform or Python")
        raw=file.file.read(MAX_BYTES+1); df=read_csv_bytes(raw,separator,decimal,encoding)
        return save_dataset(user,df,name,{"type":"uploaded","separator":separator,"decimal":decimal,"encoding":encoding})
    @app.get("/api/datasets/{rid}")
    def dataset(rid:str,user=Depends(current)):
        with store.tx() as c: rec=store.get(c,user["tenant"],rid,"dataset",True)
        df=pd.read_csv(io.BytesIO(rec.pop("blob")))
        rec["preview"]=json.loads(df.head(12).to_json(orient="records",date_format="iso")); return rec
    @app.post("/api/datasets/{rid}/transform")
    def prepare(rid:str,req:Transform,user=Depends(editor)):
        with store.tx() as c: rec=store.get(c,user["tenant"],rid,"dataset",True)
        df=pd.read_csv(io.BytesIO(rec["blob"]))
        out=transform(df,req.model_dump())
        return save_dataset(user,out,req.name,{"type":"transformation","parent_id":rid,"parent_digest":rec["digest"],"recipe":req.model_dump()})

    @app.get("/api/agents")
    def agents(user=Depends(current)):
        return {"agents":AGENTS,"orchestration":"persisted bounded workflow; deterministic typed tools", "llm_optional":settings.llm_enabled,"autonomous_price_publication":False}
    @app.get("/api/runs")
    def list_runs(user=Depends(current)):
        with store.tx() as c:
            rows=c.execute(select(runs.c.id).where(runs.c.tenant==user["tenant"]).order_by(runs.c.created.desc()).limit(100)).scalars()
            return [store.run(c,user["tenant"],x) for x in rows]
    @app.post("/api/runs")
    def launch(req:RunCreate,request:Request,user=Depends(editor)):
        key=request.headers.get("Idempotency-Key") or uid()
        if len(key)>100: raise ValueError("Idempotency key too long")
        return create_run(store,user,req.model_dump(),key)
    @app.get("/api/runs/{rid}")
    def get_run(rid:str,user=Depends(current)):
        with store.tx() as c: return store.run(c,user["tenant"],rid)
    @app.post("/api/runs/{rid}/cancel")
    def cancel(rid:str,req:Note,user=Depends(editor)):
        with store.tx() as c:
            r=store.run(c,user["tenant"],rid)
            if r["status"] not in ("queued","running"): raise ValueError("Only a queued/running job can be cancelled")
            c.execute(update(runs).where(runs.c.id==rid).values(status="cancelled",lease_token=None,lease_until=0,updated=time.time()))
            store.log(c,user["tenant"],user["id"],"run.cancelled",rid,{"comment":req.comment})
        return {"cancelled":True}
    @app.post("/api/runs/{rid}/decision")
    def decision(rid:str,req:Approval,user=Depends(reviewer)): return approve(store,user,rid,**req.model_dump())
    @app.post("/api/runs/{rid}/deploy")
    def publish(rid:str,req:Note,user=Depends(editor)): return deploy(store,user,rid,req.comment)
    @app.post("/api/runs/{rid}/monitor")
    def measure(rid:str,req:MonitorRequest,user=Depends(editor)): return monitor(store,user,rid,req.model_dump())
    @app.get("/api/runs/{rid}/bundle")
    def bundle(rid:str,user=Depends(roles("admin","analyst","approver"))):
        with store.tx() as c:
            r=store.run(c,user["tenant"],rid)
            if "tariff_id" not in r["result"]: raise ValueError("No tariff generated")
            plan=store.get(c,user["tenant"],r["result"]["tariff_id"],"tariff")
            store.log(c,user["tenant"],user["id"],"tariff.exported",plan["id"],{"run_id":rid,"run_status":r["status"]})
        return JSONResponse({"export_schema":"riskiq.export/1","run_id":rid,"run_status":r["status"],"digest":plan["digest"],"tariff":plan["body"]},headers={"Content-Disposition":f'attachment; filename="riskiq-{rid}.json"'})
    @app.get("/api/resources/{kind}")
    def list_resource(kind:str,user=Depends(current)):
        if kind not in ("tariff","training","approval","deployment","monitor"): raise KeyError()
        with store.tx() as c: return store.list(c,user["tenant"],kind)
    @app.post("/api/rating/{did}/quote")
    def rating(did:str,req:QuoteRequest,user=Depends(current)):
        payload=req.model_dump()
        with store.tx() as c:
            dep=store.get(c,user["tenant"],did,"deployment")
            r=store.run(c,user["tenant"],dep["body"]["run_id"])
            if r["status"] not in ("deployed","measured"): raise ValueError("Deployment is not active")
            plan=store.get(c,user["tenant"],dep["body"]["tariff_id"],"tariff")
            if plan["digest"]!=digest(plan["body"]): raise ValueError("Artifact integrity failure")
            result=quote(plan["body"],payload["risk"],float(payload["previous_premium"]))
            store.log(c,user["tenant"],user["id"],"quote.computed",did,{"tariff_digest":plan["digest"],"input_hash":digest(payload)})
        return {"deployment_id":did,"tariff_digest":plan["digest"],**result}
    @app.post("/api/runs/{rid}/withdraw")
    def withdraw(rid:str,req:Note,user=Depends(reviewer)):
        with store.tx() as c:
            r=store.run(c,user["tenant"],rid)
            if r["status"] not in ("deployed","measured"): raise ValueError("Only a deployed tariff can be withdrawn")
            c.execute(update(runs).where(runs.c.id==rid).values(status="withdrawn",updated=time.time()))
            store.log(c,user["tenant"],user["id"],"deployment.withdrawn",rid,{"comment":req.comment})
        return {"withdrawn":True,"effect":"Quotes for this deployment are rejected; choose a separately approved earlier deployment explicitly"}
    @app.post("/api/copilot")
    def copilot(req:CopilotRequest,user=Depends(current)):
        with store.tx() as c:
            r=store.run(c,user["tenant"],req.run_id) if req.run_id else None
            store.log(c,user["tenant"],user["id"],"copilot.requested",req.run_id or "help",{"llm":req.use_llm})
        return answer(settings,req.model_dump(),r)

    def source_for(user,name):
        sources=load_sources(settings.sources_file)
        cfg=sources.get(name)
        if not cfg or user["tenant"] not in cfg.get("tenants",[]): raise KeyError("Source not available")
        return cfg
    @app.get("/api/integrations")
    def integrations(user=Depends(current)):
        configured=[]
        for name,cfg in load_sources(settings.sources_file).items():
            if user["tenant"] in cfg.get("tenants",[]): configured.append({"name":name,"provider":cfg["provider"],"tables":cfg.get("tables",[]),"status":"configured_not_live_verified"})
        return {"adapters":[{"provider":k,"scope":v,"validation":"HTTP/SDK contract tests only; live account validation required","native_execution":False} for k,v in PROVIDERS.items()],"sources":configured,
            "standalone":{"storage":"SQLite + DB artifacts","limit_rows":MAX_ROWS,"limit_bytes":MAX_BYTES},"server_database":store.engine.dialect.name}
    @app.post("/api/integrations/check")
    def check_source(req:ImportRemote,user=Depends(admin)):
        cfg=source_for(user,req.source)
        # Actually execute a bounded table read; no timer or hardcoded success.
        df=Adapter(cfg).read(req.table,limit=MAX_ROWS)
        with store.tx() as c: store.log(c,user["tenant"],user["id"],"source.read_verified",req.source,{"provider":cfg["provider"],"rows":len(df)})
        return {"status":"live_read_succeeded","rows":len(df),"columns":list(df.columns),"warning":"A real read may consume provider resources"}
    @app.post("/api/integrations/import")
    def import_source(req:ImportRemote,user=Depends(editor)):
        cfg=source_for(user,req.source); df=Adapter(cfg).read(req.table)
        return save_dataset(user,df,req.name,{"type":"external_extract","source":req.source,"provider":cfg["provider"],"table":req.table,"extracted_at":time.time(),"native_pushdown_training":False})
    @app.get("/api/audit")
    def audit_log(user=Depends(roles("admin","approver"))):
        with store.tx() as c:
            return {"verification":store.verify_audit(c,user["tenant"]),"events":store.audit_entries(c,user["tenant"])[-300:]}
    @app.get("/api/overview")
    def overview(user=Depends(current)):
        with store.tx() as c:
            ds=store.list(c,user["tenant"],"dataset"); deployments=store.list(c,user["tenant"],"deployment")
            rs=[dict(x) for x in c.execute(select(runs.c.id,runs.c.name,runs.c.status,runs.c.step,runs.c.created).where(runs.c.tenant==user["tenant"]).order_by(runs.c.created.desc()).limit(100)).mappings()]
            monitors=store.list(c,user["tenant"],"monitor")
        return {"datasets":len(ds),"runs":len(rs),"awaiting_approval":sum(x["status"]=="awaiting_approval" for x in rs),"deployments":len(deployments),"recent_runs":rs[:8],"latest_monitor":monitors[0] if monitors else None,
            "release":{"version":"0.1.0","scope":"executable reference release / single-coverage renewal","llm":"optional" if settings.llm_enabled else "disabled","mode":settings.mode}}
    return app
