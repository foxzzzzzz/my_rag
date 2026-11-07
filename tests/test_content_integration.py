import hashlib, json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tmp/web-deps'))
from fastapi.testclient import TestClient
from personalkb.workflow import load_config, import_file, run_once, make_store, export_version
from personalkb.html_pipeline import load_html_config, run_html
from personalkb.web_service import WebService
from personalkb.web_app import create_app, load_web_config

class Provider:
    def __init__(self): self.calls=0
    def summarize(self, body, title):
        self.calls+=1
        return {'structured':{'summary':'摘要','notes':'笔记'},'model':'fake','usage':{'input_tokens':1},'estimated_cost_cny':'0.001'}

class ContentIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='tmp'); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name).resolve()
        self.wc=load_config(); self.wc.update(data_dir=str(self.root/'data'),min_free_bytes=0)
        self.cfg=load_web_config(); self.cfg['trusted_hosts'].append('testserver'); self.cfg['frontend_dist']=str(self.root/'missing')
        self.s=WebService(self.wc,{},self.cfg); self.s.start=lambda:None; self.s.stop=lambda:None
        p=self.root/'sample.html'; p.write_text('<html><body>Evidence</body></html>',encoding='utf8')
        obj=import_file(self.wc,p,True); self.sid=obj['source']['id']; self.tid=obj['task']['id']
    def test_html_write_failure_reconcile_without_repost(self):
        config=load_html_config(); config['budget']['ledger']=str(self.root/'ledger'); provider=Provider()
        with patch('personalkb.content_storage.write',side_effect=OSError('disk')):
            version=run_html(self.wc,config,{},task_id=self.tid,services=provider)
        store=make_store(self.wc)
        self.assertEqual(store.get_task(self.tid)['status'],'succeeded')
        self.assertEqual(store.content_status(self.sid),'content_unsynced'); self.assertEqual(store.eligible_sources(),[])
        self.assertEqual(store.reconcile(self.sid)[self.sid],'synced')
        self.assertEqual([v['id'] for v in store.list_versions(self.sid)],[version['id']]); self.assertEqual(provider.calls,1)
        progress=next(t['progress'] for t in self.s.tasks()['items'] if t['id']==self.tid)
        self.assertEqual(progress,dict(completed_stages=1,total_stages=1,completed_frames=None,total_frames=None))
        with store._tx() as db: self.assertEqual(db.execute('SELECT count(*) FROM reviews').fetchone()[0],0)
    def test_exports_match_across_review_and_old_version(self):
        v=run_once(self.wc,task_id=self.tid); store=make_store(self.wc)
        def check(version, label):
            path=export_version(self.wc,version['id'],self.root/'data'/label)['path']
            self.assertEqual(Path(path).read_bytes(), self.s.export(version['id'])[0])
        check(v,'pending')
        store.review(self.sid,v['id'],v['content_sha256'],99,'approve','me'); check(v,'approved')
        store.review(self.sid,v['id'],v['content_sha256'],80,'rework','me'); check(v,'rework')
        old=store.get_version(v['id']); new=dict(old['result']); new.update(body='new',output_kind='human_edited',provenance='human_edited')
        store.revise(self.sid,v['id'],new); check(v,'old')
    def test_permanent_frame_from_web_service(self):
        store=make_store(self.wc); task=store.claim_specific(self.tid,'test'); folder=self.root/'data'/'video-work'/self.tid; folder.mkdir(parents=True)
        data=b'fake-jpeg'; sha=hashlib.sha256(data).hexdigest(); (folder/'frame.jpg').write_bytes(data)
        (folder/'media-manifest.json').write_text(json.dumps({'frames':[{'index':0,'file':'frame.jpg','sha256':sha}]}))
        result=dict(title='T',body='B',summary='S',notes='N',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='provider',evidence=[{'text':'e'}],frames=[{'index':0,'seconds':0,'sha256':sha}])
        store.finish(self.tid,task['lease_token'],result); folder.rename(folder.with_name('moved'))
        self.assertEqual(self.s.frame(self.sid,0).read_bytes(),data)
    def test_api_reprocess_and_start_consent(self):
        v=run_once(self.wc,task_id=self.tid)
        with TestClient(create_app(self.wc,{},self.cfg,self.s)) as client:
            headers={'x-csrf-token':client.get('/api/session').json()['csrf_token']}; url='/api/sources/'+self.sid+'/process'
            payload={'expected_version_id':v['id'],'allow_paid':True}
            self.assertEqual(client.post(url,json=payload,headers=headers).status_code,400)
            self.cfg['live_html_enabled']=True
            self.assertEqual(client.post(url,json={**payload,'allow_paid':False},headers=headers).status_code,400)
            self.assertEqual(client.post(url,json={**payload,'expected_version_id':'bad'},headers=headers).status_code,409)
            response=client.post(url,json=payload,headers=headers); self.assertEqual(response.status_code,200,response.text)
            tid=response.json()['task_id']
            with self.s.store._tx() as db: self.assertEqual(db.execute('SELECT processing_mode FROM web_dispatch WHERE task_id=?',(tid,)).fetchone()[0],'model')
            other=self.root/'other.html'; other.write_text('<html><body>Other</body></html>',encoding='utf8')
            other_tid=import_file(self.wc,other,True)['task']['id']
            start=client.post('/api/tasks/'+other_tid+'/start',json={'processing_mode':'model','allow_paid':True},headers=headers)
            self.assertEqual(start.status_code,200,start.text)
            with self.s.store._tx() as db: self.assertEqual(db.execute('SELECT processing_mode FROM web_dispatch WHERE task_id=?',(other_tid,)).fetchone()[0],'model')
