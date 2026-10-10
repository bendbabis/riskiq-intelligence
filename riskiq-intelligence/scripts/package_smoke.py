"""Verify an already-built wheel and a no-site-packages JSON scorer.
Usage: python scripts/package_smoke.py path/to/riskiq_intelligence-0.1.0-py3-none-any.whl
No network, cloud calls or production writes.
"""
import csv,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
wheel=Path(sys.argv[1]).resolve()
report={"wheel":wheel.name,"cloud_calls":False}
with tempfile.TemporaryDirectory(prefix='riskiq-package-') as tmp:
    d=Path(tmp);target=d/'installed'
    installed=subprocess.run([sys.executable,'-m','pip','install','--no-deps','--no-index','--target',str(target),str(wheel)],capture_output=True,text=True,check=True)
    env=os.environ|{'PYTHONPATH':str(target),'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    smoke="""from riskiq.app import STATIC
from riskiq.core.data import synthetic
assert (STATIC/'index.html').is_file()
assert (STATIC/'logo.png').is_file()
synthetic(5000).to_csv('input.csv',index=False)
print('Installed wheel imports and includes static files')"""
    subprocess.run([sys.executable,'-c',smoke],cwd=d,env=env,capture_output=True,text=True,check=True)
    subprocess.run([sys.executable,'-m','riskiq.cli','analyse','--input','input.csv','--out','output'],cwd=d,env=env,capture_output=True,text=True,check=True)
    bundle=json.loads((d/'output/tariff.json').read_text())
    assert bundle['run_status']=='unapproved_headless_candidate'
    shutil.copyfile(root/'examples/score_export.py',d/'score_export.py')
    shutil.copyfile(root/'riskiq/core/scoring.py',d/'scoring.py')
    # -S removes site packages: pandas/numpy/sklearn/cloud SDKs are unavailable.
    result=subprocess.run([sys.executable,'-S',str(d/'score_export.py'),'output/tariff.json','input.csv','scored.csv'],cwd=d,capture_output=True,text=True,check=True)
    with (d/'scored.csv').open() as f:rows=list(csv.DictReader(f))
    assert len(rows)==5000 and float(rows[0]['premium_ttc'])>0
    report.update({"passed":True,"wheel_install_no_dependencies":True,"static_assets_included":True,"headless_candidate_created":True,"standard_library_only_scorer":True,"rows_scored":len(rows),"scorer_output":result.stdout.strip()})
(root/'qa/package-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
