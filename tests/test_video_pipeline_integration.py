import hashlib, json, sqlite3, tempfile, time, unittest
from pathlib import Path
from personalkb.asr_storage import PreparedAudio
from personalkb.workflow import make_store
from personalkb.workflow_store import WorkflowError
from personalkb.video_pipeline import load_pipeline_config, run_video, cleanup_video, video_status

class FakeStorage:
    def prepare(self,path,model):
        data=Path(path).read_bytes()
        return PreparedAudio('temporary',model,'asset1',hashlib.sha256(data).hexdigest(),len(data),time.time()+3600,'https://secret.example/private?token=secret')

class FakeServices:
    def __init__(self): self.submit_count=0; self.query_count=0; self.vision_count=0; self.mode=''; self.cancel=None
    def submit_asr(self,asset):
        self.submit_count+=1
        if self.cancel: self.cancel()
        if self.mode=='submit': raise TimeoutError()
        return 'remote-1'
    def query_asr(self,ident):
        self.query_count+=1
        if self.mode=='query': self.mode=''; raise TimeoutError()
        if self.mode=='subtask_failed': return {'task_status':'SUCCEEDED','results':[{'subtask_status':'FAILED'}]}
        return {'task_status':'SUCCEEDED','results':[{'subtask_status':'SUCCEEDED','transcription_url':'https://unused'}]}
    def download_asr(self,url,seconds): return {'text':'spoken', 'segments':[{'text':'spoken','start':0,'end':1}]}
    def vision(self,path):
        self.vision_count+=1
        if self.mode=='vision': raise TimeoutError()
        return {'content':'visual','model':'fake','estimated_cost_cny':0}
    def summarize(self,body,title): return {'structured':{'summary':'summary','notes':'notes'},'content':'notes','model':'fake','estimated_cost_cny':0}

def media(source,work,wc,pc,*,heartbeat):
    heartbeat(); audio=work/'audio.wav'; audio.write_bytes(b'audio'); frame=work/'frame.jpg'; frame.write_bytes(b'jpeg')
    return {'audio_path':str(audio),'audio_seconds':1,'duration_seconds':1,'frames':[{'index':0,'seconds':0,'path':str(frame),'sha256':hashlib.sha256(b'jpeg').hexdigest()}]}

class PipelineIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='tmp'); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name).resolve()
        self.wc=json.loads(Path('config/workflow.json').read_text(encoding='utf-8')); self.wc['data_dir']=str(self.root/'data')
        self.pc=load_pipeline_config(); self.pc['budget']['ledger']=str(self.root/'budget.sqlite'); self.s=FakeServices(); self.storage=FakeStorage()
        store=make_store(self.wc); root=Path(self.wc['data_dir']); (root/'source.mp4').write_bytes(b'video')
        self.task=store.import_source('video',hashlib.sha256(b'video').hexdigest(),'source.mp4','source.mp4')['task']['id']
    def run_pipeline(self,resume=False): return run_video(self.wc,self.pc,{},task_id=self.task,resume=resume,services=self.s,storage=self.storage,media=media)
    def status(self): return make_store(self.wc).get_task(self.task)['status']
    def test_success_and_private_url(self):
        version=self.run_pipeline(); self.assertEqual(version['output_kind'],'machine_initial'); self.assertEqual(self.status(),'succeeded')
        status=video_status(self.wc,self.pc,self.task); self.assertEqual(status['assets'][0]['status'],'provider_managed')
        self.assertNotIn('secret',json.dumps(status)); self.assertNotIn(b'secret', (Path(self.wc['data_dir'])/'workflow.sqlite3').read_bytes())
    def test_query_resume_only_get(self):
        self.s.mode='query'
        strategy = self.pc['strategy']
        legacy = strategy['legacy_text_prompt']['value']
        self.pc['strategy'] = {key: value for key, value in strategy.items() if key != 'legacy_text_prompt'}
        self.pc['strategy']['text_system_prompt'] = legacy
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.pc['strategy'] = strategy
        self.assertEqual(self.status(),'needs_attention'); self.run_pipeline(True); self.assertEqual(self.s.submit_count,1); self.assertEqual(self.s.query_count,2)
        c=sqlite3.connect(self.pc['budget']['ledger']); self.addCleanup(c.close); self.assertEqual(c.execute("SELECT count(*) FROM reservations WHERE request_id=?",(self.task+':asr_submit',)).fetchone()[0],1)
    def test_failed_subtask_cleanup(self):
        self.s.mode='subtask_failed'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.assertEqual(self.status(),'needs_attention')
        self.assertEqual(video_status(self.wc,self.pc,self.task)['assets'][0]['status'],'remote_terminal')
        result=cleanup_video(self.wc,self.pc,{},self.task,storage=self.storage)
        self.assertEqual(result['assets'][0]['status'],'provider_managed')
        with self.assertRaises(WorkflowError): self.run_pipeline(True)
        self.assertEqual(self.s.submit_count,1)
    def test_unknown_submit_never_repeats(self):
        self.s.mode='submit'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        with self.assertRaises(WorkflowError): self.run_pipeline(True)
        self.assertEqual(self.s.submit_count,1)
    def test_unknown_vision_never_repeats(self):
        self.s.mode='vision'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        with self.assertRaises(WorkflowError): self.run_pipeline(True)
        self.assertEqual(self.s.vision_count,1)
    def test_budget_prevents_post(self):
        self.pc['budget']['run_limit']='0.00000001'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.assertEqual(self.s.submit_count,0)
    def test_incomplete_managed_storage_before_claim_or_reservation(self):
        self.pc['storage']['backend']='managed_oss'
        with self.assertRaises(WorkflowError):
            run_video(self.wc,self.pc,{},task_id=self.task,services=self.s,media=media)
        self.assertEqual(self.status(),'queued')
        self.assertFalse(Path(self.pc['budget']['ledger']).exists())
        self.assertEqual(self.s.submit_count,0)
    def test_cancel_prevents_publish(self):
        self.s.cancel=lambda: make_store(self.wc).cancel(self.task)
        with self.assertRaises(WorkflowError): self.run_pipeline()
        self.assertEqual(self.status(),'cancelled'); self.assertEqual(make_store(self.wc).list_versions(make_store(self.wc).get_task(self.task)['source_id']),[])
    def test_attention_cleanup_preserves_wav(self):
        self.s.mode='vision'
        with self.assertRaises(WorkflowError): self.run_pipeline()
        audio=Path(self.wc['data_dir'])/'video-work'/self.task/'audio.wav'; self.assertTrue(audio.exists())
        cleanup_video(self.wc,self.pc,{},self.task,storage=self.storage); self.assertTrue(audio.exists())
