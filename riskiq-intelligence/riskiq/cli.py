"""Install, administer and run the portable core without a data platform."""
import argparse
import getpass
import json
import os
from pathlib import Path
from sqlalchemy import select
from .config import Settings
from .store import Store,users,tenants


def init_from_env(store):
    tenant=os.getenv("RISKIQ_BOOTSTRAP_TENANT","demo")
    accounts=[(os.getenv("RISKIQ_BOOTSTRAP_ADMIN_EMAIL","admin@riskiq.local"),os.getenv("RISKIQ_BOOTSTRAP_ADMIN_PASSWORD",""),"admin"),
              (os.getenv("RISKIQ_BOOTSTRAP_APPROVER_EMAIL","approver@riskiq.local"),os.getenv("RISKIQ_BOOTSTRAP_APPROVER_PASSWORD",""),"approver")]
    with store.tx() as c:
        existing=c.execute(select(users.c.id).where(users.c.tenant==tenant)).first()
    if existing: return
    if any(len(password)<12 for _,password,_ in accounts):
        raise ValueError("Run scripts/configure.py or configure.ps1 first: two bootstrap passwords of >=12 characters are required")
    if accounts[0][0].lower()==accounts[1][0].lower(): raise ValueError("Distinct administrator and approver accounts are required")
    for email,password,role in accounts: store.bootstrap(tenant,email,password,role)
    print("Initial tenant and two separate accounts created. No password is printed by the server.")


def analyse_frame(df,spec):
    """Headless capability callable from notebooks/jobs; no platform SDK dependency."""
    from .core.data import select_coverage,quality,canonical_numeric
    from .core.modeling import train_candidates
    from .core.pricing import optimise
    from .store import digest
    m=spec["mapping"]; df=select_coverage(df,m); q=quality(df,m)
    if not q["passed"]: raise ValueError("Blocking quality violations: "+json.dumps(q))
    df=canonical_numeric(df,m); training=train_candidates(df,m,spec["alpha"])
    opt=optimise(df,m,training["model"],spec["policy"])
    if not opt["feasible"]: raise ValueError("No feasible candidate")
    plan={"schema":"riskiq.tariff/1","model":training["model"],"policy":spec["policy"],"factors":opt["factors"],"coverage":m.get("coverage_value") or "selected","currency":m["currency"],"version":1,"scope":"single-coverage renewals"}
    return {"export_schema":"riskiq.export/1","run_status":"unapproved_headless_candidate","digest":digest(plan),"tariff":plan}, {"quality":q,"test":training["test"],"split":training["split"],"optimisation":opt}


def main():
    parser=argparse.ArgumentParser(description="RiskIQ Intelligence — private-pilot reference release")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("init",help="Create initial tenant/accounts using environment variables")
    serve=sub.add_parser("serve"); serve.add_argument("--host",default="127.0.0.1"); serve.add_argument("--port",type=int,default=int(os.getenv("PORT","8080")))
    sub.add_parser("worker",help="Run a separate durable-queue worker")
    user=sub.add_parser("create-user"); user.add_argument("--tenant",default="demo"); user.add_argument("--email",required=True); user.add_argument("--role",choices=["admin","analyst","approver","viewer"],default="analyst")
    reset=sub.add_parser("set-password",help="Local admin password rotation; revokes sessions"); reset.add_argument("--tenant",default="demo"); reset.add_argument("--email",required=True)
    sub.add_parser("verify-audit").add_argument("--tenant",default="demo")
    ana=sub.add_parser("analyse"); ana.add_argument("--input",required=True); ana.add_argument("--spec"); ana.add_argument("--out",required=True)
    args=parser.parse_args()
    if args.command=="analyse":
        from .core.data import read_csv_bytes
        from .schemas import RunCreate
        spec=json.loads(Path(args.spec).read_text()) if args.spec else RunCreate(dataset_id="headless").model_dump()
        spec=RunCreate.model_validate(spec).model_dump()
        df=read_csv_bytes(Path(args.input).read_bytes(),separator=",")
        bundle,report=analyse_frame(df,spec)
        out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
        (out/"tariff.json").write_text(json.dumps(bundle,indent=2),encoding="utf-8")
        (out/"evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print("Headless candidate generated. Not approved, not published."); return
    settings=Settings.load(); store=Store(settings)
    if args.command=="init": init_from_env(store)
    elif args.command=="create-user":
        password=getpass.getpass("New password (>=12 characters): "); confirm=getpass.getpass("Confirm: ")
        if password!=confirm: raise ValueError("Passwords differ")
        u=store.bootstrap(args.tenant,args.email,password,args.role); print("Created",u["email"],u["role"])
    elif args.command=="set-password":
        password=getpass.getpass("New password (12–256 characters): "); confirm=getpass.getpass("Confirm: ")
        if password!=confirm: raise ValueError("Passwords differ")
        store.reset_password(args.tenant,args.email,password); print("Password changed; all existing sessions revoked.")
    elif args.command=="verify-audit":
        with store.tx() as c: print(json.dumps(store.verify_audit(c,args.tenant),indent=2))
    elif args.command=="worker":
        from .workflow import Worker
        Worker(store).loop()
    else:
        init_from_env(store)
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(settings),host=args.host,port=args.port,proxy_headers=False)

if __name__=="__main__": main()
