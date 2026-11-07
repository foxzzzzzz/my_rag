import json
import pytest
from fastapi.testclient import TestClient
from personalkb.web_app import create_app, load_web_config
from personalkb.web_auth import hash_password
from personalkb.workflow_store import WorkflowError

class Fake:
    def start(self): pass
    def stop(self): pass
    def sources(self): return {'items':[]}

@pytest.fixture
def setup(tmp_path):
    dist=tmp_path/'dist'; (dist/'assets').mkdir(parents=True)
    (dist/'index.html').write_text('<script src="/assets/app.js"></script><link rel="stylesheet" href="/assets/app.css">')
    for f in ('app.js','app.css','index-old.js'): (dist/'assets'/f).write_text('content')
    config=tmp_path/'auth.json'; config.write_text(json.dumps({'enabled':True,'password_hash_env':'TEST_AUTH_HASH','login_limit':5,'login_window_seconds':60,'api_limit':100,'api_window_seconds':60}))
    env=tmp_path/'private.env'; env.write_text('TEST_AUTH_HASH='+hash_password('correct horse',100000)+'\n')
    c=load_web_config(); c.update(deployment_mode='production',dispatch_enabled=False,host='127.0.0.1',trusted_hosts=['testserver'],trusted_origins=['https://testserver'],frontend_dist=str(dist),auth_config=str(config),env_file=str(env))
    wc={'quality_target':98,'max_upload_bytes':100,'max_html_bytes':100,'data_dir':str(tmp_path)}
    return c,wc

def test_public_and_login_flow(setup):
    c,wc=setup
    with TestClient(create_app(wc,None,c,Fake()),base_url='https://testserver') as client:
        assert client.get('/healthz').json()=={'ok':True}
        assert client.get('/').status_code==200
        assert client.get('/assets/app.js').status_code==200
        assert client.get('/assets/app.css').status_code==200
        assert client.get('/assets/index-old.js').status_code==401
        assert client.get('/api/session').status_code==401
        assert client.get('/api/sources').status_code==401
        assert client.post('/api/auth/login',json={'password':'correct horse'}).status_code==403
        h={'origin':'https://testserver'}
        assert client.post('/api/auth/login',content='{',headers=h).status_code==400
        assert client.post('/api/auth/login',json={'password':'wrong'},headers=h).status_code==401
        r=client.post('/api/auth/login',json={'password':'correct horse'},headers=h)
        assert r.status_code==200
        assert all(x in r.headers['set-cookie'].lower() for x in ('secure','httponly','samesite=strict'))
        token=client.get('/api/session').json()['csrf_token']
        assert client.get('/api/sources').status_code==200
        assert client.post('/api/auth/logout',headers=h).status_code==403
        assert client.post('/api/auth/logout',headers={**h,'x-csrf-token':token}).status_code==200
        assert client.get('/api/sources').status_code==401

def test_limit_and_restart(setup):
    c,wc=setup; app=create_app(wc,None,c,Fake()); h={'origin':'https://testserver'}
    with TestClient(app,base_url='https://testserver') as client:
        for _ in range(5): assert client.post('/api/auth/login',json={'password':'bad'},headers=h).status_code==401
        assert client.post('/api/auth/login',json={'password':'correct horse'},headers=h).status_code==429
    app=create_app(wc,None,c,Fake())
    with TestClient(app,base_url='https://testserver') as client:
        assert client.post('/api/auth/login',json={'password':'correct horse'},headers=h).status_code==200
        cookie=client.cookies.get('pkb_session')
    with TestClient(create_app(wc,None,c,Fake()),base_url='https://testserver') as client:
        client.cookies.set('pkb_session',cookie)
        assert client.get('/api/sources').status_code==401

def test_fail_closed(setup):
    c,wc=setup
    for changes in ({'trusted_origins':['http://testserver']},{'trusted_hosts':['*']},{'dispatch_enabled':True},{'env_file':'missing'}):
        with pytest.raises(WorkflowError): create_app(wc,None,{**c,**changes},Fake())

def test_rotation_csrf_host_and_https(setup):
    c,wc=setup; h={'origin':'https://testserver'}
    with TestClient(create_app(wc,None,c,Fake()),base_url='https://testserver') as client:
        assert client.get('/api/auth/status',headers={'host':'testserver:9999'}).status_code==400
        assert client.get('http://testserver/api/sources').status_code==403
        assert client.post('/api/auth/login',json={'password':'correct horse'},headers=h).status_code==200
        old=client.cookies.get('pkb_session'); old_token=client.get('/api/session').json()['csrf_token']
        assert client.post('/api/auth/login',json={'password':'correct horse'},headers=h).status_code==200
        new=client.cookies.get('pkb_session'); assert old != new
        new_token=client.get('/api/session').json()['csrf_token']; assert old_token != new_token
        assert client.post('/api/auth/logout',headers={'origin':'https://evil.example','x-csrf-token':new_token}).status_code==403
        assert client.post('/api/auth/logout',headers={**h,'x-csrf-token':old_token}).status_code==403
        assert client.get('/api/sources',headers={'cookie':'pkb_session='+old}).status_code==401

def test_private_cache_headers_and_public_write(setup):
    c,wc=setup
    with TestClient(create_app(wc,None,c,Fake()),base_url='https://testserver') as client:
        for response in (client.get('/assets/index-old.js'), client.get('/api/sources'),
                         client.post('/',headers={'origin':'https://testserver'}),
                         client.get('http://testserver/api/sources'),
                         client.post('/api/auth/login',json={'password':'bad'},headers={'origin':'https://testserver'})):
            assert response.status_code in (401,403)
            assert response.headers['cache-control']=='no-store'
        assert client.post('/api/auth/login',json={'password':'correct horse'},headers={'origin':'https://testserver'}).status_code==200
        response=client.get('/assets/index-old.js')
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
