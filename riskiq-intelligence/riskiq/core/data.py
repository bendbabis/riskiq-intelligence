"""Bounded ingestion, explicit actuarial grain and deterministic synthetic data."""
import csv
import io
import hashlib
import numpy as np
import pandas as pd

MAX_ROWS = 100_000
MAX_BYTES = 15 * 1024 * 1024


def read_csv_bytes(raw: bytes, separator: str = "auto", decimal: str = ".", encoding: str = "utf-8-sig") -> pd.DataFrame:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Empty file or limit exceeded (15 MiB)")
    if encoding not in ("utf-8-sig", "utf-8", "cp1252"):
        raise ValueError("Unsupported encoding")
    if decimal not in (".",","):
        raise ValueError("Decimal must be . or ,")
    text = raw.decode(encoding,errors="strict")
    if "\x00" in text:
        raise ValueError("NUL characters are not accepted")
    if separator == "auto":
        try:
            separator = csv.Sniffer().sniff(text[:16000],delimiters=",;\t|").delimiter
        except csv.Error as exc:
            raise ValueError("Separator is ambiguous. Select it explicitly.") from exc
    if separator not in (",",";","\t","|") or separator == decimal:
        raise ValueError("Select a separator different from the decimal character")
    header = next(csv.reader(io.StringIO(text),delimiter=separator))
    if not header or len(header) > 150 or len(set(header)) != len(header) or any(not x.strip() for x in header):
        raise ValueError("Column names must be unique/nonempty; maximum 150 columns")
    df = pd.read_csv(io.StringIO(text),sep=separator,decimal=decimal,nrows=MAX_ROWS+1,on_bad_lines="error")
    if len(df)>MAX_ROWS or len(df)<1:
        raise ValueError("Supported dataset size: 1–100,000 rows")
    return df


def frame_bytes(df: pd.DataFrame) -> bytes:
    # CSV is canonical in this bounded reference implementation; no pickle load.
    return df.to_csv(index=False,lineterminator="\n").encode("utf-8")


def fingerprint(df: pd.DataFrame) -> str:
    return hashlib.sha256(frame_bytes(df)).hexdigest()


def select_coverage(df: pd.DataFrame, m: dict) -> pd.DataFrame:
    if m.get("coverage"):
        if m["coverage"] not in df:
            raise ValueError("Coverage column is missing")
        out = df[df[m["coverage"]].astype(str)==str(m["coverage_value"])].copy()
        if out.empty:
            raise ValueError("Selected coverage has no rows")
        return out.reset_index(drop=True)
    return df.reset_index(drop=True).copy()


def quality(df: pd.DataFrame, m: dict) -> dict:
    checks=[]
    def add(code, n, severity, description):
        checks.append({"code":code,"count":int(n),"severity":severity,"description":description,"passed":bool(n==0)})
    mandatory=[m[k] for k in ("policy_id","exposure","claim_count","claim_amount","premium")]
    mandatory += [x["name"] for x in m["features"]]
    mandatory += [m[k] for k in ("period","coverage") if m.get(k)]
    missing=sorted(set(mandatory)-set(df.columns))
    add("required_columns",len(missing),"blocking","Missing columns: "+", ".join(missing))
    if missing:
        return {"passed":False,"checks":checks,"rows":len(df),"blocking_count":len(missing)}
    add("policy_id",df[m["policy_id"]].isna().sum(),"blocking","Missing policy identifiers")
    numeric={k:pd.to_numeric(df[m[k]],errors="coerce") for k in ("exposure","claim_count","claim_amount","premium")}
    for k,s in numeric.items():
        add("finite_"+k,(~np.isfinite(s)).sum(),"blocking","Non-numeric/missing/non-finite "+k)
    e,n,c,p=[numeric[k] for k in ("exposure","claim_count","claim_amount","premium")]
    add("positive_exposure",(e<=0).sum(),"blocking","Exposure must be positive in this modeling table")
    if m.get("max_exposure"):
        add("exposure_basis",(e>m["max_exposure"]).sum(),"blocking","Exposure exceeds the declared period basis")
    add("nonnegative_integer_count",((n<0)|(n%1!=0)).sum(),"blocking","Claim count must be an integer >= 0")
    add("nonnegative_loss",(c<0).sum(),"blocking","This release models nonnegative losses, not recovery transactions")
    add("positive_premium",(p<=0).sum(),"blocking","Annual current premium excl. tax must be > 0")
    add("amount_without_claim",((n==0)&(c>0)).sum(),"blocking","Positive loss with zero claim count")
    add("claim_without_amount",((n>0)&(c<=0)).sum(),"blocking","Positive-count rows require a positive severity target in this release")
    keys=[m["policy_id"]]+[m[k] for k in ("period","coverage") if m.get(k)]
    add("unique_grain",df.duplicated(keys,keep=False).sum(),"blocking","Duplicate policy × period × coverage")
    if m.get("period"):
        d=pd.to_datetime(df[m["period"]],errors="coerce",utc=True)
        add("valid_dates",d.isna().sum(),"blocking","Invalid period date (use ISO 8601)")
    for f in m["features"]:
        s=df[f["name"]]
        if f["kind"]=="numeric":
            conv=pd.to_numeric(s,errors="coerce")
            add("numeric_"+f["name"],((s.notna()&conv.isna())|np.isinf(conv)).sum(),"blocking","Invalid numeric feature")
            add("all_missing_"+f["name"],int(conv.isna().all()),"blocking","Entirely missing feature")
        else:
            add("cardinality_"+f["name"],max(0,s.nunique()-40),"blocking","Maximum 40 categories; prepare/group rare levels first")
        add("missing_"+f["name"],s.isna().sum(),"warning","Missing predictors will use a training-fitted transformation")
    blocked=sum(x["count"] for x in checks if x["severity"]=="blocking")
    return {"passed":blocked==0,"checks":checks,"rows":len(df),"blocking_count":blocked,
            "exposure":float(e.sum()),"claims":float(n.sum()),"loss":float(c.sum()),
            "earned_premium_ht":float((p*e).sum())}


def canonical_numeric(df:pd.DataFrame,m:dict)->pd.DataFrame:
    out=df.copy()
    for col in [m[k] for k in ("exposure","claim_count","claim_amount","premium")]+[f["name"] for f in m["features"] if f["kind"]=="numeric"]:
        out[col]=pd.to_numeric(out[col],errors="raise")
    return out


def synthetic(n=5000,seed=42,shock=1.0,period_shift=0)->pd.DataFrame:
    r=np.random.default_rng(seed)
    age=r.integers(18,81,n); power=r.integers(4,16,n)
    usage=r.choice(["Private","Commercial"],n,p=[.8,.2]); region=r.choice(["North","South","East","West"],n)
    exposure=r.uniform(.3,1,n)
    freq=np.exp(-2.45+.027*(power-8)+.32*(age<26)+.38*(usage=="Commercial")+.16*(region=="South"))
    sev=np.exp(7.7+.018*(power-8)+.17*(usage=="Commercial"))
    count=r.poisson(exposure*freq*shock)
    loss=np.where(count>0,r.gamma(np.maximum(count,1)*2.0,sev/2),0)
    theoretical=freq*sev
    current=theoretical/.70*np.where((age<26)|(usage=="Commercial"),.88,1.08)
    years=r.choice([2022,2023,2024],n,p=[.6,.2,.2])+period_shift
    return pd.DataFrame({"policy_id":[f"SYN-{seed}-{i:06}" for i in range(n)],
        "period":[f"{y}-01-01" for y in years],"coverage":"RC","driver_age":age,"vehicle_power":power,
        "region":region,"usage":usage,"exposure":exposure,"claim_count":count,
        "claim_amount":np.round(loss,2),"premium_ht":np.round(current,2)})


def transform(df:pd.DataFrame,spec:dict)->pd.DataFrame:
    out=df.copy()
    for term in spec["filters"]:
        if term["column"] not in out:
            raise ValueError("Unknown filter column")
        s=out[term["column"]]; v=term["value"]; op=term["operator"]
        if op=="in":
            if not isinstance(v,list): raise ValueError("in expects a list")
            mask=s.isin(v)
        elif isinstance(v,list): raise ValueError("Scalar comparison expects a scalar")
        elif op=="eq": mask=s==v
        elif op=="ne": mask=s!=v
        elif op=="gt": mask=s>v
        elif op=="ge": mask=s>=v
        elif op=="lt": mask=s<v
        elif op=="le": mask=s<=v
        else: raise ValueError("Unknown operator")
        out=out[mask.fillna(False)]
    rename=spec["rename"]
    if set(rename)-set(out.columns): raise ValueError("Unknown rename column")
    new=[rename.get(c,c) for c in out.columns]
    if len(set(new))!=len(new) or any(not c.strip() for c in new): raise ValueError("Invalid renamed columns")
    if out.empty: raise ValueError("Transformation removed all rows")
    return out.rename(columns=rename).reset_index(drop=True)
