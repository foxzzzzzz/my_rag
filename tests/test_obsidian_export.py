import hashlib, io, json, zipfile
import pytest
from personalkb.workflow import load_config
from personalkb.workflow_store import WorkflowError
from personalkb.obsidian_export import EditableExport, readonly_files, load_obsidian_config

@pytest.fixture
def case(tmp_path):
    cfg=load_config(); cfg['data_dir']=str(tmp_path); e=EditableExport(cfg)
    item=e.store.import_source('html','a'*64,'private.html','private/path')
    t=e.store.claim_specific(item['task']['id'],'worker')
    result=dict(title='Title',body='Body',summary='Summary',notes='笔记',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'text':'proof','api_key':'secret'}])
    v=e.store.finish(t['id'],t['lease_token'],result)
    return e,item['source']['id'],v

def test_note(case):
    e,sid,v=case; data,name=e.export_note(sid); head,body=data.decode().split('---\n\n',1)
    assert body=='笔记' and name==sid+'.md'
    fields=dict(line.split(': ',1) for line in head.splitlines()[1:])
    assert json.loads(fields['pkb_format'])=='pkb-obsidian-v1'
    assert json.loads(fields['source_id'])==sid and json.loads(fields['base_version_id'])==v['id']

def test_zip_manifest(case):
    e,sid,v=case; data,_=e.export_zip(sid)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        m=json.loads(z.read('manifest.json')); assert m['base_version_id']==v['id']
        assert all(hashlib.sha256(z.read(k)).hexdigest()==h for k,h in m['files'].items())
        assert json.loads(z.read('evidence.json'))['evidence']==[{'text':'proof'}]
        assert b'secret' not in z.read('evidence.json') and b'private/path' not in z.read('manifest.json')

def test_frame_hash(case):
    e,sid,v=case; source=e.store.get_source(sid); result=dict(v['result']); result['frames']=[{'sha256':'a'*64}]
    v=dict(v,result=result,content_sha256=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    p=e.store.content_root/sid/'frames'/('a'*64+'.jpg'); p.parent.mkdir(exist_ok=True); p.write_bytes(b'wrong')
    with pytest.raises(WorkflowError): readonly_files(e.store,source,v)

def test_invalid_config(tmp_path):
    p=tmp_path/'bad.json'; p.write_text('{"max_members": 0}')
    with pytest.raises(WorkflowError): load_obsidian_config(p)

def test_deleted(case):
    e,sid,v=case; e.store.delete_source(sid)
    with pytest.raises(WorkflowError): e.export_note(sid)
