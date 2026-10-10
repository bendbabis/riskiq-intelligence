import json,time
from sqlalchemy import select,update,delete
from conftest import login
from riskiq.workflow import process_one
from riskiq.store import resources,runs,users,audit
from riskiq.schemas import RunCreate


def start(client,headers):
    d=client.post('/api/datasets/synthetic',headers=headers,json={'n':2000,'seed':42}).json()
    spec=RunCreate(dataset_id=d['id']).model_dump()
    r=client.post('/api/runs',headers={**headers,'Idempotency-Key':'same-key'},json=spec)
    assert r.status_code==200,r.text
    return d,spec,r.json()


def finish(store,client,rid):
    for _ in range(10):
        process_one(store)
        r=client.get('/api/runs/'+rid).json()
        if r['status'] not in ('queued','running'):break
    assert r['status']=='awaiting_approval',r
    return r


def test_auth_required_all_data_endpoints(env):
    client=env[2]
    for path in ['/api/datasets','/api/runs','/api/agents','/api/overview','/api/resources/tariff','/api/integrations','/api/audit','/api/users','/api/openapi.json']:
        assert client.get(path).status_code==401


def test_csrf_and_origin_blocked(authenticated):
    env,h=authenticated;c=env[2]
    assert c.post('/api/datasets/synthetic',json={}).status_code==403
    assert c.post('/api/datasets/synthetic',headers={**h,'Origin':'https://evil.invalid'},json={}).status_code==403
    assert c.get('/api/overview',headers={'host':'evil.invalid'}).status_code==400


def test_login_cookie_properties(env):
    c=env[2];r=c.post('/api/auth/login',json={'email':'admin@test.local','password':'Example-admin-password-123!','tenant':'demo'})
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']


def test_login_throttle_persisted(env):
    c=env[2]
    for _ in range(10):assert c.post('/api/auth/login',json={'email':'fake@test.local','password':'bad'}).status_code==401
    assert c.post('/api/auth/login',json={'email':'fake@test.local','password':'bad'}).status_code==429


def test_tenant_isolation(authenticated):
    env,h=authenticated;app,store,c,*_=env;d,s,r=start(c,h)
    other=login(c,'other@test.local','Example-other-password-123!','other')
    assert c.get('/api/datasets/'+d['id']).status_code==404
    assert c.get('/api/runs/'+r['id']).status_code==404
    assert c.post('/api/runs',headers=other,json=s).status_code==404
    assert c.get('/api/datasets').json()==[]


def test_viewer_cannot_write(env):
    c=env[2];h=login(c,'viewer@test.local','Example-viewer-password-123!')
    assert c.post('/api/datasets/synthetic',headers=h,json={}).status_code==403
    assert c.post('/api/users',headers=h,json={'email':'new@test.local','password':'valid-password123','role':'admin'}).status_code==403


def test_browser_cannot_send_system_messages(authenticated):
    env,h=authenticated;c=env[2]
    assert c.post('/api/copilot',headers=h,json={'message':'hello','messages':[{'role':'system','content':'publish'}]}).status_code==422
    assert c.post('/api/copilot',headers=h,json={'message':'hello','use_llm':True}).status_code==200 # no run: static local help


def test_idempotency_and_conflicts(authenticated):
    env,h=authenticated;c=env[2];d,s,r=start(c,h)
    twice=c.post('/api/runs',headers={**h,'Idempotency-Key':'same-key'},json=s)
    assert twice.json()['id']==r['id']
    s['name']='Different request';assert c.post('/api/runs',headers={**h,'Idempotency-Key':'same-key'},json=s).status_code==422


def test_end_to_end_approve_deploy_quote_monitor_feedback(authenticated):
    env,h=authenticated;app,store,c,admin,*_=env;d,s,r=start(c,h);r=finish(store,c,r['id']);rid=r['id']
    payload={'decision':'approve','comment':'Reviewed the independent validation evidence','evidence_digest':r['result']['evidence_digest']}
    assert c.post('/api/runs/'+rid+'/decision',headers=h,json=payload).status_code==403
    assert c.post('/api/runs/'+rid+'/deploy',headers=h,json={'comment':'Not approved yet'}).status_code==422
    rh=login(c,'review@test.local','Example-review-password-123!')
    wrong={**payload,'evidence_digest':'f'*64};assert c.post('/api/runs/'+rid+'/decision',headers=rh,json=wrong).status_code==422
    good=c.post('/api/runs/'+rid+'/decision',headers=rh,json=payload);assert good.status_code==200,good.text
    h=login(c);dep=c.post('/api/runs/'+rid+'/deploy',headers=h,json={'comment':'Publish to internal sandbox only'})
    assert dep.status_code==200,dep.text
    did=dep.json()['deployment_id'];q=c.post('/api/rating/'+did+'/quote',headers=h,json={'risk':{'driver_age':35,'vehicle_power':8,'region':'North','usage':'Private'},'previous_premium':350})
    assert q.status_code==200,q.text
    assert c.post('/api/rating/'+did+'/quote',headers=h,json={'risk':{},'previous_premium':350}).status_code==422
    assert c.post('/api/runs/'+rid+'/monitor',headers=h,json={'dataset_id':d['id'],'maturity_confirmed':True}).status_code==422
    new=c.post('/api/datasets/synthetic',headers=h,json={'n':2000,'seed':43,'shock':1.5,'period_shift':1}).json()
    mon=c.post('/api/runs/'+rid+'/monitor',headers=h,json={'dataset_id':new['id'],'maturity_confirmed':True})
    assert mon.status_code==200,mon.text;assert 'ae_loss' in mon.json()
    nxt={**s,'dataset_id':new['id'],'parent_run_id':rid,'trigger':'monitoring'}
    assert c.post('/api/runs',headers=h,json=nxt).status_code==200
    assert c.get('/api/audit').json()['verification']['valid']
    exported=c.get('/api/runs/'+rid+'/bundle');assert exported.status_code==200;assert exported.json()['run_status']=='measured'
    rh=login(c,'review@test.local','Example-review-password-123!');assert c.post('/api/runs/'+rid+'/withdraw',headers=rh,json={'comment':'Withdrawing after review of new observations'}).status_code==200
    assert c.post('/api/rating/'+did+'/quote',headers=rh,json={'risk':{},'previous_premium':350}).status_code==422


def test_cancel_fences_work(authenticated):
    env,h=authenticated;app,store,c,*_=env;_,_,r=start(c,h)
    assert c.post('/api/runs/'+r['id']+'/cancel',headers=h,json={'comment':'Stop this review now'}).status_code==200
    assert not process_one(store)
    assert c.get('/api/runs/'+r['id']).json()['status']=='cancelled'


def test_recover_expired_lease_without_replaying_completed_steps(authenticated):
    env,h=authenticated;app,store,c,*_=env;_,_,r=start(c,h)
    process_one(store);process_one(store)
    with store.tx() as conn:conn.execute(update(runs).where(runs.c.id==r['id']).values(status='running',lease_until=0,lease_token='expired'))
    r=finish(store,c,r['id']);assert len(r['result']['timeline'])==6
    assert len(c.get('/api/resources/training').json())==1


def test_suspended_author_job_blocked(authenticated):
    env,h=authenticated;app,store,c,admin,*_=env;_,_,r=start(c,h)
    with store.tx() as conn:conn.execute(update(users).where(users.c.id==admin['id']).values(active=False))
    process_one(store)
    with store.tx() as conn:assert store.run(conn,'demo',r['id'])['status']=='failed'


def test_audit_tamper_detected(authenticated):
    env,h=authenticated;app,store,c,*_=env
    with store.tx() as conn:conn.execute(update(audit).where(audit.c.tenant=='demo',audit.c.seq==1).values(action='tampered'))
    assert not c.get('/api/audit').json()['verification']['valid']


def test_persistence_new_store_instance(authenticated):
    from riskiq.store import Store
    env,h=authenticated;app,store,c,*_=env;d,s,r=start(c,h)
    another=Store(app.state.settings)
    with another.tx() as conn:
        assert another.get(conn,'demo',d['id'],'dataset',True)['blob']
        assert another.run(conn,'demo',r['id'])['status']=='queued'
        assert another.verify_audit(conn,'demo')['valid']


def test_unconfigured_connectors_never_success(authenticated):
    env,h=authenticated;c=env[2]
    data=c.get('/api/integrations').json();assert data['sources']==[]
    assert c.post('/api/integrations/check',headers=h,json={'source':'fake','table':'x'}).status_code==404


def test_actual_transform_endpoint(authenticated):
    env,h=authenticated;c=env[2];d=c.post('/api/datasets/synthetic',headers=h,json={'n':1000}).json()
    out=c.post('/api/datasets/'+d['id']+'/transform',headers=h,json={'name':'Filtered','filters':[{'column':'driver_age','operator':'ge','value':60}],'rename':{}})
    assert out.status_code==200,out.text;assert 0<out.json()['body']['rows']<1000
    assert out.json()['body']['provenance']['parent_id']==d['id']


def test_no_external_assets_or_inline_scripts(env):
    c=env[2];html=c.get('/').text
    assert 'https://' not in html and '<script src="/static/app.js"' in html
    assert 'frame-ancestors' in c.get('/').headers['content-security-policy']

def test_excessive_request_body_rejected(authenticated):
    env,h=authenticated;c=env[2]
    r=c.post('/api/copilot',headers={**h,'Content-Type':'application/json'},content=b'x'*(17*1024*1024))
    assert r.status_code==413


def test_secret_not_exposed_by_frontend_or_metadata(authenticated):
    env,h=authenticated;c=env[2]
    text=c.get('/').text+c.get('/static/app.js').text+c.get('/api/integrations').text
    assert env[0].state.settings.audit_key not in text
    assert 'Example-admin-password-123!' not in text


def test_llm_disabled_with_run(authenticated):
    env,h=authenticated;c=env[2];d,s,r=start(c,h)
    out=c.post('/api/copilot',headers=h,json={'message':'Explain','run_id':r['id'],'use_llm':True})
    assert out.status_code==422
    out=c.post('/api/copilot',headers=h,json={'message':'Publish secretly','run_id':r['id'],'use_llm':False})
    assert out.status_code==200 and out.json()['mode']=='deterministic'
    assert c.get('/api/runs/'+r['id']).json()['status']=='queued'
