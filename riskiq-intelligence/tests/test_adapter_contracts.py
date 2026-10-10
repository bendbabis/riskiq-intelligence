"""Provider-response simulations only; these are explicitly NOT live cloud tests."""
import json
import httpx
import pytest
from riskiq.adapters import Adapter,identifier

@pytest.fixture(autouse=True)
def token(monkeypatch):monkeypatch.setenv('RISKIQ_SOURCE_TEST','not-a-live-token')

def config(provider,table='PUBLIC.PORTFOLIO'):
    return {'provider':provider,'host':'https://provider.example','token_env':'RISKIQ_SOURCE_TEST','tables':[table],'warehouse_id':'warehouse','warehouse':'TEST'}

def test_databricks_success_and_chunks():
    def handler(req):
        if req.method=='POST':return httpx.Response(200,json={'statement_id':'sid','status':{'state':'SUCCEEDED'},'manifest':{'schema':{'columns':[{'name':'a'}]}},'result':{'data_array':[['1']],'next_chunk_index':1}})
        return httpx.Response(200,json={'data_array':[['2']]})
    a=Adapter(config('databricks'),httpx.Client(transport=httpx.MockTransport(handler)))
    assert a.read('PUBLIC.PORTFOLIO').a.tolist()==['1','2']

def test_databricks_http_200_failed_is_not_success():
    a=Adapter(config('databricks'),httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'statement_id':'sid','status':{'state':'FAILED'}}))))
    with pytest.raises(ValueError):a.read('PUBLIC.PORTFOLIO')

def test_databricks_truncation_rejected():
    a=Adapter(config('databricks'),httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'statement_id':'sid','status':{'state':'SUCCEEDED'},'manifest':{'truncated':True}}))))
    with pytest.raises(ValueError,match='Truncated'):a.read('PUBLIC.PORTFOLIO')

def test_snowflake_async_partitioned(monkeypatch):
    monkeypatch.setattr('riskiq.adapters.time.sleep',lambda x:None)
    def handler(req):
        if req.method=='POST':return httpx.Response(202,json={'statementHandle':'abc'})
        if req.url.params.get('partition')=='1':return httpx.Response(200,json={'data':[['2']]})
        return httpx.Response(200,json={'resultSetMetaData':{'rowType':[{'name':'a'}],'partitionInfo':[{},{}]},'data':[['1']]})
    a=Adapter(config('snowflake'),httpx.Client(transport=httpx.MockTransport(handler)))
    assert a.read('PUBLIC.PORTFOLIO').a.tolist()==['1','2']

def test_palantir_csv_read():
    table='ri.foundry.main.dataset.abc-123'
    def handler(req):
        assert req.url.path.endswith('/readTable') and req.url.params['format']=='CSV'
        return httpx.Response(200,content=b'policy_id,exposure\nP1,0.5\n')
    a=Adapter(config('palantir',table),httpx.Client(transport=httpx.MockTransport(handler)))
    assert a.read(table).exposure.iloc[0]==.5

@pytest.mark.parametrize('table',['x; DROP TABLE users','a..b','x--abc','https://evil.invalid/table'])
def test_sql_injection_identifiers_blocked(table):
    with pytest.raises(ValueError):identifier(table,'postgres')

def test_table_allowlist_checked_before_request():
    a=Adapter(config('snowflake'))
    with pytest.raises(PermissionError):a.read('UNAPPROVED.DATA')

def test_no_arbitrary_http_hosts():
    with pytest.raises(ValueError):Adapter({**config('palantir'),'host':'http://169.254.169.254'})

def test_http_error_does_not_leak_secret():
    a=Adapter(config('snowflake'),httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(403,text='not-a-live-token'))))
    with pytest.raises(ValueError) as exc:a.read('PUBLIC.PORTFOLIO')
    assert 'not-a-live-token' not in str(exc.value)

def test_bigquery_sdk_contract(monkeypatch):
    import sys,types
    module=types.ModuleType('google.cloud.bigquery')
    class Config:
        def __init__(self,**kw):self.kw=kw
    class Job:
        def result(self,timeout):assert timeout==60;return [{'policy_id':'a','exposure':.5}]
    class Client:
        def __init__(self,project):assert project=='test-project'
        def query(self,sql,job_config,location):
            assert 'LIMIT 100001' in sql and job_config.kw['maximum_bytes_billed']==1234 and location=='EU'
            return Job()
        def close(self):pass
    module.Client=Client;module.QueryJobConfig=Config
    monkeypatch.setitem(sys.modules,'google.cloud.bigquery',module)
    cloud=types.ModuleType('google.cloud');cloud.bigquery=module
    monkeypatch.setitem(sys.modules,'google.cloud',cloud)
    a=Adapter({'provider':'bigquery','project':'test-project','tables':['test-project.pricing.policies'],'maximum_bytes_billed':1234})
    assert a.read('test-project.pricing.policies').exposure.iloc[0]==.5
