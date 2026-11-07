import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TMP = PROJECT / 'tmp'
TMP.mkdir(exist_ok=True)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TMP)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.write(self.config, {'video_count': 2, 'dev_count': 1, 'acceptance_count': 1, 'html_count': 1, 'fact_count': 2, 'accuracy':'0.98', 'coverage':'0.98', 'budget':'100', 'extensions':{'video':['.mp4'],'html':['.html']}, 'required_tags':[]})
        self.manifest = self.root / 'manifest.json'
        self.lock = self.root / 'lock.json'
        self.results = self.root / 'results.json'
        samples=[]
        for ident,kind,split in [('d','video','dev'),('a','video','acceptance'),('h','html','html')]:
            data=('media-'+ident).encode(); filename=ident+('.html' if kind=='html' else '.mp4'); (self.root / filename).write_bytes(data)
            self.write(self.root / (ident+'.json'), {'reviewer':'A','confirmed':True,'facts':[{'id':'g','text':'fact','evidence':{'type':'audio','start':0,'end':1}}]})
            samples.append({'id':ident,'kind':kind,'split':split,'path':filename,'duration_seconds':None if kind=='html' else 10,'tags':[],'rights_confirmed':True,'sha256':hashlib.sha256(data).hexdigest(),'annotation':ident+'.json'})
        self.m={'samples':samples}; self.write(self.manifest,self.m)
        self.r={'split':'acceptance','version':'machine_initial','reviewer':'A','confirmed':True,'samples':[{'id':'a','predictions':[{'id':'p','text':'fact','decision':'correct','gold_id':'g','evidence':{'type':'audio','start':0,'end':1},'duplicate_of':None}]}]}
        self.write(self.results,self.r)
    def tearDown(self): self.temp.cleanup()
    def write(self,path,obj): path.write_text(json.dumps(obj),encoding='utf-8')
    def cli(self,*args):
        return subprocess.run([sys.executable,'-m','tools.research_cli','--config',str(self.config),*map(str,args)],cwd=PROJECT,text=True,encoding='utf-8',capture_output=True)
    def action(self,cmd,*extra): return self.cli(cmd,'--manifest',self.manifest,'--root',self.root,*extra)
    def freeze(self): self.assertEqual(self.action('freeze','--lock',self.lock).returncode,0)
    def evaluate(self): return self.action('evaluate','--lock',self.lock,'--results',self.results)
    def test_r01_validate_and_formal_workflow(self):
        self.assertEqual(self.action('validate').returncode,0); self.freeze()
        result=self.evaluate(); self.assertEqual(result.returncode,0,result.stderr); self.assertFalse(json.loads(result.stdout)['formal_pass'])
    def test_r02_incomplete_and_unconfirmed(self):
        self.m['samples'].pop(); self.write(self.manifest,self.m); self.assertNotEqual(self.action('validate').returncode,0)
    def test_r02_unconfirmed_gold(self):
        self.write(self.root/'a.json',{'reviewer':'A','confirmed':False,'facts':[]}); self.assertNotEqual(self.action('validate').returncode,0)
    def test_r03_hash_duplicate_and_missing(self):
        for mutation in ('hash','duplicate','missing'):
            m=copy.deepcopy(self.m)
            if mutation=='hash': m['samples'][0]['sha256']='bad'
            if mutation=='duplicate': m['samples'][1]['id']='d'
            if mutation=='missing': m['samples'][0]['path']='absent'
            self.write(self.manifest,m); self.assertNotEqual(self.action('validate').returncode,0,mutation)
    def test_r03_cross_split_identical(self):
        self.m['samples'][1]['path']='d.mp4'; self.m['samples'][1]['sha256']=self.m['samples'][0]['sha256']; self.write(self.manifest,self.m)
        self.assertNotEqual(self.action('validate').returncode,0)
    def test_r04_traversal(self):
        self.m['samples'][0]['path']='../outside'; self.write(self.manifest,self.m); self.assertNotEqual(self.action('validate').returncode,0)
    def test_r05_lock_immutable_and_tamper(self):
        self.freeze(); before=self.lock.read_bytes(); self.assertNotEqual(self.action('freeze','--lock',self.lock).returncode,0); self.assertEqual(before,self.lock.read_bytes())
        self.write(self.root/'a.json',{'reviewer':'B','confirmed':True,'facts':[{'id':'g','text':'changed','evidence':{'type':'audio','start':0,'end':1}}]}); self.assertNotEqual(self.evaluate().returncode,0)
    def test_r06_duplicate_does_not_raise_score(self):
        self.freeze(); p=copy.deepcopy(self.r['samples'][0]['predictions'][0]); p.update(id='p2',decision='duplicate',duplicate_of='p'); self.r['samples'][0]['predictions'].append(p); self.write(self.results,self.r)
        result=self.evaluate(); self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout)['predictions'],1)
    def test_r07_reject_invalid_results(self):
        self.freeze()
        for variant in ('missing','unknown','duplicate_id','evidence','unconfirmed','duplicate_cycle','duplicate_gold'):
            r=copy.deepcopy(self.r); p=r['samples'][0]['predictions'][0]
            if variant=='missing': r['samples']=[]
            if variant=='unknown': p['gold_id']='unknown'
            if variant=='duplicate_id': r['samples'][0]['predictions'].append(copy.deepcopy(p))
            if variant=='evidence': p['evidence']=None
            if variant=='unconfirmed': r['confirmed']=False
            if variant=='duplicate_cycle': p.update(decision='duplicate',duplicate_of='p')
            if variant=='duplicate_gold': p2=copy.deepcopy(p); p2['id']='p2'; r['samples'][0]['predictions'].append(p2)
            self.write(self.results,r); self.assertNotEqual(self.evaluate().returncode,0,variant)
    def test_r08_zero_predictions(self):
        self.freeze(); self.r['samples'][0]['predictions']=[]; self.write(self.results,self.r)
        result=self.evaluate(); self.assertEqual(result.returncode,0); self.assertFalse(json.loads(result.stdout)['formal_pass'])
    def test_r09_reviewed_not_formal(self):
        self.freeze(); self.r['version']='human_reviewed'; self.write(self.results,self.r); self.assertFalse(json.loads(self.evaluate().stdout)['formal_pass'])
    def test_r09_dev_not_formal(self):
        self.freeze(); self.r['split']='dev'; self.r['samples'][0]['id']='d'; self.write(self.results,self.r); self.assertFalse(json.loads(self.evaluate().stdout)['formal_pass'])
    def test_cli_utf8_output(self):
        result=self.cli('budget-check','--actual','0','--pending','0','--new','1')
        self.assertEqual(result.returncode,0)
        self.assertEqual(json.loads(result.stdout)['note'],'离线上界预检，不能阻断外部调用')
        error=self.cli('budget-check','--actual','NaN','--pending','0','--new','1')
        self.assertIn('金额',error.stderr)
    def test_r10_budget(self):
        for value,ok in [('100',True),('100.01',False),('-1',False),('NaN',False),('Infinity',False),('unknown',False)]:
            result=self.cli('budget-check','--actual','0','--pending','0','--new',value); self.assertEqual(result.returncode==0,ok,value)
    def test_r11_invalid_config_and_json(self):
        self.write(self.config,{'video_count':-1}); self.assertNotEqual(self.action('validate').returncode,0)
        self.config.write_text('{',encoding='utf8'); self.assertNotEqual(self.action('validate').returncode,0)
    def test_default_scale_dataset(self):
        self.config.write_text((PROJECT/'config/research.json').read_text(encoding='utf8'),encoding='utf8')
        samples=[]
        for i in range(60):
            video=i<50; ident=str(i); filename=ident+('.mp4' if video else '.html')
            data=('unique-'+ident).encode(); (self.root/filename).write_bytes(data)
            facts=[{'id':str(j),'text':'fact','evidence':{'type':'visual','start':0,'end':1}} for j in range(10 if video else 0)]
            self.write(self.root/(ident+'.json'),{'reviewer':'A','confirmed':True,'facts':facts})
            samples.append({'id':ident,'kind':'video' if video else 'html','split':('dev' if i<30 else 'acceptance') if video else 'html','path':filename,'sha256':hashlib.sha256(data).hexdigest(),'annotation':ident+'.json','duration_seconds':10 if video else None,'tags':[],'rights_confirmed':True})
        self.write(self.manifest,{'samples':samples})
        result=self.action('validate'); self.assertEqual(result.returncode,0,result.stderr)
        self.freeze()
        results=[]
        for i in range(30,50):
            predictions=[{'id':str(j),'text':'fact','decision':'correct','gold_id':str(j),'evidence':{'type':'visual','start':0,'end':1},'duplicate_of':None} for j in range(10)]
            results.append({'id':str(i),'predictions':predictions})
        self.write(self.results,{'split':'acceptance','version':'machine_initial','reviewer':'A','confirmed':True,'samples':results})
        result=self.evaluate(); self.assertEqual(result.returncode,0,result.stderr); self.assertTrue(json.loads(result.stdout)['formal_pass'])
        c=json.loads(self.config.read_text(encoding='utf8')); c['accuracy']='0.5'; c['coverage']='0.5'; self.write(self.config,c)
        self.lock.unlink(); self.freeze(); report=json.loads(self.evaluate().stdout); self.assertTrue(report['passed']); self.assertFalse(report['formal_eligible'])
        c['accuracy']='1'; c['coverage']='1'; self.write(self.config,c)
        self.lock.unlink(); self.freeze(); self.assertTrue(json.loads(self.evaluate().stdout)['formal_pass'])
    def test_budget_policy_cap(self):
        c=json.loads(self.config.read_text(encoding='utf8')); c['budget']='200'; self.write(self.config,c)
        self.assertNotEqual(self.cli('budget-check','--actual','0','--pending','0','--new','150').returncode,0)
        self.assertNotEqual(self.cli('budget-check','--actual','1e1000000000','--pending','1','--new','0').returncode,0)
    def test_invalid_config_structures(self):
        original=json.loads(self.config.read_text(encoding='utf8'))
        for value in (None, [], 'bad'):
            c=copy.deepcopy(original); c['extensions']=value; self.write(self.config,c)
            result=self.action('validate'); self.assertEqual(result.returncode,2); self.assertNotIn('Traceback',result.stderr)
    def test_bad_json_shapes(self):
        for value in (None, [], {'samples':[None]}, {'samples':['x']}):
            self.write(self.manifest,value); result=self.action('validate')
            self.assertEqual(result.returncode,2); self.assertNotIn('Traceback',result.stderr)
    def test_low_configuration_never_formal(self):
        c=json.loads(self.config.read_text(encoding='utf8')); c['accuracy']='0.5'; c['coverage']='0.5'; self.write(self.config,c)
        self.freeze(); result=self.evaluate(); report=json.loads(result.stdout)
        self.assertTrue(report['passed']); self.assertFalse(report['formal_eligible']); self.assertFalse(report['formal_pass'])
    def test_lock_captures_config(self):
        self.freeze()
        c=json.loads(self.config.read_text(encoding='utf8')); c['accuracy']='0.5'; self.write(self.config,c)
        self.assertNotEqual(self.evaluate().returncode,0)
    def test_invalid_metadata_and_gold_evidence(self):
        for change in ('rights','duration','extension','evidence'):
            m=copy.deepcopy(self.m)
            if change=='rights': m['samples'][0]['rights_confirmed']=False
            if change=='duration': m['samples'][0]['duration_seconds']=float('nan')
            if change=='extension': m['samples'][0]['path']='bad.exe'
            if change=='evidence': self.write(self.root/'d.json',{'reviewer':'A','confirmed':True,'facts':[{'id':'g','text':'f','evidence':{'type':'audio','start':0,'end':11}}]})
            self.write(self.manifest,m); self.assertNotEqual(self.action('validate').returncode,0,change)
    def test_same_split_duplicate_media(self):
        m=copy.deepcopy(self.m); other=copy.deepcopy(m['samples'][0]); other['id']='extra'; m['samples'].append(other); self.write(self.manifest,m)
        self.assertNotEqual(self.action('validate').returncode,0)
    def test_invalid_evidence_numeric(self):
        self.freeze()
        for value in (float('nan'),float('inf'),True,-1):
            r=copy.deepcopy(self.r); r['samples'][0]['predictions'][0]['evidence']['start']=value; self.write(self.results,r); self.assertNotEqual(self.evaluate().returncode,0,str(value))

if __name__=='__main__': unittest.main()

