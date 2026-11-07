import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from personalkb import workflow
from personalkb.douyin_import import DouyinImporter
from personalkb.workflow_store import WorkflowError

class DouyinImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.wc=workflow.load_config(); self.wc['data_dir']=str(self.root/'data')
        self.cfg={'enabled':True,'resolver_python':__import__('sys').executable,'cookie_env':'COOKIE','lease_seconds':30,'max_attempts':3,'min_free_bytes':1}
        self.calls=[]
        self.worker=DouyinImporter(self.wc,self.cfg,{'COOKIE':'secret'},share_resolver=lambda url,cfg:'123',resolver=self.resolve,downloader=self.download)
    def tearDown(self): self.tmp.cleanup()
    def resolve(self,work,cookie,cfg): self.calls.append('resolve'); return {'media_url':'https://secret.example/media'}
    def download(self,url,target,cfg): self.calls.append('download'); target.write_bytes(b'video')
    def test_success_cache_and_safe_response(self):
        source=self.worker.store.import_source('video','a'*64,'v.mp4','originals/'+('a'*64))['source']
        def fake_import(wc,path,rights_confirmed,**kwargs): return {'source':source}
        with patch('personalkb.douyin_import.workflow.import_file',fake_import):
            self.worker.enqueue('https://www.douyin.com/video/123',True)
            job=self.worker.process_next(); self.assertEqual(job['status'],'succeeded')
            self.assertNotIn('secret',str(job)); self.assertNotIn('canonical_url',str(self.worker.jobs()))
        self.assertEqual(self.calls,['resolve','download'])
        with self.worker.store._tx() as c: self.assertIsNone(c.execute('SELECT * FROM video_maintenance').fetchone())
    def test_failure_retry_and_global_lock(self):
        job=self.worker.enqueue('https://www.douyin.com/video/123',True)
        with self.worker.store._tx() as c: c.execute('INSERT INTO video_maintenance VALUES(1)')
        self.assertIsNone(self.worker.process_next())
        with self.worker.store._tx() as c: c.execute('DELETE FROM video_maintenance')
        self.worker.downloader=lambda *args: (_ for _ in ()).throw(ValueError('secret'))
        result=self.worker.process_next(); self.assertEqual(result['error_code'],'douyin_import_failed')
        self.assertEqual(self.worker.retry(job['id'])['status'],'queued')
    def test_recover_expired_own_lock_and_preserve_unrelated(self):
        job=self.worker.enqueue('https://www.douyin.com/video/123',True)
        with self.worker.store._tx() as c:
            c.execute("UPDATE douyin_jobs SET status='running',token='own',lease_until=0 WHERE id=?",(job['id'],))
            c.execute('INSERT INTO video_maintenance VALUES(1)')
            c.execute("INSERT INTO douyin_lock VALUES(1,?,'own')",(job['id'],))
        self.cfg['enabled']=False; self.worker.recover_expired()
        self.assertEqual(self.worker.jobs()[0]['status'],'needs_attention')
        with self.worker.store._tx() as c:
            self.assertIsNone(c.execute('SELECT * FROM video_maintenance').fetchone())
            c.execute('INSERT INTO video_maintenance VALUES(1)')
        self.worker.recover_expired()
        with self.worker.store._tx() as c: self.assertIsNotNone(c.execute('SELECT * FROM video_maintenance').fetchone())

    def test_running_task_blocks_and_lost_lease_cannot_finish(self):
        job=self.worker.enqueue('https://www.douyin.com/video/123',True)
        source=self.worker.store.import_source('video','b'*64,'v','originals/b')
        with self.worker.store._tx() as c: c.execute("UPDATE tasks SET status='running' WHERE id=?",(source['task']['id'],))
        self.assertIsNone(self.worker.process_next())
        with self.worker.store._tx() as c: c.execute("UPDATE tasks SET status='queued' WHERE id=?",(source['task']['id'],))
        def expire(url,target,cfg):
            target.write_bytes(b'x')
            with self.worker.store._tx() as c: c.execute('UPDATE douyin_jobs SET lease_until=0 WHERE id=?',(job['id'],))
        self.worker.downloader=expire
        with patch('personalkb.douyin_import.workflow.import_file') as imported:
            self.assertEqual(self.worker.process_next()['status'],'needs_attention')
            imported.assert_not_called()

    def test_revoked_during_real_import_cannot_commit_source(self):
        from personalkb.workflow_store import WorkflowStore
        job=self.worker.enqueue('https://www.douyin.com/video/123',True)
        self.worker.downloader=lambda url,target,cfg: target.write_bytes(b'\x00\x00\x00\x10ftypmp42')
        original=WorkflowStore.import_source
        def revoke(store,*args,**kwargs):
            with store._tx() as c: c.execute('UPDATE douyin_jobs SET lease_until=0 WHERE id=?',(job['id'],))
            return original(store,*args,**kwargs)
        class Probe: stderr=b'Stream Video:'
        with patch.object(WorkflowStore,'import_source',revoke), patch('personalkb.workflow.shutil.which',return_value='ffmpeg'), patch('personalkb.workflow.subprocess.run',return_value=Probe()):
            result=self.worker.process_next()
        self.assertEqual(result['status'],'needs_attention')
        with self.worker.store._tx() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM sources').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],0)

    def test_disabled_and_rights(self):
        self.cfg['enabled']=False
        with self.assertRaises(WorkflowError): self.worker.enqueue('https://www.douyin.com/video/123',True)
        self.cfg['enabled']=True
        with self.assertRaises(WorkflowError): self.worker.enqueue('https://www.douyin.com/video/123',False)
        self.assertEqual(self.worker.jobs(),[])

    def test_safe_resolver_errors_persist(self):
        for code in ('download_denied','download_permission_unknown','douyin_resolver_failed','media_tool_missing','secret'):
            with self.subTest(code=code):
                self.worker.resolver=lambda *args: (_ for _ in ()).throw(WorkflowError(code))
                job=self.worker.enqueue('https://www.douyin.com/video/123',True)
                result=self.worker.process_next()
                self.assertEqual(result['error_code'], code if code != 'secret' else 'douyin_import_failed')
                self.assertEqual(next(x for x in self.worker.jobs() if x['id']==job['id'])['error_code'],result['error_code'])
                self.assertEqual(self.calls,[])

    def test_missing_media_tool_during_import(self):
        self.worker.enqueue('https://www.douyin.com/video/123',True)
        with patch('personalkb.douyin_import.workflow.import_file',side_effect=WorkflowError('media_tool_missing')):
            result=self.worker.process_next()
        self.assertEqual(result['error_code'],'media_tool_missing')
        with self.worker.store._tx() as c:
            self.assertIsNone(c.execute('SELECT * FROM douyin_lock').fetchone())
            self.assertIsNone(c.execute('SELECT * FROM video_maintenance').fetchone())
