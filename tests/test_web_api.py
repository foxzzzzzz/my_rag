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

    def test_trash_hides_source_and_restores_existing_review(self):
        from personalkb.execution_guard import execution_guard

        sid, version = self.make_version()
        self.service.store.review(sid, version['id'], version['content_sha256'], 99, 'approve', 'tester')
        original = self.service.original(sid)[0]
        restore = f'/api/trash/{sid}/restore'
        assert self.client.delete(f'/api/sources/{sid}', headers=self.h).status_code == 200
        assert self.client.get('/api/sources').json()['items'] == []
        assert self.service.store.eligible_sources() == []
        assert original.is_file()
        trash = self.client.get('/api/trash').json()
        assert trash['retention_days'] == 7
        item, = trash['items']
        assert item['id'] == sid and item['can_restore'] is True
        assert self.client.delete(f'/api/sources/{sid}', headers=self.h).status_code == 200
        assert self.client.get('/api/trash').json()['items'] == [item]
        assert self.client.post(restore, json={}).status_code == 403
        with execution_guard(self.service.store):
            assert self.client.post(restore, json={}, headers=self.h).json()['error'] == 'worker_busy'
        assert self.service.store.get_source(sid)['deleted'] == 1
        assert self.client.post(restore, json={}, headers=self.h).status_code == 200
        assert self.client.get('/api/trash').json()['items'] == []
        assert self.service.store.eligible_sources()[0]['current_version_id'] == version['id']
        assert self.client.get(f'/api/sources/{sid}').json()['review']['score'] == 99

    def test_expired_trash_cannot_restore(self):
        import time
        sid, _ = self.make_version()
        self.service.store.delete_source(sid)
        with self.service.store._tx() as db:
            db.execute('UPDATE source_trash SET deleted_at=? WHERE source_id=?',
                       (time.time()-self.service.store.trash_retention_seconds, sid))
        item, = self.client.get('/api/trash').json()['items']
        assert item['can_restore'] is False
        result = self.client.post(f'/api/trash/{sid}/restore', json={}, headers=self.h)
        assert result.json()['error'] == 'trash_expired'
        assert self.service.store.get_source(sid)['deleted']

    def test_legacy_deleted_source_gets_full_grace_on_upgrade(self):
        from datetime import datetime, timedelta

        sid, _ = self.make_version()
        with self.service.store._tx() as db:
            db.execute('UPDATE sources SET deleted=1 WHERE id=?', (sid,))
        workflow.make_store(self.wc)
        item, = self.client.get('/api/trash').json()['items']
        assert item['id'] == sid and item['can_restore'] is True
        assert datetime.fromisoformat(item['expires_at']) - datetime.fromisoformat(item['deleted_at']) == timedelta(days=7)
        workflow.make_store(self.wc)
        assert self.client.get('/api/trash').json()['items'] == [item]

    def test_video_cancel_retry_without_consent(self):
        obj=self.service.store.import_source('video','a'*64,'video.mp4','originals/'+('a'*64))
        tid=obj['task']['id']; base='/api/tasks/'+tid+'/'
        self.assertEqual(self.client.post(base+'start',json={'allow_paid':True},headers=self.h).status_code,200)
        self.assertEqual(self.client.post(base+'cancel',json={},headers=self.h).status_code,200)
        self.assertEqual(self.client.post(base+'retry',json={'allow_paid':False},headers=self.h).status_code,400)
        self.assertEqual(self.service.store.get_task(tid)['status'],'cancelled')
        self.assertIsNone(self.service.process_next()); self.assertEqual(self.calls,[])
        with self.service.store._tx() as db: self.assertEqual(db.execute("SELECT count(*) FROM web_dispatch WHERE state='pending'").fetchone()[0],0)

    def test_unknown_html_archive_preserves_task_and_blocks_resume(self):
        from personalkb.video_journal import VideoJournal
        from tools.api_smoke import reserve

        self.service.webcfg['live_html_enabled'] = True
        store = self.service.store
        task_id = store.import_source('html', 'a'*64, 'drill.html', 'originals/drill')['task']['id']
        ledger = self.tmp_path/'budget.sqlite'
        reserve(ledger, task_id, task_id+':html-text', '0.75', '2', '100')
        budget_before = ledger.read_bytes()
        path = f'/api/tasks/{task_id}/'
        assert self.client.post(path+'archive', json={}, headers=self.h).status_code == 409
        VideoJournal(store)
        with store._tx() as db:
            db.execute("UPDATE tasks SET status='needs_attention',external_started=1,attempts=1 WHERE id=?", (task_id,))
            db.execute("INSERT INTO video_stages(task_id,name,status) VALUES(?,'html-text','in_flight')", (task_id,))
        before = store.get_task(task_id)

        def visible_state():
            return self.client.get('/api/tasks').json()['items'][0]

        assert visible_state()['resume_blocked_reason'] == 'unknown_submission'
        consent = {'processing_mode':'model', 'allow_paid':True}
        assert self.client.post(path+'resume', json=consent, headers=self.h).json()['error'] == 'unknown_submission'
        for _ in range(2):
            assert self.client.post(path+'archive', json={}, headers=self.h).json()['archived'] is True
        assert visible_state()['archived'] is True
        assert self.client.post(path+'resume', json=consent, headers=self.h).json()['error'] == 'task_archived'
        assert self.client.post(path+'unarchive', json={}, headers=self.h).json()['archived'] is False
        assert visible_state()['archived'] is False
        assert visible_state()['dispatch'] is None
        assert store.get_task(task_id) == before
        assert ledger.read_bytes() == budget_before

    def test_video_with_queryable_asr_can_resume_after_unarchive(self):
        from personalkb.video_journal import VideoJournal

        store = self.service.store
        task_id = store.import_source('video', 'a'*64, 'clip.mp4', 'originals/clip')['task']['id']
        VideoJournal(store)
        with store._tx() as db:
            db.execute("UPDATE tasks SET status='needs_attention',external_started=1 WHERE id=?", (task_id,))
            db.execute("INSERT INTO video_stages(task_id,name,status,remote_task_id) VALUES(?,'asr_submit','in_flight','remote-asr')", (task_id,))
        path = f'/api/tasks/{task_id}/'
        assert self.client.get('/api/tasks').json()['items'][0]['resume_blocked_reason'] is None
        assert self.client.post(path+'archive', json={}, headers=self.h).status_code == 200
        assert self.client.post(path+'unarchive', json={}, headers=self.h).status_code == 200
        assert self.client.post(path+'resume', json={'allow_paid':True}, headers=self.h).status_code == 200
        assert self.client.post(path+'archive', json={}, headers=self.h).status_code == 409

    def test_finished_tasks_can_archive_without_changing_task_or_source(self):
        sid, version = self.make_version()
        store = self.service.store
        done = next(task for task in store.list_tasks() if task['source_id'] == sid)
        assert done['status'] == 'succeeded'
        source = store.get_source(sid)
        jobs = [done]
        with store._tx() as db:
            for status in ('failed', 'cancelled'):
                db.execute('INSERT INTO tasks(id,source_id,status) VALUES(?,?,?)', (status, sid, status))
                jobs.append(store._row(db, 'tasks', status))

        def task_state(task_id):
            return next(task for task in self.client.get('/api/tasks').json()['items'] if task['id'] == task_id)

        for task in jobs:
            task_id = task['id']
            path = f'/api/tasks/{task_id}/'
            assert task_state(task_id)['can_archive'] is True
            assert self.client.post(path+'archive', json={}, headers=self.h).json()['archived'] is True
            assert task_state(task_id)['archived'] is True
            if task['status'] != 'succeeded':
                assert self.client.post(path+'retry', json={}, headers=self.h).json()['error'] == 'task_archived'
            assert self.client.post(path+'unarchive', json={}, headers=self.h).json()['archived'] is False
            assert task_state(task_id)['can_archive'] is True
            assert store.get_task(task_id) == task
            assert task_state(task_id)['dispatch'] is None
        assert store.get_source(sid) == source
        assert store.get_version(version['id'])['content_sha256'] == version['content_sha256']

    def test_archive_rejects_active_tasks_and_dispatches(self):
        store = self.service.store
        task_id = store.import_source('html', 'd'*64, 'active.html', 'originals/active')['task']['id']
        path = f'/api/tasks/{task_id}/archive'
        for status, dispatch in (('queued', None), ('running', None), ('succeeded', 'working'), ('failed', 'pending')):
            with store._tx() as db:
                db.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))
                if dispatch:
                    db.execute("INSERT OR REPLACE INTO web_dispatch(task_id,mode,state,requested) VALUES(?,'run',?,0)", (task_id, dispatch))
            assert self.client.get('/api/tasks').json()['items'][0]['can_archive'] is False
            assert self.client.post(path, json={}, headers=self.h).status_code == 409

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

    def test_source_review_revision_changes_on_new_review_but_not_idempotent_retry(self):
        sid,version=self.make_version()
        path=f'/api/sources/{sid}/reviews'
        payload=dict(version_id=version['id'],content_sha256=version['content_sha256'],
                     score=100,decision='approve',reviewer='tester',review_id='first')

        def source():
            return self.client.get('/api/sources').json()['items'][0]

        assert source()['review_revision'] is None
        assert self.client.post(path,json=payload,headers=self.h).status_code==200
        first=source()
        payload['review_id']='second'
        assert self.client.post(path,json=payload,headers=self.h).status_code==200
        second=source()
        assert first['eligible'] and second['eligible']
        assert first['current_version_id']==second['current_version_id']==version['id']
        assert second['review_revision']>first['review_revision']
        assert self.client.post(path,json=payload,headers=self.h).status_code==200
        assert source()['review_revision']==second['review_revision']

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
