"""Explicit private OSS backup transfer; no remote deletion or credential logging."""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path
from .workflow_store import WorkflowError


def _bucket(config):
    if config.get('storage_mode') != 'oss': raise WorkflowError('oss_not_selected')
    s = config.get('oss', {}); region = s.get('region', ''); prefix = s.get('prefix', ''); name = s.get('bucket', '')
    if (s.get('private') is not True or not re.fullmatch(r'cn-[a-z0-9-]+', region) or s.get('endpoint') != f'https://oss-{region}.aliyuncs.com'
        or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', name) or not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/', prefix)):
        raise WorkflowError('invalid_oss_config')
    key, secret = s.get('access_key_id_env'), s.get('access_key_secret_env')
    from tools.demo_setup import dotenv
    from .workflow import ROOT
    env_path = ROOT / config.get('env_file', '.env')
    values = dotenv(env_path) if env_path.exists() else {}
    values.update(os.environ)
    if not all(isinstance(x, str) and re.fullmatch(r'[A-Z_][A-Z0-9_]*', x) and values.get(x) for x in (key, secret)): raise WorkflowError('missing_oss_credentials')
    import oss2
    from oss2.credentials import StaticCredentialsProvider
    bucket = oss2.Bucket(oss2.ProviderAuthV4(StaticCredentialsProvider(values[key], values[secret])), s['endpoint'], name, region=region)
    if bucket.get_bucket_acl().acl != 'private': raise WorkflowError('oss_bucket_not_private')
    return bucket, prefix, oss2


def _private(bucket, key):
    if bucket.get_object_acl(key).acl != 'private': raise WorkflowError('oss_object_not_private')


def push(config, snapshot):
    from .maintenance import verify, _guard_store
    from .runtime_guard import maintenance_guard
    try:
        bucket, prefix, oss2 = _bucket(config)
        root = Path(config['backup_root'])
        def upload(key, path, digest):
            try: bucket.put_object_from_file(key, str(path), headers={'x-oss-object-acl':'private', 'x-oss-forbid-overwrite':'true'})
            except oss2.exceptions.ObjectAlreadyExists: pass
            _private(bucket, key)
            h = hashlib.sha256(); result = bucket.get_object(key)
            for block in iter(lambda: result.read(1024 * 1024), b''): h.update(block)
            if h.hexdigest() != digest: raise WorkflowError('remote_integrity')
        with maintenance_guard(_guard_store(config)):
            manifest = verify(config, snapshot)
            for sha in sorted({x['sha256'] for x in manifest['files']}): upload(prefix + 'objects/' + sha, root / 'objects' / sha, sha)
            upload(prefix + 'snapshots/' + snapshot + '.json', root / 'snapshots' / (snapshot + '.json'), snapshot)
        return {'snapshot': snapshot, 'uploaded': True}
    except WorkflowError: raise
    except Exception: raise WorkflowError('oss_upload_failed') from None


def pull(config, snapshot):
    from .maintenance import _guard_store, _validate_manifest, _no_links, _sha, _space
    from .runtime_guard import maintenance_guard
    if not isinstance(snapshot, str) or not re.fullmatch(r'[0-9a-f]{64}', snapshot): raise WorkflowError('invalid_snapshot')
    try:
        bucket, prefix, _ = _bucket(config)
        root = Path(config['backup_root']); _no_links(root); root.mkdir(parents=True, exist_ok=True)
        with maintenance_guard(_guard_store(config)):
            objects = root / 'objects'; manifests = root / 'snapshots'
            for p in (objects, manifests): _no_links(p); p.mkdir(exist_ok=True)
            dest = manifests / (snapshot + '.json'); _no_links(dest)
            if dest.exists(): raise WorkflowError('snapshot_exists')
            key = prefix + 'snapshots/' + snapshot + '.json'; _private(bucket, key)
            stream = bucket.get_object(key); limit = config.get('max_manifest_bytes', 4194304)
            raw = stream.read(limit + 1)
            if len(raw) > limit or hashlib.sha256(raw).hexdigest() != snapshot: raise WorkflowError('remote_integrity')
            manifest = _validate_manifest(json.loads(raw)); sizes = {}
            for item in manifest['files']:
                if item['sha256'] in sizes and sizes[item['sha256']] != item['size']: raise WorkflowError('invalid_manifest')
                sizes[item['sha256']] = item['size']
            with tempfile.TemporaryDirectory(dir=root, prefix='.pull-') as stage:
                stage = Path(stage)
                for sha, size in sizes.items():
                    dest_obj = objects / sha; _no_links(dest_obj)
                    if dest_obj.exists():
                        if not dest_obj.is_file() or dest_obj.stat().st_size != size or _sha(dest_obj) != sha: raise WorkflowError('corrupt_object')
                        continue
                    _space(root, size, config['min_free_bytes']); key = prefix + 'objects/' + sha; _private(bucket, key)
                    stream = bucket.get_object(key); part = stage / sha; h = hashlib.sha256(); total = 0
                    with part.open('xb') as f:
                        while True:
                            block = stream.read(min(1024 * 1024, size - total + 1))
                            if not block: break
                            total += len(block)
                            if total > size: raise WorkflowError('remote_integrity')
                            h.update(block); f.write(block)
                    if total != size or h.hexdigest() != sha: raise WorkflowError('remote_integrity')
                    os.replace(part, dest_obj)
                for item in manifest['files']:
                    if item['path'] in ('workflow/workflow.sqlite3', 'budget.sqlite'):
                        with closing(sqlite3.connect('file:' + (objects / item['sha256']).as_posix() + '?mode=ro', uri=True)) as db:
                            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise WorkflowError('invalid_database')
                _space(root, len(raw), config['min_free_bytes'])
                part = stage / 'manifest'; part.write_bytes(raw)
                os.replace(part, dest)
        return {'snapshot': snapshot, 'downloaded': True}
    except WorkflowError: raise
    except Exception: raise WorkflowError('oss_pull_failed') from None
