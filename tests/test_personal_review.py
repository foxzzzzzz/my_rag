import hashlib, json, subprocess, sys, tempfile, unittest, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TMP=ROOT/'tmp'; TMP.mkdir(exist_ok=True)
class PersonalReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=TMP); self.dir=Path(self.tmp.name); self.source=self.dir/'source.mp4'; self.source.write_bytes(b'fake-test-only')
        item={'id':'one','source_path':'source.mp4','source_sha256':hashlib.sha256(self.source.read_bytes()).hexdigest(),'scheme_id':'scheme','scheme_version':'v1','run_id':'run','output_version':'1','output_kind':'machine_initial','status':'completed','provenance':'provider','transcript':'hello','visual':'scene','body':'output','summary':'summary','notes':'notes','duration_seconds':2,'cost_cny':None}
        self.bundle={'items':[item]}; self.bp=self.dir/'bundle.json'; self.write(self.bp,self.bundle); self.html=self.dir/'review.html'; self.feedback=self.dir/'feedback.json'
    def tearDown(self): self.tmp.cleanup()
    def write(self,p,obj): p.write_text(json.dumps(obj),encoding='utf8')
    def cli(self,*args): return subprocess.run([sys.executable,'-m','tools.personal_review',*map(str,args)],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
    def build(self): return self.cli('build','--bundle',self.bp,'--source-root',self.dir,'--output',self.html)
    def record(self,score=98,decision='approve'):
        from tools.personal_review import bundle_hash, item_binding
        return {'review_id':'r1','item_id':'one','binding':item_binding(self.bundle['items'][0],bundle_hash(self.bundle)),'overall_score':score,'decision':decision,'reviewer':'me','reviewed_at':'2026-11-03T12:00:00+08:00','tags':[],'note':''}
    def summary(self,records):
        self.write(self.feedback,{'reviews':records}); return self.cli('summarize','--bundle',self.bp,'--source-root',self.dir,'--feedback',self.feedback)
    def test_p01_build(self): self.assertEqual(self.build().returncode,0); self.assertIn('personal_review',self.html.read_text(encoding='utf8'))
    def test_p02_p03_score(self):
        for score,decision,expected in [(98,'approve',True),(97,'approve',False),(100,'reject',False)]:
            result=self.summary([self.record(score,decision)]); self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout)['all_review_ready'],expected)
        self.assertFalse(json.loads(self.summary([]).stdout)['all_review_ready'])
    def test_p04_invalid(self):
        for score in [-1,101,True,None,float('nan'),float('inf')]: self.assertNotEqual(self.summary([self.record(score)]).returncode,0)
        r=self.record(); r['reviewer']=''; self.assertNotEqual(self.summary([r]).returncode,0)
    def test_p05_binding(self):
        r=self.record(); self.bundle['items'][0]['body']='changed'; self.write(self.bp,self.bundle); self.assertNotEqual(self.summary([r]).returncode,0)
    def test_p06_unreviewed(self): self.assertFalse(json.loads(self.summary([]).stdout)['all_review_ready'])
    def test_p07_history(self):
        a=self.record(); b=self.record(100,'reject'); b['review_id']='r2'; b['reviewed_at']='2026-11-04T12:00:00+08:00'; self.assertFalse(json.loads(self.summary([a,b]).stdout)['all_review_ready'])
        b['review_id']='r1'; self.assertNotEqual(self.summary([a,b]).returncode,0)
        b['review_id']='r2'; b['reviewed_at']=a['reviewed_at']; self.assertNotEqual(self.summary([a,b]).returncode,0)
    def test_p08_escape(self):
        self.bundle['items'][0]['body']='</script><script>alert(1)</script>'; self.write(self.bp,self.bundle); self.assertEqual(self.build().returncode,0); self.assertNotIn('</script><script>alert(1)',self.html.read_text(encoding='utf8'))
    def test_p09_empty_placeholder(self):
        for patch in [{'provenance':'synthetic'},{'status':'pending'},{'transcript':'','visual':'','body':''}]:
            self.bundle['items'][0].update(patch); self.write(self.bp,self.bundle); self.assertNotEqual(self.build().returncode,0)
    def test_p06_multiple_items_and_independent_binding(self):
        import copy
        first=self.record(); second=copy.deepcopy(self.bundle['items'][0]); second.update(id='two',output_version='2')
        self.bundle['items'].append(second); self.write(self.bp,self.bundle)
        result=self.summary([first]); self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout); self.assertFalse(data['all_review_ready']); self.assertEqual(data['unreviewed'],['two']); self.assertTrue(data['items'][0]['review_ready'])
        from tools.personal_review import item_binding, bundle_hash
        other=dict(first,review_id='r2',item_id='two',binding=item_binding(second,bundle_hash(self.bundle)),overall_score=97)
        data=json.loads(self.summary([first,other]).stdout); self.assertFalse(data['all_review_ready']); self.assertEqual(data['low_score'],['two'])
    def test_p09_missing_sections(self):
        import copy
        original=copy.deepcopy(self.bundle)
        for field in ('summary','notes','transcript','visual'):
            self.bundle=copy.deepcopy(original); self.bundle['items'][0][field]=''; self.write(self.bp,self.bundle)
            self.assertNotEqual(self.build().returncode,0,field)
    def test_source_traversal(self):
        self.bundle['items'][0]['source_path']='../outside.mp4'; self.write(self.bp,self.bundle); self.assertNotEqual(self.build().returncode,0)
    def test_multiple_feedback_files_and_tags(self):
        a=self.record(); b=self.record(96,'rework'); b.update(review_id='r2',reviewed_at='2026-11-04T12:00:00+08:00',tags=['术语'],note='检查')
        f2=self.dir/'second.json'; self.write(self.feedback,{'reviews':[a]}); self.write(f2,{'reviews':[b]})
        result=self.cli('summarize','--bundle',self.bp,'--source-root',self.dir,'--feedback',self.feedback,'--feedback',f2)
        self.assertEqual(result.returncode,0,result.stderr); report=json.loads(result.stdout)
        self.assertEqual(report['items'][0]['scheme_id'],'scheme'); self.assertEqual(report['items'][0]['source_sha256'],self.bundle['items'][0]['source_sha256']); self.assertEqual(report['problem_tags'],{'术语':1}); self.assertEqual(report['items'][0]['note'],'检查'); self.assertEqual(report['rework'],['one'])
    def test_page_javascript_export(self):
        node=shutil.which('node')
        if not node: self.skipTest('Node unavailable')
        self.assertEqual(self.build().returncode,0)
        js=self.dir/'harness.js'
        js.write_text(r"""
const fs=require('fs'), vm=require('vm');
const html=fs.readFileSync(process.argv[2],'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
let fields={}, handler, exported=null, alerted=false;
global.document={getElementById(id){if(id==='export')return {addEventListener(_,f){handler=f}};return {value:fields[id]||''}},createElement(){return {click(){exported=global.savedBlob.parts[0]}}}};
global.crypto={randomUUID(){return 'actual-js-review'}};
global.Blob=class {constructor(parts){this.parts=parts}};
global.URL={createObjectURL(blob){global.savedBlob=blob;return 'blob:local'},revokeObjectURL(){}};
global.alert=()=>{alerted=true};
vm.runInThisContext(script);
fields={score0:'98',decision0:'approve',reviewer0:'本人',tags0:'术语',note0:'备注'};handler();
const valid=exported;if(!valid)throw Error('no export');
exported=null;fields={};handler();if(JSON.parse(exported).reviews.length!==0)throw Error('unreviewed exported');
exported=null;fields={score0:'101',decision0:'approve',reviewer0:'本人'};handler();if(exported||!alerted)throw Error('invalid exported');
process.stdout.write(valid);
""",encoding='utf8')
        result=subprocess.run([node,str(js),str(self.html)],capture_output=True,text=True,encoding='utf8')
        self.assertEqual(result.returncode,0,result.stderr)
        exported=json.loads(result.stdout); self.assertEqual(exported['reviews'][0]['overall_score'],98)
        report=self.summary(exported['reviews']); self.assertEqual(report.returncode,0,report.stderr); self.assertTrue(json.loads(report.stdout)['all_review_ready'])
    def test_review_layout(self):
        self.assertEqual(self.build().returncode,0)
        page=self.html.read_text(encoding='utf8')
        self.assertIn('href="#item-0"',page); self.assertIn('<h2>source.mp4</h2>',page)
        self.assertIn('<h3>摘要</h3><pre>summary</pre>',page)
        self.assertIn('<details><summary>转录</summary><pre>hello</pre></details>',page)
        self.assertIn('<details><summary>视觉</summary>',page)
        self.assertIn('<details><summary>正文</summary>',page)
        self.assertLess(page.index('id="score0"'),page.index('<details><summary>转录'))
    def test_p05_source_modified(self):
        self.source.write_bytes(b'changed'); self.assertNotEqual(self.build().returncode,0)
if __name__=='__main__': unittest.main()
