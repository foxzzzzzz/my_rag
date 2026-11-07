import tempfile, unittest
from pathlib import Path
from personalkb.workflow_store import WorkflowStore, WorkflowError
from personalkb.video_journal import VideoJournal

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir="tmp"); self.db=str(Path(self.tmp.name)/'db.sqlite')
        self.store=WorkflowStore(self.db); self.j=VideoJournal(self.store)
        self.task=self.store.import_source('video','a'*64,'v.mp4','v.mp4')['task']['id']
        self.token=self.j.claim_task(self.task,'worker')['lease_token']
    def tearDown(self): self.tmp.cleanup()
    def test_restart_and_conflict(self):
        self.j.bind(self.task,self.token,'fingerprint'); self.j.begin(self.task,self.token,'asr','b'*64)
        self.j.mark_started(self.task,self.token,'asr'); self.j.save_remote(self.task,self.token,'asr','remote')
        self.j.complete(self.task,self.token,'asr',{'text':'ok'})
        self.assertEqual(VideoJournal(WorkflowStore(self.db)).stage(self.task,'asr')['result'],{'text':'ok'})
        with self.assertRaises(WorkflowError): self.j.begin(self.task,self.token,'asr','c'*64)
    def test_old_lease_and_uncertain(self):
        self.j.begin(self.task,self.token,'asr','b'*64); self.j.mark_started(self.task,self.token,'asr')
        self.store.fail(self.task,self.token,'uncertain'); new=self.j.resume_claim(self.task,'second')['lease_token']
        with self.assertRaises(WorkflowError): self.j.complete(self.task,self.token,'asr',{})
        with self.assertRaises(WorkflowError): self.j.mark_started(self.task,new,'asr')
    def test_cleanup_excludes_running(self):
        with self.assertRaises(WorkflowError):
            with self.j.cleanup_claim(self.task): pass
        self.store.fail(self.task,self.token,'fail')
        with self.j.cleanup_claim(self.task): self.assertEqual(self.j.assets(self.task),[])

    def test_corrupt_completed_result_rejected(self):
        self.j.begin(self.task,self.token,'asr','b'*64); self.j.mark_started(self.task,self.token,'asr'); self.j.complete(self.task,self.token,'asr',{'text':'ok'})
        with self.store._tx() as c: c.execute("UPDATE video_stages SET result='{}'")
        with self.assertRaises(WorkflowError): self.j.stage(self.task,'asr')
    def test_maintenance_blocks_claim(self):
        import sqlite3
        self.store.fail(self.task,self.token,'done')
        other=self.store.import_source('video','c'*64,'other','other')['task']['id']
        store=WorkflowStore(self.db,busy_timeout_seconds=0.01)
        with self.j.cleanup_claim(self.task):
            with self.assertRaises(sqlite3.OperationalError): store.claim('another')
        self.assertEqual(store.claim('another')['id'],other)
    def test_asset_validation_and_idempotency(self):
        m=dict(asset_id='asset',backend='managed_oss',object_key='prefix/a.wav',source_sha256='a'*64,size_bytes=2,model='m',expires_at=123,scope=dict(bucket='test-bucket',endpoint='https://oss-cn-beijing.aliyuncs.com',region='cn-beijing',prefix='prefix/'))
        self.j.register_asset(self.task,self.token,m); self.j.register_asset(self.task,self.token,m)
        for bad in (dict(m,file_url='https://secret'),dict(m,size_bytes=0),dict(m,object_key='other/a.wav'),dict(m,model='changed')):
            with self.assertRaises(WorkflowError): self.j.register_asset(self.task,self.token,bad)
    def test_remote_id_cannot_rebind(self):
        self.j.begin(self.task,self.token,'asr','b'*64); self.j.mark_started(self.task,self.token,'asr')
        for invalid in ('', 'https://evil', 'bad id'):
            with self.assertRaises(WorkflowError): self.j.save_remote(self.task,self.token,'asr',invalid)
        self.j.save_remote(self.task,self.token,'asr','remote-1')
        with self.assertRaises(WorkflowError): self.j.save_remote(self.task,self.token,'asr','remote-2')

    def test_rollback_requires_lease_task_and_registered(self):
        m=dict(asset_id='asset',backend='managed_oss',object_key='prefix/a.wav',source_sha256='a'*64,size_bytes=2,model='m',expires_at=123,scope=dict(bucket='test-bucket',endpoint='https://oss-cn-beijing.aliyuncs.com',region='cn-beijing',prefix='prefix/'))
        self.j.register_asset(self.task,self.token,m)
        with self.assertRaises(WorkflowError): self.j.asset_rolled_back(self.task,'bad','asset')
        other=self.store.import_source('video','c'*64,'other','other')['task']['id']
        with self.assertRaises(WorkflowError): self.j.asset_rolled_back(other,self.token,'asset')
        self.j.asset_rolled_back(self.task,self.token,'asset'); self.j.asset_rolled_back(self.task,self.token,'asset')
        self.assertEqual(self.j.assets(self.task)[0]['status'],'deleted')
        m['asset_id']='second'; self.j.register_asset(self.task,self.token,m); self.j.asset_terminal(self.task,self.token,'second')
        with self.assertRaises(WorkflowError): self.j.asset_rolled_back(self.task,self.token,'second')
        self.store.fail(self.task,self.token,'done')
        with self.j.cleanup_claim(self.task):
            with self.assertRaises(WorkflowError): self.j.mark_cleaned('second','arbitrary')
            self.j.mark_cleaned('second','deleted')

if __name__=='__main__': unittest.main()
