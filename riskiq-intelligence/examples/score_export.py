"""Score exported JSON in any Python 3.11+ environment, without a cloud SDK.
Copy this file and riskiq/core/scoring.py next to it, renamed scoring.py.
Usage: python score_export.py tariff.json input.csv output.csv
All inputs are local files. Never publishes a tariff.
"""
import csv,json,sys,hashlib
try:
    from scoring import quote
except ImportError:
    from riskiq.core.scoring import quote

def safe_text(value):
    text=str(value)
    return "\'"+text if text.lstrip().startswith(("=","+","-","@")) else text

def main():
    if len(sys.argv)!=4: raise SystemExit("Usage: score_export.py tariff.json input.csv output.csv")
    with open(sys.argv[1],encoding="utf-8") as f: bundle=json.load(f)
    canonical=json.dumps(bundle["tariff"],sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    if hashlib.sha256(canonical.encode()).hexdigest()!=bundle["digest"]: raise ValueError("Bundle digest mismatch")
    with open(sys.argv[2],encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
    scored=[]
    for row in rows:
        prediction=quote(bundle["tariff"],row,float(row["premium_ht"]))
        scored.append({"policy_id":safe_text(row.get("policy_id","")),**prediction})
    if not scored: raise ValueError("Empty input")
    with open(sys.argv[3],"w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(scored[0])); w.writeheader(); w.writerows(scored)
    print(f"Scored {len(scored)} rows; bundle status was {bundle['run_status']} (no publication).")
if __name__=="__main__": main()
