"""Frequency/severity and Tweedie candidates; chronological/grouped separation.
L2 only: elastic-net is NOT advertised or silently substituted.
"""
import math
import warnings
import numpy as np
import pandas as pd
from sklearn.linear_model import PoissonRegressor, GammaRegressor, TweedieRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import mean_tweedie_deviance
from .scoring import SCHEMA, category, vector, score_records


def design_fit(df:pd.DataFrame,features:list[dict])->dict:
    out=[]
    for f in features:
        s=df[f["name"]]; rec={"name":f["name"],"kind":f["kind"]}
        if f["kind"]=="numeric":
            a=pd.to_numeric(s,errors="raise").to_numpy(dtype=float)
            med=float(np.nanmedian(a)); a=np.where(np.isnan(a),med,a)
            scale=float(np.std(a))
            if not math.isfinite(med) or scale<1e-9: raise ValueError(f"No training variation: {f['name']}")
            knots=sorted(set(float(v) for v in np.quantile(a,[.2,.5,.8]))) if f.get("nonlinear") else []
            rec.update(median=med,center=med,scale=scale,knots=knots)
        else:
            cats=s.map(category)
            levels=sorted(set(cats)|{"__missing__"})
            rec.update(levels=levels,reference=str(cats.value_counts().index[0]))
        out.append(rec)
    return {"schema":"riskiq.design/1","features":out}


def matrix(df:pd.DataFrame,design:dict)->np.ndarray:
    return np.asarray([vector(row,design) for row in df.to_dict(orient="records")],dtype=float)


def split(df:pd.DataFrame,m:dict,seed:int=42)->tuple[list[np.ndarray],dict]:
    """Chronological splits use disjoint dates; reject cross-boundary repeated policies.
    Without dates, group by policy and keep the test set completely outside selection.
    """
    ids=df[m["policy_id"]].astype(str)
    if m.get("period"):
        dates=pd.to_datetime(df[m["period"]],utc=True,errors="raise")
        unique=sorted(dates.unique())
        if len(unique)<3: raise ValueError("At least three distinct period dates required for time-based train/validation/test; remove period mapping only for an explicit grouped-random split")
        cut1=max(1,min(len(unique)-2,int(.6*len(unique))))
        cut2=max(cut1+1,min(len(unique)-1,int(.8*len(unique))))
        folds=[np.flatnonzero(dates<unique[cut1]), np.flatnonzero((dates>=unique[cut1])&(dates<unique[cut2])), np.flatnonzero(dates>=unique[cut2])]
        method="chronological"
    else:
        groups=ids.unique().copy(); np.random.default_rng(seed).shuffle(groups)
        a,b=int(len(groups)*.6),int(len(groups)*.8)
        folds=[np.flatnonzero(ids.isin(g)) for g in (groups[:a],groups[a:b],groups[b:])]
        method="policy-grouped random; not out-of-time"
    sets=[set(ids.iloc[f]) for f in folds]
    if any(sets[i]&sets[j] for i in range(3) for j in range(i+1,3)):
        raise ValueError("Repeated policies cross time boundaries. Build independent cohorts first; no silent temporal leakage.")
    for f in folds:
        if len(f)<100 or df.iloc[f][m["claim_count"]].sum()<10:
            raise ValueError("Each train/validation/test split needs >=100 rows and >=10 claims")
    return folds,{"method":method,"seed":seed,"counts":[len(x) for x in folds],"group_overlap":False,"selection_set":"validation","final_test_used_for_selection":False}


def fit_component(df:pd.DataFrame,m:dict,kind:str,alpha:float)->dict:
    e=df[m["exposure"]].to_numpy(float); n=df[m["claim_count"]].to_numpy(float); c=df[m["claim_amount"]].to_numpy(float)
    if kind=="severity":
        keep=n>0; source=df.loc[keep]; y=c[keep]/n[keep]; w=n[keep]
        estimator=GammaRegressor(alpha=alpha,max_iter=2000,tol=1e-8)
    else:
        source=df; w=e
        y=n/e if kind=="frequency" else c/e
        estimator=PoissonRegressor(alpha=alpha,max_iter=2000,tol=1e-8) if kind=="frequency" else TweedieRegressor(power=1.5,link="log",alpha=alpha,max_iter=2000,tol=1e-8)
    design=design_fit(source,m["features"]); X=matrix(source,design)
    with warnings.catch_warnings():
        warnings.simplefilter("error",ConvergenceWarning)
        estimator.fit(X,y,sample_weight=w)
    bundle={"schema":SCHEMA,"kind":kind,"design":design,"intercept":float(estimator.intercept_),
        "coefficients":[float(x) for x in estimator.coef_],"regularisation":{"type":"L2","alpha":alpha},
        "link":"log","power":1.5 if kind=="pure_premium" else (1 if kind=="frequency" else 2),
        "target_unit":{"frequency":"claims/exposure-year","severity":"currency/claim","pure_premium":"currency/exposure-year"}[kind],
        "exposure_handling":"rate target; exposure weights" if kind!="severity" else "loss/count target; claim-count weights",
        "imputation_scope":"training subset only","iterations":int(estimator.n_iter_)}
    # Cross-check a distinct scoring implementation, not just nonzero coefficients.
    p=np.asarray(score_records(bundle,source.to_dict("records")))
    if not np.allclose(p,estimator.predict(X),rtol=1e-10,atol=1e-10):
        raise ValueError("Portable scoring parity failed")
    return bundle


def weighted_gini(y_total,p_rate,exposure)->float|None:
    """Ascending risk rates; tied scores grouped so a constant predictor returns 0."""
    t=pd.DataFrame({"s":p_rate,"y":y_total,"e":exposure}).groupby("s",sort=True)[["y","e"]].sum()
    if t.y.sum()<=0 or t.e.sum()<=0: return None
    x=np.r_[0,t.e.cumsum()/t.e.sum()]; y=np.r_[0,t.y.cumsum()/t.y.sum()]
    return float(1-np.sum((y[1:]+y[:-1])*np.diff(x)))


def evaluate(bundle:dict,df:pd.DataFrame,m:dict)->dict:
    p=np.asarray(score_records(bundle,df.to_dict("records"))); e=df[m["exposure"]].to_numpy(float); c=df[m["claim_amount"]].to_numpy(float)
    pred=float(np.sum(p*e)); actual=float(np.sum(c))
    # Same monetary target and same Tweedie deviance for both candidates.
    return {"rows":len(df),"exposure":float(e.sum()),"actual_loss":actual,"expected_loss":pred,
        "ae":actual/pred if pred>0 else None,"tweedie_deviance":float(mean_tweedie_deviance(c/e,p,power=1.5,sample_weight=e)),
        "gini":weighted_gini(c,p,e),"mean_pure_premium":float(np.average(p,weights=e))}


def train_candidates(df:pd.DataFrame,m:dict,alpha:float)->dict:
    folds,split_info=split(df,m); tr,va,te=[df.iloc[i] for i in folds]
    freq=fit_component(tr,m,"frequency",alpha); sev=fit_component(tr,m,"severity",alpha)
    pair={"schema":SCHEMA,"kind":"frequency_severity","frequency":freq,"severity":sev,"target_unit":"currency/exposure-year"}
    tw=fit_component(tr,m,"pure_premium",alpha)
    candidates=[{"name":"Frequency × severity","bundle":pair},{"name":"Tweedie pure premium","bundle":tw}]
    for candidate in candidates:
        candidate["validation"]=evaluate(candidate["bundle"],va,m)
    champion=min(range(2),key=lambda i:candidates[i]["validation"]["tweedie_deviance"])
    # Final test is evaluated only after selection is frozen. No refit in this release.
    final=evaluate(candidates[champion]["bundle"],te,m)
    e=tr[m["exposure"]].to_numpy(float); c=tr[m["claim_amount"]].to_numpy(float)
    baseline=float(c.sum()/e.sum())
    test_e=te[m["exposure"]].to_numpy(float); test_c=te[m["claim_amount"]].to_numpy(float)
    base_dev=float(mean_tweedie_deviance(test_c/test_e,np.full(len(te),baseline),power=1.5,sample_weight=test_e))
    bins=[]; pred=np.asarray(score_records(candidates[champion]["bundle"],te.to_dict("records")))
    dec=pd.qcut(pd.Series(pred),q=10,labels=False,duplicates="drop").fillna(0).astype(int).to_numpy()
    for k in sorted(set(dec)):
        mask=dec==k; actual=float(test_c[mask].sum()); expected=float((pred[mask]*test_e[mask]).sum())
        bins.append({"decile":int(k)+1,"exposure":float(test_e[mask].sum()),"actual":actual,"expected":expected,"ae":actual/expected if expected else None})
    return {"candidates":candidates,"champion":champion,"champion_name":candidates[champion]["name"],
        "model":candidates[champion]["bundle"],"split":split_info,"test":final,"baseline_test_deviance":base_dev,
        "calibration_deciles":bins,"limitations":["L2 only; no elastic net or tree models in this release", "Single selected coverage per workflow", "No loss-development, censoring or inflation adjustment; inputs must already be fit for purpose"]}


def reference_distributions(df:pd.DataFrame,m:dict)->dict:
    out={}
    for f in m["features"]:
        s=df[f["name"]]
        if f["kind"]=="numeric":
            a=pd.to_numeric(s,errors="raise").to_numpy(float); finite=a[np.isfinite(a)]
            edges=np.unique(np.quantile(finite,np.linspace(0,1,11)))[1:-1]
            counts=np.histogram(finite,bins=np.r_[-np.inf,edges,np.inf])[0].astype(float)
            counts=np.r_[counts,np.isnan(a).sum()]
            out[f["name"]]={"kind":"numeric","inner_edges":edges.tolist(),"proportions":(counts/len(a)).tolist()}
        else:
            cats=s.map(category); levels=sorted(set(cats)); counts=[int((cats==v).sum()) for v in levels]+[0]
            out[f["name"]]={"kind":"categorical","levels":levels,"proportions":(np.array(counts)/len(df)).tolist()}
    return out


def psi(reference:dict,df:pd.DataFrame)->list[dict]:
    result=[]
    for name,ref in reference.items():
        if name not in df: raise ValueError("Missing drift feature "+name)
        if ref["kind"]=="numeric":
            a=pd.to_numeric(df[name],errors="raise").to_numpy(float)
            finite=a[np.isfinite(a)]
            cnt=np.histogram(finite,bins=np.r_[-np.inf,ref["inner_edges"],np.inf])[0].astype(float)
            cnt=np.r_[cnt,(~np.isfinite(a)).sum()]
        else:
            cats=df[name].map(category); cnt=np.array([(cats==v).sum() for v in ref["levels"]]+[(~cats.isin(ref["levels"])).sum()],float)
        q=(cnt+.5)/(cnt.sum()+.5*len(cnt)); p=np.asarray(ref["proportions"])
        p=(p+1e-6)/(p+1e-6).sum()
        value=float(np.sum((q-p)*np.log(q/p)))
        result.append({"feature":name,"psi":value,"alert":value>.25,"threshold":.25,"threshold_basis":"configurable heuristic, not a significance test"})
    return result
