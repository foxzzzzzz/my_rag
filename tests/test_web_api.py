import sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tmp/web-deps'))
from fastapi.testclient import TestClient
from personalkb.web_app import create_app, load_web_config
from personalkb import workflow
from personalkb.web_service import WebService
class Fake:
    def start(self): pass
    def stop(self): pass
    def sources(self): return {"items":[]}
    def tasks(self): return {"items":[]}

class WebApiTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'tmp'; root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root); self.tmp_path=Path(self.temp.name)
        c=load_web_config(); c['trusted_hosts'].append('testserver'); c['frontend_dist']=str(self.tmp_path/'missing'); c['live_video_enabled']=True
        self.wc=workflow.load_config(); self.wc.update(data_dir=str(self.tmp_path/'data'),min_free_bytes=0,max_html_bytes=1024,max_upload_bytes=2048)
        self.service=WebService(self.wc,{},c,video_runner=lambda *a,**kw: self.calls.append(1)); self.calls=[]
        self.service.start=lambda:None; self.service.stop=lambda:None
        self.client=TestClient(create_app(self.wc,{},c,self.service)); self.client.__enter__()
        self.h={'x-csrf-token':self.client.get('/api/session').json()['csrf_token']}
    def tearDown(self):
        self.client.__exit__(None,None,None); self.temp.cleanup()
    def test_session_origin_csrf_and_host(self):
        tmp_path=self.tmp_path
        c=load_web_config(); c['trusted_hosts'].append('testserver'); c['frontend_dist']=str(tmp_path)
        wc={'quality_target':98,'max_upload_bytes':10,'max_html_bytes':5,'data_dir':str(tmp_path),'min_free_bytes':0}
        with TestClient(create_app(wc,None,c,Fake())) as client:
            assert client.get('/api/sources').status_code==401
            s=client.get('/api/session'); assert s.status_code==200
            assert 'httponly' in s.headers['set-cookie'].lower()
            token=s.json()['csrf_token']
            assert client.get('/api/sources').json()=={'items':[]}
            assert client.put('/api/imports?filename=x.html&rights_confirmed=true',content=b'x').status_code==403
            assert client.put('/api/imports?filename=x.html&rights_confirmed=true',content=b'x',headers={'x-csrf-token':token,'origin':'https://evil.example'}).status_code==403
            assert client.put('/api/imports?filename=x.html',content=b'x',headers={'x-csrf-token':token}).status_code==400
            assert client.put('/api/imports?filename=x.html&rights_confirmed=true',content=b'123456',headers={'x-csrf-token':token}).status_code==413
            assert client.put('/api/imports?filename=..%2Fx.html&rights_confirmed=true',content=b'x',headers={'x-csrf-token':token}).status_code==400
            assert client.get('/').status_code==503
            assert client.get('/api/sources',headers={'host':'evil.example'}).status_code==400

    def test_raw_html_duplicate_and_original(self):
        client,h=self.client,self.h
        url='/api/imports?filename=hello.html&rights_confirmed=true'
        a=client.put(url,content=b'<html><body>Hello<script>alert(1)</script></body></html>',headers=h)
        assert a.status_code==200, a.text
        b=client.put('/api/imports?filename=other.html&rights_confirmed=true',content=b'<html><body>Hello<script>alert(1)</script></body></html>',headers=h)
        assert b.json()['duplicate'] and b.json()['source_id']==a.json()['source_id']
        original=client.get('/api/sources/'+a.json()['source_id']+'/original')
        assert 'attachment' in original.headers['content-disposition']
        assert 'sandbox' in original.headers['content-security-policy']
        assert client.get('/api/sources').json()['items'][0]['original_name']=='hello.html'

    def test_oversize_creates_no_source(self):
        client,h=self.client,self.h
        assert client.put('/api/imports?filename=x.html&rights_confirmed=true',content=b'x'*1025,headers=h).status_code==413
        assert client.get('/api/sources').json()['items']==[]

    def test_bad_filename_rejected(self):
        client,h=self.client,self.h
        assert client.put('/api/imports?filename=..%5Cx.html&rights_confirmed=true',content=b'x',headers=h).status_code==400

    def test_bad_json_rejected(self):
        client,h=self.client,self.h
        assert client.post('/api/sources/foo/reviews',content='[]',headers=h).status_code==400

    def test_static_paths_rejected(self):
        client=self.client
        assert client.get('/assets/missing.js').status_code==404
        assert client.get('/secret.txt').status_code==404

    def test_unknown_source(self):
        client=self.client
        assert client.get('/api/sources/missing').status_code==404

    def test_video_cancel_retry_without_consent(self):
        obj=self.service.store.import_source('video','a'*64,'video.mp4','originals/'+('a'*64))
        tid=obj['task']['id']; base='/api/tasks/'+tid+'/'
        self.assertEqual(self.client.post(base+'start',json={'allow_paid':True},headers=self.h).status_code,200)
        self.assertEqual(self.client.post(base+'cancel',json={},headers=self.h).status_code,200)
        self.assertEqual(self.client.post(base+'retry',json={'allow_paid':False},headers=self.h).status_code,400)
        self.assertEqual(self.service.store.get_task(tid)['status'],'cancelled')
        self.assertIsNone(self.service.process_next()); self.assertEqual(self.calls,[])
        with self.service.store._tx() as db: self.assertEqual(db.execute("SELECT count(*) FROM web_dispatch WHERE state='pending'").fetchone()[0],0)

    def make_version(self):
        response=self.client.put('/api/imports?filename=review.html&rights_confirmed=true',content=b'<html><body>Review text</body></html>',headers=self.h)
        item=response.json(); workflow.run_once(self.wc,task_id=item['task_id'])
        detail=self.client.get('/api/sources/'+item['source_id']).json()
        return item['source_id'],detail['current']

    def test_low_score_approve_rejected(self):
        sid,v=self.make_version()
        payload=dict(version_id=v['id'],content_sha256=v['content_sha256'],score=50,decision='approve',reviewer='tester',review_id='r1')
        self.assertEqual(self.client.post('/api/sources/'+sid+'/reviews',json=payload,headers=self.h).status_code,400)

    def test_stale_review_rejected(self):
        sid,v=self.make_version()
        payload=dict(version_id='stale',content_sha256=v['content_sha256'],score=100,decision='approve',reviewer='tester',review_id='r1')
        self.assertEqual(self.client.post('/api/sources/'+sid+'/reviews',json=payload,headers=self.h).status_code,409)
    def test_config_rejects_nonfinite_and_fractional_integer(self):
        import json
        from personalkb.workflow_store import WorkflowError
        c=load_web_config(); path=self.tmp_path/'config.json'
        for key,value in [('max_sessions',1.5),('port',True),('dispatch_poll_seconds',float('nan'))]:
            bad=dict(c); bad[key]=value; path.write_text(json.dumps(bad),encoding='utf8')
            with self.assertRaises(WorkflowError): load_web_config(path)

    def test_oversized_json_no_mutation(self):
        response=self.client.post('/api/sources/missing/reviews',content=b' '+b'x'*(1024*1024+1),headers=self.h)
        self.assertEqual(response.status_code,413)
        self.assertEqual(self.client.get('/api/sources').json()['items'],[])

    def test_non_ascii_csrf_is_forbidden(self):
        response=self.client.post('/api/tasks/missing/start',content='{}',headers={b'x-csrf-token':bytes([233])})
        self.assertEqual(response.status_code,403)

    def test_second_tab_preserves_existing_csrf(self):
        token=self.h['x-csrf-token']
        self.assertEqual(self.client.get('/api/session').json()['csrf_token'],token)
        response=self.client.put('/api/imports?filename=multi.html&rights_confirmed=true',content=b'<html><body>multi tab</body></html>',headers=self.h)
        self.assertEqual(response.status_code,200)

def test_suggestion_api_security_and_apply(tmp_path):
    import json
    from personalkb.classification_suggestions import SuggestionService
    c=load_web_config(); c['trusted_hosts'].append('testserver')
    wc=workflow.load_config(); wc.update(data_dir=str(tmp_path/'data'),min_free_bytes=0)
    service=WebService(wc,{},c); service.start=lambda:None; service.stop=lambda:None
    sid=service.store.import_source('html','a'*64,'test','test')['source']['id']
    with service.store._tx() as db:
        db.execute('INSERT INTO versions(id,source_id,content_sha256,result,output_kind) VALUES(?,?,?,?,?)',('v',sid,'b'*64,json.dumps({'body':'test'}),'machine_initial'))
        db.execute('UPDATE sources SET current_version_id=? WHERE id=?',('v',sid))
    cfg=json.loads((Path(__file__).resolve().parents[1]/'config/classification-suggestions.json').read_text(encoding='utf-8-sig')); cfg['enabled']=True; cfg['budget']['ledger']=str(tmp_path/'ledger')
    calls=[]
    def fake(messages):
        calls.append(messages); return {'content':json.dumps({'existing_topics':[],'existing_tags':[],'new_topics':['AI'],'new_tags':[]})}
    service._suggestions=SuggestionService(service.store,cfg,lambda:fake)
    with TestClient(create_app(wc,{},c,service)) as client:
        path='/api/sources/'+sid+'/classification/suggestions'
        assert client.get(path).status_code==401
        token=client.get('/api/session').json()['csrf_token']; headers={'x-csrf-token':token}
        assert client.post(path,json={}).status_code==403
        assert client.post(path,headers=headers,json={'expected_version_id':'v','expected_revision':0}).status_code==400
        assert not calls
        r=client.post(path,headers=headers,json={'expected_version_id':'v','expected_revision':0,'allow_paid':True}); assert r.status_code==200,r.text
        suggestion=r.json(); assert client.get(path).json()['id']==suggestion['id']
        apply='/api/classification-suggestions/'+suggestion['id']+'/apply'
        r=client.post(apply,headers=headers,json={'existing_topics':[],'existing_tags':[],'confirmed_new_topics':['AI'],'confirmed_new_tags':[]}); assert r.status_code==200,r.text
        assert r.json()['receipt']['topics'][0]['name']=='AI'
