import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tmp/web-deps'))
from fastapi.testclient import TestClient
from personalkb.web_app import create_app, load_web_config
from personalkb.rag_auto_index import RagAutoIndex
from personalkb.workflow_store import WorkflowError, WorkflowStore
class Index:
 config={'enabled':True}
 def status(self): return {'ready':False}
 def citation(self,chunk_id): raise WorkflowError('rag_invalidated')
 def build(self,**kwargs): return kwargs
 def query(self,**kwargs): return []
class Answers:
 def stream(self,**kwargs):
  yield {'type':'progress'}
  yield {'type':'error','code':'rag_invalidated'}
 def ask(self,**kwargs): return {}
class Service:
 rag=Index(); rag_answers=Answers()
 def __init__(self, path):
  self.rag_auto_index=RagAutoIndex(WorkflowStore(path),lambda:self.rag,enabled=True,reconcile_seconds=1)
 def rag_status(self): return {**self.rag.status(),'auto_index':self.rag_auto_index.status()}
 def start(self): pass
 def stop(self): pass
class RagApiTests(unittest.TestCase):
 def setUp(self):
  c=load_web_config();c['trusted_hosts'].append('testserver');wc={'quality_target':98,'max_upload_bytes':100,'max_html_bytes':50}
  tmp=tempfile.TemporaryDirectory(dir='tmp');self.addCleanup(tmp.cleanup)
  self.client=TestClient(create_app(wc,{},c,Service(Path(tmp.name)/'workflow.db')));self.client.__enter__()
 def tearDown(self): self.client.__exit__(None,None,None)
 def test_security_validation_and_citation(self):
  c=self.client;self.assertEqual(c.get('/api/rag/status').status_code,401)
  token=c.get('/api/session').json()['csrf_token'];h={'x-csrf-token':token};self.assertEqual(c.post('/api/rag/build',json={'allow_paid':True,'request_id':'a'}).status_code,403)
  self.assertEqual(c.post('/api/rag/build',json={'allow_paid':'yes','request_id':'a'},headers=h).status_code,400)
  base={'question':'test','allow_paid':False,'request_id':'a','mode':'lexical'}
  self.assertEqual(c.post('/api/rag/search',json={**base,'filters':{'topics':'x'}},headers=h).status_code,400)
  self.assertEqual(c.post('/api/rag/search',json={**base,'request_id':''},headers=h).status_code,400)
  r=c.get('/api/rag/citations/old');self.assertEqual(r.status_code,409);self.assertNotIn('text',r.json())
  r=c.post('/api/rag/stream',json=base,headers=h);self.assertIn('"type": "progress"',r.text);self.assertIn('"type": "error"',r.text)
 def test_automatic_index_permissions_and_paid_consent(self):
  c=self.client; h={'x-csrf-token':c.get('/api/session').json()['csrf_token']}
  self.assertTrue(c.get('/api/rag/status').json()['auto_index']['enabled'])
  self.assertEqual(c.post('/api/rag/auto-index',json={'enabled':False}).status_code,403)
  self.assertEqual(c.post('/api/rag/auto-index',json={'enabled':False},headers=h).json()['state'],'paused')
  self.assertEqual(c.post('/api/rag/auto-index',json={'enabled':True},headers=h).json()['error'],'paid_consent_required')
  self.assertEqual(c.post('/api/rag/index/retry',json={},headers=h).json()['error'],'paid_consent_required')
  self.assertEqual(c.post('/api/rag/index/retry',json={'allow_paid':True},headers=h).json()['state'],'queued')
