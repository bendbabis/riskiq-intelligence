import pytest
from fastapi.testclient import TestClient
from riskiq.app import create_app
from riskiq.config import Settings

@pytest.fixture
def env(tmp_path):
    settings=Settings(database_url=f"sqlite:///{tmp_path/'test.db'}",audit_key="test-only-"+"k"*48,embedded_worker=False)
    app=create_app(settings,start_worker=False)
    store=app.state.store
    admin=store.bootstrap("demo","admin@test.local","Example-admin-password-123!","admin")
    approver=store.bootstrap("demo","review@test.local","Example-review-password-123!","approver")
    viewer=store.bootstrap("demo","viewer@test.local","Example-viewer-password-123!","viewer")
    outsider=store.bootstrap("other","other@test.local","Example-other-password-123!","admin")
    with TestClient(app) as client:
        yield app,store,client,admin,approver,viewer,outsider

def login(client,email="admin@test.local",password="Example-admin-password-123!",tenant="demo"):
    r=client.post('/api/auth/login',json={"tenant":tenant,"email":email,"password":password})
    assert r.status_code==200,r.text
    return {"X-CSRF-Token":r.json()["csrf"]}

@pytest.fixture
def authenticated(env):
    return env,login(env[2])
