"""Real, read-only, bounded data adapters. No cloud SDK is imported by the core.
Live validation requires accounts. HTTP contract tests are NOT live certification.
Sources and table allowlists are operator-defined, never an arbitrary user SQL/URL.
"""
import io
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse,quote
import httpx
import pandas as pd
from .core.data import MAX_ROWS,MAX_BYTES,read_csv_bytes

PROVIDERS={
    "databricks":"SQL Statement Execution API; bounded read-only extracts",
    "snowflake":"SQL API; bounded read-only extracts",
    "palantir":"Foundry v2 readTable; CSV dataset snapshots (not Ontology actions)",
    "bigquery":"Google BigQuery SDK; bounded extracts with maximum_bytes_billed",
    "postgres":"Read-only SQL transaction; allowlisted tables"
}

def identifier(value,provider):
    parts=value.split(".")
    regex=r"[A-Za-z_][A-Za-z0-9_]*"
    if provider=="bigquery":
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+",value): raise ValueError("Invalid BigQuery table identifier")
        return "`"+value+"`"
    if len(parts)>3 or any(not re.fullmatch(regex,p) for p in parts): raise ValueError("Invalid table identifier")
    q="`" if provider=="databricks" else '"'
    return ".".join(q+p+q for p in parts)


def load_sources(path):
    if not path: return {}
    doc=json.loads(Path(path).read_text(encoding="utf-8"))
    return doc.get("sources",{})

class Adapter:
    def __init__(self,config:dict,client:httpx.Client|None=None):
        self.config=config; self.provider=config["provider"]
        if self.provider not in PROVIDERS: raise ValueError("Unsupported provider")
        self.external_client=client
        self.host=config.get("host","").rstrip("/")
        if self.provider in ("databricks","snowflake","palantir"):
            parsed=urlparse(self.host)
            if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
                raise ValueError("Configure an HTTPS origin without credentials/path/query")
    def secret(self,key):
        name=self.config.get(key)
        if not name or not re.fullmatch(r"RISKIQ_SOURCE_[A-Z0-9_]+",name): raise ValueError("Use a RISKIQ_SOURCE_* environment secret reference")
        v=os.getenv(name,"")
        if not v: raise ValueError("Source credentials are not configured on the server")
        return v
    def request(self,method,path,**kwargs):
        if not path.startswith("/") or path.startswith("//"): raise ValueError("Unsafe provider path")
        headers={"Authorization":"Bearer "+self.secret("token_env"),"Accept":"application/json","User-Agent":"RiskIQ/0.1"}
        if self.provider=="snowflake": headers["X-Snowflake-Authorization-Token-Type"]=self.config.get("token_type","OAUTH")
        client=self.external_client or httpx.Client(timeout=45,follow_redirects=False,trust_env=False)
        try:
            with client.stream(method,self.host+path,headers=headers,**kwargs) as r:
                if r.status_code not in (200,202):
                    raise ValueError(f"Provider {self.provider} returned HTTP {r.status_code}; no success was recorded")
                raw=b""
                for chunk in r.iter_bytes():
                    raw+=chunk
                    if len(raw)>MAX_BYTES*2: raise ValueError("Provider response exceeds bounded connector limit")
                return r.status_code,raw
        except httpx.HTTPError as exc:
            raise ValueError("Provider network/timeout error; check server-side credentials and network policy") from exc
        finally:
            if not self.external_client: client.close()
    def json(self,method,path,**kw):
        status,raw=self.request(method,path,**kw)
        return status,json.loads(raw)
    def read(self,table:str,limit=MAX_ROWS):
        if table not in self.config.get("tables",[]): raise PermissionError("Table is not allowlisted for this source")
        if not 1<=limit<=MAX_ROWS: raise ValueError("Invalid extraction limit")
        # +1 detects overflow rather than claiming a partial sample is a full portfolio.
        n=limit+1
        if self.provider=="palantir":
            if not re.fullmatch(r"ri\.foundry\.main\.dataset\.[a-zA-Z0-9-]+",table): raise ValueError("Invalid Foundry dataset RID")
            _,raw=self.request("GET",f"/api/v2/datasets/{table}/readTable",params={"format":"CSV","rowLimit":n,"branchName":self.config.get("branch","master")})
            df=read_csv_bytes(raw,separator=",",encoding="utf-8-sig")
        elif self.provider=="databricks":
            statement=f"SELECT * FROM {identifier(table,self.provider)} LIMIT {n}"
            _,r=self.json("POST","/api/2.0/sql/statements",json={"statement":statement,"warehouse_id":self.config["warehouse_id"],"disposition":"INLINE","format":"JSON_ARRAY","wait_timeout":"10s","on_wait_timeout":"CONTINUE"})
            sid=r.get("statement_id","")
            for _ in range(100):
                state=r.get("status",{}).get("state")
                if state=="SUCCEEDED": break
                if state not in ("PENDING","RUNNING"): raise ValueError("Databricks query failed or was cancelled")
                time.sleep(.25); _,r=self.json("GET",f"/api/2.0/sql/statements/{quote(sid,safe='')}")
            else:
                self.json("POST",f"/api/2.0/sql/statements/{quote(sid,safe='')}/cancel")
                raise ValueError("Databricks query timeout; cancellation requested")
            manifest=r["manifest"]
            if manifest.get("truncated"): raise ValueError("Truncated result rejected; materialise a smaller approved view")
            names=[c["name"] for c in manifest["schema"]["columns"]]; chunk=r.get("result",{}); rows=list(chunk.get("data_array",[])); seen=set()
            while chunk.get("next_chunk_index") is not None:
                nxt=chunk["next_chunk_index"]
                if nxt in seen: raise ValueError("Repeated result chunk")
                seen.add(nxt)
                _,chunk=self.json("GET",f"/api/2.0/sql/statements/{quote(sid,safe='')}/result/chunks/{int(nxt)}")
                rows.extend(chunk.get("data_array",[]))
                if len(rows)>limit: raise ValueError("Extract exceeds row limit; no partial dataset imported")
            df=pd.DataFrame(rows,columns=names)
        elif self.provider=="snowflake":
            body={"statement":f"SELECT * FROM {identifier(table,self.provider)} LIMIT {n}","timeout":45}
            for key in ("warehouse","database","schema","role"):
                if key in self.config: body[key]=self.config[key]
            status,r=self.json("POST","/api/v2/statements",params={"requestId":str(uuid.uuid4())},json=body)
            handle=r.get("statementHandle","")
            for _ in range(100):
                if status==200 and "resultSetMetaData" in r: break
                if status!=202: raise ValueError("Snowflake query failed")
                time.sleep(.25); status,r=self.json("GET",f"/api/v2/statements/{quote(handle,safe='')}")
            else:
                self.json("POST",f"/api/v2/statements/{quote(handle,safe='')}/cancel")
                raise ValueError("Snowflake query timeout; cancellation requested")
            meta=r["resultSetMetaData"]; names=[v["name"] for v in meta["rowType"]]; rows=list(r.get("data",[]))
            for i in range(1,len(meta.get("partitionInfo",[]))):
                _,part=self.json("GET",f"/api/v2/statements/{quote(handle,safe='')}",params={"partition":i})
                rows.extend(part.get("data",[]))
                if len(rows)>limit: raise ValueError("Extract exceeds row limit")
            df=pd.DataFrame(rows,columns=names)
        elif self.provider=="postgres":
            from sqlalchemy import create_engine,text
            dsn=self.secret("dsn_env")
            if not dsn.startswith(("postgresql://","postgresql+psycopg://")): raise ValueError("PostgreSQL DSN required")
            engine=create_engine(dsn,connect_args={"connect_timeout":10})
            try:
                with engine.begin() as c:
                    c.execute(text("SET TRANSACTION READ ONLY")); c.execute(text("SET LOCAL statement_timeout = '45s'"))
                    df=pd.read_sql(text(f"SELECT * FROM {identifier(table,'postgres')} LIMIT {n}"),c)
            finally: engine.dispose()
        else:
            from google.cloud import bigquery
            client=bigquery.Client(project=self.config["project"])
            try:
                cfg=bigquery.QueryJobConfig(maximum_bytes_billed=int(self.config.get("maximum_bytes_billed",1_000_000_000)),use_legacy_sql=False)
                job=client.query(f"SELECT * FROM {identifier(table,'bigquery')} LIMIT {n}",job_config=cfg,location=self.config.get("location","EU"))
                try: rows=list(job.result(timeout=60))
                except Exception:
                    job.cancel(); raise ValueError("BigQuery query failed or timed out; cancellation requested")
                df=pd.DataFrame([dict(row.items()) for row in rows])
            finally: client.close()
        if len(df)>limit: raise ValueError("Extract exceeds row limit; no silent sampling")
        if df.empty: raise ValueError("Source returned no rows")
        if len(df.columns)>150 or df.columns.duplicated().any(): raise ValueError("Invalid source schema")
        if len(df.to_csv(index=False).encode())>MAX_BYTES: raise ValueError("Extract exceeds byte limit")
        return df
