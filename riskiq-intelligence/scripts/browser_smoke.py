"""Real-browser E2E on an isolated synthetic database. No live cloud calls.
Run from the repo: python scripts/browser_smoke.py
Requires: pip install '.[test]' && playwright install chromium
"""
import json,os,secrets,subprocess,sys,tempfile,time,urllib.request,base64,re
import httpx
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]; qa=root/'qa';qa.mkdir(exist_ok=True)
shots=qa/'screenshots';shots.mkdir(exist_ok=True)
port=int(os.getenv('RISKIQ_QA_PORT','8877'));url=f'http://127.0.0.1:{port}'
password1=secrets.token_urlsafe(24);password2=secrets.token_urlsafe(24)
errors=[];steps=[]
with tempfile.TemporaryDirectory(prefix='riskiq-ui-') as tmp:
    env=os.environ|{'RISKIQ_MODE':'local','RISKIQ_DATABASE_URL':f'sqlite:///{tmp}/ui.db','RISKIQ_PUBLIC_URL':url,'RISKIQ_AUDIT_KEY':secrets.token_hex(32),'RISKIQ_BOOTSTRAP_ADMIN_EMAIL':'admin@riskiq.local','RISKIQ_BOOTSTRAP_APPROVER_EMAIL':'approver@riskiq.local','RISKIQ_BOOTSTRAP_ADMIN_PASSWORD':password1,'RISKIQ_BOOTSTRAP_APPROVER_PASSWORD':password2,'RISKIQ_BOOTSTRAP_TENANT':'demo','RISKIQ_EMBEDDED_WORKER':'true','RISKIQ_LLM_ENABLED':'false','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','RISKIQ_SOURCES_FILE':''}
    with open(qa/'browser-server.log','w') as log:
        proc=subprocess.Popen([sys.executable,'-m','riskiq.cli','serve','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url+'/health',timeout=1);break
                except Exception:time.sleep(.15)
            else:raise RuntimeError('Server did not start')
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=os.getenv("RISKIQ_CHROMIUM_PATH") or None)
                page=browser.new_page(viewport={'width':1600,'height':1080},device_scale_factor=1)
                page.set_default_timeout(7000)
                page.on('pageerror',lambda err:errors.append(str(err)))
                def sign_in(email,password):
                    page.locator('#login-form [name=email]').fill(email)
                    page.locator('#login-form [name=password]').fill(password)
                    page.locator('#login-form button[type=submit]').click()
                    page.locator('#shell').wait_for(state='visible')
                def nav(route):
                    page.locator(f'#nav [data-route={route}]').click()
                    page.wait_for_timeout(600)
                    print('NAV',route,flush=True)
                def shot(name):
                    page.locator('#toast').evaluate('(el)=>el.hidden=true')
                    page.screenshot(path=shots/(name+'.png'),full_page=True)
                if os.getenv('RISKIQ_QA_BRIDGE')=='1':
                    # Transport-isolated UI integration harness, NOT a direct-network E2E.
                    # Useful where the test browser cannot reach loopback. Actual API is used;
                    # responses, model calculations and session cookies are not mocked.
                    transport=httpx.Client(base_url=url,trust_env=False)
                    def bridge(path,options):
                        headers=options.get('headers',{})|{'Origin':url}
                        response=transport.request(options.get('method','GET'),path,headers=headers,content=options.get('body'))
                        return {'ok':response.is_success,'status':response.status_code,'data':response.json()}
                    page.expose_function('__riskiqTestFetch',bridge)
                    html=(root/'riskiq/static/index.html').read_text()
                    html=re.sub(r'<script[^>]*>.*?</script>','',html,flags=re.S)
                    html=re.sub(r'<link[^>]+>','',html)
                    logo='data:image/png;base64,'+base64.b64encode((root/'riskiq/static/logo.png').read_bytes()).decode()
                    html=html.replace('/static/logo.png',logo)
                    page.set_content(html)
                    page.add_style_tag(content=(root/'riskiq/static/app.css').read_text())
                    page.evaluate("""window.fetch=async (path,options={})=>{let r=await window.__riskiqTestFetch(path,options);return {...r,json:async()=>r.data}};
                    if(!crypto.randomUUID)crypto.randomUUID=()=> '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^(crypto.getRandomValues(new Uint8Array(1))[0]&15)>>(c/4)).toString(16));""")
                    page.add_script_tag(content=(root/'riskiq/static/app.js').read_text())
                else:
                    page.goto(url)
                page.locator('#login-view').wait_for(state='visible');shot('01-login')
                sign_in('admin@riskiq.local',password1);steps.append('local login')
                nav('data');page.locator('[data-action=synthetic]').click()
                page.locator('#synthetic-form [name=n]').fill('5000')
                page.locator('#synthetic-form button[type=submit]').click()
                page.wait_for_timeout(500)
                page.locator('.data-card').wait_for();steps.append('real synthetic dataset persisted')
                shot('02-data')
                page.locator('.data-card [data-action=launch]').first.click()
                page.locator('#launch-form [name=name]').fill('Revue RC · recette navigateur')
                page.locator('#launch-form button[type=submit]').click()
                page.wait_for_function("document.querySelector('#main').textContent.includes('La proposition est scellée')",timeout=60000)
                steps.append('six persisted agent steps executed; awaiting approval');shot('03-intelligence-loop')
                nav('overview');shot('04-overview');nav('models');shot('05-models');nav('integrations');shot('06-integrations')
                nav('loop');page.locator('[data-action=logout]').click();page.locator('#login-view').wait_for(state='visible')
                sign_in('approver@riskiq.local',password2)
                page.locator('[data-action=decide][data-decision=approve]').wait_for();page.locator('[data-action=decide][data-decision=approve]').click()
                page.locator('#decision-form [name=comment]').fill('Independent review of validation data, assumptions and scenario. Approved for internal sandbox only.')
                page.locator('#decision-form input[type=checkbox]').check()
                page.locator('#decision-form button[type=submit]').click()
                page.wait_for_function("document.querySelector('#main').textContent.includes('L’approbation a été enregistrée')")
                steps.append('approval by a different authenticated person')
                page.locator('[data-action=logout]').click();page.locator('#login-view').wait_for(state='visible');sign_in('admin@riskiq.local',password1)
                page.locator('[data-action=deploy]').wait_for();page.locator('[data-action=deploy]').click()
                page.locator('#note-form [name=comment]').fill('Publish approved immutable version to internal rating sandbox')
                page.locator('#note-form button[type=submit]').click();page.wait_for_timeout(700)
                nav('deployments');page.locator('[data-action=quote]').first.click();page.locator('#quote-form button[type=submit]').click()
                page.locator('#quote-result .kpis').wait_for();shot('07-quote');steps.append('internal API deployment and actual quote')
                page.locator('[data-action=close-dialog]').click();nav('monitoring');page.locator('[data-action=outcome]').click()
                page.locator('#synthetic-form button[type=submit]').click();page.wait_for_timeout(700)
                page.locator('#monitor-form [name=maturity_confirmed]').check()
                page.locator('#monitor-form button[type=submit]').click()
                page.locator('[data-action=feedback]').wait_for();shot('08-monitoring');steps.append('outcome A/E and drift on a distinct synthetic snapshot')
                page.locator('[data-action=feedback]').first.click();page.locator('#launch-form button[type=submit]').click()
                page.wait_for_function("document.querySelector('#main').textContent.includes('La proposition est scellée')",timeout=60000)
                steps.append('second loop linked to the deployed parent')
                page.locator('[data-action=copilot]').click();page.locator('#copilot-form textarea').fill('Explique les résultats')
                page.locator('#copilot-form button[type=submit]').click()
                page.wait_for_function("document.querySelector('#copilot-output').textContent.includes('AUCUN LLM APPELÉ')")
                steps.append('grounded read-only deterministic copilot');page.locator('[data-action=close-copilot]').click()
                nav('admin');shot('09-audit');steps.append('audit hash chain verified and user registry displayed')
                if errors:raise AssertionError(errors)
                browser.close()
        except Exception as exc:
            print('BROWSER FAILED',str(exc),'PAGE ERRORS',errors,flush=True)
            raise
        finally:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
result={'passed':True,'browser':'Chromium / Playwright','steps':steps,'page_errors':errors,'data':'synthetic only; isolated temporary DB','cloud_connections_tested':False,'transport':'Python bridge to real HTTP API; not direct browser network' if os.getenv('RISKIQ_QA_BRIDGE')=='1' else 'direct browser HTTP'}
(qa/'browser-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
