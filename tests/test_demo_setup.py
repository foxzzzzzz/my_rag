import copy, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; TMP=ROOT/'tmp'; TMP.mkdir(exist_ok=True)
class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TMP); self.dir=Path(self.temp.name); self.cfg=self.dir/'config.json'; self.envfile=self.dir/'.env'
        self.c=json.loads((ROOT/'config/demo-models.json').read_text(encoding='utf-8-sig')); self.c['source_root']=str((self.dir/'sources').relative_to(ROOT)); (self.dir/'sources').mkdir()
        (self.dir/'sources'/'a.mp4').write_bytes(b'video'); (self.dir/'sources'/'b.html').write_bytes(b'html'); self.save()
        self.env={'PATH':os.environ.get('PATH',''),'SYSTEMROOT':os.environ.get('SYSTEMROOT',''),'PYTHONIOENCODING':'utf-8'}
    def tearDown(self): self.temp.cleanup()
    def save(self): self.cfg.write_text(json.dumps(self.c),encoding='utf8')
    def runcli(self,*args): return subprocess.run([sys.executable,'-m','tools.demo_setup',*map(str,args),'--config',str(self.cfg),'--env-file',str(self.envfile)],cwd=ROOT,env=self.env,capture_output=True,text=True,encoding='utf8')
    def test_c01_missing(self):
        result=self.runcli('doctor','--json'); self.assertEqual(result.returncode,1); data=json.loads(result.stdout); self.assertEqual(data['keys']['DASHSCOPE_API_KEY'],'missing'); self.assertFalse(data['service_verified'])
    def test_c02_env_priority_no_secret(self):
        self.envfile.write_text('DASHSCOPE_API_KEY="fake-file-secret"\nDEEPSEEK_API_KEY=fake-second-secret\n',encoding='utf8'); self.env['DASHSCOPE_API_KEY']='fake-env-secret'
        out=self.runcli('doctor','--json'); self.assertNotIn('fake-',out.stdout+out.stderr); self.assertEqual(json.loads(out.stdout)['keys']['DASHSCOPE_API_KEY'],'configured')
    def test_c03_bom_comments_invalid(self):
        self.envfile.write_text('\ufeff# comment\nDASHSCOPE_API_KEY="fake-a" # comment\nDEEPSEEK_API_KEY=\'fake-b\'\n',encoding='utf8'); self.assertNotEqual(self.runcli('doctor','--json').returncode,2)
        self.envfile.write_text('bad line secret-data',encoding='utf8'); result=self.runcli('doctor','--json'); self.assertEqual(result.returncode,2); self.assertNotIn('secret-data',result.stderr+result.stdout)
    def test_c04_init_no_overwrite(self):
        (self.dir/'.env.example').write_text('DASHSCOPE_API_KEY=\n',encoding='utf8'); self.assertEqual(self.runcli('init').returncode,0); self.envfile.write_text('keep',encoding='utf8'); self.assertEqual(self.runcli('init').returncode,0); self.assertEqual(self.envfile.read_text(),'keep')
    def test_c05_ffmpeg_explicit_path_and_ready(self):
        from tools import demo_setup
        from unittest.mock import patch
        from types import SimpleNamespace
        self.envfile.write_text('DASHSCOPE_API_KEY=fake-a\nDEEPSEEK_API_KEY=fake-b\nFFMPEG_PATH=local-ffmpeg\n',encoding='utf8')
        with patch.dict(os.environ,{},clear=True), patch.object(demo_setup.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'ffmpeg version test')) as run:
            report=demo_setup.doctor(self.c,self.envfile)
        self.assertTrue(report['ready_for_smoke_test']); self.assertEqual(report['ffmpeg'],'local-version-ok'); self.assertEqual(run.call_args.args[0][0],'local-ffmpeg')
    def test_c05_path_search(self):
        from tools import demo_setup
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch.dict(os.environ,{},clear=True), patch.object(demo_setup.shutil,'which',return_value='path-ffmpeg'), patch.object(demo_setup.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'ffmpeg version test')) as run:
            self.assertEqual(demo_setup.ffmpeg(self.c,{}),'local-version-ok'); self.assertEqual(run.call_args.args[0][0],'path-ffmpeg')
    def test_c01_placeholder_and_os_override(self):
        self.envfile.write_text('DASHSCOPE_API_KEY=fake-a\nDEEPSEEK_API_KEY=fake-b\n',encoding='utf8'); self.env['DASHSCOPE_API_KEY']='replace_me'
        result=self.runcli('doctor','--json'); self.assertEqual(json.loads(result.stdout)['keys']['DASHSCOPE_API_KEY'],'missing')
    def test_c06_missing_directory(self):
        self.c['source_root']='tmp/absent-test-folder-xyz'; self.save(); report=json.loads(self.runcli('doctor','--json').stdout); self.assertIn('素材目录不存在',report['issues'])
    def test_c07_traversal(self):
        self.c['source_root']='../outside'; self.save(); self.assertEqual(self.runcli('doctor','--json').returncode,2)
    def test_c06_duplicate_missing(self):
        (self.dir/'sources'/'copy.mp4').write_bytes(b'video'); out=self.runcli('doctor','--json'); self.assertTrue(any('重复' in x for x in json.loads(out.stdout)['issues']))
    def test_c07_invalid_url_and_budget(self):
        for k,v in [('url','http://bad'),('budget','101'),('nan','NaN')]:
            c=copy.deepcopy(self.c)
            if k=='url': c['providers']['deepseek']['compatible_base_url']=v
            else: c['limits']['research_budget_cny']=v
            self.cfg.write_text(json.dumps(c),encoding='utf8'); self.assertEqual(self.runcli('doctor','--json').returncode,2)
    def test_c08_offline(self):
        self.envfile.write_text('DASHSCOPE_API_KEY=fake-a\nDEEPSEEK_API_KEY=fake-b\n',encoding='utf8'); data=json.loads(self.runcli('doctor','--json').stdout); self.assertEqual(data['network_requests'],0); self.assertEqual(data['model_calls'],0); self.assertFalse(data['service_verified'])
