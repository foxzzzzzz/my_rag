"""Purge expired sources while holding the offline maintenance lock."""
import re
import json
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .runtime_guard import maintenance_guard
from .workflow import make_store
from .workflow_store import WorkflowError


def _purge_indexes(root, sid, maintenance_config):
    from .maintenance import _no_links, _path, _safe_name
    from .rag_index import GENERATION_DB, STAGING_FILE, active_manifest
    from .workflow import ROOT
    rag_path = maintenance_config.get('rag_config')
    if rag_path is None:
        web = Path(maintenance_config.get('workflow_config', ROOT / 'config/workflow.json')).parent / 'web.json'
        if web.is_file():
            rag_path = json.loads(web.read_text(encoding='utf-8-sig')).get('rag_config')
    rag_config = _path(rag_path or 'config/rag.json')
    _no_links(rag_config)
    config = json.loads(rag_config.read_text(encoding='utf-8-sig'))
    index = root.joinpath(*Path(_safe_name(config['index_dir'])).parts)
    _no_links(index)
    if not index.exists():
        return
    manifest = active_manifest(index)
    active = manifest['file'] if manifest else None
    if active and not (index / active).is_file():
        raise WorkflowError('rag_index_invalid')
    for path in index.iterdir():
        if STAGING_FILE.fullmatch(path.name):
            # Maintenance owns all writer locks; staging files are interrupted builds.
            _no_links(path)
            path.unlink()
            continue
        if not GENERATION_DB.fullmatch(path.name):
            continue
        _no_links(path)
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True)) as db:
            db.execute('PRAGMA secure_delete=ON')
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'chunks' not in names:
                if path.name == active:
                    raise WorkflowError('rag_index_invalid')
                continue
            ids = [row[0] for row in db.execute('SELECT id FROM chunks WHERE source_id=?', (sid,))]
            if not ids:
                continue
            if 'vec' in names:
                import sqlite_vec
                db.enable_load_extension(True)
                try: sqlite_vec.load(db)
                finally: db.enable_load_extension(False)
            with db:
                for chunk_id in ids:
                    if 'fts' in names: db.execute('DELETE FROM fts WHERE rowid=?', (chunk_id,))
                    if 'vec' in names: db.execute('DELETE FROM vec WHERE id=?', (chunk_id,))
                    db.execute('DELETE FROM chunks WHERE id=?', (chunk_id,))


def purge(config, apply=False):
    from .maintenance import _guard_store, _no_links, _safe_name, _sha
    workflow = config['_workflow']
    root = Path(workflow['data_dir'])
    result = []
    with maintenance_guard(_guard_store(config)):
        store = make_store(workflow)
        with store._tx() as db:
            rows = [dict(r) for r in db.execute('''SELECT s.*, t.deleted_at, t.purge_started
                FROM sources s JOIN source_trash t ON t.source_id=s.id
                WHERE s.deleted=1 AND (t.purge_started=1 OR t.deleted_at<=?)''', (time.time()-store.trash_retention_seconds,))]
        for source in rows:
            sid = source['id']
            if not re.fullmatch(r'[0-9a-f]{32}', sid):
                raise WorkflowError('unsafe_path')
            with store._tx() as db:
                tasks = [r[0] for r in db.execute('SELECT id FROM tasks WHERE source_id=?', (sid,))]
                if any(not re.fullmatch(r'[0-9a-f]{32}', tid) for tid in tasks):
                    raise WorkflowError('unsafe_path')
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'video_assets' in tables and any(db.execute("SELECT 1 FROM video_assets WHERE task_id=? AND status NOT IN ('deleted','provider_managed')", (tid,)).fetchone() for tid in tasks):
                    result.append({'source_id':sid, 'status':'pending_remote_assets'})
                    continue
                shared = db.execute('SELECT 1 FROM sources WHERE id<>? AND blob_relpath=?', (sid, source['blob_relpath'])).fetchone()
                original = root.joinpath(*Path(_safe_name(source['blob_relpath'])).parts)
                if not source['blob_relpath'].startswith('originals/'):
                    raise WorkflowError('unsafe_path')
                _no_links(original)
                if not shared and original.exists() and (not original.is_file() or _sha(original) != source['sha256']):
                    raise WorkflowError('source_integrity')
                paths = [root / workflow['content']['directory'] / sid, *(root / 'video-work' / tid for tid in tasks)]
                for path in paths:
                    _no_links(path)
                    if path.exists():
                        if not path.is_dir(): raise WorkflowError('unsafe_path')
                        for base, dirs, files in __import__('os').walk(path, followlinks=False):
                            for name in dirs + files: _no_links(Path(base) / name)
                if not apply:
                    result.append({'source_id':sid, 'status':'eligible'})
                    continue
                db.execute('UPDATE source_trash SET purge_started=1 WHERE source_id=?', (sid,))
            _purge_indexes(root, sid, config)
            _no_links(original)
            if not shared and original.exists():
                if not original.is_file() or _sha(original) != source['sha256']:
                    raise WorkflowError('source_integrity')
                original.unlink()
            for path in paths:
                _no_links(path)
                if path.exists():
                    if not path.is_dir(): raise WorkflowError('unsafe_path')
                    for base, dirs, files in __import__('os').walk(path, followlinks=False):
                        for name in dirs + files: _no_links(Path(base) / name)
                    shutil.rmtree(path)
            with store._tx() as db:
                db.execute('PRAGMA secure_delete=ON')
                for table in ('web_task_archive','web_dispatch','video_stages','video_assets','video_runs','html_runs','video_reprocess'):
                    if table in tables:
                        for tid in tasks: db.execute(f'DELETE FROM {table} WHERE task_id=?', (tid,))
                for table in ('reviews','versions','content_sync','source_labels','source_metadata','classification_suggestions','obsidian_previews','douyin_cache','media_retention','source_display_titles'):
                    if table in tables: db.execute(f'DELETE FROM {table} WHERE source_id=?', (sid,))
                if 'douyin_jobs' in tables: db.execute('UPDATE douyin_jobs SET source_id=NULL WHERE source_id=?', (sid,))
                db.execute('DELETE FROM tasks WHERE source_id=?', (sid,))
                db.execute('DELETE FROM source_trash WHERE source_id=?', (sid,))
                db.execute('DELETE FROM sources WHERE id=? AND deleted=1', (sid,))
            result.append({'source_id':sid, 'status':'removed'})
    return {'dry_run':not apply, 'items':result}
