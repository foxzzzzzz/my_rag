import json
import pytest
from personalkb.workflow_store import WorkflowStore, WorkflowError
from personalkb.classification_suggestions import SuggestionService

@pytest.fixture
def setup(tmp_path):
    store=WorkflowStore(tmp_path/'db.sqlite')
    source=store.import_source('html','a'*64,'sample','sample')['source']['id']
    with store._tx() as c:
        c.execute("INSERT INTO versions(id,source_id,content_sha256,result,output_kind) VALUES(?,?,?,?,?)",('v1',source,'b'*64,json.dumps({'body':'data','summary':'summary','notes':'notes'}),'machine_initial'))
        c.execute("UPDATE sources SET current_version_id='v1' WHERE id=?",(source,))
    cfg=json.loads((__import__('pathlib').Path(__file__).resolve().parents[1]/'config/classification-suggestions.json').read_text(encoding='utf-8-sig'))
    cfg['enabled']=True; cfg['budget']['ledger']=str(tmp_path/'budget.sqlite')
    calls=[]
    output={'existing_topics':[],'existing_tags':[],'new_topics':['新主题'],'new_tags':[]}
    def provider(messages):
        calls.append(messages); return {'content':json.dumps(output),'model':'fake','usage':{'prompt_tokens':3,'completion_tokens':2},'estimated_cost_cny':'0.01'}
    svc=SuggestionService(store,cfg,lambda:provider)
    return svc,source,calls,output

def test_consent_generate_and_confirm(setup):
    svc,sid,calls,out=setup
    with pytest.raises(WorkflowError): svc.generate(sid,'v1',0)
    assert not calls
    result=svc.generate(sid,'v1',0,True)
    assert svc.classifications.catalog()==[]
    applied=svc.apply(result['id'],[],[],[],[])
    assert applied['status']=='applied' and svc.classifications.catalog()==[]
    assert svc.apply(result['id'],[],[],[],[])==applied
    result=svc.generate(sid,'v1',0,True)
    applied=svc.apply(result['id'],[],[],['新主题'],[])
    assert applied['receipt']['topics'][0]['name']=='新主题'

def test_tag_only_apply_rolls_back_new_label(setup):
    svc,sid,calls,out=setup
    out['new_topics']=[]; out['new_tags']=['新标签']
    result=svc.generate(sid,'v1',0,True)
    with pytest.raises(WorkflowError,match='classification_topic_required'):
        svc.apply(result['id'],[],[],[],['新标签'])
    assert svc.classifications.catalog()==[]
    assert svc.latest(sid)['status']=='ready'
    assert svc.classifications.snapshot(sid)['revision']==0

def test_invalid_and_unknown_keeps_reservation(setup):
    svc,sid,calls,out=setup
    out['existing_topics']=['untrusted']
    with pytest.raises(WorkflowError): svc.generate(sid,'v1',0,True)
    assert svc.latest(sid)['status']=='needs_attention'
    import sqlite3
    with sqlite3.connect(svc.config['budget']['ledger']) as c: assert c.execute('select count(*) from reservations').fetchone()[0]==1

def test_catalog_conflict_and_reject(setup):
    svc,sid,calls,out=setup
    result=svc.generate(sid,'v1',0,True)
    svc.classifications.create_label('tag','other')
    with pytest.raises(WorkflowError,match='classification_conflict'): svc.apply(result['id'],[],[],['新主题'],[])
    assert len(svc.classifications.catalog())==1
    assert svc.reject(result['id'])['status']=='rejected'
    assert svc.reject(result['id'])['status']=='rejected'
    with pytest.raises(WorkflowError): svc.apply(result['id'],[],[],[],[])

def test_budget_insufficient_no_call(setup):
    svc,sid,calls,out=setup
    svc.config['budget']['research_limit']='0.01'
    with pytest.raises(WorkflowError): svc.generate(sid,'v1',0,True)
    assert not calls

def test_version_and_metadata_conflict(setup):
    svc,sid,calls,out=setup
    result=svc.generate(sid,'v1',0,True)
    svc.classifications.create_label('topic','manual')
    label=svc.classifications.catalog()[0]['id']
    svc.classifications.update(sid,0,[label],[])
    with pytest.raises(WorkflowError,match='classification_conflict'): svc.apply(result['id'],[],[],['新主题'],[])
    assert len(svc.classifications.catalog())==1
    with svc.store._tx() as c: c.execute("UPDATE sources SET current_version_id=NULL WHERE id=?",(sid,))
    with pytest.raises(WorkflowError,match='version_conflict'): svc.apply(result['id'],[],[],[],[])

def test_known_cost_settled_and_unknown_not_retried(setup):
    svc,sid,calls,out=setup
    import sqlite3
    result=svc.generate(sid,'v1',0,True)
    with sqlite3.connect(svc.config['budget']['ledger']) as c: assert c.execute('select amount from reservations').fetchone()[0]=='0.000022'
    def fail(messages): raise RuntimeError('private remote error')
    svc.provider_factory=lambda:fail
    with pytest.raises(WorkflowError): svc.generate(sid,'v1',0,True)
    assert svc.latest(sid)['error_code']=='suggestion_generation_failed'
    with sqlite3.connect(svc.config['budget']['ledger']) as c: assert sorted(x[0] for x in c.execute('select amount from reservations'))==['0.000022','0.20']
    assert len(calls)==1

def test_disabled_and_invalid_output(setup):
    svc,sid,calls,out=setup
    svc.config['enabled']=False
    with pytest.raises(WorkflowError): svc.generate(sid,'v1',0,True)
    assert not calls
    svc.config['enabled']=True
    out['new_topics']=['重复','重复']
    with pytest.raises(WorkflowError): svc.generate(sid,'v1',0,True)
    assert svc.classifications.catalog()==[]

def test_missing_usage_does_not_release_and_bad_config(setup):
    svc,sid,calls,out=setup
    svc.provider_factory=lambda:lambda messages: {'content':json.dumps(out),'estimated_cost_cny':'0'}
    r=svc.generate(sid,'v1',0,True)
    assert r['result']['estimated_cost_cny'] is None
    import sqlite3
    with sqlite3.connect(svc.config['budget']['ledger']) as c: assert c.execute('select amount from reservations').fetchone()[0]=='0.20'
    svc.config['prices']['text']=[float('nan'),8]
    with pytest.raises(WorkflowError,match='invalid_config'): svc.generate(sid,'v1',0,True)

def test_latest_recovers_only_when_guard_free(setup):
    import threading
    from personalkb.execution_guard import execution_guard
    svc,sid,calls,out=setup
    with svc.store._tx() as c:
        c.execute("INSERT INTO classification_suggestions(id,source_id,version_id,content_sha256,revision,catalog_hash,fingerprint,status) VALUES('running',?,'v1','hash',0,'hash','hash','running')",(sid,))
    held=threading.Event(); release=threading.Event()
    def run():
        with execution_guard(svc.store): held.set(); release.wait(5)
    t=threading.Thread(target=run); t.start(); assert held.wait(5)
    try: assert svc.latest(sid)['status']=='running'
    finally: release.set(); t.join()
    assert svc.latest(sid)['status']=='needs_attention'

def test_apply_different_selection_conflicts(setup):
    svc,sid,calls,out=setup
    r=svc.generate(sid,'v1',0,True)
    svc.apply(r['id'],[],[],[],[])
    with pytest.raises(WorkflowError,match='suggestion_conflict'): svc.apply(r['id'],[],[],['新主题'],[])


def test_custom_classification_limit_rolls_back_new_labels(setup):
    svc,sid,calls,out=setup
    cfg=dict(svc.classifications.config); cfg['max_labels_per_kind']=1
    custom=SuggestionService(svc.store,svc.config,svc.provider_factory,classification_config=cfg)
    out['new_topics']=['一','二']
    r=custom.generate(sid,'v1',0,True)
    with pytest.raises(WorkflowError): custom.apply(r['id'],[],[],['一','二'],[])
    assert custom.classifications.catalog()==[]
    assert custom.latest(sid)['status']=='ready'
