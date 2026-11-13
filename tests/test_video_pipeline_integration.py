import hashlib, json, sqlite3, tempfile, time, unittest
from contextlib import closing
from pathlib import Path
from personalkb.asr_storage import PreparedAudio, StorageError
from personalkb.asr_storage_temporary import TemporaryStorage
from personalkb.workflow import make_store
from personalkb.workflow_store import WorkflowError
from personalkb.video_journal import VideoJournal
from personalkb.video_pipeline import _bind_strategy, _digest, load_pipeline_config, run_video, cleanup_video, video_status
from tools.api_smoke import reserve

class FakeStorage:
    def prepare(self,path,model):
        data=Path(path).read_bytes()
        return PreparedAudio('temporary',model,'asset1',hashlib.sha256(data).hexdigest(),len(data),time.time()+3600,'https://secret.example/private?token=secret')

class FakeServices:
    def __init__(self): self.submit_count=0; self.query_count=0; self.vision_count=0; self.mode=''; self.cancel=None
    def submit_asr(self,asset):
        self.submit_count+=1
        if self.cancel: self.cancel()
        if self.mode=='submit': raise TimeoutError()
        return 'remote-1'
    def query_asr(self,ident):
        self.query_count+=1
        if self.mode=='query': self.mode=''; raise TimeoutError()
        if self.mode=='subtask_failed': return {'task_status':'SUCCEEDED','results':[{'subtask_status':'FAILED'}]}
        return {'task_status':'SUCCEEDED','results':[{'subtask_status':'SUCCEEDED','transcription_url':'https://unused'}]}
    def download_asr(self,url,seconds): return {'text':'spoken', 'segments':[{'text':'spoken','start':0,'end':1}]}
    def vision(self,path):
        self.vision_count+=1
        if self.mode=='vision': raise TimeoutError()
        return {'content':'visual','model':'fake','estimated_cost_cny':0}
    def summarize(self,body,title): return {'structured':{'summary':'summary','notes':'notes'},'content':'notes','model':'fake','estimated_cost_cny':0}

def media(source,work,wc,pc,*,heartbeat):
    heartbeat(); audio=work/'audio.wav'; audio.write_bytes(b'audio'); frame=work/'frame.jpg'
    payload = ('jpeg-' + work.name).encode()
    frame.write_bytes(payload)
    frame_metadata = {'index':0,'seconds':0,'sha256':hashlib.sha256(payload).hexdigest()}
    (work/'media-manifest.json').write_text(json.dumps({'frames':[{**frame_metadata,'file':frame.name}]}), encoding='utf-8')
    return {'audio_path':str(audio),'audio_seconds':1,'duration_seconds':1,'frames':[{**frame_metadata,'path':str(frame)}]}

class PipelineIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='tmp'); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name).resolve()
        self.wc=json.loads(Path('config/workflow.json').read_text(encoding='utf-8')); self.wc['data_dir']=str(self.root/'data')
        self.pc=load_pipeline_config(); self.pc['budget']['ledger']=str(self.root/'budget.sqlite'); self.s=FakeServices(); self.storage=FakeStorage()
        store=make_store(self.wc); root=Path(self.wc['data_dir']); (root/'source.mp4').write_bytes(b'video')
        self.task=store.import_source('video',hashlib.sha256(b'video').hexdigest(),'source.mp4','source.mp4')['task']['id']
    def run_pipeline(self,resume=False): return run_video(self.wc,self.pc,{},task_id=self.task,resume=resume,services=self.s,storage=self.storage,media=media)
    def status(self): return make_store(self.wc).get_task(self.task)['status']
    def test_success_and_private_url(self):
        version=self.run_pipeline(); self.assertEqual(version['output_kind'],'machine_initial'); self.assertEqual(self.status(),'succeeded')
        status=video_status(self.wc,self.pc,self.task); self.assertEqual(status['assets'][0]['status'],'provider_managed')
        self.assertNotIn('secret',json.dumps(status)); self.assertNotIn(b'secret', (Path(self.wc['data_dir'])/'workflow.sqlite3').read_bytes())

    def test_reprocess_creates_pending_child_and_keeps_prior_review(self):
        from types import SimpleNamespace
        from personalkb.web_dispatch import WebDispatcher

        old = self.run_pipeline()
        store = make_store(self.wc)
        sid = old['source_id']
        store.review(sid, old['id'], old['content_sha256'], 90, 'rework', 'tester')
        dispatcher = WebDispatcher(SimpleNamespace(store=store, webcfg={'live_video_enabled': True,'dispatch_recovery_seconds':60},
            video_runner=lambda wc, pc, keys, *, task_id, resume: run_video(wc, pc, keys, task_id=task_id,
                resume=resume, services=self.s, storage=self.storage, media=media), wc=self.wc, pc=self.pc))
        self.task = dispatcher.reprocess(sid, old['id'], True)['task_id']
        self.storage.prepare = lambda path, model: PreparedAudio('temporary',model,'asset2',
            hashlib.sha256(Path(path).read_bytes()).hexdigest(),Path(path).stat().st_size,time.time()+3600,'https://unused')
        self.assertEqual(dispatcher.process_next()['dispatch_state'], 'done')
        new = store.get_version(store.get_source(sid)['current_version_id'])
        self.assertEqual(new['parent_version_id'], old['id'])
        self.assertEqual(store.get_source(sid)['current_version_id'], new['id'])
        self.assertEqual(self.s.submit_count, 2)
        store.assert_synced(sid)
        for version in (old, new):
            self.assertTrue((store.content_root/sid/'versions'/version['id']/'evidence.json').is_file())
            self.assertTrue((store.content_root/sid/'frames'/(version['result']['frames'][0]['sha256']+'.jpg')).is_file())
        with store._tx() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT version_id,decision FROM reviews WHERE source_id=?', (sid,))], [(old['id'], 'rework')])
        self.assertEqual(store.eligible_sources(), [])
        from personalkb.web_app import load_web_config
        from personalkb.web_service import WebService
        service = WebService(self.wc, self.pc, load_web_config())
        for version in (old, new):
            detail = service.detail(sid, version['id'])
            self.assertIn('?version_id='+version['id'], detail['frames'][0]['url'])
            frame = service.frame(sid, 0, version['id'])
            self.assertEqual(hashlib.sha256(frame.read_bytes()).hexdigest(), version['result']['frames'][0]['sha256'])
        other = store.import_source('video', 'b'*64, 'other.mp4', 'other.mp4')['source']['id']
        with self.assertRaisesRegex(WorkflowError, 'version_not_found'):
            service.frame(other, 0, old['id'])

    def test_reprocess_version_race_preserves_newer_manual_edit(self):
        from types import SimpleNamespace
        from personalkb.web_dispatch import WebDispatcher

        old = self.run_pipeline()
        store = make_store(self.wc)
        sid = old['source_id']
        dispatcher = WebDispatcher(SimpleNamespace(store=store, webcfg={'live_video_enabled': True}))
        self.task = dispatcher.reprocess(sid, old['id'], True)['task_id']
        self.storage.prepare = lambda path, model: PreparedAudio('temporary',model,'asset2',
            hashlib.sha256(Path(path).read_bytes()).hexdigest(),Path(path).stat().st_size,time.time()+3600,'https://unused')
        edit = dict(old['result'], title='Manual revision', output_kind='human_edited', provenance='human_edited')
        revised = {}
        self.s.cancel = lambda: revised.update(store.revise(sid, old['id'], edit))
        with self.assertRaisesRegex(WorkflowError, 'version_conflict'):
            self.run_pipeline()
        self.assertEqual(store.get_source(sid)['current_version_id'], revised['id'])
        self.assertEqual(len(store.list_versions(sid)), 2)
        with self.assertRaisesRegex(WorkflowError, 'version_conflict'):
            dispatcher.enqueue(self.task, mode='resume', allow_paid=True)
        self.assertNotEqual(dispatcher.reprocess(sid, revised['id'], True)['task_id'], self.task)
    def test_query_resume_only_get(self):
        self.s.mode='query'
        strategy = self.pc['strategy']
        legacy = strategy['legacy_text_prompt']['value']
        self.pc['strategy'] = {key: value for key, value in strategy.items() if key != 'legacy_text_prompt'}
        self.pc['strategy']['text_system_prompt'] = legacy
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.pc['strategy'] = strategy
        self.assertEqual(self.status(),'needs_attention'); self.run_pipeline(True); self.assertEqual(self.s.submit_count,1); self.assertEqual(self.s.query_count,2)
        c=sqlite3.connect(self.pc['budget']['ledger']); self.addCleanup(c.close); self.assertEqual(c.execute("SELECT count(*) FROM reservations WHERE request_id=?",(self.task+':asr_submit',)).fetchone()[0],1)
    def test_failed_subtask_cleanup(self):
        self.s.mode='subtask_failed'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.assertEqual(self.status(),'needs_attention')
        self.assertEqual(video_status(self.wc,self.pc,self.task)['assets'][0]['status'],'remote_terminal')
        result=cleanup_video(self.wc,self.pc,{},self.task,storage=self.storage)
        self.assertEqual(result['assets'][0]['status'],'provider_managed')
        with self.assertRaises(WorkflowError): self.run_pipeline(True)
        self.assertEqual(self.s.submit_count,1)
    def test_unknown_submit_never_repeats(self):
        self.s.mode='submit'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        with self.assertRaises(WorkflowError): self.run_pipeline(True)
        self.assertEqual(self.s.submit_count,1)

    def test_upload_failure_can_resume_without_duplicate_asr(self):
        class UploadTransport:
            def __init__(self): self.fail = 'policy'

            def request(self, url, *, key=None, data=None, content_type=None):
                if self.fail == ('policy' if key else 'audio'):
                    raise StorageError('network_timeout')
                if key:
                    return 200, {'data': dict(upload_dir='dir', upload_host='https://upload.oss-cn-beijing.aliyuncs.com',
                        oss_access_key_id='id', signature='sig', policy='policy', x_oss_object_acl='private',
                        x_oss_forbid_overwrite='true')}
                return 200, {}

        transport = UploadTransport()
        self.storage = TemporaryStorage(self.pc['storage'], {'DASHSCOPE_API_KEY': 'secret'}, transport)
        store = make_store(self.wc)
        journal = VideoJournal(store)
        for failure, phase, resume in (('policy', 'asr_upload_policy', False), ('audio', 'asr_audio_upload', True)):
            transport.fail = failure
            with self.assertRaisesRegex(WorkflowError, 'network_timeout'):
                self.run_pipeline(resume)
            task = store.get_task(self.task)
            self.assertEqual((task['status'], task['stage'], task['external_started']), ('needs_attention', phase, 0))
            self.assertEqual(journal.stage(self.task, phase)['status'], 'in_flight')
            self.assertEqual(journal.stage(self.task, 'asr_submit')['status'], 'prepared')
            self.assertEqual(self.s.submit_count, 0)
        with closing(sqlite3.connect(self.pc['budget']['ledger'])) as ledger:
            self.assertEqual(ledger.execute('SELECT count(*) FROM reservations').fetchone()[0], 0)
        transport.fail = None
        self.run_pipeline(True)
        self.assertIsNone(store.get_task(self.task)['error_code'])
        self.assertEqual(self.s.submit_count, 1)
        self.assertEqual(journal.stage(self.task, 'asr_audio_upload')['status'], 'completed')

    def test_legacy_upload_failure_keeps_reservation_and_resumes_with_new_timeouts(self):
        store = make_store(self.wc)
        journal = VideoJournal(store)
        task = journal.claim_task(self.task, 'legacy-worker')
        token = task['lease_token']
        old_pc = {**self.pc, 'storage': {key: value for key, value in self.pc['storage'].items()
                                         if not key.startswith(('policy_timeout', 'upload_timeout'))}}
        _bind_strategy(journal, self.task, token, old_pc, ('models', 'strategy', 'storage', 'prices', 'default_profile'))
        digest = _digest({'audio': hashlib.sha256(b'audio').hexdigest(), 'model': self.pc['models']['models']['asr']})
        journal.begin(self.task, token, 'asr_submit', digest)
        journal.mark_started(self.task, token, 'asr_submit')
        request_id = self.task + ':asr_submit'
        reserve(self.pc['budget']['ledger'], self.task, request_id, '0.10', '5', '100')
        store.fail(self.task, token, 'network_unconfirmed')
        self.run_pipeline(True)
        self.assertEqual(self.s.submit_count, 1)
        self.assertEqual(self.status(), 'succeeded')
        with closing(sqlite3.connect(self.pc['budget']['ledger'])) as ledger:
            self.assertEqual(ledger.execute('SELECT amount FROM reservations WHERE request_id=?', (request_id,)).fetchall(), [('0.10',)])
    def test_unknown_vision_never_repeats(self):
        self.s.mode='vision'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        with self.assertRaises(WorkflowError): self.run_pipeline(True)
        self.assertEqual(self.s.vision_count,1)
    def test_budget_prevents_post(self):
        self.pc['budget']['run_limit']='0.00000001'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.assertEqual(self.s.submit_count,0)
    def test_incomplete_managed_storage_before_claim_or_reservation(self):
        self.pc['storage']['backend']='managed_oss'
        with self.assertRaises(WorkflowError):
            run_video(self.wc,self.pc,{},task_id=self.task,services=self.s,media=media)
        self.assertEqual(self.status(),'queued')
        self.assertFalse(Path(self.pc['budget']['ledger']).exists())
        self.assertEqual(self.s.submit_count,0)
    def test_cancel_prevents_publish(self):
        self.s.cancel=lambda: make_store(self.wc).cancel(self.task)
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.assertEqual(self.status(),'cancelled'); self.assertEqual(make_store(self.wc).list_versions(make_store(self.wc).get_task(self.task)['source_id']),[])
    def test_attention_cleanup_preserves_wav(self):
        self.s.mode='vision'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        audio=Path(self.wc['data_dir'])/'video-work'/self.task/'audio.wav'; self.assertTrue(audio.exists())
        cleanup_video(self.wc,self.pc,{},self.task,storage=self.storage); self.assertTrue(audio.exists())
