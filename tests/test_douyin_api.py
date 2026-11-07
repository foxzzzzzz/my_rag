import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tmp/web-deps'))
from fastapi.testclient import TestClient
from personalkb import workflow
from personalkb.web_app import create_app, load_web_config
from personalkb.web_service import WebService

class DouyinApiTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]; self.tmp=tempfile.TemporaryDirectory(dir=root/'tmp'); self.path=Path(self.tmp.name)
        self.cfg=json.loads((root/'config/douyin.json').read_text(encoding='utf8')); self.cfg.update(enabled=False,resolver_python=sys.executable)
        self.config=self.path/'douyin.json'; self.write_config()
        self.env=self.path/'env'; self.env.write_text('PERSONALKB_DOUYIN_COOKIE=fake-cookie-only\n',encoding='utf8')
        web=load_web_config(); web['trusted_hosts'].append('testserver'); web.update(douyin_config=str(self.config),env_file=str(self.env))
        self.wc=workflow.load_config(); self.wc.update(data_dir=str(self.path/'data'),min_free_bytes=0)
        self.service=WebService(self.wc,{},web); self.service.start=lambda:None; self.service.stop=lambda:None
        self.client=TestClient(create_app(self.wc,{},web,self.service)); self.client.__enter__(); self.h={'x-csrf-token':self.client.get('/api/session').json()['csrf_token']}
    def write_config(self): self.config.write_text(json.dumps(self.cfg),encoding='utf8')
    def enable(self): self.cfg['enabled']=True; self.write_config()
    def tearDown(self): self.client.__exit__(None,None,None); self.tmp.cleanup()
    def test_disabled_no_dotenv_or_enqueue(self):
        with patch('tools.demo_setup.dotenv') as dotenv:
            status=self.client.get('/api/douyin/status'); self.assertFalse(status.json()['enabled']); dotenv.assert_not_called()
        self.assertEqual(self.client.post('/api/douyin/import',json={'share_text':'https://www.douyin.com/video/123','rights_confirmed':True},headers=self.h).status_code,400)
        self.assertEqual(self.client.get('/api/douyin/jobs').json()['items'],[])
    def test_enabled_enqueue_safe_output_and_retry(self):
        self.enable()
        p={'share_text':'https://www.douyin.com/video/123','rights_confirmed':True}
        self.assertEqual(self.client.post('/api/douyin/import',json={**p,'rights_confirmed':False},headers=self.h).status_code,400)
        res=self.client.post('/api/douyin/import',json=p,headers=self.h); self.assertEqual(res.status_code,200); job=res.json()
        for response in (res,self.client.get('/api/douyin/jobs'),self.client.get('/api/douyin/status')):
            for secret in ('fake-cookie-only',str(self.path),'https://www.douyin.com'): self.assertNotIn(secret,response.text)
        url='/api/douyin/jobs/'+job['id']+'/retry'
        self.assertEqual(self.client.post(url,json={},headers=self.h).status_code,409)
        with self.service.store._tx() as c: c.execute("UPDATE douyin_jobs SET status='failed' WHERE id=?",(job['id'],))
        self.assertEqual(self.client.post(url,json={},headers=self.h).json()['status'],'queued')
    def test_missing_config_does_not_block_html_or_recovery(self):
        self.enable(); job=self.client.post('/api/douyin/import',json={'share_text':'https://www.douyin.com/video/123','rights_confirmed':True},headers=self.h).json()
        with self.service.store._tx() as c:
            c.execute("UPDATE douyin_jobs SET status='running',token='own',lease_until=0 WHERE id=?",(job['id'],)); c.execute('INSERT INTO video_maintenance VALUES(1)'); c.execute("INSERT INTO douyin_lock VALUES(1,?,'own')",(job['id'],))
        self.config.unlink()
        source=self.client.put('/api/imports?filename=preview.html&rights_confirmed=true',content=b'<html><body>preview</body></html>',headers=self.h).json()
        self.service.dispatcher.enqueue(source['task_id'],processing_mode='preview')
        self.service.process_next()
        self.assertEqual(self.service.store.get_task(source['task_id'])['status'],'succeeded')
        with self.service.store._tx() as c: self.assertIsNone(c.execute('SELECT * FROM video_maintenance').fetchone())
