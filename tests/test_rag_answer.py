import json, sqlite3
from contextlib import contextmanager
from pathlib import Path
import pytest
from personalkb.rag_answer import AnswerService
from personalkb.workflow_store import WorkflowError
A='a'*64
B='b'*64
X='c'*64
ROOT=Path(__file__).resolve().parent.parent
class Store:
    def __init__(self,path): self.db_path=path
class Index:
    def __init__(self):
        self.valid=True; self.items=[{'chunk_id':A,'source_id':'s','version_id':'v','content_sha256':'h','space_id':'p','text':'fact','locator':{}},{'chunk_id':B,'source_id':'s2','version_id':'v2','content_sha256':'h2','space_id':'p','text':'fact2','locator':{}}]
    def query(self,*args,**kwargs): return self.items
    def validate_citations(self,contexts,filters=None):
        if not self.valid: raise WorkflowError('rag_invalidated')
class Provider:
    def __init__(self,index,answer=None,invalidate=False): self.index=index; self.calls=0; self.invalidate=invalidate; self.result=answer or {'answer':'事实['+A+']','citation_ids':[A],'insufficient_evidence':False}
    def answer(self,*args,**kwargs):
        self.calls+=1
        if self.invalidate: self.index.valid=False
        return {'content':json.dumps(self.result)}
@pytest.fixture
def setup(tmp_path):
    cfg=json.loads((ROOT/'config/rag.json').read_text(encoding='utf-8')); store=Store(tmp_path/'db'); index=Index(); p=Provider(index)
    return AnswerService(store,index,cfg,p),index,p

def test_answer_and_stream(setup):
    svc,index,p=setup
    assert svc.ask('why')['citations'][0]['chunk_id']==A
    events=list(svc.stream('why')); assert [e['type'] for e in events]==['progress','answer','done']

def test_coverage_rejects_narrowing_and_allows_explicit_covered_subset(setup):
    svc, index, provider = setup
    def status(filters):
        scoped = filters.get('sources') or ['s', 's2']
        return {'eligible_source_ids': scoped, 'indexed_source_ids': ['s']}
    index.status = status
    with pytest.raises(WorkflowError, match='rag_coverage_changed'):
        svc.ask('why', filters={}, expected_source_ids=['s', 's2'], allow_paid=True)
    with pytest.raises(WorkflowError, match='rag_coverage_changed'):
        svc.ask('why', filters={'sources': ['s']}, expected_source_ids=['s', 's2'], allow_paid=True)
    assert provider.calls == 0
    assert svc.ask('why', filters={'sources': ['s']}, expected_source_ids=['s'], allow_paid=True)['citations']

def test_empty_and_invalid_citations(setup):
    svc,index,p=setup; index.items=[]
    assert svc.ask('why')['insufficient_evidence'] and p.calls==0
    index.items=[{'chunk_id':A}]; p.result={'answer':'事实['+X+']','citation_ids':[X],'insufficient_evidence':False}
    with pytest.raises(WorkflowError,match='invalid_model_response'): svc.ask('why')

def test_invalidation_all_contexts_and_stream(setup):
    svc,index,p=setup; p.invalidate=True
    events=list(svc.stream('why'))
    assert [e['type'] for e in events]==['progress','invalidated']
    assert '事实' not in json.dumps(events,ensure_ascii=False)

def test_error_not_invalidation(setup):
    svc,index,p=setup
    def fail(*args,**kwargs): raise WorkflowError('budget_invalid_or_exceeded')
    p.answer=fail
    assert list(svc.stream('why'))[-1]=={'type':'error','code':'budget_invalid_or_exceeded'}

def test_real_index_answer_and_revocation(tmp_path):
    import sys
    sys.path.insert(0,str(ROOT/'tmp'/'benchmark-deps'))
    from personalkb.workflow_store import WorkflowStore
    from personalkb.rag_index import RagIndex, load_rag_config
    store=WorkflowStore(tmp_path/'workflow',content_root=tmp_path/'knowledge',data_root=tmp_path)
    item=store.import_source('html','a'*64,'a.html','a'); task=store.claim_specific(item['task']['id'],'test')
    result=dict(title='标题',body='正文',summary='摘要',notes='笔记',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'text':'独特证据 原始文本'}])
    version=store.finish(task['id'],task['lease_token'],result)
    store.review(item['source']['id'],version['id'],version['content_sha256'],99,'approve','synthetic')
    cfg=load_rag_config(); cfg['embedding']['dimensions']=2
    class Embedding:
        def embed(self,texts,**kwargs): return {'vectors':[[1.,0.] for _ in texts], 'model':'text-embedding-v4'}
    index=RagIndex(store,cfg,Embedding()); index.build(allow_paid=True)
    class Answer:
        def answer(self,messages,**kwargs):
            evidence=json.loads(messages[1]['content'])['evidence']; chunk=evidence[0]['chunk_id']
            return {'content':json.dumps({'answer':'事实['+chunk+']','citation_ids':[chunk],'insufficient_evidence':False})}
    service=AnswerService(store,index,cfg,Answer())
    assert service.ask('独特证据',mode='lexical')['citations']
    store.review(item['source']['id'],version['id'],version['content_sha256'],80,'rework','synthetic')
    assert service.ask('独特证据',mode='lexical')['insufficient_evidence']

def test_before_model_gate_and_unreferenced_revocation(setup):
    svc,index,p=setup
    original=index.validate_citations
    count=0
    def gate(contexts,filters=None):
        nonlocal count
        count+=1
        assert {x['chunk_id'] for x in contexts} == {A,B}
        if count==2: index.valid=False
        original(contexts,filters=filters)
    index.validate_citations=gate
    with pytest.raises(WorkflowError,match='rag_invalidated'): svc.ask('why')
    assert p.calls==0
    index.valid=True; count=0; p.invalidate=True
    index.validate_citations=original
    with pytest.raises(WorkflowError,match='rag_invalidated'): svc.ask('why')
    assert list(svc.stream('why'))[-1]['type']=='invalidated'

def test_final_revalidation_after_answer_yield(setup):
    svc,index,p=setup
    events=svc.stream('why')
    assert next(events)['type']=='progress'
    assert next(events)['type']=='answer'
    index.valid=False
    assert next(events)=={'type':'invalidated'}
    with pytest.raises(StopIteration): next(events)

def test_reference_mismatch_and_request_id_validation(setup):
    svc,index,p=setup
    for result in ({'answer':'事实['+A+']','citation_ids':[B],'insufficient_evidence':False}, {'answer':'事实['+X+']','citation_ids':[X],'insufficient_evidence':False}):
        p.result=result
        with pytest.raises(WorkflowError,match='invalid_model_response'): svc.ask('why')
    for value in ([],{},'', 'x'*129, 5):
        with pytest.raises(WorkflowError,match='invalid_request_id'): svc.ask('why',request_id=value)

def test_provider_return_file_corruption(tmp_path):
    import sys
    sys.path.insert(0,str(ROOT/'tmp'/'benchmark-deps'))
    from personalkb.workflow_store import WorkflowStore
    from personalkb.rag_index import RagIndex, load_rag_config
    store=WorkflowStore(tmp_path/'workflow',content_root=tmp_path/'knowledge',data_root=tmp_path)
    item=store.import_source('html','b'*64,'b.html','b'); task=store.claim_specific(item['task']['id'],'test')
    result=dict(title='标题',body='正文',summary='摘要',notes='笔记',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'text':'独特证据 原始文本'}])
    version=store.finish(task['id'],task['lease_token'],result)
    store.review(item['source']['id'],version['id'],version['content_sha256'],99,'approve','synthetic')
    cfg=load_rag_config(); cfg['embedding']['dimensions']=2
    class Embedding:
        def embed(self,texts,**kwargs): return {'vectors':[[1.,0.] for _ in texts], 'model':'text-embedding-v4'}
    index=RagIndex(store,cfg,Embedding()); index.build(allow_paid=True)
    class Corrupt:
        def answer(self,messages,**kwargs):
            evidence=json.loads(messages[1]['content'])['evidence']; chunk=evidence[0]['chunk_id']
            # Delete a persisted version file while the model is generating.
            files=[p for p in (tmp_path/'knowledge').rglob('*') if p.is_file()]
            assert files
            for path in files: path.write_bytes(b'corrupted')
            return {'content':json.dumps({'answer':'事实['+chunk+']','citation_ids':[chunk],'insufficient_evidence':False})}
    events=list(AnswerService(store,index,cfg,Corrupt()).stream('独特证据',mode='lexical'))
    assert [e['type'] for e in events]==['progress','invalidated']


def test_disabled_no_calls(setup):
    svc,index,p=setup; svc.config['enabled']=False
    with pytest.raises(WorkflowError,match='rag_disabled'): svc.ask('why')
    assert list(svc.stream('why'))[-1]=={'type':'error','code':'rag_disabled'}
    assert p.calls==0


def test_literal_brackets_are_preserved_with_valid_citation(setup):
    svc,index,p=setup
    answer='Config [sandbox] and [tool_calls], access items[0]. Fact ['+A+']'
    p.result={'answer':answer,'citation_ids':[A],'insufficient_evidence':False}
    assert svc.ask('why')['answer']==answer

def test_unknown_hex_and_reference_set_mismatch_rejected(setup):
    svc,index,p=setup
    for answer, ids in [('Fact ['+X+']', [X]), ('Fact ['+A+']', [B]), ('Fact ['+A+']['+B+']', [A])]:
        p.result={'answer':answer,'citation_ids':ids,'insufficient_evidence':False}
        with pytest.raises(WorkflowError,match='invalid_model_response'): svc.ask('why')


def test_insufficient_discards_model_answer_and_citations(setup):
    svc,index,p=setup
    for ids in ([A], [X]):
        p.result={'answer':'secret ['+ids[0]+']','citation_ids':ids,'insufficient_evidence':True}
        result=svc.ask('why')
        assert result['answer']==svc.config['refusal_text']
        assert result['citations']==[] and result['insufficient_evidence']
        assert 'secret' not in result['answer']
