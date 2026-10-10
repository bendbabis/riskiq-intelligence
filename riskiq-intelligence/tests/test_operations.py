"""Additional operations and malformed-request regression tests."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from riskiq.config import Settings
from riskiq.store import Store, users


def test_password_rotation_revokes_sessions(authenticated):
    (app, store, client, admin, *_), headers=authenticated
    store.reset_password('demo',admin['email'],'New-test-password-example-456!')
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={'email':admin['email'],'password':'Example-admin-password-123!'}).status_code==401
    assert client.post('/api/auth/login',json={'email':admin['email'],'password':'New-test-password-example-456!'}).status_code==200
    with store.tx() as c:
        assert store.verify_audit(c,'demo')['valid']


def test_password_rotation_cannot_target_other_tenant(env):
    store=env[1]
    with pytest.raises(KeyError): store.reset_password('other','admin@test.local','Long-test-password-example-789!')


@pytest.mark.parametrize('payload',[
    {'risk':{'driver_age':[10]},'previous_premium':100},
    {'risk':{'driver_age':30},'previous_premium':None},
    {'risk':{},'previous_premium':100},
    {'risk':{'driver_age':30},'previous_premium':-1},
    {'risk':{'driver_age':30},'previous_premium':100,'role':'admin'},
])
def test_quote_contract_rejects_malformed_inputs(authenticated,payload):
    (_,_,client,*_),headers=authenticated
    assert client.post('/api/rating/any/quote',headers=headers,json=payload).status_code==422


def test_consistent_backup_restore_and_no_overwrite(env,tmp_path):
    _,store,_,admin,*_=env
    path=Path(__file__).parents[1]/'scripts/backup_sqlite.py'
    spec=importlib.util.spec_from_file_location('backup_tool',path)
    tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
    source=Path(store.engine.url.database);destination=tmp_path/'recovery.db'
    result=tool.backup(source,destination)
    assert result['integrity']=='ok' and result['bytes']>0
    with pytest.raises(FileExistsError):tool.backup(source,destination)
    restored=Store(Settings(database_url=f'sqlite:///{destination}',audit_key=store.settings.audit_key,embedded_worker=False))
    with restored.tx() as c:
        assert restored.verify_audit(c,'demo')['valid']
        assert c.execute(select(users.c.email).where(users.c.id==admin['id'])).scalar_one()==admin['email']
    restored.engine.dispose()
