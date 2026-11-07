import hashlib, json, shutil
import pytest
from personalkb.workflow_store import WorkflowStore, WorkflowError
from personalkb.content_storage import read

def setup(tmp_path):
    root=tmp_path/'data'; root.mkdir()
    store=WorkflowStore(root/'db',content_root=root/'knowledge',data_root=root)
    item=store.import_source('html','a'*64,'a.html','originals/a')
    task=store.claim_specific(item['task']['id'],'test')
    result=dict(title='Title',body='Body',summary='Summary',notes='Notes',scheme_id='s',scheme_version='1',output_kind='machine_initial',provenance='local_extraction',evidence=[{'text':'evidence','api_key':'secret'}])
    return store,item,task,result

def test_versions_review_corruption_and_reconcile(tmp_path):
    store,item,task,result=setup(tmp_path); sid=item['source']['id']
    v=store.finish(task['id'],task['lease_token'],result)
    assert store.assert_synced(sid)
    base=store.content_root/sid/'versions'/v['id']
    assert 'secret' not in (base/'evidence.json').read_text(encoding='utf8')
    store.review(sid,v['id'],v['content_sha256'],99,'approve','me')
    assert len(store.eligible_sources())==1
    (base/'content.md').write_text('broken')
    assert not store.eligible_sources()
    assert store.reconcile(sid)[sid]=='synced'
    assert store.assert_synced(sid)
    revised={**result,'body':'new','output_kind':'human_edited','provenance':'human_edited'}
    v2=store.revise(sid,v['id'],revised)
    assert not store.eligible_sources() and (base/'content.md').exists()
    assert json.loads((store.content_root/sid/'current.json').read_text())['current_version_id']==v2['id']
    store.delete_source(sid)
    assert json.loads((store.content_root/sid/'current.json').read_text())['status']=='deleted'

def test_failure_remains_dirty_and_retry(tmp_path, monkeypatch):
    store,item,task,result=setup(tmp_path); sid=item['source']['id']
    import personalkb.content_storage as content
    original=content.write
    monkeypatch.setattr(content,'write',lambda *args: (_ for _ in ()).throw(OSError('disk')))
    v=store.finish(task['id'],task['lease_token'],result)
    assert store.get_version(v['id']) and store.content_status(sid)=='content_unsynced'
    monkeypatch.setattr(content,'write',original)
    assert store.reconcile(sid)[sid]=='synced'
    assert len(store.list_versions(sid))==1

def test_permanent_frames_and_paths(tmp_path):
    store,item,task,result=setup(tmp_path); sid=item['source']['id']; tid=task['id']
    folder=store.data_root/'video-work'/tid; folder.mkdir(parents=True)
    data=b'jpeg'; sha=hashlib.sha256(data).hexdigest()
    (folder/'frame.jpg').write_bytes(data)
    (folder/'media-manifest.json').write_text(json.dumps({'frames':[{'index':0,'file':'frame.jpg','sha256':sha}]}))
    result['frames']=[{'index':0,'seconds':0,'sha256':sha}]
    store.finish(tid,task['lease_token'],result)
    shutil.rmtree(folder)
    assert read(store.content_root,f'{sid}/frames/{sha}.jpg')==data
    assert store.assert_synced(sid)
    with pytest.raises(WorkflowError): read(store.content_root,'../db')

def test_expected_version_guard(tmp_path):
    store,item,task,result=setup(tmp_path)
    with pytest.raises(WorkflowError,match='version_conflict'):
        store.finish(task['id'],task['lease_token'],result,expected_version_id='wrong')


def test_failed_review_and_delete_never_use_stale_approval(tmp_path, monkeypatch):
    store,item,task,result=setup(tmp_path); sid=item['source']['id']
    v=store.finish(task['id'],task['lease_token'],result)
    store.review(sid,v['id'],v['content_sha256'],99,'approve','me')
    import personalkb.content_storage as content
    original=content.write
    monkeypatch.setattr(content,'write',lambda *args: (_ for _ in ()).throw(OSError('disk')))
    store.review(sid,v['id'],v['content_sha256'],80,'rework','me')
    assert not store.eligible_sources() and store.content_status(sid)=='content_unsynced'
    store.delete_source(sid)
    assert not store.eligible_sources()
    monkeypatch.setattr(content,'write',original)
    assert store.reconcile(sid)[sid]=='synced'
    assert json.loads((store.content_root/sid/'current.json').read_text())['status']=='deleted'

def test_manifest_and_file_tamper_cannot_self_validate(tmp_path):
    store,item,task,result=setup(tmp_path); sid=item['source']['id']
    v=store.finish(task['id'],task['lease_token'],result)
    root=store.content_root; state_path=root/sid/'current.json'
    state=json.loads(state_path.read_text())
    path=f"{sid}/versions/{v['id']}/content.md"
    (root/path).write_text('changed')
    state['files'][path]=hashlib.sha256(b'changed').hexdigest()
    state_path.write_text(json.dumps(state))
    assert store.content_status(sid)=='content_integrity'

def test_text_preserved_and_current_note_links(tmp_path):
    store,item,task,result=setup(tmp_path); sid=item['source']['id']
    result['body']='https://example.org /home/user/code api_key=example'
    v=store.finish(task['id'],task['lease_token'],result)
    text=(store.content_root/sid/'note.md').read_text(encoding='utf8')
    assert result['body'] in text and f"versions/{v['id']}/evidence.json" in text

def test_eligibility_verifies_under_same_database_lock(tmp_path, monkeypatch):
    import sqlite3
    import personalkb.content_storage as content
    store,item,task,result=setup(tmp_path); sid=item['source']['id']
    v=store.finish(task['id'],task['lease_token'],result)
    store.review(sid,v['id'],v['content_sha256'],99,'approve','me')
    original=content.verify
    def competing_write(store_, sid_, connection=None):
        assert connection is not None
        with sqlite3.connect(store.db_path,timeout=0) as other:
            with pytest.raises(sqlite3.OperationalError,match='locked'):
                other.execute('UPDATE sources SET deleted=1 WHERE id=?',(sid,))
        return original(store_,sid_,connection)
    monkeypatch.setattr(content,'verify',competing_write)
    assert len(store.eligible_sources())==1
