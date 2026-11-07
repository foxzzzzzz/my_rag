import json, tempfile, unittest
from pathlib import Path
from dataclasses import replace
from personalkb.asr_storage import StorageError
from personalkb.asr_storage_managed import ManagedOSSStorage
from personalkb.workflow_store import WorkflowStore, WorkflowError
from personalkb.video_journal import VideoJournal

class Bucket:
    def __init__(self): self.calls=[]; self.fail=False
    def put_object_from_file(self,*a,**kw): self.calls.append('put')
    def sign_url(self,*a,**kw): return 'https://test-bucket.oss-cn-beijing.aliyuncs.com/a?secret=x'
    def delete_object(self,key):
        self.calls.append('delete')
        if self.fail: raise OSError()

class Owner:
    def __init__(self,j,task,token,scope): self.j=j; self.task=task; self.token=token; self.scope=scope
    def register(self,m): self.j.register_asset(self.task,self.token,m)
    def owns(self,a):
        return any(x['asset_id']==a.asset_id and x['object_key']==a.object_key and x['scope']==self.scope and x['status']=='remote_terminal' for x in self.j.assets(self.task))
    def deleted(self,a): self.j.mark_cleaned(a.asset_id,'deleted')

class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='tmp'); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'a.wav'; self.path.write_bytes(b'audio')
        self.config=json.loads(Path('config/asr-storage.json').read_text(encoding='utf-8')); self.config['managed_oss']['bucket']='test-bucket'
        self.scope={k:self.config['managed_oss'][k] for k in ('bucket','endpoint','region','prefix')}
        self.secrets={'PERSONALKB_OSS_ACCESS_KEY_ID':'id','PERSONALKB_OSS_ACCESS_KEY_SECRET':'secret'}
        self.db=str(Path(self.tmp.name)/'db'); self.store=WorkflowStore(self.db); self.j=VideoJournal(self.store)
        self.task=self.store.import_source('video','a'*64,'v','v')['task']['id']; self.token=self.j.claim_task(self.task,'w')['lease_token']
        self.bucket=Bucket(); self.owner=Owner(self.j,self.task,self.token,self.scope)
    def storage(self,owner=None): return ManagedOSSStorage(self.config,self.secrets,lambda c,s:self.bucket,owner or self.owner)
    def test_cross_instance_cleanup(self):
        a=self.storage().prepare(self.path,'model'); self.j.asset_terminal(self.task,self.token,a.asset_id); self.store.fail(self.task,self.token,'done')
        j=VideoJournal(WorkflowStore(self.db)); owner=Owner(j,self.task,self.token,self.scope)
        with j.cleanup_claim(self.task): self.storage(owner).cleanup(replace(a,file_url=''))
        self.assertEqual(j.assets(self.task)[0]['status'],'deleted')
    def test_wrong_scope_and_nonterminal(self):
        a=self.storage().prepare(self.path,'model'); self.store.fail(self.task,self.token,'done')
        with self.j.cleanup_claim(self.task):
            with self.assertRaises(StorageError): self.storage().cleanup(a)
        self.assertNotIn('delete',self.bucket.calls)
        # Scope mismatch remains rejected even for terminal ledger records.
        with self.store._tx() as c: c.execute("UPDATE video_assets SET status='remote_terminal'")
        bad=Owner(self.j,self.task,self.token,dict(self.scope,bucket='other-bucket'))
        with self.j.cleanup_claim(self.task):
            with self.assertRaises(StorageError): self.storage(bad).cleanup(a)
    def test_failed_delete_retry(self):
        a=self.storage().prepare(self.path,'model'); self.j.asset_terminal(self.task,self.token,a.asset_id); self.store.fail(self.task,self.token,'done'); self.bucket.fail=True
        with self.assertRaises(StorageError):
            with self.j.cleanup_claim(self.task): self.storage().cleanup(a)
        self.assertEqual(self.j.assets(self.task)[0]['status'],'remote_terminal'); self.bucket.fail=False
        with self.j.cleanup_claim(self.task): self.storage().cleanup(a)
        self.assertEqual(self.j.assets(self.task)[0]['status'],'deleted')
    def test_registration_failure_prevents_put(self):
        self.store.fail(self.task,self.token,'failed')
        with self.assertRaises(WorkflowError): self.storage().prepare(self.path,'model')
        self.assertEqual(self.bucket.calls,[])
