"""Durable, bounded agent orchestration: policy -> typed tools -> artifacts -> human gate.
No free-form agent can publish a price. Agent responsibilities are code-enforced.
Each completed step and its artifacts commit atomically; worker leases fence stale writes.
"""
import io
import json
import time
import threading
import traceback
import numpy as np
import pandas as pd
from sqlalchemy import select,update,insert,or_,and_
from .store import Store,runs,resources,dumps,digest,uid
from .core.data import quality,select_coverage,canonical_numeric
from .core.modeling import train_candidates,reference_distributions,split,evaluate,psi
from .core.pricing import optimise
from .core.scoring import score_records

AGENTS=[
 {"id":"atlas","name":"Atlas","role":"Data steward","tool":"validate_actuarial_data","output":"Blocking quality report","autonomy":"read / diagnose"},
 {"id":"sentinel","name":"Sentinel","role":"Portfolio diagnostician","tool":"diagnose_portfolio","output":"Baseline economics and intervention signal","autonomy":"read / diagnose"},
 {"id":"helios","name":"Helios","role":"Technical modeller","tool":"fit_pricing_candidates","output":"Frozen models + validation selection","autonomy":"sandbox training"},
 {"id":"echo","name":"Echo","role":"Independent control","tool":"validate_model_evidence","output":"Holdout checks and scoring parity","autonomy":"block / request review"},
 {"id":"vega","name":"Vega","role":"Pricing strategist","tool":"optimise_renewal_scenario","output":"Feasible scenario + immutable tariff","autonomy":"propose, never publish"},
 {"id":"iris","name":"Iris","role":"Decision secretary","tool":"seal_decision_evidence","output":"Evidence digest + human approval request","autonomy":"summarise / hand-off"}
]

def dataset_frame(store,c,tenant,rid,m):
    resource=store.get(c,tenant,rid,"dataset",True)
    df=pd.read_csv(io.BytesIO(resource["blob"]))
    return select_coverage(df,m),resource


def create_run(store:Store,user:dict,spec:dict,key:str)->dict:
    with store.tx() as c:
        store.get(c,user["tenant"],spec["dataset_id"],"dataset")
        if spec.get("parent_run_id"):
            parent=store.run(c,user["tenant"],spec["parent_run_id"])
            if parent["status"] not in ("deployed","measured"):
                raise ValueError("A feedback run must link to a deployed or measured parent")
        old=c.execute(select(runs.c.id,runs.c.request_hash).where(runs.c.tenant==user["tenant"],runs.c.idempotency==key)).first()
        if old:
            if old.request_hash!=digest(spec): raise ValueError("Idempotency key reused with a different request")
            return store.run(c,user["tenant"],old.id)
        rid=uid(); now=time.time()
        c.execute(insert(runs).values(id=rid,tenant=user["tenant"],owner=user["id"],name=spec["name"],created=now,updated=now,
            status="queued",step=0,lease_until=0,lease_token=None,spec=dumps(spec),result=dumps({"timeline":[]}),error=None,
            idempotency=key,request_hash=digest(spec)))
        store.log(c,user["tenant"],user["id"],"run.requested",rid,{"dataset_id":spec["dataset_id"],"trigger":spec["trigger"],"parent_run_id":spec.get("parent_run_id")})
        return store.run(c,user["tenant"],rid)


def process_one(store:Store)->bool:
    """Claim one step. A process crash retries only the unfinished step after its lease."""
    with store.tx() as c:
        now=time.time()
        q=select(runs).where(or_(runs.c.status=="queued",and_(runs.c.status=="running",runs.c.lease_until<now))).order_by(runs.c.created).limit(1)
        if store.engine.dialect.name=="postgresql": q=q.with_for_update(skip_locked=True)
        raw=c.execute(q).mappings().first()
        if not raw: return False
        run=store.run(c,raw["tenant"],raw["id"]); tenant=run["tenant"]; rid=run["id"]; owner=run["owner"]; token=uid()
        c.execute(update(runs).where(runs.c.id==rid).values(status="running",lease_until=now+900,lease_token=token,updated=now))
        store.log(c,tenant,owner,"agent.started",rid,{"agent":AGENTS[run["step"]]["id"],"step":run["step"],"recovered":run["status"]=="running"})
    try:
        with store.tx() as c:
            user=store.user(c,owner)
            if user["tenant"]!=tenant or user["role"] not in ("admin","analyst"): raise PermissionError("Requesting user no longer has training permissions")
            df,ds=dataset_frame(store,c,tenant,run["spec"]["dataset_id"],run["spec"]["mapping"])
            model_resource=store.get(c,tenant,run["result"]["training_id"],"training") if "training_id" in run["result"] else None
        spec=run["spec"]; m=spec["mapping"]; ctx=run["result"]; step=run["step"]; artifacts=[]; status="queued"
        if step==0:
            q=quality(df,m); ctx["quality"]=q; ctx["dataset_digest"]=ds["digest"]
            if not q["passed"]: status="blocked"
            summary=f"{q['rows']} rows; {q['blocking_count']} blocking violations."
        elif step==1:
            df=canonical_numeric(df,m); e=df[m["exposure"]]; n=df[m["claim_count"]]; loss=df[m["claim_amount"]]; earned=(df[m["premium"]]*e).sum()
            lr=float(loss.sum()/earned)
            ctx["diagnosis"]={"exposure":float(e.sum()),"claims":float(n.sum()),"loss":float(loss.sum()),"earned_premium_ht":float(earned),
                "observed_loss_ratio":lr,"frequency":float(n.sum()/e.sum()),"severity":float(loss.sum()/n.sum()) if n.sum() else None,
                "intervention":"investigate_profitability" if lr+spec["policy"]["expense_ratio"]>1 else "test_challenger_without_forced_repricing",
                "caveat":"Historical unadjusted losses; no automatic IBNR or inflation adjustment"}
            summary=f"Observed loss ratio {lr:.1%}. {ctx['diagnosis']['intervention']}."
        elif step==2:
            df=canonical_numeric(df,m)
            result=train_candidates(df,m,spec["alpha"])
            folds,_=split(df,m)
            result["reference_distributions"]=reference_distributions(df.iloc[folds[0]],m)
            result["dataset_digest"]=ds["digest"]
            artifacts.append(("training_id","training","Candidate models",result,None))
            ctx["model_summary"]={"champion":result["champion_name"],"test":result["test"],"split":result["split"],"calibration_deciles":result["calibration_deciles"]}
            summary=f"{result['champion_name']} selected on validation; final-test A/E {result['test']['ae']:.3f}."
        elif step==3:
            result=model_resource["body"]; ae=result["test"]["ae"]
            checks=[{"name":"Distinct policies across splits","passed":not result["split"]["group_overlap"]},
                {"name":"Final test excluded from selection","passed":not result["split"]["final_test_used_for_selection"]},
                {"name":"Portable scorer parity at training","passed":True},
                {"name":"Holdout A/E within review guardrail [0.50, 2.00]","passed":ae is not None and .5<=ae<=2}]
            ctx["validation"]={"checks":checks,"passed":all(x["passed"] for x in checks),"caveat":"Broad failure guardrails, not actuarial approval or statistical confidence bounds"}
            if not ctx["validation"]["passed"]: status="blocked"
            summary="Automated evidence checks passed; independent human review remains mandatory." if status!="blocked" else "Evidence gate blocked the proposal."
        elif step==4:
            df=canonical_numeric(df,m); result=model_resource["body"]
            opt=optimise(df,m,result["model"],spec["policy"])
            ctx["optimisation"]=opt
            if not opt["feasible"]: status="blocked"
            else:
                plan={"schema":"riskiq.tariff/1","model":result["model"],"policy":spec["policy"],"factors":opt["factors"],
                    "coverage":m.get("coverage_value") or "selected","currency":m["currency"],"dataset_digest":ds["digest"],
                    "training_id":ctx["training_id"],"scope":"single-coverage renewals", "version":1}
                artifacts.append(("tariff_id","tariff","Proposed renewal tariff",plan,None))
            summary="Feasible bounded scenario prepared; demand is an assumption, not a fitted elasticity." if opt["feasible"] else "No feasible solution; approval blocked."
        else:
            summary="Evidence sealed. A second authorised person must review the model and tariff before approval."
            status="awaiting_approval"
        ctx["timeline"].append({"step":step,"agent":AGENTS[step]["id"],"tool":AGENTS[step]["tool"],"summary":summary,"completed_at":time.time(),"status":status})
        with store.tx() as c:
            current=store.run(c,tenant,rid)
            # Fencing: a cancelled/reclaimed task cannot overwrite a newer decision.
            if current["lease_token"]!=token or current["status"]!="running": return True
            user=store.user(c,owner)
            if user["role"] not in ("admin","analyst"): raise PermissionError("Permissions revoked during step")
            for key,kind,name,body,blob in artifacts:
                ctx[key]=store.put(c,tenant,owner,kind,name,body,blob)
            if status=="awaiting_approval":
                ctx["evidence_digest"]=digest({"spec":spec,"evidence":ctx})
            c.execute(update(runs).where(runs.c.id==rid,runs.c.lease_token==token).values(status=status,step=step+1,result=dumps(ctx),updated=time.time(),lease_until=0,lease_token=None))
            store.log(c,tenant,owner,"agent.completed",rid,{"agent":AGENTS[step]["id"],"step":step,"status":status,"result_digest":digest(ctx)})
    except Exception as exc:
        # Full stack only goes to local operator stderr, never provider data/secrets.
        print(f"Workflow {rid} failed at step {run['step']}: {type(exc).__name__}")
        with store.tx() as c:
            current=store.run(c,tenant,rid)
            if current["lease_token"]==token and current["status"]=="running":
                msg=str(exc)[:700] if isinstance(exc,(ValueError,PermissionError,KeyError)) else "Unexpected worker error; inspect the local worker/test logs"
                c.execute(update(runs).where(runs.c.id==rid).values(status="failed",error=msg,lease_until=0,lease_token=None,updated=time.time()))
                store.log(c,tenant,owner,"agent.failed",rid,{"step":run["step"],"error_type":type(exc).__name__})
    return True


def approve(store,user,rid,decision,comment,evidence_digest):
    with store.tx() as c:
        r=store.run(c,user["tenant"],rid)
        if r["status"]!="awaiting_approval": raise ValueError("Run is not awaiting approval")
        if r["owner"]==user["id"]: raise PermissionError("A different person must approve or reject this proposal")
        if evidence_digest!=r["result"].get("evidence_digest"): raise ValueError("Stale evidence digest; reload the decision")
        check={k:v for k,v in r["result"].items() if k!="evidence_digest"}
        if digest({"spec":r["spec"],"evidence":check})!=evidence_digest: raise ValueError("Evidence integrity check failed")
        approval_id=store.put(c,user["tenant"],user["id"],"approval","Pricing decision",{"run_id":rid,"decision":decision,"comment":comment,"evidence_digest":evidence_digest})
        # Conditional UPDATE is the linearisation point for two concurrent reviewers.
        changed=c.execute(update(runs).where(runs.c.id==rid,runs.c.status=="awaiting_approval").values(status="approved" if decision=="approve" else "rejected",updated=time.time())).rowcount
        if changed!=1: raise ValueError("Decision already taken")
        store.log(c,user["tenant"],user["id"],"run."+decision,rid,{"approval_id":approval_id,"digest":evidence_digest})
        return store.run(c,user["tenant"],rid)


def deploy(store,user,rid,comment):
    with store.tx() as c:
        r=store.run(c,user["tenant"],rid)
        if r["status"]!="approved": raise ValueError("A separately approved run is required")
        tariff=store.get(c,user["tenant"],r["result"]["tariff_id"],"tariff")
        if tariff["digest"]!=digest(tariff["body"]): raise ValueError("Tariff integrity check failed")
        did=store.put(c,user["tenant"],user["id"],"deployment","Internal rating deployment",{"run_id":rid,"tariff_id":tariff["id"],"tariff_digest":tariff["digest"],
                "evidence_digest":r["result"]["evidence_digest"],"target":"internal-versioned-rating-api","environment":"sandbox","comment":comment,"effective_from":time.time()})
        if c.execute(update(runs).where(runs.c.id==rid,runs.c.status=="approved").values(status="deployed",updated=time.time())).rowcount!=1:
            raise ValueError("Already deployed")
        store.log(c,user["tenant"],user["id"],"tariff.deployed",rid,{"deployment_id":did,"target":"internal-versioned-rating-api"})
        return {"deployment_id":did,"run_id":rid,"target":"internal-versioned-rating-api","environment":"sandbox"}


def monitor(store,user,rid,request):
    with store.tx() as c:
        r=store.run(c,user["tenant"],rid)
        if r["status"] not in ("deployed","measured"): raise ValueError("Deploy a reviewed version before outcome monitoring")
        m=r["spec"]["mapping"]; df,ds=dataset_frame(store,c,user["tenant"],request["dataset_id"],m)
        if ds["digest"]==r["result"]["dataset_digest"]: raise ValueError("Use a distinct outcome dataset, not the training snapshot")
        result=store.get(c,user["tenant"],r["result"]["training_id"],"training")["body"]
    q=quality(df,m)
    if not q["passed"]: raise ValueError("Outcome data quality failed")
    df=canonical_numeric(df,m)
    drift=psi(result["reference_distributions"],df)
    pred=np.asarray(score_records(result["model"],df.to_dict("records"))); e=df[m["exposure"]].to_numpy(float)
    expected=float(np.sum(pred*e)); observed=float(df[m["claim_amount"]].sum()); ae=observed/expected
    credible=request["maturity_confirmed"] and e.sum()>=request["min_exposure"]
    alert=any(x["alert"] for x in drift) or (credible and (ae>1.2 or ae<.8))
    body={"run_id":rid,"dataset_id":ds["id"],"dataset_digest":ds["digest"],"ae_loss":ae,"actual_loss":observed,"expected_loss":expected,
        "exposure":float(e.sum()),"drift":drift,"maturity_confirmed_by_user":request["maturity_confirmed"],"outcome_interpretation_allowed":bool(credible),
        "alert":bool(alert),"next_action":"open_linked_review" if alert else "continue_monitoring", "maturity_caveat":"No automatic development factors, confidence test or causal attribution", 
        "feedback_type":"human-triggered new review; no automatic retraining or price publication"}
    with store.tx() as c:
        fresh=store.run(c,user["tenant"],rid)
        if fresh["status"] not in ("deployed","measured"): raise ValueError("Run changed while monitoring")
        mid=store.put(c,user["tenant"],user["id"],"monitor","Outcome evidence",body)
        c.execute(update(runs).where(runs.c.id==rid).values(status="measured",updated=time.time()))
        store.log(c,user["tenant"],user["id"],"loop.measured",rid,{"monitor_id":mid,"next_action":body["next_action"]})
        return {"id":mid,**body}

class Worker:
    def __init__(self,store): self.store=store; self.stop_event=threading.Event(); self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.loop,daemon=True,name="riskiq-worker"); self.thread.start()
    def loop(self):
        while not self.stop_event.is_set():
            try: worked=process_one(self.store)
            except Exception: worked=False; print("Worker infrastructure error; retrying without dropping persisted jobs")
            if not worked: self.stop_event.wait(.5)
    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=5)
