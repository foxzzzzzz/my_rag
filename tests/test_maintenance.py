import os
import subprocess
import sys
import pytest
from personalkb.runtime_guard import runtime_guard, maintenance_guard
from personalkb.workflow_store import WorkflowStore, WorkflowError

def test_runtime_cross_process_and_release(tmp_path):
    script = "from personalkb.runtime_guard import runtime_guard; import sys;\nwith runtime_guard(sys.argv[1], 'web'): pass"
    with runtime_guard(tmp_path, 'web'):
        with pytest.raises(WorkflowError, match='maintenance_busy'):
            with runtime_guard(tmp_path, 'web'): pass
        proc = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True, text=True, env=os.environ.copy())
        assert proc.returncode != 0 and 'maintenance_busy' in proc.stderr
    assert subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True).returncode == 0

def test_maintenance_excludes_runtimes(tmp_path):
    store = WorkflowStore(tmp_path / 'workflow.sqlite', data_root=tmp_path)
    with maintenance_guard(store):
        for role in ('web', 'worker'):
            with pytest.raises(WorkflowError, match='maintenance_busy'):
                with runtime_guard(tmp_path, role): pass
    with runtime_guard(tmp_path, 'worker'):
        with pytest.raises(WorkflowError, match='maintenance_busy'):
            with maintenance_guard(store): pass

def test_backup_export_import_and_corruption(tmp_path):
    import hashlib, json, sqlite3, zipfile
    from personalkb import maintenance
    from personalkb.workflow import load_config, make_store
    from pathlib import Path
    base = json.loads(Path('config/workflow.json').read_text(encoding='utf-8-sig'))
    base['data_dir'] = str(tmp_path / 'data')
    workflow_path = tmp_path / 'workflow.json'
    workflow_path.write_text(json.dumps(base), encoding='utf8')
    store = make_store(load_config(workflow_path))
    with sqlite3.connect(store.db_path) as db:
        db.execute("INSERT INTO sources(id,kind,sha256,original_name,blob_relpath) VALUES('s','html',?,'a','originals/a')", ('a' * 64,))
        db.execute("INSERT INTO versions(id,source_id,content_sha256,result,output_kind) VALUES('v','s',?,'{}','html')", ('b' * 64,))
        db.execute("INSERT INTO reviews(id,source_id,version_id,content_sha256,score,decision,reviewer,note,tags) VALUES('r','s','v',?,99,'approved','me','','[]')", ('b' * 64,))
    attachment = tmp_path / 'data' / 'originals' / 'a'; attachment.parent.mkdir(); attachment.write_bytes(b'attachment')
    (tmp_path / 'data' / '.env').write_text('SECRET')
    ledger = tmp_path / 'budget.sqlite'
    with sqlite3.connect(ledger) as db: db.execute('CREATE TABLE ledger(x)'); db.execute('INSERT INTO ledger VALUES(42)')
    config_path = tmp_path / 'maintenance.json'
    config_path.write_text(json.dumps({'workflow_config': str(workflow_path), 'backup_root': str(tmp_path / 'backup'), 'ledger_paths': [str(ledger)], 'keep_snapshots': 7, 'min_free_bytes': 0}), encoding='utf8')
    config = maintenance.load_config(config_path)
    snapshot = maintenance.create(config)
    manifest = maintenance.verify(config, snapshot)
    assert not any('.env' in x['path'] for x in manifest['files'])
    archive = tmp_path / 'export.zip'; maintenance.export(config, snapshot, archive)
    target = tmp_path / 'restore'; maintenance.import_archive(archive, target, 0)
    assert (target / 'workflow/originals/a').read_bytes() == b'attachment'
    with sqlite3.connect(target / 'workflow/workflow.sqlite3') as db:
        assert [db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in ('sources', 'versions', 'reviews')] == [1, 1, 1]
    with sqlite3.connect(target / 'budget.sqlite') as db: assert db.execute('SELECT x FROM ledger').fetchone()[0] == 42
    with pytest.raises(WorkflowError, match='target_not_empty'): maintenance.import_archive(archive, target, 0)
    obj = tmp_path / 'backup/objects' / hashlib.sha256(b'attachment').hexdigest(); obj.write_bytes(b'corrupt')
    with pytest.raises(WorkflowError, match='corrupt_object'): maintenance.verify(config, snapshot)
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z: z.writestr('../escape', 'x'); z.writestr('manifest.json', '{}')
    with pytest.raises(WorkflowError): maintenance.import_archive(bad, tmp_path / 'badtarget', 0)
    assert not (tmp_path / 'badtarget').exists()

def test_manifest_hash_and_space_fail_before_publish(tmp_path, monkeypatch):
    import json, sqlite3
    from pathlib import Path
    from personalkb import maintenance
    from personalkb.workflow import load_config, make_store
    cfg = json.loads(Path('config/workflow.json').read_text(encoding='utf-8-sig'))
    cfg['data_dir'] = str(tmp_path / 'data')
    wp = tmp_path / 'workflow.json'; wp.write_text(json.dumps(cfg))
    make_store(load_config(wp))
    ledger = tmp_path / 'budget.sqlite'
    with sqlite3.connect(ledger) as db: db.execute('CREATE TABLE t(x)')
    cp = tmp_path / 'config.json'; cp.write_text(json.dumps({'workflow_config':str(wp),'backup_root':str(tmp_path/'backups'),'ledger_paths':[str(ledger)],'keep_snapshots':7,'min_free_bytes':0}))
    c = maintenance.load_config(cp)
    snap = maintenance.create(c)
    manifest = tmp_path / 'backups/snapshots' / (snap + '.json')
    manifest.write_bytes(manifest.read_bytes() + b' ')
    with pytest.raises(WorkflowError, match='invalid_manifest'): maintenance.verify(c, snap)
    c['min_free_bytes'] = 10**30
    with pytest.raises(WorkflowError, match='insufficient_backup_space'): maintenance.create(c)
    assert len(list(manifest.parent.glob('*.json'))) == 1

def test_retention_dry_run_apply_and_failed_source(tmp_path):
    import hashlib, json, sqlite3
    from pathlib import Path
    from personalkb import maintenance
    from personalkb.workflow import load_config, make_store
    from personalkb.content_storage import encoded
    cfg = json.loads(Path('config/workflow.json').read_text(encoding='utf-8-sig')); cfg['data_dir'] = str(tmp_path / 'data')
    wp = tmp_path / 'workflow.json'; wp.write_text(json.dumps(cfg))
    store = make_store(load_config(wp)); data = Path(store.data_root); (data / 'originals').mkdir()
    raw = b'video'; sha = hashlib.sha256(raw).hexdigest()
    for sid in ('ok', 'bad'):
        raw = ('video-' + sid).encode(); sha = hashlib.sha256(raw).hexdigest()
        (data / 'originals' / sid).write_bytes(raw)
        with sqlite3.connect(store.db_path) as db:
            db.execute('INSERT INTO sources(id,kind,sha256,original_name,blob_relpath,current_version_id) VALUES(?,?,?,?,?,?)', (sid,'video',sha,sid,'originals/'+sid,'v'+sid))
            db.execute('INSERT INTO tasks(id,source_id,status,updated_at) VALUES(?,?,?,?)', ('t'+sid,sid,'succeeded' if sid=='ok' else 'failed','2020-01-01T00:00:00Z'))
            result = {'evidence':[{'text':'evidence'}], 'frames':[{'sha256': hashlib.sha256(b'frame').hexdigest()}]}
            raw_result = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            db.execute('INSERT INTO versions(id,source_id,content_sha256,result,output_kind) VALUES(?,?,?,?,?)', ('v'+sid,sid,hashlib.sha256(raw_result.encode()).hexdigest(),raw_result,'machine_initial'))
            generation = db.execute('SELECT generation FROM content_sync WHERE source_id=?',(sid,)).fetchone()[0]
            folder = Path(store.content_root) / sid; folder.mkdir(parents=True)
            files = {}
            for name, content in [('versions/v'+sid+'/content.md',b'content'), ('versions/v'+sid+'/evidence.json',b'evidence'), ('versions/v'+sid+'/manifest.json',b'manifest'), ('frames/'+result['frames'][0]['sha256']+'.jpg',b'frame')]:
                target = folder / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content); files[sid+'/'+name] = hashlib.sha256(content).hexdigest()
            state = encoded({'note_id':sid,'current_version_id':'v'+sid,'generation':generation,'files':files})
            (folder / 'current.json').write_bytes(state)
            db.execute('UPDATE content_sync SET synced_generation=?,state_sha256=? WHERE source_id=?',(generation,hashlib.sha256(state).hexdigest(),sid))
    config = {'_workflow': load_config(wp), 'video_retention_days':7}
    dry = maintenance.retention(config)
    assert {x['source_id']: x['status'] for x in dry['items']} == {'ok':'eligible','bad':'requires_attention_tasks'}
    assert (data / 'originals/ok').exists()
    with sqlite3.connect(store.db_path) as db:
        db.execute('CREATE TABLE web_dispatch(task_id TEXT, state TEXT)')
        db.execute("INSERT INTO web_dispatch VALUES('tok','pending')")
    assert {x['source_id']:x['status'] for x in maintenance.retention(config, apply=True)['items']}['ok'] == 'requires_attention_dispatch'
    assert (data / 'originals/ok').exists()
    with sqlite3.connect(store.db_path) as db: db.execute('DELETE FROM web_dispatch')
    maintenance.retention(config, apply=True)
    assert not (data / 'originals/ok').exists() and (data / 'originals/bad').exists()
    assert maintenance.media_status(store, 'ok')['status'] == 'removed'
    with sqlite3.connect(store.db_path) as db: db.execute("UPDATE media_retention SET status='planned',removed_at=NULL WHERE source_id='ok'")
    assert {x['source_id']:x['status'] for x in maintenance.retention(config)['items']}['ok'] == 'pending_reconciliation'
    assert {x['source_id']:x['status'] for x in maintenance.retention(config, apply=True)['items']}['ok'] == 'removed'
    assert {x['source_id']: x['status'] for x in maintenance.retention(config, apply=True)['items']}['ok'] == 'removed'


def test_oss_rejects_public_configuration_without_network():
    from personalkb.backup_storage import push
    with pytest.raises(WorkflowError, match='invalid_oss_config'):
        push({'storage_mode':'oss','oss':{'private':False}}, 'a' * 64)


def test_oss_private_upload_order_and_failure(tmp_path, monkeypatch):
    import hashlib, io, sys, types
    from contextlib import nullcontext
    from personalkb import maintenance, runtime_guard, backup_storage
    obj = b'attachment'; sha = hashlib.sha256(obj).hexdigest()
    manifest = b'manifest'; snap = hashlib.sha256(manifest).hexdigest()
    (tmp_path / 'objects').mkdir(); (tmp_path / 'snapshots').mkdir()
    (tmp_path / 'objects' / sha).write_bytes(obj); (tmp_path / 'snapshots' / (snap+'.json')).write_bytes(manifest)
    class Exists(Exception): pass
    class Bucket:
        def __init__(self): self.data = {}; self.order = []; self.fail = False
        def get_bucket_acl(self): return types.SimpleNamespace(acl='private')
        def get_object_acl(self,key): return types.SimpleNamespace(acl='private')
        def put_object_from_file(self,key,path,headers):
            assert headers['x-oss-forbid-overwrite'] == 'true'
            if self.fail: raise RuntimeError('network')
            self.order.append(key); self.data[key] = open(path,'rb').read()
        def get_object(self,key): return io.BytesIO(self.data[key])
    b = Bucket(); sdk = types.ModuleType('oss2'); sdk.ProviderAuthV4 = lambda p: p; sdk.Bucket = lambda *a, **k: b; sdk.exceptions = types.SimpleNamespace(ObjectAlreadyExists=Exists)
    creds = types.ModuleType('oss2.credentials'); creds.StaticCredentialsProvider = lambda *a: None
    monkeypatch.setitem(sys.modules,'oss2',sdk); monkeypatch.setitem(sys.modules,'oss2.credentials',creds)
    monkeypatch.setenv('BACKUP_ID','id'); monkeypatch.setenv('BACKUP_SECRET','secret')
    monkeypatch.setattr(maintenance,'verify', lambda c,s: {'files':[{'sha256':sha}]})
    monkeypatch.setattr(maintenance,'_guard_store',lambda c: None); monkeypatch.setattr(runtime_guard,'maintenance_guard',lambda s: nullcontext())
    c = {'storage_mode':'oss','backup_root':str(tmp_path),'_workflow':{},'oss':{'private':True,'region':'cn-test','endpoint':'https://oss-cn-test.aliyuncs.com','bucket':'test-bucket','prefix':'backup/','access_key_id_env':'BACKUP_ID','access_key_secret_env':'BACKUP_SECRET'}}
    assert backup_storage.push(c,snap)['uploaded']
    assert b.order == ['backup/objects/'+sha, 'backup/snapshots/'+snap+'.json']
    b.fail = True
    with pytest.raises(WorkflowError, match='oss_upload_failed'): backup_storage.push(c,snap)
    assert (tmp_path / 'snapshots' / (snap+'.json')).read_bytes() == manifest

def test_seven_snapshots_deduplicate_and_collect_unreferenced(tmp_path):
    import json, sqlite3
    from pathlib import Path
    from personalkb import maintenance
    from personalkb.workflow import load_config, make_store
    workflow = json.loads(Path('config/workflow.json').read_text(encoding='utf-8-sig')); workflow['data_dir'] = str(tmp_path / 'data')
    wp = tmp_path / 'workflow.json'; wp.write_text(json.dumps(workflow)); make_store(load_config(wp))
    ledger = tmp_path / 'budget.sqlite'
    with sqlite3.connect(ledger) as db: db.execute('CREATE TABLE ledger(x)')
    attachment = tmp_path / 'data' / 'attachment'; attachment.write_bytes(b'old')
    cp = tmp_path / 'maintenance.json'; cp.write_text(json.dumps({'workflow_config':str(wp),'backup_root':str(tmp_path/'backups'),'ledger_paths':[str(ledger)],'keep_snapshots':7,'min_free_bytes':0}))
    c = maintenance.load_config(cp); first = maintenance.create(c); oldsha = next(x['sha256'] for x in maintenance.verify(c,first)['files'] if x['path']=='workflow/attachment')
    attachment.write_bytes(b'new')
    ids = [maintenance.create(c) for _ in range(7)]
    snapshots = list((tmp_path/'backups/snapshots').glob('*.json'))
    assert len(snapshots) == 7 and len(set(ids)) == 7
    assert not (tmp_path/'backups/objects'/oldsha).exists()
    assert len(list((tmp_path/'backups/objects').iterdir())) < sum(len(maintenance.verify(c, i)['files']) for i in ids)

def test_oss_pull_checks_content_before_publishing(tmp_path, monkeypatch):
    import hashlib, io, json, sqlite3, sys, types
    from contextlib import nullcontext
    from personalkb import backup_storage, maintenance, runtime_guard
    dbfile = tmp_path/'db.sqlite'
    with sqlite3.connect(dbfile) as db: db.execute('CREATE TABLE test(x)')
    data = dbfile.read_bytes(); digest = hashlib.sha256(data).hexdigest()
    manifest = {'format':1,'files':[{'path':'workflow/workflow.sqlite3','sha256':digest,'size':len(data)},{'path':'budget.sqlite','sha256':digest,'size':len(data)}]}
    payload = json.dumps(manifest).encode(); snap = hashlib.sha256(payload).hexdigest()
    class Bucket:
        def get_bucket_acl(self): return types.SimpleNamespace(acl='private')
        def get_object_acl(self,key): return types.SimpleNamespace(acl='private')
        def get_object(self,key): return io.BytesIO(self.data[key])
    b=Bucket(); b.data = {'p/snapshots/'+snap+'.json':payload, 'p/objects/'+digest:data}; sdk=types.ModuleType('oss2'); sdk.ProviderAuthV4=lambda p:p; sdk.Bucket=lambda *a, **k:b
    creds=types.ModuleType('oss2.credentials'); creds.StaticCredentialsProvider=lambda *a:None
    monkeypatch.setitem(sys.modules,'oss2',sdk); monkeypatch.setitem(sys.modules,'oss2.credentials',creds)
    monkeypatch.setenv('BACKUP_ID','id'); monkeypatch.setenv('BACKUP_SECRET','secret')
    monkeypatch.setattr(maintenance,'_guard_store',lambda c:None); monkeypatch.setattr(runtime_guard,'maintenance_guard',lambda s:nullcontext())
    config={'storage_mode':'oss','backup_root':str(tmp_path/'repo'),'min_free_bytes':0,'oss':{'private':True,'region':'cn-test','endpoint':'https://oss-cn-test.aliyuncs.com','bucket':'test-bucket','prefix':'p/','access_key_id_env':'BACKUP_ID','access_key_secret_env':'BACKUP_SECRET'}}
    b.data['p/objects/'+digest] = b'corrupt'
    with pytest.raises(WorkflowError, match='remote_integrity'): backup_storage.pull(config,snap)
    assert not (tmp_path/'repo/snapshots'/ (snap+'.json')).exists()
    b.data['p/objects/'+digest] = data
    assert backup_storage.pull(config,snap)['downloaded']
    assert maintenance.verify(config,snap) == manifest
    with pytest.raises(WorkflowError, match='snapshot_exists'): backup_storage.pull(config,snap)

def test_real_workflow_backup_restore_approved_content(tmp_path):
    import json, sqlite3
    from pathlib import Path
    from personalkb import maintenance
    from personalkb.workflow import load_config, make_store, import_file, run_once
    c = json.loads(Path('config/workflow.json').read_text(encoding='utf-8-sig')); c.update(data_dir=str(tmp_path/'data'), min_free_bytes=0)
    wp = tmp_path/'workflow.json'; wp.write_text(json.dumps(c),encoding='utf8'); wc=load_config(wp)
    html=tmp_path/'source.html'; html.write_text('<html><title>Test</title><body>Verified evidence</body></html>',encoding='utf8')
    item=import_file(wc,html,True); sid=item['source']['id']; version=run_once(wc,task_id=item['task']['id'])
    store=make_store(wc); store.review(sid,version['id'],version['content_sha256'],99,'approve','tester')
    assert len(store.eligible_sources()) == 1 and store.content_status(sid) == 'synced'
    ledger=tmp_path/'budget.sqlite'
    with sqlite3.connect(ledger) as db: db.execute('CREATE TABLE budget(x)')
    cp=tmp_path/'maintenance.json'; cp.write_text(json.dumps({'workflow_config':str(wp),'backup_root':str(tmp_path/'repository'),'ledger_paths':[str(ledger)],'keep_snapshots':7,'min_free_bytes':0}))
    config=maintenance.load_config(cp); snap=maintenance.create(config); archive=tmp_path/'backup.zip'; maintenance.export(config,snap,archive)
    target=tmp_path/'restored'; maintenance.import_archive(archive,target,0)
    restored=wc.copy(); restored['data_dir']=str(target/'workflow'); recovered=make_store(restored)
    assert len(recovered.eligible_sources()) == 1 and recovered.content_status(sid) == 'synced'
    assert recovered.get_version(version['id'])['content_sha256'] == version['content_sha256']

def test_media_status_planned_file_presence(tmp_path):
    from personalkb import maintenance
    import sqlite3
    from types import SimpleNamespace
    store=SimpleNamespace(db_path=tmp_path/'db.sqlite',data_root=tmp_path)
    with sqlite3.connect(store.db_path) as db:
        db.execute('CREATE TABLE media_retention(source_id TEXT, status TEXT, blob_relpath TEXT)')
        db.execute("INSERT INTO media_retention VALUES('a','planned','originals/a')")
    assert maintenance.media_status(store,'a') == {'available':False,'status':'removed'}
    (tmp_path/'originals').mkdir(); (tmp_path/'originals'/'a').write_bytes(b'video')
    assert maintenance.media_status(store,'a') == {'available':True,'status':'planned'}


def test_oss_reads_secret_file_with_environment_override(tmp_path, monkeypatch):
    import sys, types
    from personalkb.backup_storage import _bucket
    secrets = tmp_path/'secret.env'; secrets.write_text('BACKUP_ID=file-id\nBACKUP_SECRET=file-secret\n',encoding='utf8')
    monkeypatch.delenv('BACKUP_ID', raising=False); monkeypatch.setenv('BACKUP_SECRET','override')
    captured=[]
    sdk=types.ModuleType('oss2'); sdk.ProviderAuthV4=lambda provider:provider
    sdk.Bucket=lambda *a, **k:types.SimpleNamespace(get_bucket_acl=lambda:types.SimpleNamespace(acl='private'))
    creds=types.ModuleType('oss2.credentials'); creds.StaticCredentialsProvider=lambda *args:captured.append(args)
    monkeypatch.setitem(sys.modules,'oss2',sdk); monkeypatch.setitem(sys.modules,'oss2.credentials',creds)
    c={'storage_mode':'oss','env_file':str(secrets),'oss':{'private':True,'region':'cn-test','endpoint':'https://oss-cn-test.aliyuncs.com','bucket':'test-bucket','prefix':'p/','access_key_id_env':'BACKUP_ID','access_key_secret_env':'BACKUP_SECRET'}}
    _bucket(c)
    assert captured == [('file-id','override')]
