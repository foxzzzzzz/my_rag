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

def test_rebuild_reclaims_stale_generation_and_sidecars(setup):
    s,index,sid,v=setup
    index.build(allow_paid=True); old=index._active()
    (old.parent/(old.name+'-journal')).write_bytes(b'stale')
    index.build(allow_paid=True)
    assert not old.exists()
    assert not (old.parent/(old.name+'-journal')).exists()
    assert index.query('独特',mode='lexical')

def test_missing_active_never_recreated(setup):
    s,index,sid,v=setup
    index.build(allow_paid=True); old=index._active(); old.unlink()
    with pytest.raises(WorkflowError,match='rag_invalidated'):
        index.query('独特',mode='lexical')
    assert not old.exists()

def test_index_lock_wait_is_bounded(setup):
    import threading
    from personalkb.rag_lock import index_guard
    s,index,_,_=setup; s.busy_timeout_seconds=0.05
    results=[]
    with index_guard(index):
        def reader():
            try: index.status()
            except WorkflowError as exc: results.append(str(exc))
        t=threading.Thread(target=reader); t.start(); t.join(2)
        assert not t.is_alive() and results == ['worker_busy']


def test_rebuild_preserves_generation_held_by_another_process(setup, tmp_path):
    import subprocess, time
    store, index, _, _ = setup
    index.build(allow_paid=True)
    old = index._active()
    class CountingProvider(Fake):
        calls = 0
        def embed(self, texts, **kwargs):
            self.calls += 1
            return super().embed(texts, **kwargs)
    index.provider = CountingProvider()
    marker = tmp_path / 'reader-ready'
    script = '''import sqlite3, sys
from pathlib import Path
from types import SimpleNamespace
from personalkb.rag_lock import index_guard
index = SimpleNamespace(store=SimpleNamespace(db_path=sys.argv[1], busy_timeout_seconds=1))
with index_guard(index):
    db = sqlite3.connect(sys.argv[2])
    try:
        assert db.execute('SELECT count(*) FROM chunks').fetchone()[0] == 1
        Path(sys.argv[3]).touch()
        sys.stdin.readline()
        assert db.execute('SELECT count(*) FROM chunks').fetchone()[0] == 1
    finally:
        db.close()
'''
    with subprocess.Popen([sys.executable, '-c', script, store.db_path, str(old), str(marker)], stdin=subprocess.PIPE) as reader:
        try:
            deadline = time.monotonic() + 10
            while not marker.exists():
                assert reader.poll() is None and time.monotonic() < deadline
                time.sleep(0.05)
            store.busy_timeout_seconds = 0.1
            with pytest.raises(WorkflowError, match='worker_busy'):
                index.build(allow_paid=True)
            assert index.provider.calls == 0
            assert index._active() == old and old.exists()
            assert list(index.root.glob('*.sqlite')) == [old]
        finally:
            reader.communicate(b'continue\n', timeout=10)
    assert reader.returncode == 0
    index.build(allow_paid=True)
    assert index.provider.calls > 0
    assert not old.exists() and index.query('独特', mode='lexical')


def test_status_and_lexical_query_remain_available_during_embedding(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    store, index, _, _ = setup
    index.build(allow_paid=True)
    started, resume = Event(), Event()
    class BlockingProvider(Fake):
        def embed(self, texts, **kwargs):
            started.set()
            assert resume.wait(10)
            return super().embed(texts, **kwargs)
    index.provider = BlockingProvider()
    store.busy_timeout_seconds = 0.1
    with ThreadPoolExecutor() as pool:
        hybrid = pool.submit(index.query, '独特', mode='hybrid', allow_paid=True)
        try:
            assert started.wait(10)
            assert index.status()['ready']
            assert index.query('独特', mode='lexical')
        finally:
            resume.set()
        assert hybrid.result(timeout=10)

def test_incremental_reuses_vectors_and_reports_current_coverage(setup):
    store,index,sid,version=setup
    index.update(allow_paid=True,request_id='stable')
    original=index.query('独特证据',mode='lexical')[0]
    class NoCalls:
        def embed(self,*args,**kwargs): raise AssertionError('unchanged text should be reused')
    index.provider=NoCalls()
    store.review(sid,version['id'],version['content_sha256'],99,'approve','again')
    assert index.status()['indexed_source_ids']==[]
    assert index.query('独特证据',mode='lexical',filters={'sources':['other']})==[]
    with pytest.raises(WorkflowError,match='rag_invalidated'):
        index.citation(original['chunk_id'])
    index.update(request_id='stable')
    status=index.status()
    assert status['eligible_source_ids']==[sid]
    assert status['indexed_source_ids']==[sid]
    assert status['unindexable_source_ids']==[]

def test_incremental_receipts_survive_regrouping_and_block_unknown(setup):
    import json
    store,index,_,_=setup
    index.config['limits']['embedding_batch_size']=2
    class Durable:
        def __init__(self): self.calls=[]
        def embed(self,texts,*,request_id,**kwargs):
            self.calls.append(list(texts))
            result={'model':'text-embedding-v4','vectors':[[1.,0.] for _ in texts]}
            with store._tx() as c:
                c.execute('INSERT INTO rag_requests VALUES (?,?,?,?)',(request_id,'fake','completed',json.dumps(result)))
            return result
    provider=Durable(); index.provider=provider
    index._incremental_embeddings([{'text':'a'},{'text':'b'}],{},'run',True,None)
    cache={}; index._incremental_embeddings([{'text':'b'},{'text':'c'}],cache,'run',True,None)
    assert provider.calls==[['a','b'],['c']]
    with store._tx() as c:
        c.execute("UPDATE rag_requests SET status='needs_attention' WHERE id=(SELECT batch_id FROM rag_index_batches WHERE text_hashes LIKE ? LIMIT 1)",('%'+__import__('personalkb.rag_index',fromlist=['_hash'])._hash('a')+'%',))
    with pytest.raises(WorkflowError,match='request_needs_attention'):
        index._incremental_embeddings([{'text':'a'},{'text':'d'}],{},'run',True,None)
    assert len(provider.calls)==2


def test_completed_vector_supersedes_unknown_receipt_for_same_text(setup):
    import json
    from personalkb.rag_index import _hash

    store,index,_,_=setup
    index._incremental_embeddings([],{},'current',False,None)
    with store._tx() as c:
        c.executemany('INSERT INTO rag_index_batches VALUES (?,?,?,?)',[
            ('old',index.space_id,'unknown',json.dumps([_hash('a')])),
            ('current',index.space_id,'finished',json.dumps([_hash('a')])),
        ])
        c.executemany('INSERT INTO rag_requests VALUES (?,?,?,?)',[
            ('unknown','fingerprint','in_flight',None),
            ('finished','fingerprint','completed',json.dumps(Fake().embed(['a']))),
        ])
    cache={}
    index._incremental_embeddings([{'text':'a'}],cache,'current',False,None)
    assert set(cache)=={'a'}
