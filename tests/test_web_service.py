import json, tempfile, unittest
from pathlib import Path
from personalkb.workflow import load_config, import_file, run_once
from personalkb.workflow_store import WorkflowError
from personalkb.web_service import WebService

TMP=Path(__file__).resolve().parents[1]/'tmp'
TMP.mkdir(exist_ok=True)
class WebServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=TMP); self.root=Path(self.tmp.name)
        self.wc=load_config(); self.wc['data_dir']=str(self.root/'data')
        self.s=WebService(self.wc,{}, {'live_video_enabled':False,'dispatch_recovery_seconds':0,'dispatch_poll_seconds':1,'shutdown_timeout_seconds':1})
        p=self.root/'test.html'; p.write_text('<html><title>Hello</title><body>World</body></html>',encoding='utf8')
        imported=import_file(self.wc,p,True); self.sid=imported['source']['id']; self.tid=imported['task']['id']
    def tearDown(self): self.tmp.cleanup()
    def finish(self): run_once(self.wc,task_id=self.tid); return self.s.detail(self.sid)['current']
    def test_selected_task(self):
        p=self.root/'other.html'; p.write_text('<html><body>Other</body></html>',encoding='utf8'); other=import_file(self.wc,p,True)
        run_once(self.wc,task_id=other['task']['id'])
        self.assertEqual(self.s.store.get_task(self.tid)['status'],'queued')
    def test_sources_and_hidden_fields(self):
        self.finish(); text=json.dumps(self.s.detail(self.sid))+json.dumps(self.s.tasks())+json.dumps(self.s.sources())
        for field in ('lease_token','blob_relpath','worker_id','remote_task_id'): self.assertNotIn(field,text)
    def test_task_source_metadata_survives_trash(self):
        self.finish()
        before = self.s.tasks()['items'][0]
        self.assertEqual(before['source']['id'], self.sid)
        self.assertEqual(before['source']['original_name'], 'test.html')
        self.assertEqual(before['source']['title'], 'Hello')
        self.assertEqual(before['source']['kind'], 'html')
        self.assertFalse(before['source']['deleted'])
        self.s.store.delete_source(self.sid)
        after = self.s.tasks()['items'][0]
        self.assertEqual(after['source']['title'], 'Hello')
        self.assertTrue(after['source']['deleted'])
        self.assertNotIn('blob_relpath', after['source'])
    def test_review_revoke(self):
        v=self.finish(); p=dict(version_id=v['id'],content_sha256=v['content_sha256'],score=99,decision='approve',reviewer='A',review_id='1')
        self.assertTrue(self.s.review(self.sid,p)['eligible']); p.update(decision='reject',review_id='2'); self.assertFalse(self.s.review(self.sid,p)['eligible']); self.assertEqual(self.s.detail(self.sid)['review']['decision'],'reject')
    def test_douyin_title_consistent_in_library_detail_and_tasks(self):
        template = self.finish()['result']
        store = self.s.store
        filename = 'douyin-123.mp4'
        entry = store.import_source('video', 'd'*64, filename, 'originals/test.mp4')
        source_id = entry['source']['id']
        task = store.claim_specific(entry['task']['id'], 'test')
        version = store.finish(task['id'], task['lease_token'], {
            **template, 'title': filename, 'transcript': '语音示例', 'visual': '画面示例',
        })

        def titles():
            return [
                next(item['title'] for item in self.s.sources()['items'] if item['id']==source_id),
                self.s.detail(source_id)['source']['title'],
                next(item['source']['title'] for item in self.s.tasks()['items'] if item['id']==task['id']),
            ]

        self.assertEqual(titles(), [filename]*3)
        with store._tx() as c:
            c.execute('INSERT INTO source_display_titles VALUES (?,?)', (source_id,'平台标题'))
        self.assertEqual(titles(), ['平台标题']*3)
        self.assertEqual(self.s.detail(source_id)['current']['result']['title'], filename)
        self.s.revise(source_id, {'expected_version_id':version['id'], 'title':'人工标题'})
        self.assertEqual(titles(), ['人工标题']*3)
    def test_approval_queues_index_and_worker_makes_evidence_retrievable(self):
        from personalkb.rag_index import RagIndex, load_rag_config

        class Embeddings:
            def embed(self, texts, **kwargs):
                self.calls.append(texts)
                return {'model': 'text-embedding-v4', 'vectors': [[1.0, 0.0] for _ in texts]}

        v = self.finish()
        provider = Embeddings()
        provider.calls = []
        cfg = load_rag_config()
        cfg['embedding']['dimensions'] = 2
        self.s._rag = RagIndex(self.s.store, cfg, provider)
        payload = dict(version_id=v['id'], content_sha256=v['content_sha256'],
                       score=99, decision='approve', reviewer='A')
        self.s.review(self.sid, payload)
        pending = self.s.rag_status()
        self.assertEqual(pending['eligible_source_ids'], [self.sid])
        self.assertEqual(pending['indexed_source_ids'], [])
        self.assertEqual(pending['auto_index']['state'], 'queued')
        self.assertEqual(provider.calls, [])
        self.s.process_next()
        self.assertEqual(self.s.rag_status()['indexed_source_ids'], [self.sid])
        hit = self.s.rag.query('World', mode='lexical')[0]
        self.assertEqual(hit['version_id'], v['id'])
        self.assertEqual(len(provider.calls), 1)
    def test_revision_rejects_old_review(self):
        v=self.finish(); self.s.revise(self.sid,{'expected_version_id':v['id'],'body':'Edited'})
        with self.assertRaises(WorkflowError): self.s.review(self.sid,dict(version_id=v['id'],content_sha256=v['content_sha256'],score=99,decision='approve',reviewer='A'))
    def test_export(self):
        v=self.finish(); data,name=self.s.export(v['id']); self.assertIn(v['content_sha256'].encode(),data); self.assertTrue(name.endswith('.md'))
    def test_original_and_delete(self):
        self.assertEqual(self.s.original(self.sid)[1],'html'); self.s.store.delete_source(self.sid)
        with self.assertRaises(WorkflowError): self.s.original(self.sid)
    def test_frame_missing(self):
        self.finish()
        with self.assertRaises(WorkflowError): self.s.frame(self.sid,0)
    def test_score_validation(self):
        v=self.finish()
        with self.assertRaises(WorkflowError): self.s.review(self.sid,dict(version_id=v['id'],content_sha256=v['content_sha256'],score=True,decision='approve',reviewer='A'))

    def test_dispatch_only_confirmed_and_duplicate(self):
        p=self.root/'other.html'; p.write_text('<html><body>Other</body></html>',encoding='utf8'); other=import_file(self.wc,p,True)
        self.assertFalse(self.s.enqueue(other['task']['id'])['duplicate']); self.assertTrue(self.s.enqueue(other['task']['id'])['duplicate'])
        self.assertEqual(self.s.process_next()['dispatch_state'],'done'); self.assertIsNone(self.s.process_next()); self.assertEqual(self.s.store.get_task(self.tid)['status'],'queued')
    def test_disabled_video(self):
        source=self.s.store.import_source('video','a'*64,'movie.mp4','originals/'+('a'*64))
        with self.assertRaises(WorkflowError): self.s.enqueue(source['task']['id'],allow_paid=True)
    def test_paid_consent(self):
        self.s.webcfg['live_video_enabled']=True
        source=self.s.store.import_source('video','a'*64,'movie.mp4','originals/'+('a'*64))
        with self.assertRaises(WorkflowError): self.s.enqueue(source['task']['id'])
    def test_stale_unknown_not_replayed(self):
        self.s.webcfg['live_video_enabled']=True; calls=[]; self.s.video_runner=lambda *a,**kw:calls.append(kw)
        source=self.s.store.import_source('video','a'*64,'movie.mp4','originals/'+('a'*64)); tid=source['task']['id']
        self.s.enqueue(tid,allow_paid=True)
        with self.s.store._tx() as c:
            c.execute("UPDATE tasks SET status='needs_attention',external_started=1 WHERE id=?",(tid,)); c.execute("UPDATE web_dispatch SET state='working',claimed=0 WHERE task_id=?",(tid,))
        self.assertIsNone(self.s.process_next()); self.assertEqual(calls,[])
    def test_frame_hash_mismatch(self):
        import hashlib
        source=self.s.store.import_source('video','b'*64,'movie.mp4','originals/'+('b'*64)); tid=source['task']['id']; sid=source['source']['id']
        task=self.s.store.claim_specific(tid,'test'); token=task['lease_token']
        result=dict(title='T',body='B',summary='S',notes='N',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='provider',evidence=[{'text':'e'}],transcript='t',visual='v',frames=[{'index':0,'seconds':0,'sha256':hashlib.sha256(b'original').hexdigest()}])
        self.s.store.finish(tid,token,result)
        folder=self.root/'data'/'video-work'/tid; folder.mkdir(parents=True); (folder/'frame.jpg').write_bytes(b'changed')
        (folder/'media-manifest.json').write_text(json.dumps({'frames':[{'index':0,'file':'frame.jpg','sha256':result['frames'][0]['sha256']}]}),encoding='utf8')
        with self.assertRaises(WorkflowError): self.s.frame(sid,0)
    def test_pending_dispatch_survives_restart(self):
        self.s.enqueue(self.tid)
        restarted=WebService(self.wc,{},self.s.webcfg)
        self.assertEqual(restarted.process_next()['dispatch_state'],'done')
        self.assertIsNone(restarted.process_next())
        self.assertEqual(restarted.store.get_task(self.tid)['attempts'],1)
    def test_stale_working_queued_dispatch_recovers(self):
        self.s.enqueue(self.tid)
        with self.s.store._tx() as c:
            c.execute("UPDATE web_dispatch SET state='working',claimed=0,owner='old' WHERE task_id=?",(self.tid,))
        restarted=WebService(self.wc,{},self.s.webcfg)
        self.assertEqual(restarted.process_next()['dispatch_state'],'done')
        self.assertEqual(restarted.store.get_task(self.tid)['attempts'],1)
    def test_expired_external_dispatch_requires_attention(self):
        self.s.webcfg['live_video_enabled']=True
        source=self.s.store.import_source('video','c'*64,'movie.mp4','originals/'+('c'*64)); tid=source['task']['id']
        self.s.enqueue(tid,allow_paid=True)
        with self.s.store._tx() as c:
            c.execute("UPDATE tasks SET status='running',external_started=1,lease_until=0,lease_token='old',worker_id='old' WHERE id=?",(tid,))
            c.execute("UPDATE web_dispatch SET state='working',claimed=0,owner='old' WHERE task_id=?",(tid,))
        calls=[]; restarted=WebService(self.wc,{},self.s.webcfg,video_runner=lambda *a,**kw:calls.append(kw))
        self.assertIsNone(restarted.process_next()); self.assertEqual(calls,[])
        self.assertEqual(restarted.store.get_task(tid)['status'],'needs_attention')
        with restarted.store._tx() as c:
            self.assertEqual(c.execute('SELECT state FROM web_dispatch WHERE task_id=?',(tid,)).fetchone()[0],'error')
