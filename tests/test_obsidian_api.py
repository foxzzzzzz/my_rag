import io, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tmp/web-deps'))
from fastapi.testclient import TestClient
from personalkb import workflow
from personalkb.web_app import create_app, load_web_config
from personalkb.web_service import WebService

class ObsidianAPITests(unittest.TestCase):
 def setUp(self):
  root=Path(__file__).resolve().parents[1]/'tmp'; root.mkdir(exist_ok=True)
  self.temp=tempfile.TemporaryDirectory(dir=root); p=Path(self.temp.name)
  c=load_web_config(); c['trusted_hosts'].append('testserver'); c['frontend_dist']=str(p/'missing')
  wc=workflow.load_config(); wc.update(data_dir=str(p/'data'),min_free_bytes=0)
  self.s=WebService(wc,{},c); self.s.start=lambda:None; self.s.stop=lambda:None
  x=self.s.store.import_source('html','a'*64,'a','originals/a'); self.sid=x['source']['id']; t=self.s.store.claim_specific(x['task']['id'],'test')
  result=dict(title='Title',body='Body',summary='Summary',notes='Notes',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'text':'proof'}])
  self.v=self.s.store.finish(t['id'],t['lease_token'],result)
  self.client=TestClient(create_app(wc,{},c,self.s)); self.client.__enter__(); self.h={'x-csrf-token':self.client.get('/api/session').json()['csrf_token']}
 def tearDown(self):
  self.client.__exit__(None,None,None); self.temp.cleanup()
 def get(self,kind): return self.client.get(f'/api/sources/{self.sid}/obsidian/{kind}')
 def test_downloads(self):
  n=self.get('note'); self.assertEqual(n.status_code,200); self.assertIn(b'pkb-obsidian-v1',n.content); self.assertIn('text/markdown',n.headers['content-type'])
  z=self.get('zip'); self.assertEqual(z.status_code,200); self.assertIn('note.md',zipfile.ZipFile(io.BytesIO(z.content)).namelist())
 def test_preview_apply(self):
  note=self.get('note').content.replace(b'Notes',b'Edited')
  r=self.client.post('/api/obsidian/preview?filename=note.md',content=note,headers={**self.h,'content-type':'text/markdown'}); self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(self.s.store.get_source(self.sid)['current_version_id'],self.v['id'])
  a=self.client.post('/api/obsidian/apply',json={'preview_id':r.json()['preview_id'],'choice':'use_uploaded'},headers=self.h); self.assertEqual(a.status_code,200,a.text)
  self.assertTrue(a.json()['review_required']); self.assertEqual(self.s.store.get_version(a.json()['version_id'])['output_kind'],'human_edited')
 def test_csrf(self):
  r=self.client.post('/api/obsidian/preview?filename=note.md',content=b'x'); self.assertEqual(r.status_code,403)
 def test_size(self):
  self.s.obsidian.config=dict(self.s.obsidian.config,max_input_bytes=10)
  r=self.client.post('/api/obsidian/preview?filename=note.md',content=b'x'*11,headers=self.h); self.assertEqual(r.status_code,413,r.text)
 def test_invalid(self):
  r=self.client.post('/api/obsidian/preview?filename=note.md',content=b'garbage',headers=self.h); self.assertEqual(r.status_code,400)
 def test_unknown_deleted(self):
  self.assertEqual(self.client.get('/api/sources/'+('0'*32)+'/obsidian/note').status_code,404)
  self.s.store.delete_source(self.sid); self.assertEqual(self.get('note').status_code,400)
