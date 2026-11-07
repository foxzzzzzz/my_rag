import json, sqlite3
from contextlib import contextmanager
from pathlib import Path
import pytest
from personalkb.rag_provider import RagProvider
from personalkb.workflow_store import WorkflowError

ROOT=Path(__file__).resolve().parent.parent
class Store:
    def __init__(self,path): self.db_path=path
    @contextmanager
    def _tx(self):
        with sqlite3.connect(self.db_path) as db: yield db
class Transport:
    def __init__(self, response): self.response=response; self.calls=0
    def request(self,*args,**kwargs):
        self.calls+=1
        if isinstance(self.response,Exception): raise self.response
        return 200,self.response
@pytest.fixture
def setup(tmp_path):
    cfg=json.loads((ROOT/'config/rag.json').read_text(encoding='utf-8'))
    cfg['budget']['ledger']=str(tmp_path/'ledger.db')
    store=Store(tmp_path/'workflow.db')
    return store,cfg

def response(usage=None, index=0):
    return {'model':'text-embedding-v4','data':[{'index':index,'embedding':[1.0]*1024}], 'usage':usage or {}}

def test_success_cache_conflict_and_settlement(setup):
    store,cfg=setup; t=Transport(response({'prompt_tokens':10}))
    p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    assert len(p.embed(['a'],allow_paid=True,request_id='x')['vectors'][0])==1024
    assert p.embed(['a'],allow_paid=True,request_id='x')['usage']['prompt_tokens']==10
    assert t.calls==1
    with pytest.raises(WorkflowError,match='request_conflict'): p.embed(['b'],allow_paid=True,request_id='x')
    with sqlite3.connect(cfg['budget']['ledger']) as db: assert float(db.execute('select amount from reservations').fetchone()[0]) < 0.1

def test_consent_and_unknown_replay(setup):
    store,cfg=setup; t=Transport(RuntimeError('secret'))
    p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    with pytest.raises(WorkflowError,match='paid_consent_required'): p.embed(['a'])
    assert t.calls==0
    with pytest.raises(WorkflowError,match='provider_request_failed'): p.embed(['a'],allow_paid=True,request_id='x')
    with pytest.raises(WorkflowError,match='request_needs_attention'): p.embed(['a'],allow_paid=True,request_id='x')
    assert t.calls==1
    with sqlite3.connect(cfg['budget']['ledger']) as db: assert float(db.execute('select amount from reservations').fetchone()[0])==0.1

def test_invalid_index_and_missing_usage(setup):
    store,cfg=setup; t=Transport(response(index=1)); p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    with pytest.raises(WorkflowError): p.embed(['a'],allow_paid=True,request_id='bad')
    t.response=response()
    assert p.embed(['a'],allow_paid=True,request_id='good')['estimated_cost_cny'] is None
    with sqlite3.connect(cfg['budget']['ledger']) as db: assert float(db.execute("select amount from reservations where request_id='good'").fetchone()[0])==0.1

def test_answer_payload_and_usage(setup):
    store,cfg=setup
    t=Transport({'model':'deepseek-flash','choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':5,'completion_tokens':3}})
    p=RagProvider(store,cfg,t,{'DEEPSEEK_API_KEY':'fake'})
    result=p.answer([{'role':'user','content':'hello'}],allow_paid=True,request_id='answer')
    assert result['content']=='{}' and result['estimated_cost_cny'] is not None

def test_invalid_vector_and_budget_fail_before_post(setup):
    store,cfg=setup; t=Transport(response()); p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    cfg['budget']['embedding_reserve']='0.00000000001'
    with pytest.raises(WorkflowError): p.embed(['a'],allow_paid=True,request_id='a')
    assert t.calls==0
    cfg['budget']['embedding_reserve']='0.1'; t.response=response(); t.response['data'][0]['embedding'][0]=True
    with pytest.raises(WorkflowError): p.embed(['a'],allow_paid=True,request_id='b')

def test_known_cost_above_reserve_is_recorded(setup):
    store,cfg=setup; t=Transport(response({'prompt_tokens':1000000})); p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    with pytest.raises(WorkflowError,match='provider_request_failed'): p.embed(['a'],allow_paid=True,request_id='expensive')
    with sqlite3.connect(cfg['budget']['ledger']) as db:
        assert float(db.execute("select amount from reservations where request_id='expensive'").fetchone()[0]) == 0.5
    with pytest.raises(WorkflowError,match='request_needs_attention'): p.embed(['a'],allow_paid=True,request_id='expensive')
    assert t.calls == 1

def test_invalid_content_known_usage_charged_and_no_replay(setup):
    store,cfg=setup
    for kind in ('embedding','answer'):
        if kind=='embedding':
            data=response({'prompt_tokens':1000000},index=1); secret={'DASHSCOPE_API_KEY':'fake'}
        else:
            data={'model':'deepseek-flash','choices':[{'message':{'content':'partial'},'finish_reason':'length'}], 'usage':{'prompt_tokens':1000000,'completion_tokens':1000000}}; secret={'DEEPSEEK_API_KEY':'fake'}
        t=Transport(data); p=RagProvider(store,cfg,t,secret)
        def invoke():
            return p.embed(['a'],allow_paid=True,request_id=kind) if kind=='embedding' else p.answer([{'role':'user','content':'a'}],allow_paid=True,request_id=kind)
        with pytest.raises(WorkflowError): invoke()
        with pytest.raises(WorkflowError,match='request_needs_attention'): invoke()
        assert t.calls==1
        with sqlite3.connect(cfg['budget']['ledger']) as db:
            assert float(db.execute('select amount from reservations where request_id=?',(kind,)).fetchone()[0]) == (0.5 if kind=='embedding' else 10)
        with sqlite3.connect(store.db_path) as db:
            status,summary=db.execute('select status,result from rag_requests where id=?',(kind,)).fetchone()
            assert status=='needs_attention' and json.loads(summary)['usage']['prompt_tokens']==1000000

def test_wrong_model_and_disabled(setup):
    store,cfg=setup; t=Transport(response()); t.response['model']='wrong'; p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    cfg['enabled']=False
    with pytest.raises(WorkflowError,match='rag_disabled'): p.embed(['a'],allow_paid=True)
    assert t.calls==0
    cfg['enabled']=True
    with pytest.raises(WorkflowError,match='provider_request_failed'): p.embed(['a'],allow_paid=True)

def test_missing_response_model_charged_no_replay(setup):
    store,cfg=setup; data=response({'prompt_tokens':1000000}); del data['model']
    t=Transport(data); p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    with pytest.raises(WorkflowError,match='provider_request_failed'): p.embed(['a'],allow_paid=True,request_id='missing-model')
    with pytest.raises(WorkflowError,match='request_needs_attention'): p.embed(['a'],allow_paid=True,request_id='missing-model')
    assert t.calls==1
    with sqlite3.connect(cfg['budget']['ledger']) as db:
        assert float(db.execute("select amount from reservations where request_id='missing-model'").fetchone()[0])==0.5

def test_invalid_content_known_cost_below_reserve_settled(setup):
    store,cfg=setup
    data=response({'prompt_tokens':10},index=1)
    t=Transport(data); p=RagProvider(store,cfg,t,{'DASHSCOPE_API_KEY':'fake'})
    with pytest.raises(WorkflowError,match='provider_request_failed'):
        p.embed(['a'],allow_paid=True,request_id='invalid-low-cost')
    with sqlite3.connect(cfg['budget']['ledger']) as db:
        assert float(db.execute("select amount from reservations where request_id='invalid-low-cost'").fetchone()[0])==0.000005
    with pytest.raises(WorkflowError,match='request_needs_attention'):
        p.embed(['a'],allow_paid=True,request_id='invalid-low-cost')
    assert t.calls==1
