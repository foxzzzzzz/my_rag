import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from personalkb.workflow_store import WorkflowStore, WorkflowError

class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp_root=Path(__file__).resolve().parents[1] / 'tmp'; tmp_root.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=tmp_root); self.db=Path(self.tmp.name)/'db.sqlite'; self.s=WorkflowStore(self.db,lease_seconds=10)
    def tearDown(self): self.tmp.cleanup()
    def source(self,sha='a'*64): return self.s.import_source('html',sha,'file.html','originals/file')
    def result(self,kind='machine_initial'):
        return dict(title='title',body='body',summary='summary',notes='notes',scheme_id='s',scheme_version='1',output_kind=kind,provenance='human_edited' if kind=='human_edited' else 'local_extraction',evidence=[{'text':'real evidence'}])
    def test_concurrent_import_claim_recovery(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _: WorkflowStore(self.db).import_source('html','a'*64,'a','originals/a'),range(12)))
        self.assertEqual(len({x['source']['id'] for x in results}),1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            claims=list(pool.map(lambda i: WorkflowStore(self.db,lease_seconds=10).claim(str(i),now=0),range(8)))
        t=next(x for x in claims if x); self.assertEqual(sum(x is not None for x in claims),1)
        self.s.recover_expired(now=11)
        with self.assertRaises(WorkflowError): self.s.finish(t['id'],t['lease_token'],self.result(),now=11)
        t=self.s.claim('new',now=12); self.s.checkpoint(t['id'],t['lease_token'],'submitted',remote_task_id='remote',external_started=True,now=12)
        with self.assertRaises(WorkflowError): self.s.checkpoint(t['id'],t['lease_token'],'submitted',remote_task_id='other',now=12)
        self.s.recover_expired(now=23); self.assertEqual(self.s.get_task(t['id'])['status'],'needs_attention')
        with self.assertRaises(WorkflowError): self.s.retry(t['id'])
    def test_review_revision_delete(self):
        src=self.source(); t=self.s.claim('w',now=0)
        with self.assertRaises(WorkflowError): self.s.finish(t['id'],t['lease_token'],{},now=1)
        bad=self.result(); bad['provenance']='simulation'
        with self.assertRaises(WorkflowError): self.s.finish(t['id'],t['lease_token'],bad,now=1)
        v=self.s.finish(t['id'],t['lease_token'],self.result(),now=1); sid=src['source']['id']
        self.assertEqual(self.s.get_version(v['id'])['result'],self.result())
        for score in (True,float('nan'),97,101):
            with self.assertRaises(WorkflowError): self.s.review(sid,v['id'],v['content_sha256'],score,'approve','me')
        args=(sid,v['id'],v['content_sha256'],99,'approve','me')
        a=self.s.review(*args,review_id='r'); self.assertEqual(a,self.s.review(*args,review_id='r')); self.assertEqual(len(self.s.eligible_sources()),1)
        with self.assertRaises(WorkflowError): self.s.review(sid,v['id'],v['content_sha256'],100,'approve','me',review_id='r')
        self.s.review(sid,v['id'],v['content_sha256'],99,'reject','me'); self.assertEqual(self.s.eligible_sources(),[])
        v2=self.s.revise(sid,v['id'],self.result('human_edited')); self.assertEqual(v2['parent_version_id'],v['id'])
        with self.assertRaises(WorkflowError): self.s.review(*args)
        self.s.delete_source(sid)
        with self.assertRaises(WorkflowError): self.source()
    def test_cancel_and_validation(self):
        t=self.source()['task']; t=self.s.claim('w',now=0); self.s.cancel(t['id'])
        with self.assertRaises(WorkflowError): self.s.heartbeat(t['id'],t['lease_token'],now=1)
        self.s.retry(t['id']); self.assertIsNotNone(self.s.claim('w',now=2))
        for path in ('../bad','C:\\bad','/bad','a/../b'):
            with self.assertRaises(WorkflowError): self.s.import_source('html','b'*64,'b',path)
        for val in (True,float('nan'),-1):
            with self.assertRaises(WorkflowError): WorkflowStore(self.db,quality_target=val)

    def test_retry_limit_preserves_attempts(self):
        tid=self.source()['task']['id']
        for attempt in range(1,4):
            t=self.s.claim('w',now=attempt*20)
            self.assertEqual(t['attempts'],attempt)
            self.s.fail(tid,t['lease_token'],'failure',now=attempt*20)
            if attempt < 3:
                self.assertEqual(self.s.retry(tid)['attempts'],attempt)
        with self.assertRaises(WorkflowError): self.s.retry(tid)
        self.assertIsNone(self.s.claim('w',now=100))

    def test_heartbeat_and_cancel_fence(self):
        t=self.source()['task']; t=self.s.claim('w',now=0)
        self.s.heartbeat(t['id'],t['lease_token'],now=9)
        self.s.checkpoint(t['id'],t['lease_token'],'working',now=10)
        self.s.cancel(t['id'])
        with self.assertRaises(WorkflowError): self.s.checkpoint(t['id'],t['lease_token'],'late',now=11)
        with self.assertRaises(WorkflowError): self.s.finish(t['id'],t['lease_token'],self.result(),now=11)

    def test_invalid_finish_rolls_back(self):
        src=self.source()['source']; t=self.s.claim('w',now=0)
        bad=self.result(); bad['evidence']=[]
        with self.assertRaises(WorkflowError): self.s.finish(t['id'],t['lease_token'],bad,now=1)
        self.assertEqual(self.s.get_task(t['id'])['status'],'running')
        self.assertEqual(self.s.list_versions(src['id']),[])
        self.assertIsNone(self.s.get_source(src['id'])['current_version_id'])

    def test_review_boundaries_and_revision_race(self):
        sid=self.source()['source']['id']; t=self.s.claim('w',now=0)
        v=self.s.finish(t['id'],t['lease_token'],self.result(),now=1)
        for sha,score,reviewer in [('0'*64,99,'me'),(v['content_sha256'],99,''),(v['content_sha256'],True,'me'),(v['content_sha256'],float('nan'),'me')]:
            with self.assertRaises(WorkflowError): self.s.review(sid,v['id'],sha,score,'approve',reviewer)
        self.s.review(sid,v['id'],v['content_sha256'],99,'approve','me')
        self.s.review(sid,v['id'],v['content_sha256'],80,'rework','me')
        self.assertEqual(self.s.eligible_sources(),[])
        def revise(_):
            try: return WorkflowStore(self.db).revise(sid,v['id'],self.result('human_edited'))
            except WorkflowError as e: return e.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(revise,range(2)))
        self.assertEqual(sum(isinstance(x,dict) for x in results),1)
        self.assertIn('version_conflict',results)

    def test_checkpoint_persists_after_reopen(self):
        src=self.source(); t=self.s.claim('w',now=0)
        self.s.checkpoint(t['id'],t['lease_token'],'submitted',remote_task_id='remote',now=1)
        reopened=WorkflowStore(self.db); saved=reopened.get_task(t['id'])
        self.assertEqual((saved['stage'],saved['remote_task_id'],saved['external_started']),('submitted','remote',1))
        self.assertTrue(saved['created_at']); self.assertTrue(saved['updated_at'])
        self.assertTrue(reopened.get_source(src['source']['id'])['created_at'])
        reopened.recover_expired(now=11)
        self.assertEqual(reopened.get_task(t['id'])['status'],'needs_attention')

if __name__=='__main__': unittest.main()
