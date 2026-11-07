import io
import json
from email.message import Message
import pytest
from tools import cloud_acceptance as ca


class Response:
    def __init__(self, status, obj, cookie=None):
        self.status=status; self.data=json.dumps(obj).encode(); self.headers=Message()
        if cookie: self.headers.add_header('Set-Cookie', cookie)
    def read(self, n): return self.data[:n]
    def __enter__(self): return self
    def __exit__(self,*args): pass

class Fake:
    def __init__(self, redirect=False): self.logged=False; self.redirect=redirect; self.calls=[]
    def open(self,req,timeout):
        path=req.full_url.removeprefix('https://example.test'); self.calls.append((path,req.method))
        if self.redirect: return Response(302,{})
        if path == '/api/session': return Response(200,{'csrf_token':'csrf-secret'}) if self.logged else Response(401,{})
        if path == '/api/auth/login':
            assert req.get_header('Origin') == 'https://example.test'; assert json.loads(req.data)['password']=='test-secret'
            self.logged=True; return Response(200,{},'pkb_session=cookie-secret; Secure; HttpOnly; SameSite=Strict')
        if path == '/api/sources': return Response(200,{'items':[{'id':'secret-source-id','title':'private-content'}]})
        if path == '/api/rag/status': return Response(200,{'ready':True,'space_id':'secret-space-id','indexed_chunks':3})
        if path == '/api/auth/logout':
            if not req.get_header('X-csrf-token'): return Response(403,{})
            assert req.get_header('X-csrf-token') == 'csrf-secret'; self.logged=False; return Response(200,{})
        return Response(404,{})

@pytest.fixture
def config(tmp_path):
    return {'allowed_origin':'https://example.test','request_timeout_seconds':1,'max_response_bytes':10000,'max_sample_seconds':300,'sample_interval_seconds':1,'disk_path':str(tmp_path),'protected_historical_path':None}


def test_authenticated_read_only_flow_and_sanitized_report(config,monkeypatch):
    monkeypatch.setattr(ca,'host_info',lambda c: {})
    fake=Fake(); result=ca.run(config,'https://example.test','test-secret',opener=fake)
    assert result['result']=='passed' and result['checks']['source_count']==1
    assert result['checks']['logout_without_csrf']==403 and result['checks']['session_after_logout']==401
    text=json.dumps(result); assert all(s not in text for s in ('test-secret','cookie-secret','csrf-secret','private-content','secret-source-id','secret-space-id'))
    assert all('build' not in p and 'answer' not in p and 'search' not in p for p,_ in fake.calls)
    assert result['paid_end_to_end']=='not_tested' and result['external_backup_restore']=='not_tested'


def test_redirect_rejected_before_password(config,monkeypatch):
    monkeypatch.setattr(ca,'host_info',lambda c:{})
    fake=Fake(redirect=True); report=ca.run(config,'https://example.test','test-secret',opener=fake)
    assert report['error']=='redirect_rejected' and fake.calls == [('/api/session','GET')]


def test_unconfigured_origin_rejected_and_response_bounded(config,monkeypatch):
    with pytest.raises(ValueError,match='invalid_origin'): ca.run(config,'https://attacker.test','test-secret',opener=Fake())
    monkeypatch.setattr(ca,'host_info',lambda c:{})
    config['max_response_bytes']=2
    report=ca.run(config,'https://example.test','test-secret',opener=Fake())
    assert report['result']=='failed' and report['error']=='response_too_large'
