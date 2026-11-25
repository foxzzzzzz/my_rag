import hashlib, json, sqlite3, tempfile, time, unittest
from contextlib import closing
from pathlib import Path
from personalkb.asr_storage import PreparedAudio, StorageError
from personalkb.asr_storage_temporary import TemporaryStorage
from personalkb.workflow import make_store
from personalkb.workflow_store import WorkflowError
from personalkb.video_journal import VideoJournal
from personalkb.video_services import ProviderError
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
    def summarize(self,body,title):
        summary = 'summary' if self.mode=='legacy' else {'overview':'summary','key_points':['point'],'limitations':''}
        return {'structured':{'summary':summary,'notes':'notes'},'content':'notes','model':'fake','estimated_cost_cny':0}

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

    def test_no_detectable_speech_continues_and_preserves_provenance(self):
        store = make_store(self.wc)
        with store._tx() as db:
            db.execute('INSERT INTO source_display_titles VALUES (?,?)', (store._row(db, 'tasks', self.task)['source_id'], '平台原文'))
        code = 'SUCCESS_WITH_NO_VALID_FRAGMENT'
        self.s.query_asr = lambda ident: {'task_status':'FAILED', 'code':code,
                                          'results':[{'subtask_status':'FAILED', 'code':code}]}
        version = self.run_pipeline()
        result = version['result']
        self.assertEqual((self.status(), version['output_kind']), ('succeeded', 'machine_initial'))
        self.assertEqual((result['transcript_status'], result['transcript']), ('no_speech', ''))
        self.assertIn('平台原文', result['body'])
        self.assertIn('未检测到可转录语音', result['body'])
        self.assertEqual([item['type'] for item in result['evidence']], ['visual'])
        self.assertEqual(self.s.vision_count, 1)
        self.assertEqual(VideoJournal(store).stage(self.task, 'asr_result')['result']['provider_code'], code)
        self.assertEqual(store.eligible_sources(), [])
        service = self.recovery_service()
        sid = version['source_id']
        notes = service.revise(sid, {'expected_version_id':version['id'], 'notes':'补充笔记'})
        self.assertEqual(service.detail(sid)['current']['result']['transcript_status'], 'no_speech')
        service.revise(sid, {'expected_version_id':notes['id'], 'transcript':'人工补写'})
        self.assertNotIn('transcript_status', service.detail(sid)['current']['result'])
        self.assertEqual(service.detail(sid, version['id'])['current']['result']['transcript_status'], 'no_speech')

    def test_no_audio_track_does_not_submit_or_reserve_asr(self):
        def no_audio(source, work, wc, pc, *, heartbeat):
            return {**media(source, work, wc, pc, heartbeat=heartbeat), 'audio_path':None, 'audio_seconds':0}
        version = run_video(self.wc, self.pc, {}, task_id=self.task, services=self.s, storage=self.storage, media=no_audio)
        self.assertEqual(version['result']['transcript_status'], 'no_audio')
        self.assertEqual(self.s.submit_count, 0)
        with closing(sqlite3.connect(self.pc['budget']['ledger'])) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations WHERE request_id LIKE '%:asr_submit'").fetchone()[0], 0)

    def recovery_service(self):
        from personalkb.web_service import WebService
        return WebService(self.wc, self.pc, {'live_video_enabled':True, 'dispatch_recovery_seconds':60},
            video_runner=lambda wc, pc, keys, **options: run_video(wc, pc, keys, services=self.s,
                storage=self.storage, media=media, **options))

    def test_legacy_terminal_asr_requires_explicit_visual_recovery(self):
        self.s.mode = 'subtask_failed'
        with self.assertRaisesRegex(WorkflowError, 'asr_subtask_failed'):
            self.run_pipeline()
        service = self.recovery_service()
        item = service.tasks()['items'][0]
        self.assertEqual(item['failure_stage'], 'asr_result')
        self.assertEqual(item['video_recovery']['mode'], 'visual-only')
        with self.assertRaisesRegex(WorkflowError, 'video_recovery_conflict'):
            service.dispatcher.enqueue(self.task, 'resume', True)
        with self.assertRaisesRegex(WorkflowError, 'paid_consent_required'):
            service.dispatcher.recover_video(self.task, 'visual-only')
        queued = service.dispatcher.recover_video(self.task, 'visual-only', allow_paid=True)
        duplicate = service.dispatcher.recover_video(self.task, 'visual-only', allow_paid=True)
        self.assertFalse(queued['duplicate'])
        self.assertTrue(duplicate['duplicate'])
        self.assertNotIn('video_recovery', service.tasks()['items'][0])
        self.assertEqual(service.dispatcher.process_next()['dispatch_state'], 'done')
        self.assertEqual((self.s.submit_count, self.s.query_count), (1, 1))
        journal = VideoJournal(service.store)
        self.assertEqual(journal.stage(self.task, 'asr_result')['result']['error'], 'asr_subtask_failed')
        self.assertEqual(journal.stage(self.task, 'asr_visual_only')['result']['previous_error'], 'asr_subtask_failed')
        source = service.store.get_task(self.task)['source_id']
        self.assertEqual(service.detail(source)['current']['result']['transcript_status'], 'visual_only')

    def test_rebuild_legacy_partial_cache_after_regular_attempt_limit(self):
        service = self.recovery_service()
        work = Path(self.wc['data_dir'])/'video-work'/self.task
        work.mkdir(parents=True)
        (work/'audio.wav').write_bytes(b'partial audio')
        with service.store._tx() as db:
            db.execute("UPDATE tasks SET status='failed',stage='preparing_video',attempts=?,error_code='video_processing_failed' WHERE id=?",
                       (service.store.max_attempts, self.task))
        task = service.tasks()['items'][0]
        self.assertEqual(task['failure_code'], 'media_workdir_unverified')
        self.assertEqual(task['video_recovery']['mode'], 'rebuild-media')
        with self.assertRaisesRegex(WorkflowError, 'invalid_state'):
            service.dispatcher.retry(self.task, allow_paid=True)
        with self.assertRaisesRegex(WorkflowError, 'paid_consent_required'):
            service.dispatcher.recover_video(self.task, 'rebuild-media')
        service.dispatcher.recover_video(self.task, 'rebuild-media', allow_paid=True)
        self.assertEqual(service.dispatcher.process_next()['dispatch_state'], 'done')
        self.assertEqual(service.store.get_task(self.task)['attempts'], service.store.max_attempts + 1)
        self.assertEqual((work.with_name('.'+work.name+'-incomplete')/'audio.wav').read_bytes(), b'partial audio')
        self.assertEqual(self.s.submit_count, 1)
        with self.assertRaisesRegex(WorkflowError, 'video_recovery_conflict'):
            service.dispatcher.recover_video(self.task, 'rebuild-media', allow_paid=True)

    def test_interrupted_rebuild_can_continue_from_retained_backup(self):
        service = self.recovery_service()
        journal = VideoJournal(service.store)
        work = Path(self.wc['data_dir'])/'video-work'/self.task
        work.mkdir(parents=True)
        (work/'audio.wav').write_bytes(b'original partial cache')
        with service.store._tx() as db:
            db.execute("UPDATE tasks SET status='failed',stage='preparing_video',attempts=?,error_code='video_processing_failed' WHERE id=?",
                       (service.store.max_attempts, self.task))
        service.dispatcher.recover_video(self.task, 'rebuild-media', allow_paid=True)
        service.dispatcher._claim()
        claimed = journal.claim_task(self.task, 'video-worker', rebuild_media=True)
        token = claimed['lease_token']
        source = service.store.get_source(claimed['source_id'])
        journal.record_local_recovery(self.task, token, 'media_rebuilt', source['sha256'], claimed['error_code'])
        service.store.checkpoint(self.task, token, 'rebuilding_media')
        backup = work.with_name('.'+work.name+'-incomplete')
        work.rename(backup)
        with service.store._tx() as db:
            db.execute('UPDATE tasks SET lease_until=0 WHERE id=?', (self.task,))
        self.assertIsNone(service.dispatcher._claim())
        self.assertEqual(service.tasks()['items'][0]['video_recovery']['mode'], 'rebuild-media')
        service.dispatcher.recover_video(self.task, 'rebuild-media', allow_paid=True)
        self.assertEqual(service.dispatcher.process_next()['dispatch_state'], 'done')
        self.assertEqual((backup/'audio.wav').read_bytes(), b'original partial cache')
        self.assertEqual(self.s.submit_count, 1)

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
        self.pc['strategy'] = {key: value for key, value in strategy.items() if key not in ('legacy_text_prompt','previous_text_prompt','summary_format','summary_format说明')}
        self.pc['strategy']['text_system_prompt'] = legacy
        suffix = self.pc.pop('video_notes_prompt_suffix')
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.pc['strategy'] = strategy
        self.pc['video_notes_prompt_suffix'] = suffix
        self.assertEqual(self.status(),'needs_attention'); self.s.mode='legacy'; self.run_pipeline(True); self.assertEqual(self.s.submit_count,1); self.assertEqual(self.s.query_count,2)
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

    def test_resume_legacy_vision_limit_keeps_media_strategy_and_uses_current_request_limit(self):
        from unittest.mock import patch

        current = self.pc['strategy']['vision_max_tokens']
        legacy = self.pc['legacy_vision_max_tokens']
        self.pc['strategy']['vision_max_tokens'] = legacy
        self.s.mode = 'vision'
        with self.assertRaises(WorkflowError):
            self.run_pipeline()
        self.pc['strategy']['vision_max_tokens'] = current
        dispatcher = self._recovery_dispatcher()
        dispatcher.recover_model(self.task, dict(self._recovery_quote(dispatcher), allow_paid=True))

        def verify_media(source, work, wc, pc, *, heartbeat):
            self.assertEqual(pc['strategy']['vision_max_tokens'], legacy)
            self.assertTrue((work / 'media-manifest.json').is_file())
            return media(source, work, wc, pc, heartbeat=heartbeat)

        def provider(models, pc, secrets):
            self.assertEqual(pc['strategy']['vision_max_tokens'], 3072)
            return self.s

        self.s.mode = ''
        keys = {spec['api_key_env']: 'fixture' for spec in self.pc['models']['providers'].values()}
        dispatcher.service.video_runner = lambda wc, pc, _, *, task_id, resume: run_video(
            wc, pc, keys, task_id=task_id, resume=resume, storage=self.storage, media=verify_media)
        with patch('personalkb.video_services.ProviderClient', side_effect=provider):
            self.assertEqual(dispatcher.process_next()['dispatch_state'], 'done')
        self.assertEqual((self.s.submit_count, self.s.vision_count), (1, 2))

    def test_model_diagnostics_in_task_api_and_legacy_records(self):
        from unittest.mock import Mock
        from fastapi.testclient import TestClient
        from personalkb.web_app import create_app, load_web_config
        from personalkb.web_service import WebService

        metrics = {'finish_reason':'length', 'output_chars':231, 'usage':{'completion_tokens':1536}}
        self.s.vision = Mock(side_effect=ProviderError('model_output_truncated', 'chatcmpl-fixture', metrics=metrics))
        with self.assertRaisesRegex(WorkflowError, 'model_output_truncated'):
            self.run_pipeline()
        self.assertEqual(self.s.vision.call_count, 1)
        config = load_web_config()
        config.update(dispatch_enabled=False, live_video_enabled=True)
        config['trusted_hosts'].append('testserver')
        service = WebService(self.wc, self.pc, config)
        with TestClient(create_app(self.wc, self.pc, config, service)) as client:
            client.get('/api/session')
            row = next(t for t in client.get('/api/tasks').json()['items'] if t['id'] == self.task)
            self.assertEqual(row['resume_blocked_reason'], 'unknown_submission')
            self.assertEqual(row['model_diagnostic'], dict(metrics, code='model_output_truncated',
                stage='vision-0', provider_request_id='chatcmpl-fixture'))
            with service.store._tx() as db:
                saved = db.execute('SELECT response,response_metrics FROM video_chat_attempts WHERE task_id=?', (self.task,)).fetchone()
                self.assertIsNone(saved['response'])
                self.assertEqual(json.loads(saved['response_metrics']), metrics)
                db.execute("""UPDATE video_chat_attempts SET diagnostic='empty_or_truncated_model_output',
                    response_metrics=NULL WHERE task_id=?""", (self.task,))
            row = next(t for t in client.get('/api/tasks').json()['items'] if t['id'] == self.task)
            self.assertEqual(row['model_diagnostic'], {'code':'empty_or_truncated_model_output',
                'stage':'vision-0', 'provider_request_id':'chatcmpl-fixture'})

    def test_favorites_video_reauthorization_api_reuses_task_and_media(self):
        from uuid import uuid4

        from fastapi.testclient import TestClient
        from personalkb.web_app import create_app, load_web_config
        from personalkb.web_service import WebService

        prepared = []
        media_seconds = 2113.250875

        def long_media(source, work, wc, pc, *, heartbeat):
            manifest = work/'media-manifest.json'
            if not manifest.is_file():
                prepared.append(work)
                (work/'audio.wav').write_bytes(b'audio')
                frames = []
                for index in range(32):
                    path = work/f'frame-{index}.jpg'
                    blob = str(index).encode()
                    path.write_bytes(blob)
                    frames.append({'index': index, 'seconds': index, 'file': path.name,
                                   'sha256': hashlib.sha256(blob).hexdigest()})
                manifest.write_text(json.dumps({'audio': {'file': 'audio.wav'}, 'audio_seconds': media_seconds,
                                                'frames': frames}), encoding='utf-8')
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            return {'audio_path': str(work/'audio.wav'), 'audio_seconds': saved['audio_seconds'],
                    'duration_seconds': saved['audio_seconds'],
                    'frames': [{**frame, 'path': str(work/frame['file'])} for frame in saved['frames']]}

        with make_store(self.wc)._tx() as db:
            db.execute('CREATE TABLE favorites_conversion (task_id TEXT PRIMARY KEY, amount TEXT NOT NULL)')
            db.execute("INSERT INTO favorites_conversion VALUES (?,'4.05')", (self.task,))
            db.execute('CREATE TABLE favorites_queue (task_id TEXT, status TEXT)')
            db.execute("INSERT INTO favorites_queue VALUES (?,'conversion_failed')", (self.task,))
        with self.assertRaisesRegex(WorkflowError, 'favorites_budget_exceeded'):
            legacy_config = {**self.pc, 'strategy': {**self.pc['strategy'],
                              'vision_max_tokens': self.pc['legacy_vision_max_tokens']}}
            run_video(self.wc, legacy_config, {}, task_id=self.task, services=self.s, storage=self.storage, media=long_media)
        config = load_web_config()
        config.update(dispatch_enabled=False, live_video_enabled=True)
        config['trusted_hosts'].append('testserver')
        service = WebService(self.wc, self.pc, config, video_runner=lambda wc, pc, keys, **options:
                             run_video(wc, pc, keys, services=self.s, storage=self.storage, media=long_media, **options))
        with service.store._tx() as db:
            db.execute('UPDATE tasks SET attempts=2 WHERE id=?', (self.task,))
        url = f'/api/tasks/{self.task}/reauthorize-favorites'
        with TestClient(create_app(self.wc, self.pc, config, service)) as client:
            headers = {'x-csrf-token': client.get('/api/session').json()['csrf_token']}
            quote = client.get('/api/tasks').json()['items'][0]['favorites_reauthorization']
            self.assertEqual((quote['authorized_cny'], quote['required_cny']), ('4.05', '4.12'))
            self.assertEqual(client.get('/api/budget').json()['favorites_reauthorizations'][0]['task_id'], self.task)
            payload = {'allow_paid': True, 'request_id': str(uuid4()), 'amount_cny': '4.12',
                       'expected_ceiling_cny': '4.05', 'expected_required_cny': '4.12'}
            service.pc = {**self.pc, 'prices': {**self.pc['prices'], 'asr_per_second': '0.00009'}}
            try:
                blocked = client.get('/api/tasks').json()['items'][0]['favorites_reauthorization']
                self.assertEqual(blocked['blocked_reason'], 'favorites_reauthorization_strategy_changed')
                self.assertIsNone(blocked['required_cny'])
                self.assertEqual(client.post(url, headers=headers, json=payload).json()['error'],
                                 'favorites_reauthorization_strategy_changed')
                task = service.store.get_task(self.task)
                self.assertEqual((task['status'], task['attempts']), ('failed', 2))
                self.assertEqual(self.s.submit_count, 0)
            finally:
                service.pc = self.pc
            original_frame = prepared[0] / 'frame-0.jpg'
            moved_frame = original_frame.with_suffix('.bak')
            original_frame.rename(moved_frame)
            try:
                blocked = client.get('/api/budget').json()['favorites_reauthorizations'][0]
                self.assertEqual(blocked['blocked_reason'], 'favorites_reauthorization_media_unavailable')
            finally:
                moved_frame.rename(original_frame)
            for changes, expected in (
                ({'allow_paid': False}, 'paid_consent_required'),
                ({'expected_required_cny': '4.11'}, 'favorites_reauthorization_conflict'),
                ({'amount_cny': '4.11'}, 'favorites_budget_exceeded'),
                ({'amount_cny': '5.01'}, 'budget_invalid_or_exceeded'),
            ):
                response = client.post(url, headers=headers, json={**payload, **changes})
                self.assertEqual(response.json()['error'], expected)
            response = client.post(f'/api/tasks/{self.task}/retry', headers=headers, json={'allow_paid': True})
            self.assertEqual(response.json()['error'], 'favorites_budget_exceeded')
            self.assertEqual(service.store.get_task(self.task)['attempts'], 2)
            self.assertEqual(self.s.submit_count, 0)
            accepted = client.post(url, headers=headers, json=payload).json()
            duplicate = client.post(url, headers=headers, json=payload).json()
            self.assertEqual(accepted, {'task_id': self.task, 'dispatch_state': 'pending', 'duplicate': False})
            self.assertEqual(duplicate, {**accepted, 'duplicate': True})
            self.assertEqual(client.get('/api/budget').json()['favorites_reauthorizations'], [])
            self.assertEqual(service.dispatcher.process_next()['dispatch_state'], 'done')
            self.assertEqual(client.post(url, headers=headers, json=payload).json()['dispatch_state'], 'done')
        self.assertEqual(self.status(), 'succeeded')
        self.assertEqual((len(prepared), self.s.submit_count, self.s.vision_count), (1, 1, 32))
        with service.store._tx() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM favorites_video_reauthorizations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT amount FROM favorites_conversion').fetchone()[0], '4.12')

    def test_saved_audio_limit_allows_old_task_to_resume_with_its_original_binding(self):
        from unittest.mock import patch

        from personalkb.asr_storage import check_file
        from personalkb.web_app import load_web_config
        from personalkb.web_service import WebService

        actual_bytes = 67_624_152
        new_limit = 80 * 1024 * 1024
        old_limit = self.pc['storage']['max_upload_bytes']
        prepared = []

        def cached_media(source, work, wc, pc, *, heartbeat):
            if not prepared:
                material = media(source, work, wc, pc, heartbeat=heartbeat)
                path = Path(material['audio_path'])
                with path.open('r+b') as audio:
                    audio.truncate(actual_bytes)
                manifest = work / 'media-manifest.json'
                entries = json.loads(manifest.read_text(encoding='utf8'))
                entries['audio'] = {'file': path.name}
                manifest.write_text(json.dumps(entries), encoding='utf8')
                prepared.append(material)
            return prepared[0]

        class CheckedStorage:
            def __init__(self, config):
                self.config = config

            def prepare(self, path, model):
                _, digest, size = check_file(path, self.config)
                return PreparedAudio('temporary', model, 'asset1', digest, size, time.time() + 60, 'https://unused')

        def runner(wc, pc, keys, **options):
            return run_video(wc, pc, keys, services=self.s, media=cached_media, **options)

        config = {**load_web_config(), 'live_video_enabled': True}
        web = WebService(self.wc, self.pc, config, video_runner=runner)
        worker = WebService(self.wc, self.pc, config, video_runner=runner)
        with web.store._tx() as db:
            db.execute('CREATE TABLE favorites_conversion (task_id TEXT PRIMARY KEY, amount TEXT NOT NULL)')
            db.execute("INSERT INTO favorites_conversion VALUES (?,'4.12')", (self.task,))

        with patch('personalkb.video_pipeline.create_storage', side_effect=lambda config, *_args, **_kwargs: CheckedStorage(config)):
            with self.assertRaisesRegex(WorkflowError, 'file_too_large'):
                runner(self.wc, self.pc, {}, task_id=self.task)
            with web.store._tx() as db:
                db.execute('UPDATE tasks SET attempts=4 WHERE id=?', (self.task,))
                fingerprint = db.execute('SELECT fingerprint FROM video_runs WHERE task_id=?', (self.task,)).fetchone()[0]
            failed = web.tasks()['items'][0]
            self.assertEqual(failed['processing_limit'], {'key': 'asr_upload_bytes', 'actual': actual_bytes, 'limit': old_limit})
            self.assertEqual(failed['resume_blocked_reason'], 'asr_upload_limit_exceeded')
            with self.assertRaisesRegex(WorkflowError, 'asr_upload_limit_exceeded'):
                web.dispatcher.enqueue(self.task, 'resume', True)
            settings = web.processing_settings.read()
            web.processing_settings.change({'expected_revision': settings['revision'], 'values': {'asr_upload_bytes': new_limit}})
            self.assertEqual((self.status(), self.s.submit_count), ('needs_attention', 0))
            ready = web.tasks()['items'][0]
            self.assertEqual(ready['processing_limit']['limit'], new_limit)
            self.assertIsNone(ready['resume_blocked_reason'])
            self.assertEqual(web.dispatcher.enqueue(self.task, 'resume', True)['task_id'], self.task)
            self.assertEqual(worker.dispatcher.process_next()['dispatch_state'], 'done')

        self.assertEqual((self.status(), self.s.submit_count, len(prepared)), ('succeeded', 1, 1))
        self.assertEqual(self.pc['storage']['max_upload_bytes'], old_limit)
        with web.store._tx() as db:
            self.assertEqual(db.execute('SELECT fingerprint FROM video_runs WHERE task_id=?', (self.task,)).fetchone()[0], fingerprint)
            self.assertEqual(db.execute('SELECT amount FROM favorites_conversion WHERE task_id=?', (self.task,)).fetchone()[0], '4.12')

    def test_tasks_survive_broken_optional_favorites_config_and_refresh(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from fastapi.testclient import TestClient
        from personalkb.douyin_import import DouyinImporter
        from personalkb.web_app import create_app, load_web_config
        from personalkb.web_service import WebService

        settings_path = self.root / 'favorites.json'
        settings_path.write_text('{broken', encoding='utf-8')
        config = load_web_config()
        config.update(dispatch_enabled=False, live_video_enabled=True, favorites_sync_config=str(settings_path))
        config['trusted_hosts'].append('testserver')
        service = WebService(self.wc, self.pc, config)
        with TestClient(create_app(self.wc, self.pc, config, service)) as client:
            client.get('/api/session')
            response = client.get('/api/tasks')
            self.assertEqual(response.status_code, 200)
            row, = response.json()['items']
            self.assertEqual(row['id'], self.task)
            self.assertNotIn('conversion_wait', row)

            settings = json.loads(Path('config/douyin-daily-sync.json').read_text(encoding='utf-8'))
            settings.update(enabled=True, auto_download=True, conversion_enabled=True)
            settings_path.write_text(json.dumps(settings), encoding='utf-8')
            sync = service.favorites_sync
            sync.limits(40, payload={'max_images': 40, 'download_limit': 0, 'expected_revision': 0})
            DouyinImporter(self.wc, {}, {})
            day = datetime.now(ZoneInfo(settings['timezone'])).date().isoformat()
            with service.store._tx() as db:
                db.execute("UPDATE favorites_state SET state='ready',active='fixture',last_day=?", (day,))
                task = service.store._row(db, 'tasks', self.task)
                db.execute("""INSERT INTO douyin_jobs(id,canonical_url,work_id,status,source_id,created_at,updated_at)
                    VALUES ('job','https://example.invalid','1','succeeded',?,0,0)""", (task['source_id'],))
                db.execute("""INSERT INTO favorites_queue(account_id,work_id,automatic,job_id,status)
                    VALUES ('fixture','1',1,'job','downloaded')""")
            response = client.get('/api/tasks')
            self.assertEqual(response.status_code, 200)
            row, = response.json()['items']
            self.assertEqual(row['conversion_wait'], {'code': 'favorites_daily_count_limit'})

    def test_default_timeout_retry_once_for_vision_and_text(self):
        from unittest.mock import Mock
        for name in ('vision', 'summarize'):
            call = getattr(self.s, name)
            setattr(self.s, name, Mock(side_effect=[ProviderError('provider_timeout'), call(None) if name == 'vision' else call('', '')]))
        self.run_pipeline()
        self.assertEqual(self.s.submit_count, 1)
        self.assertEqual((self.s.vision.call_count, self.s.summarize.call_count), (2, 2))
        with closing(sqlite3.connect(self.pc['budget']['ledger'])) as ledger:
            self.assertEqual(ledger.execute("SELECT COUNT(*) FROM reservations WHERE request_id LIKE '%:retry:1'").fetchone()[0], 2)

    def test_timeout_retry_limit_and_no_implicit_resend_after_restart(self):
        from unittest.mock import Mock
        self.s.vision = Mock(side_effect=ProviderError('provider_timeout'))
        with self.assertRaisesRegex(WorkflowError, '^provider_timeout$'):
            self.run_pipeline()
        self.assertEqual(self.s.vision.call_count, 2)
        with self.assertRaisesRegex(WorkflowError, 'unknown_submission'):
            self.run_pipeline(True)
        self.assertEqual(self.s.vision.call_count, 2)

    def test_auto_retry_respects_original_favorites_ceiling(self):
        from unittest.mock import Mock
        self.s.vision = Mock(side_effect=ProviderError('provider_timeout'))
        with make_store(self.wc)._tx() as db:
            db.execute('CREATE TABLE favorites_conversion(task_id TEXT, amount TEXT)')
            db.execute('INSERT INTO favorites_conversion VALUES(?,?)', (self.task, '0.95'))
        with self.assertRaisesRegex(WorkflowError, 'favorites_budget_exceeded'):
            self.run_pipeline()
        self.assertEqual(self.s.vision.call_count, 1)
        self.assertEqual(VideoJournal(make_store(self.wc)).automatic_retry_count(self.task, 'vision-0'), 0)

    def test_zero_disables_timeout_retry(self):
        from unittest.mock import Mock
        self.pc['chat_timeout_retries'] = 0
        self.s.vision = Mock(side_effect=ProviderError('provider_timeout'))
        with self.assertRaisesRegex(WorkflowError, 'provider_timeout'):
            self.run_pipeline()
        self.assertEqual(self.s.vision.call_count, 1)

    def test_confirmed_manual_retry_only_sends_once_on_timeout(self):
        from unittest.mock import Mock
        self.s.vision = Mock(side_effect=ProviderError('provider_timeout'))
        self.pc['chat_timeout_retries'] = 0
        with self.assertRaisesRegex(WorkflowError, 'provider_timeout'):
            self.run_pipeline()
        self.pc['chat_timeout_retries'] = 1
        dispatcher = self._recovery_dispatcher()
        dispatcher.recover_model(self.task, dict(self._recovery_quote(dispatcher), allow_paid=True))
        self.assertEqual(dispatcher.process_next()['error'], 'provider_timeout')
        self.assertEqual(self.s.vision.call_count, 2)

    def _recovery_dispatcher(self):
        from types import SimpleNamespace
        from personalkb.web_dispatch import WebDispatcher
        return WebDispatcher(SimpleNamespace(store=make_store(self.wc), pc=self.pc, wc=self.wc,
            webcfg={'live_video_enabled': True, 'dispatch_recovery_seconds': 60},
            douyin=SimpleNamespace(status=lambda: {'enabled': False}),
            video_runner=lambda wc, pc, keys, *, task_id, resume: self.run_pipeline(resume)))

    def _recovery_quote(self, dispatcher):
        from personalkb.web_dispatch import task_stages
        with dispatcher.store._tx() as db:
            task = dispatcher.store._row(db, 'tasks', self.task)
            return dispatcher.model_recovery(db, task, task_stages(db, self.task))

    def test_saved_reply_continues_without_second_request(self):
        from unittest.mock import patch
        complete = VideoJournal.complete

        def lose_lease_before_completion(journal, task, token, stage, result):
            if stage == 'vision-0':
                raise WorkflowError('lease_lost')
            return complete(journal, task, token, stage, result)

        with patch.object(VideoJournal, 'complete', lose_lease_before_completion):
            with self.assertRaisesRegex(WorkflowError, 'lease_lost'):
                self.run_pipeline()
        dispatcher = self._recovery_dispatcher()
        quote = self._recovery_quote(dispatcher)
        self.assertEqual((quote['mode'], quote['amount']), ('restore', None))
        dispatcher.recover_model(self.task, quote)
        self.assertEqual(dispatcher.process_next()['dispatch_state'], 'done')
        self.assertEqual((self.s.submit_count, self.s.vision_count), (1, 1))

    def test_paid_stage_retry_binds_quote_and_preserves_reservations(self):
        self.s.mode = 'vision'
        with self.assertRaises(WorkflowError):
            self.run_pipeline()
        dispatcher = self._recovery_dispatcher()
        quote = self._recovery_quote(dispatcher)
        self.assertEqual((quote['stage'], quote['mode'], quote['attempt']), ('vision-0', 'retry', 1))
        with self.assertRaisesRegex(WorkflowError, 'paid_consent_required'):
            dispatcher.recover_model(self.task, quote)
        with self.assertRaisesRegex(WorkflowError, 'model_recovery_conflict'):
            dispatcher.recover_model(self.task, dict(quote, amount='0.01', allow_paid=True))
        self.assertEqual(self.s.vision_count, 1)
        dispatcher.recover_model(self.task, dict(quote, allow_paid=True))
        with self.assertRaisesRegex(WorkflowError, 'dispatch_conflict'):
            dispatcher.recover_model(self.task, dict(quote, allow_paid=True))
        self.assertEqual(dispatcher.process_next()['dispatch_state'], 'error')
        self.assertEqual(self.s.vision_count, 2)
        next_quote = self._recovery_quote(dispatcher)
        self.assertEqual(next_quote['attempt'], 2)
        with self.assertRaisesRegex(WorkflowError, 'model_recovery_conflict'):
            dispatcher.recover_model(self.task, dict(quote, allow_paid=True))
        self.s.mode = ''
        dispatcher.recover_model(self.task, dict(next_quote, allow_paid=True))
        self.assertEqual(dispatcher.process_next()['dispatch_state'], 'done')
        self.assertEqual((self.s.submit_count, self.s.vision_count), (1, 3))
        with closing(sqlite3.connect(self.pc['budget']['ledger'])) as ledger:
            self.assertEqual(ledger.execute('SELECT count(*) FROM reservations WHERE request_id LIKE ?',
                                            (self.task + ':vision-0%',)).fetchone()[0], 3)

    def test_recovery_dispatch_interrupted_before_task_claim(self):
        self.s.mode = 'vision'
        with self.assertRaises(WorkflowError):
            self.run_pipeline()
        dispatcher = self._recovery_dispatcher()
        quote = self._recovery_quote(dispatcher)
        dispatcher.recover_model(self.task, dict(quote, allow_paid=True))
        self.assertEqual(dispatcher._claim()['mode'], 'recover-model')
        self.assertIsNone(dispatcher.process_next())
        quote = self._recovery_quote(dispatcher)
        self.assertEqual(quote['authorized_amount'], self.pc['strategy']['reserve_cny']['vision'])
        dispatcher.recover_model(self.task, quote)
        self.s.mode = ''
        self.assertEqual(dispatcher.process_next()['dispatch_state'], 'done')
        self.assertEqual(self.s.vision_count, 2)

    def test_unstarted_retry_requires_new_quote_after_config_change(self):
        self.s.mode = 'vision'
        with self.assertRaises(WorkflowError):
            self.run_pipeline()
        dispatcher = self._recovery_dispatcher()
        quote = self._recovery_quote(dispatcher)
        dispatcher.recover_model(self.task, dict(quote, allow_paid=True))
        dispatcher._claim()
        dispatcher.process_next()
        self.pc['strategy']['reserve_cny']['vision'] = '0.2'
        changed = self._recovery_quote(dispatcher)
        self.assertEqual((changed['mode'], changed['attempt'], changed['amount']), ('retry', 2, '0.2'))
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
