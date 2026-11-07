import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tmp'/'benchmark-deps'))
from personalkb.workflow_store import WorkflowStore, WorkflowError
from personalkb.rag_index import RagIndex, load_rag_config

class Fake:
    def embed(self,texts,**kwargs): return {'vectors':[[1.,0.] for _ in texts], 'model':'text-embedding-v4', 'usage':{}}

@pytest.fixture
def setup(tmp_path):
    s=WorkflowStore(tmp_path/'db',content_root=tmp_path/'knowledge',data_root=tmp_path)
    x=s.import_source('html','a'*64,'a.html','a'); task=s.claim_specific(x['task']['id'],'test')
    result=dict(title='标题',body='正文',summary='摘要',notes='笔记',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'text':'独特证据 原始文本'}])
    v=s.finish(task['id'],task['lease_token'],result); s.review(x['source']['id'],v['id'],v['content_sha256'],99,'approve','synthetic')
    cfg=load_rag_config(); cfg['embedding']['dimensions']=2
    return s,RagIndex(s,cfg,Fake()),x['source']['id'],v

def test_build_and_query(setup):
    s,index,sid,v=setup
    assert index.build(allow_paid=True)['chunks']==1
    result=index.query('独特证据',mode='hybrid',allow_paid=True)
    assert result[0]['text']=='独特证据 原始文本'
    assert index.citation(result[0]['chunk_id'])['source_id']==sid
    assert not index.query('独特证据',mode='lexical',filters={'sources':['other']})

def test_revoke_removes_all_index_tables(setup):
    s,index,sid,v=setup; index.build(allow_paid=True); hit=index.query('独特',mode='lexical')[0]
    s.review(sid,v['id'],v['content_sha256'],80,'rework','synthetic')
    assert index.query('独特',mode='lexical')==[]
    with pytest.raises(WorkflowError): index.citation(hit['chunk_id'])
    db=index._db(index._active())
    try:
        assert all(db.execute('select count(*) from '+t).fetchone()[0]==0 for t in ('chunks','fts','vec'))
    finally: db.close()

def test_bad_vector_preserves_active(setup):
    s,index,sid,v=setup; index.build(allow_paid=True)
    class Bad:
        def embed(self,texts,**kwargs): return {'vectors':[[True,0.] for _ in texts]}
    index.provider=Bad()
    with pytest.raises(WorkflowError): index.build(allow_paid=True)
    assert index.query('独特',mode='lexical')


def test_space_and_forged_citation(setup):
    s,index,sid,v=setup; index.build(allow_paid=True)
    hit=index.query('evidence',mode='hybrid',allow_paid=True)[0]
    forged={**hit,'text':'forged'}
    with pytest.raises(WorkflowError): index.validate_citations([forged])
    cfg=load_rag_config(); cfg['embedding']['dimensions']=2; cfg['embedding']['revision']='another'
    assert RagIndex(s,cfg,Fake()).status()['needs_rebuild']

def test_build_race_rejected(setup):
    s,index,sid,v=setup; index.build(allow_paid=True)
    class Revoke:
        def embed(self,texts,**kwargs):
            s.review(sid,v['id'],v['content_sha256'],80,'rework','synthetic')
            return {'vectors':[[1.,0.] for _ in texts]}
    index.provider=Revoke()
    with pytest.raises(WorkflowError): index.build(allow_paid=True)
    assert index.query('anything',mode='lexical')==[]

def test_1024_dimensions(setup):
    s,index,sid,v=setup
    cfg=load_rag_config()
    class Big:
        def embed(self,texts,**kwargs): return {'vectors':[[1.]+[0.]*1023 for _ in texts], 'model':'text-embedding-v4'}
    index=RagIndex(s,cfg,Big()); assert index.build(allow_paid=True)['chunks']==1
    assert index.query('anything',mode='hybrid',allow_paid=True)

def test_filtered_vector_retrieval_before_top_k(setup):
    s,index,sid,v=setup
    for i in range(12):
        x=s.import_source('html',format(i+1,'064x'),f'{i}.html',f'{i}.html')
        t=s.claim_specific(x['task']['id'],'test')
        r=dict(title='other',body='other',summary='s',notes='n',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'type':'html','text':'other evidence'}])
        version=s.finish(t['id'],t['lease_token'],r); s.review(x['source']['id'],version['id'],version['content_sha256'],99,'approve','synthetic')
    index.build(allow_paid=True)
    assert [x['source_id'] for x in index.query('query',mode='hybrid',filters={'sources':[sid]},allow_paid=True)]==[sid]

def test_headings_offsets_and_video_points(setup):
    s,index,sid,v=setup
    snap={'version_id':'v','content_sha256':'a'*64,'review_seq':1,'metadata':{},'result':{'evidence':[
        {'type':'html','text':'# First\nhello\n# Second\nworld'},
        {'type':'audio','text':'no time'},
        {'type':'visual','text':'point','seconds':4,'image_sha256':'b'*64}]}}
    chunks=index._chunks(sid,snap)
    assert len(chunks)==3 and chunks[0]['text']=='# First\nhello\n'
    assert chunks[1]['locator']['offset']==len(chunks[0]['text'])
    assert chunks[2]['locator']['seconds']==4

def test_tampered_index_payload_is_rejected(setup):
    import json
    s,index,sid,v=setup; index.build(allow_paid=True)
    db=index._db(index._active())
    try:
        row=db.execute('select id,payload from chunks').fetchone(); payload=json.loads(row['payload']); payload['text']='forged'
        db.execute('update chunks set payload=? where id=?',(json.dumps(payload),row['id'])); db.commit()
    finally: db.close()
    assert index.query('forged',mode='lexical')==[]

def test_config_rejects_bad_values(tmp_path):
    import json
    c=load_rag_config(); c['embedding']['dimensions']=True
    path=tmp_path/'config.json'; path.write_text(json.dumps(c),encoding='utf8')
    with pytest.raises(WorkflowError): load_rag_config(path)

def test_generation_symlink_rejected(setup,tmp_path):
    import json
    s,index,sid,v=setup; index.build(allow_paid=True)
    path=index._active(); outside=tmp_path/'outside.sqlite'; path.rename(outside)
    try: path.symlink_to(outside)
    except OSError: pytest.skip('symlink unavailable')
    with pytest.raises(WorkflowError): index.status()
    with pytest.raises(WorkflowError): index.query('query',mode='lexical')

def test_wrong_embedding_model_never_publishes_or_searches(setup):
    s,index,sid,v=setup; index.build(allow_paid=True)
    old=index._active()
    class Wrong:
        def embed(self,texts,**kwargs): return {'model':'different-model','vectors':[[1.,0.] for _ in texts]}
    index.provider=Wrong()
    with pytest.raises(WorkflowError, match='embedding_model_mismatch'): index.build(allow_paid=True)
    assert index._active()==old
    with pytest.raises(WorkflowError, match='embedding_model_mismatch'): index.query('query',mode='hybrid',allow_paid=True)
    assert index.query('evidence',mode='hybrid',filters={'sources':['no-such-source']},allow_paid=True)==[]

def test_classification_change_refreshes_without_embedding(setup):
    from personalkb.classification import ClassificationStore
    s,index,sid,v=setup; index.build(allow_paid=True)
    original=index.query('anything',mode='hybrid',allow_paid=True)[0]
    class NoEmbedding:
        def embed(self,*args,**kwargs): raise AssertionError('unexpected embedding')
    index.provider=NoEmbedding()
    classifications=ClassificationStore(s); label=classifications.create_label('topic','New topic')
    classifications.update(sid,0,[label['id']],[])
    with pytest.raises(WorkflowError): index.validate_citations([original])
    current=index.query('anything',mode='lexical',filters={'topics':[label['id']]})
    # Lexical query has no matching word: use an actual original evidence token.
    current=index.query(original['text'],mode='lexical',filters={'topics':[label['id']]})
    assert len(current)==1 and current[0]['chunk_id']==original['chunk_id']
    assert current[0]['metadata']['topics'][0]['id']==label['id']
    assert index.validate_citations(current)
    assert index.citation(original['chunk_id'])['metadata']==current[0]['metadata']
    db=index._db(index._active())
    try: assert all(db.execute('select count(*) from '+t).fetchone()[0]==1 for t in ('chunks','fts','vec'))
    finally: db.close()

def test_disabled_blocks_all_knowledge_and_calls(setup):
    s,index,sid,v=setup; index.build(allow_paid=True)
    hit=index.query('anything',mode='hybrid',allow_paid=True)[0]
    class NoCalls:
        def embed(self,*args,**kwargs): raise AssertionError('unexpected embedding')
    index.provider=NoCalls(); index.config['enabled']=False
    assert index.status()['enabled'] is False
    for call in (lambda:index.build(allow_paid=True),lambda:index.query('anything',allow_paid=True),lambda:index.citation(hit['chunk_id']),lambda:index.validate_citations([hit])):
        with pytest.raises(WorkflowError, match='rag_disabled'): call()

def test_second_batch_wrong_model_keeps_active(setup):
    s,index,sid,v=setup; index.build(allow_paid=True); original=index._active()
    index.config['limits']['embedding_batch_size']=1
    s2=s.import_source('html','c'*64,'c.html','c'); task=s.claim_specific(s2['task']['id'],'test')
    result=dict(title='t',body='body',summary='s',notes='n',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'type':'html','text':'second evidence'}])
    version=s.finish(task['id'],task['lease_token'],result); s.review(s2['source']['id'],version['id'],version['content_sha256'],99,'approve','synthetic')
    class Mixed:
        calls=0
        def embed(self,texts,**kwargs):
            self.calls+=1
            return {'model':'text-embedding-v4' if self.calls==1 else 'other','vectors':[[1.,0.] for _ in texts]}
    index.provider=Mixed()
    with pytest.raises(WorkflowError, match='embedding_model_mismatch'): index.build(allow_paid=True)
    assert index._active()==original and index.provider.calls==2

def test_human_revision_evidence_has_no_inherited_video_time(setup):
    s,index,sid,old=setup
    result=dict(old['result']); result.update(output_kind='human_edited',provenance='human_edited')
    result['evidence']=[{'type':'human_body','locator':'human-edit:body','text':'corrected body'},
                        {'type':'human_transcript','locator':'human-edit:transcript','text':'corrected transcript','start_seconds':12,'end_seconds':15},
                        {'type':'human_visual','locator':'human-edit:visual','text':'corrected visual','seconds':17,'image_sha256':'a'*64}]
    revised=s.revise(sid,old['id'],result); s.review(sid,revised['id'],revised['content_sha256'],99,'approve','synthetic')
    assert index.build(allow_paid=True)['chunks']==3
    hits=index.query('corrected',mode='lexical')
    assert {x['locator']['type'] for x in hits}=={'human_body','human_transcript','human_visual'}
    for item in hits:
        loc=item['locator']; assert item['version_id']==revised['id'] and loc['origin']=='human_edit'
        assert loc['has_time'] is False and loc['temporal_status']=='unavailable'
        assert not set(loc).intersection({'start','end','start_seconds','end_seconds','seconds','image_sha256'})
        assert index.citation(item['chunk_id'])['text']==item['text']
    assert s.get_version(old['id'])['result']==old['result']
    status=index.status()
    assert (status['eligible_sources'],status['indexed_sources'],status['indexed_chunks'])==(1,1,3)
