"""Cold, content-addressed backups; callers must stop all writers first."""
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .runtime_guard import maintenance_guard
from .workflow import ROOT, load_config as load_workflow, make_store
from .workflow_store import WorkflowError


def media_status(store, source_id):
    with closing(sqlite3.connect(store.db_path)) as c:
        c.row_factory = sqlite3.Row
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_retention'").fetchone():
            return {'available': True, 'status': 'available'}
        row = c.execute('SELECT status, blob_relpath FROM media_retention WHERE source_id=?', (source_id,)).fetchone()
    status = row['status'] if row else 'available'
    if status == 'planned' and not Path(store.data_root).joinpath(*PurePosixPath(_safe_name(row['blob_relpath'])).parts).exists():
        status = 'removed'
    return {'available': status != 'removed', 'status': status}


def _path(value):
    p = Path(value)
    return (p if p.is_absolute() else ROOT / p).absolute()


def _no_links(p):
    if any(x.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(x)) for x in (p, *p.parents)):
        raise WorkflowError('unsafe_path')


def load_config(path):
    try:
        c = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        c['workflow_config'] = str(_path(c['workflow_config']))
        c['backup_root'] = str(_path(c['backup_root']))
        c['ledger_paths'] = [str(_path(x)) for x in c['ledger_paths']]
        if len(c['ledger_paths']) != 1 or type(c['keep_snapshots']) is not int or c['keep_snapshots'] < 1 or type(c['min_free_bytes']) is not int or c['min_free_bytes'] < 0: raise ValueError()
        if type(c.get('video_retention_days', 7)) is not int or c.get('video_retention_days', 7) < 7: raise ValueError()
        if type(c.get('max_manifest_bytes', 4194304)) is not int or c.get('max_manifest_bytes', 4194304) < 1: raise ValueError()
        if c.get('storage_mode', 'manual') not in ('manual', 'oss'): raise ValueError()
        workflow = load_workflow(c['workflow_config'])
        data, backup = Path(workflow['data_dir']).resolve(), Path(c['backup_root']).resolve()
        if data == backup or data in backup.parents or backup in data.parents: raise ValueError()
        if any(Path(x).resolve() == backup or backup in Path(x).resolve().parents for x in c['ledger_paths']): raise ValueError()
        for p in [Path(c['backup_root']), Path(c['workflow_config']), *map(Path, c['ledger_paths'])]: _no_links(p)
        c['_workflow'] = workflow
        return c
    except (OSError, ValueError, TypeError, KeyError):
        raise WorkflowError('invalid_maintenance_config') from None


def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()


def _safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or '\0' in name: raise WorkflowError('unsafe_path')
    p = PurePosixPath(name)
    if p.is_absolute() or p.as_posix() != name or any(x in ('', '.', '..') for x in p.parts) or ':' in name: raise WorkflowError('unsafe_path')
    return name


def _space(root, amount, reserve):
    if shutil.disk_usage(root).free - amount < reserve: raise WorkflowError('insufficient_backup_space')


def _sqlite_copy(src, dest):
    if not src.is_file(): raise WorkflowError('missing_database')
    with closing(sqlite3.connect('file:' + src.as_posix() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(dest)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise WorkflowError('invalid_database')


def _secret(p):
    name = p.name.lower()
    return name.startswith('.env') or 'secret' in name or name.startswith('auth') or name.endswith(('.lock', '-wal', '-shm', '-journal'))


def _guard_store(config):
    from types import SimpleNamespace
    root = Path(config['_workflow']['data_dir'])
    return SimpleNamespace(data_root=root, db_path=str(root / 'workflow.sqlite3'))


def create(config):
    store = _guard_store(config)
    root = Path(config['backup_root']); _no_links(root); root.mkdir(parents=True, exist_ok=True)
    objects = root / 'objects'; manifests = root / 'snapshots'
    for p in (objects, manifests): _no_links(p); p.mkdir(exist_ok=True)
    with maintenance_guard(store), tempfile.TemporaryDirectory(dir=root, prefix='.stage-') as temp:
        store = make_store(config['_workflow'])
        staging = Path(temp); files = []
        data = Path(store.data_root)
        def add(path, name):
            _no_links(path); _safe_name(name)
            if not path.is_file(): raise WorkflowError('invalid_backup_file')
            digest = _sha(path); size = path.stat().st_size
            dst = objects / digest
            if dst.exists():
                _no_links(dst)
                if _sha(dst) != digest: raise WorkflowError('corrupt_object')
            else:
                _space(root, size, config['min_free_bytes'])
                part = staging / uuid.uuid4().hex
                shutil.copyfile(path, part)
                if _sha(part) != digest: raise WorkflowError('source_changed')
                os.replace(part, dst)
            files.append({'path': name, 'sha256': digest, 'size': size})
        for base, dirs, names in os.walk(data, followlinks=False):
            base = Path(base)
            for d in dirs: _no_links(base / d)
            dirs[:] = [d for d in dirs if not _secret(base / d)]
            for name in names:
                p = base / name; _no_links(p)
                if p == Path(store.db_path) or _secret(p): continue
                add(p, 'workflow/' + p.relative_to(data).as_posix())
        for source, name in [(Path(store.db_path), 'workflow/workflow.sqlite3'), (Path(config['ledger_paths'][0]), 'budget.sqlite')]:
            _no_links(source)
            _space(root, source.stat().st_size * 2, config['min_free_bytes'])
            tmp = staging / (uuid.uuid4().hex + '.sqlite')
            _sqlite_copy(source, tmp); add(tmp, name)
        public = json.loads(Path(config['workflow_config']).read_text(encoding='utf-8-sig'))
        def scrub(value):
            if isinstance(value, dict): return {k: scrub(v) for k, v in value.items() if not any(word in k.lower() for word in ('secret', 'password', 'token', 'credential', 'api_key', 'apikey', 'auth'))}
            if isinstance(value, list): return [scrub(v) for v in value]
            return value
        public_path = staging / 'workflow-public.json'
        public_path.write_text(json.dumps(scrub(public), ensure_ascii=False), encoding='utf-8')
        add(public_path, 'publicconfig/workflow.json')
        from datetime import datetime, timezone
        manifest = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': sorted(files, key=lambda x: x['path']), 'index_rebuild_required_after_path_change': True}
        payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        identifier = hashlib.sha256(payload).hexdigest()
        _space(root, len(payload), config['min_free_bytes'])
        part = staging / 'manifest'; part.write_bytes(payload)
        # Check the complete candidate before publishing or removing older snapshots.
        _verify_objects(root, _validate_manifest(manifest))
        destination = manifests / (identifier + '.json')
        existing = sorted((p for p in manifests.glob('*.json') if p != destination),
                          key=lambda p: p.stat().st_mtime_ns, reverse=True)
        checked = [_manifest(root, p.stem) for p in existing]
        os.replace(part, destination)
        keep_previous = config['keep_snapshots'] - 1
        retained = [manifest, *checked[:keep_previous]]
        for old in existing[keep_previous:]: old.unlink()
        referenced = {i['sha256'] for m in retained for i in m['files']}
        for obj in objects.iterdir():
            if len(obj.name) == 64 and all(c in '0123456789abcdef' for c in obj.name) and obj.name not in referenced:
                _no_links(obj)
                if obj.is_file(): obj.unlink()
        return identifier


def _validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('format') != 1 or not isinstance(manifest.get('files'), list): raise WorkflowError('invalid_manifest')
    seen = set()
    for item in manifest['files']:
        try:
            name = _safe_name(item['path']); sha = item['sha256']; size = item['size']
            if name in seen or any(_secret(Path(part)) for part in PurePosixPath(name).parts) or not (name.startswith('workflow/') or name in ('budget.sqlite', 'publicconfig/workflow.json')) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or type(size) is not int or size < 0: raise ValueError()
            seen.add(name)
        except (KeyError, TypeError, ValueError): raise WorkflowError('invalid_manifest') from None
    if not {'workflow/workflow.sqlite3', 'budget.sqlite'}.issubset(seen): raise WorkflowError('invalid_manifest')
    return manifest


def _manifest(root, identifier):
    if len(identifier) != 64 or any(c not in '0123456789abcdef' for c in identifier): raise WorkflowError('invalid_snapshot')
    p = root / 'snapshots' / (identifier + '.json'); _no_links(p)
    try:
        payload = p.read_bytes()
        if hashlib.sha256(payload).hexdigest() != identifier: raise WorkflowError('invalid_manifest')
        return _validate_manifest(json.loads(payload))
    except (OSError, ValueError): raise WorkflowError('invalid_manifest') from None


def verify(config, identifier):
    root = Path(config['backup_root']); manifest = _manifest(root, identifier)
    return _verify_objects(root, manifest)


def _verify_objects(root, manifest):
    for item in manifest['files']:
        p = root / 'objects' / item['sha256']; _no_links(p)
        if not p.is_file() or p.stat().st_size != item['size'] or _sha(p) != item['sha256']: raise WorkflowError('corrupt_object')
        if item['path'] in ('workflow/workflow.sqlite3', 'budget.sqlite'):
            try:
                with closing(sqlite3.connect('file:' + p.as_posix() + '?mode=ro', uri=True)) as c:
                    if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise WorkflowError('invalid_database')
            except sqlite3.DatabaseError: raise WorkflowError('invalid_database') from None
    return manifest


def export(config, identifier, destination):
    with maintenance_guard(_guard_store(config)):
        m = verify(config, identifier); destination = Path(destination).absolute(); _no_links(destination)
        if destination.exists(): raise WorkflowError('target_exists')
        _space(destination.parent, sum(i['size'] for i in m['files']), config['min_free_bytes'])
        temp = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with zipfile.ZipFile(temp, 'x', compression=zipfile.ZIP_STORED) as z:
                z.writestr('manifest.json', (Path(config['backup_root']) / 'snapshots' / (identifier + '.json')).read_bytes())
                z.writestr('manifest.sha256', identifier)
                for sha in sorted({i['sha256'] for i in m['files']}): z.write(Path(config['backup_root']) / 'objects' / sha, 'objects/' + sha)
            os.replace(temp, destination)
        finally:
            if temp.exists(): temp.unlink()
    return str(destination)


def _publish(manifest, get_object, target, reserve):
    target = Path(target).absolute(); _no_links(target)
    if target.exists() and (not target.is_dir() or any(target.iterdir())): raise WorkflowError('target_not_empty')
    target.parent.mkdir(parents=True, exist_ok=True)
    _space(target.parent, sum(i['size'] for i in manifest['files']), reserve)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix='.restore-') as tmp:
        staging = Path(tmp)
        for item in manifest['files']:
            dst = staging.joinpath(*PurePosixPath(item['path']).parts); dst.parent.mkdir(parents=True, exist_ok=True)
            get_object(item['sha256'], dst)
            if dst.stat().st_size != item['size'] or _sha(dst) != item['sha256']: raise WorkflowError('corrupt_object')
            if item['path'] in ('workflow/workflow.sqlite3', 'budget.sqlite'):
                try:
                    with closing(sqlite3.connect('file:' + dst.as_posix() + '?mode=ro', uri=True)) as c:
                        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise WorkflowError('invalid_database')
                except sqlite3.DatabaseError: raise WorkflowError('invalid_database') from None
        if target.exists(): target.rmdir()
        os.replace(staging, target)
    return {'target': str(target), 'index_rebuild_required_after_path_change': True}


def restore(config, identifier, target):
    with maintenance_guard(_guard_store(config)):
        m = verify(config, identifier)
        return _publish(m, lambda sha, dst: shutil.copyfile(Path(config['backup_root']) / 'objects' / sha, dst), target, config['min_free_bytes'])


def import_archive(archive, target, min_free_bytes=8589934592, max_manifest_bytes=4194304):
    if type(min_free_bytes) is not int or min_free_bytes < 0 or type(max_manifest_bytes) is not int or max_manifest_bytes < 1: raise WorkflowError('invalid_maintenance_config')
    archive = Path(archive).absolute(); _no_links(archive)
    try:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            if len(names) != len(set(names)): raise WorkflowError('unsafe_archive')
            for info in z.infolist():
                _safe_name(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16) or info.is_dir(): raise WorkflowError('unsafe_archive')
            if z.getinfo('manifest.json').file_size > max_manifest_bytes: raise WorkflowError('invalid_manifest')
            if z.getinfo('manifest.sha256').file_size != 64: raise WorkflowError('invalid_manifest')
            manifest_bytes = z.read('manifest.json')
            checksum = z.read('manifest.sha256')
            if len(checksum) != 64 or hashlib.sha256(manifest_bytes).hexdigest().encode() != checksum: raise WorkflowError('invalid_manifest')
            m = _validate_manifest(json.loads(manifest_bytes))
            expected = {'manifest.json', 'manifest.sha256'} | {'objects/' + i['sha256'] for i in m['files']}
            if set(names) != expected: raise WorkflowError('unsafe_archive')
            for item in m['files']:
                if z.getinfo('objects/' + item['sha256']).file_size != item['size']: raise WorkflowError('corrupt_object')
            def get(sha, dst):
                with z.open('objects/' + sha) as source, open(dst, 'wb') as out: shutil.copyfileobj(source, out)
            return _publish(m, get, target, min_free_bytes)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError): raise WorkflowError('invalid_archive') from None



def retention(config, apply=False):
    """Report expired videos; delete only verified successful sources when explicitly requested."""
    from datetime import datetime, timezone, timedelta
    from .content_storage import verify as verify_content
    days = config.get('video_retention_days', 7)
    if type(days) is not int or days < 7: raise WorkflowError('invalid_retention')
    store = _guard_store(config)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    report = []
    with maintenance_guard(store):
        store = make_store(config['_workflow'])
        with store._tx() as c:
            sources = [dict(x) for x in c.execute("SELECT * FROM sources WHERE kind IN ('video','mp4') AND deleted=0")]
            has_table = bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_retention'").fetchone())
            if apply:
                c.execute("CREATE TABLE IF NOT EXISTS media_retention (source_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, blob_relpath TEXT NOT NULL, status TEXT NOT NULL, removed_at TEXT)")
                has_table = True
            for source in sources:
                sid = source['id']; reason = None
                marker = c.execute('SELECT * FROM media_retention WHERE source_id=?', (sid,)).fetchone() if has_table else None
                if marker and marker['status'] == 'removed':
                    report.append({'source_id': sid, 'status': 'removed'}); continue
                tasks = c.execute('SELECT status,updated_at FROM tasks WHERE source_id=?', (sid,)).fetchall()
                if not tasks or any(t['status'] != 'succeeded' for t in tasks): reason = 'requires_attention_tasks'
                else:
                    try:
                        latest = max(datetime.fromisoformat(t['updated_at'].replace('Z', '+00:00')) for t in tasks)
                        if latest > cutoff: reason = 'retention_not_expired'
                    except (ValueError, TypeError): reason = 'requires_attention_timestamp'
                if reason is None:
                    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if c.execute('SELECT 1 FROM sources WHERE id<>? AND blob_relpath=? LIMIT 1', (sid,source['blob_relpath'])).fetchone(): reason = 'requires_attention_shared_original'
                    if 'web_dispatch' in tables and c.execute("SELECT 1 FROM web_dispatch d JOIN tasks t ON t.id=d.task_id WHERE t.source_id=? AND d.state<>'done' LIMIT 1", (sid,)).fetchone(): reason = 'requires_attention_dispatch'
                    if 'video_stages' in tables and c.execute("SELECT 1 FROM video_stages v JOIN tasks t ON t.id=v.task_id WHERE t.source_id=? AND v.status<>'completed' LIMIT 1", (sid,)).fetchone(): reason = 'requires_attention_remote_stage'
                    if 'video_assets' in tables and c.execute("SELECT 1 FROM video_assets v JOIN tasks t ON t.id=v.task_id WHERE t.source_id=? AND v.status NOT IN ('deleted','provider_managed') LIMIT 1", (sid,)).fetchone(): reason = 'requires_attention_remote_asset'
                if reason is None:
                    try:
                        if not source['current_version_id'] or not store.content_root: raise WorkflowError('content_unsynced')
                        verify_content(store, sid, connection=c)
                        v = c.execute('SELECT result,content_sha256 FROM versions WHERE id=? AND source_id=?', (source['current_version_id'], sid)).fetchone()
                        if not v: raise WorkflowError('content_integrity')
                        result = json.loads(v['result'])
                        canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                        if hashlib.sha256(canonical).hexdigest() != v['content_sha256']: raise WorkflowError('content_integrity')
                        state = json.loads((Path(store.content_root) / sid / 'current.json').read_bytes())
                        if state.get('current_version_id') != source['current_version_id']: raise WorkflowError('content_integrity')
                        files = state['files']; base = sid + '/versions/' + source['current_version_id'] + '/'
                        if not all(base + n in files for n in ('content.md','evidence.json','manifest.json')): raise WorkflowError('content_integrity')
                        if not result.get('evidence') or not result.get('frames'): raise WorkflowError('content_integrity')
                        if any(files.get(sid + '/frames/' + f['sha256'] + '.jpg') != f['sha256'] for f in result['frames']): raise WorkflowError('content_integrity')
                    except (WorkflowError, OSError, ValueError, KeyError, TypeError): reason = 'requires_attention_content'
                try:
                    rel = _safe_name(source['blob_relpath'])
                    if not rel.startswith('originals/'): raise WorkflowError('unsafe_path')
                    path = Path(store.data_root).joinpath(*PurePosixPath(rel).parts); _no_links(path)
                    if marker and (marker['sha256'] != source['sha256'] or marker['blob_relpath'] != rel): raise WorkflowError('retention_conflict')
                    if not path.exists() and marker and marker['status'] == 'planned' and reason is None:
                        if apply:
                            c.execute("UPDATE media_retention SET status='removed',removed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE source_id=?", (sid,))
                        report.append({'source_id': sid, 'status': 'removed' if apply else 'pending_reconciliation'}); continue
                    if not path.is_file() or _sha(path) != source['sha256']: reason = reason or 'requires_attention_original'
                except (WorkflowError, OSError): reason = reason or 'requires_attention_original'
                if reason:
                    report.append({'source_id': sid, 'status': reason}); continue
                report.append({'source_id': sid, 'status': 'eligible', 'sha256': source['sha256'], 'blob_relpath': rel})
        if apply:
            for item in report:
                if item['status'] != 'eligible': continue
                sid = item['source_id']; path = Path(store.data_root).joinpath(*PurePosixPath(item['blob_relpath']).parts)
                with store._tx() as c:
                    c.execute("INSERT INTO media_retention(source_id,sha256,blob_relpath,status) VALUES(?,?,?,'planned') ON CONFLICT(source_id) DO UPDATE SET status='planned'", (sid,item['sha256'],item['blob_relpath']))
                _no_links(path)
                if not path.is_file() or _sha(path) != item['sha256']: raise WorkflowError('retention_original_changed')
                path.unlink()
                with store._tx() as c:
                    c.execute("UPDATE media_retention SET status='removed',removed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE source_id=?", (sid,))
                item['status'] = 'removed'
    return {'dry_run': not apply, 'items': report}
