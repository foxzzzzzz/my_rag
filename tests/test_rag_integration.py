import json, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tmp'/'benchmark-deps'))
from personalkb.workflow_store import WorkflowStore
from personalkb.web_service import WebService
from personalkb.rag_index import RagIndex, load_rag_config
from personalkb.rag_answer import AnswerService
from personalkb.classification import ClassificationStore

class Fake:
    def embed(self,texts,**kw): return {'vectors':[[1.,0.] for _ in texts], 'model':'text-embedding-v4'}
    def answer(self,messages,**kw):
        items=json.loads(messages[1]['content'])['evidence']; cid=items[0]['chunk_id']
        if hasattr(self,'revoke'): self.revoke(items)
        return {'content':json.dumps({'answer':'合成事实['+cid+']','citation_ids':[cid],'insufficient_evidence':False})}

def test_revision_scope_and_answer(tmp_path):
    s=WorkflowStore(tmp_path/'db',content_root=tmp_path/'knowledge',data_root=tmp_path)
    x=s.import_source('html','a'*64,'synthetic.html','a'); sid=x['source']['id']; t=s.claim_specific(x['task']['id'],'test')
    result=dict(title='合成标题',body='旧错误词',summary='摘要',notes='笔记',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'type':'html','text':'旧错误词'}])
    v=s.finish(t['id'],t['lease_token'],result); s.review(sid,v['id'],v['content_sha256'],99,'approve','synthetic')
    cfg=load_rag_config(); cfg['embedding']['dimensions']=2; p=Fake(); index=RagIndex(s,cfg,p); index.build(allow_paid=True)
    assert AnswerService(s,index,cfg,p).ask('旧错误词',mode='lexical')['citations']
    web=WebService.__new__(WebService); web.store=s
    revised=web.revise(sid,{'expected_version_id':v['id'],'body':'新修正词'})
    assert not index.query('旧错误词',mode='lexical')
    s.review(sid,revised['id'],revised['content_sha256'],99,'approve','synthetic'); index.build(allow_paid=True)
    hit=index.query('新修正词',mode='lexical')[0]; assert hit['locator']['type']=='human_body'
    assert not index.query('旧错误词',mode='lexical'); assert s.get_version(v['id'])['result']==result
    c=ClassificationStore(s); label=c.create_label('topic','合成主题'); c.update(sid,0,[label['id']],[])
    p.embed=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('unexpected embed'))
    assert index.query('新修正词',mode='lexical',filters={'topics':[label['id']]})

def test_video_revision_uses_human_character_locators(tmp_path):
    s=WorkflowStore(tmp_path/'db',content_root=tmp_path/'knowledge',data_root=tmp_path)
    x=s.import_source('video','b'*64,'synthetic.mp4','b'); sid=x['source']['id']; t=s.claim_specific(x['task']['id'],'test')
    result=dict(title='合成视频',body='synthetic body',transcript='旧转录',visual='旧视觉',summary='摘要',notes='笔记',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'type':'audio','text':'旧转录','start_seconds':1,'end_seconds':2},{'type':'visual','text':'旧视觉','seconds':3,'image_sha256':'c'*64}])
    old=s.finish(t['id'],t['lease_token'],result); s.review(sid,old['id'],old['content_sha256'],99,'approve','synthetic')
    web=WebService.__new__(WebService); web.store=s
    new=web.revise(sid,{'expected_version_id':old['id'],'transcript':'合成修正转录','visual':'合成修正视觉'})
    s.review(sid,new['id'],new['content_sha256'],99,'approve','synthetic')
    cfg=load_rag_config(); cfg['embedding']['dimensions']=2; index=RagIndex(s,cfg,Fake()); index.build(allow_paid=True)
    hits=index.query('合成修正',mode='lexical'); assert {h['locator']['type'] for h in hits}=={'human_transcript','human_visual'}
    for h in hits:
        loc=h['locator']; assert loc['has_time'] is False and loc['temporal_status']=='unavailable'
        assert not set(loc)&{'start','end','seconds','start_seconds','end_seconds','image_sha256'}
        assert index.citation(h['chunk_id'])['text']==h['text']
    assert s.get_version(old['id'])['result']==result

def test_unreferenced_context_revoked_during_generation(tmp_path):
    s=WorkflowStore(tmp_path/'db',content_root=tmp_path/'knowledge',data_root=tmp_path)
    for i in range(2):
        x=s.import_source('html',str(i+1)*64,f'{i}.html',str(i)); t=s.claim_specific(x['task']['id'],'test')
        r=dict(title='合成',body='共同证据',summary='摘要',notes='笔记',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'type':'html','text':f'共同证据 合成来源{i}'}])
        v=s.finish(t['id'],t['lease_token'],r); s.review(x['source']['id'],v['id'],v['content_sha256'],99,'approve','synthetic')
    cfg=load_rag_config(); cfg['embedding']['dimensions']=2; p=Fake(); index=RagIndex(s,cfg,p); index.build(allow_paid=True)
    def revoke(items):
        assert len(items)>=2
        victim=items[-1]; version=s.get_version(victim['version_id']); s.review(victim['source_id'],version['id'],version['content_sha256'],80,'reject','synthetic')
    p.revoke=revoke
    events=list(AnswerService(s,index,cfg,p).stream('共同证据',mode='lexical'))
    assert [e['type'] for e in events]==['progress','invalidated']; assert '合成事实' not in json.dumps(events,ensure_ascii=False)

