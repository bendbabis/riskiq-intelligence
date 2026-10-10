"""Portable JSON scoring: Python standard library only. Never loads pickle/code.
The encoding is frozen at training; numeric variable names are never parsed.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

SCHEMA = "riskiq.model/1"

def missing(v):
    return v is None or (isinstance(v,float) and math.isnan(v))

def category(v):
    return "__missing__" if missing(v) else str(v).strip().casefold()

def vector(record:dict, design:dict, strict:bool=True)->list[float]:
    result=[]
    for f in design["features"]:
        name=f["name"]
        if strict and name not in record:
            raise ValueError(f"Referral required: missing field {name}")
        val=record.get(name)
        if f["kind"]=="numeric":
            x=f["median"] if missing(val) else float(val)
            if not math.isfinite(x): raise ValueError(f"Invalid numeric field {name}")
            result.append((x-f["center"])/f["scale"])
            for knot in f.get("knots",[]): result.append(max(0,x-knot)/f["scale"])
        else:
            level=category(val)
            if level not in f["levels"]:
                raise ValueError(f"Referral required: unknown level for {name}")
            result.extend(float(level==lv) for lv in f["levels"] if lv!=f["reference"])
    return result

def score_one(bundle:dict,record:dict)->float:
    if bundle.get("schema")!=SCHEMA: raise ValueError("Unsupported model schema")
    if bundle["kind"]=="frequency_severity":
        return score_one(bundle["frequency"],record)*score_one(bundle["severity"],record)
    if bundle["kind"] not in ("frequency","severity","pure_premium"):
        raise ValueError("Unknown scoring target")
    x=vector(record,bundle["design"])
    if len(x)!=len(bundle["coefficients"]): raise ValueError("Invalid design/coefficients")
    eta=bundle["intercept"]+math.fsum(a*b for a,b in zip(x,bundle["coefficients"]))
    if not math.isfinite(eta) or eta>40: raise ValueError("Prediction out of supported range; referral required")
    return math.exp(eta)

def score_records(bundle:dict,records:list[dict])->list[float]:
    return [score_one(bundle,row) for row in records]

def quote(plan:dict,risk:dict,previous_premium:float)->dict:
    if plan.get("schema")!="riskiq.tariff/1": raise ValueError("Unsupported tariff schema")
    if previous_premium<=0 or not math.isfinite(previous_premium):
        raise ValueError("A positive previous annual premium excl. tax is required by this renewal plan")
    policy=plan["policy"]
    pure=score_one(plan["model"],risk)
    raw=pure/(1-policy["expense_ratio"])
    key=category(risk.get(policy["segment"]))
    if key not in plan["factors"]: raise ValueError("Referral required: unknown commercial segment")
    commercial=raw*plan["factors"][key]
    capped=min(max(commercial,previous_premium*(1-policy["max_decrease"])),previous_premium*(1+policy["max_increase"]))
    cent=Decimal(".01")
    ht=Decimal(str(capped)).quantize(cent,rounding=ROUND_HALF_UP)
    tax=(ht*Decimal(str(policy["tax_rate"]))).quantize(cent,rounding=ROUND_HALF_UP)
    return {"coverage":plan["coverage"],"currency":plan["currency"],"pure_premium":round(pure,6),
        "technical_ht":round(raw,6),"commercial_ht":round(commercial,6),"capped":abs(capped-commercial)>1e-8,
        "premium_ht":str(ht),"tax":str(tax),"premium_ttc":str(ht+tax),
        "tax_policy":"user-supplied illustrative rate, not a French tax engine",
        "scope":"single-coverage renewal pricing"}
