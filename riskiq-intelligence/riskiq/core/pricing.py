"""Consistent baseline economics and scale-normalised constrained optimisation.
Elasticity is an explicit scenario assumption, NOT an estimated causal model.
"""
import numpy as np
from scipy.optimize import minimize
from .scoring import category, score_records


def expected_metrics(premium,loss,e,q,expense):
    earned=float(np.sum(premium*e*q)); expected=float(np.sum(loss*e*q)); retained=float(np.sum(e*q)/np.sum(e))
    return {"earned_premium_ht":earned,"expected_loss":expected,"margin":earned*(1-expense)-expected,
            "retention":retained,"loss_ratio":expected/earned if earned else None,
            "combined_ratio":expected/earned+expense if earned else None}


def simulate(current,proposed,loss,exposure,policy):
    current,proposed,loss,e=[np.asarray(a,dtype=float) for a in (current,proposed,loss,exposure)]
    if any(not np.isfinite(a).all() for a in (current,proposed,loss,e)) or np.any(current<=0) or np.any(e<=0) or np.any(proposed<=0) or np.any(loss<0):
        raise ValueError("Simulation requires positive premiums/exposures and finite nonnegative costs")
    delta=proposed/current-1
    before_q=np.full(len(e),policy["base_retention"])
    after_q=np.minimum(1,policy["base_retention"]*np.exp(-policy["elasticity"]*delta))
    before=expected_metrics(current,loss,e,before_q,policy["expense_ratio"])
    after=expected_metrics(proposed,loss,e,after_q,policy["expense_ratio"])
    return {"before":before,"after":after,"delta_margin":after["margin"]-before["margin"],
        "delta_earned_premium":after["earned_premium_ht"]-before["earned_premium_ht"],
        "average_price_change":float(np.average(delta,weights=e)),
        "price_change_percentiles":{str(q):float(np.quantile(delta,q/100)) for q in (0,10,50,90,100)},
        "demand_basis":"assumed bounded exponential, not fitted or causal", "premium_basis":"annual excl-tax × exposure × retention on BOTH sides"}


def optimise(df,m,model,policy)->dict:
    loss=np.asarray(score_records(model,df.to_dict("records")))
    current=df[m["premium"]].to_numpy(float); e=df[m["exposure"]].to_numpy(float)
    base=loss/(1-policy["expense_ratio"])
    seg=df[policy["segment"]].map(category); levels=sorted(set(seg)); idx=np.array([levels.index(x) for x in seg])
    if len(levels)>20: raise ValueError("Optimisation supports at most 20 commercial segments")
    lo=current*(1-policy["max_decrease"]); hi=current*(1+policy["max_increase"])
    norm=float(np.sum(current*e)); total_e=e.sum(); exp=policy["expense_ratio"]; eps=policy["elasticity"]; q0=policy["base_retention"]
    def price(x): return np.clip(base*np.asarray(x)[idx],lo,hi)
    def arrays(x):
        raw=base*x[idx]; p=np.clip(raw,lo,hi); d=p/current-1
        r=q0*np.exp(-eps*d); q=np.minimum(1,r)
        dp=np.where((raw>lo)&(raw<hi),base,0)
        dq=np.where(r<1,-eps*q/current,0)*dp
        return p,q,dp,dq
    def objective(x):
        p,q,_,_=arrays(x)
        return -float(np.sum(e*q*(p*(1-exp)-loss)))/norm
    def grad(x):
        p,q,dp,dq=arrays(x); v=-e*(dq*(p*(1-exp)-loss)+q*(1-exp)*dp)/norm
        return np.bincount(idx,weights=v,minlength=len(levels))
    def retention(x): return float(np.sum(arrays(x)[1]*e)/total_e)
    def ret_jac(x): return np.bincount(idx,weights=arrays(x)[3]*e/total_e,minlength=len(levels))
    def avg(x): return float(np.average(price(x)/current-1,weights=e))
    def avg_jac(x): return np.bincount(idx,weights=e*arrays(x)[2]/current/total_e,minlength=len(levels))
    def solve(min_ret):
        constraints=[{"type":"ineq","fun":lambda x:retention(x)-min_ret,"jac":ret_jac},
                     {"type":"ineq","fun":lambda x:policy["max_average_increase"]-avg(x),"jac":lambda x:-avg_jac(x)}]
        starts=[np.ones(len(levels)),np.array([np.median(current[idx==i]/base[idx==i]) for i in range(len(levels))]),np.full(len(levels),.5)]
        accepted=[]; reports=[]
        for x0 in starts:
            res=minimize(objective,np.clip(x0,.05,5),jac=grad,bounds=[(.05,5)]*len(levels),constraints=constraints,method="SLSQP",options={"ftol":1e-10,"maxiter":300})
            feasible=retention(res.x)>=min_ret-1e-7 and avg(res.x)<=policy["max_average_increase"]+1e-7
            reports.append({"success":bool(res.success),"feasible":bool(feasible),"iterations":int(res.nit)})
            if feasible and np.isfinite(res.fun): accepted.append(res)
        if not accepted: return None,reports
        best=min(accepted,key=lambda r:r.fun)
        return best,reports
    best,reports=solve(policy["min_retention"])
    if best is None: return {"feasible":False,"solver_reports":reports,"reason":"No feasible candidate found; approval blocked"}
    proposed=price(best.x); sim=simulate(current,proposed,loss,e,policy)
    frontier=[]
    for floor in sorted(set([policy["min_retention"],policy["base_retention"],(policy["min_retention"]+policy["base_retention"])/2])):
        r,_=solve(floor)
        if r is not None:
            s=simulate(current,price(r.x),loss,e,policy)
            frontier.append({"minimum_retention":float(floor),"retention":s["after"]["retention"],"margin":s["after"]["margin"],"feasible":True})
    per_segment=[]
    for i,key in enumerate(levels):
        mask=idx==i
        v=simulate(current[mask],proposed[mask],loss[mask],e[mask],policy)
        per_segment.append({"segment":key,"factor":float(best.x[i]),"rows":int(mask.sum()),"simulation":v})
    return {"feasible":True,"factors":dict(zip(levels,map(float,best.x))),"simulation":sim,"segments":per_segment,
            "frontier":frontier,"solver_reports":reports,"capped_rows":int(((base*best.x[idx]<lo)|(base*best.x[idx]>hi)).sum()),
            "objective":"normalised expected underwriting margin","optimality":"best feasible multi-start local solution, not a global optimum certificate",
            "recommendation":"propose" if sim["delta_margin"]>1e-6*norm else "retain_current_or_review",
            "limitations":["Demand response is assumed, not causal","Forecast costs use fitted model, not future realised claims","This release optimises a bounded renewal adjustment by segment"]}
