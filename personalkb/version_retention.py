import json
import re

from .content_storage import safe, verify
from .workflow_store import WorkflowError, _json


def _frame_hashes(hashes):
    hashes = set(hashes)
    if any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) for sha in hashes):
        raise WorkflowError('frame_integrity')
    return hashes


def _candidates(db, source, policy, quality_target):
    history = db.execute('''SELECT v.id, r.decision, r.score FROM versions v
        LEFT JOIN reviews r ON r.seq = (SELECT MAX(seq) FROM reviews WHERE version_id=v.id)
        WHERE v.source_id=? AND v.id<>? AND v.content_pruned_at IS NULL
        ORDER BY v.created_at DESC, v.rowid DESC''', (source['id'], source['current_version_id'])).fetchall()
    approved = [v for v in history if v['decision'] == 'approve' and v['score'] is not None and v['score'] >= quality_target]
    if not approved:
        return history[policy['approved_history'] + policy['other_history']:]
    approved_ids = {v['id'] for v in approved}
    others = [v for v in history if v['id'] not in approved_ids]
    return approved[policy['approved_history']:] + others[policy['other_history']:]


def prune(store, policy, *, retry_only=False):
    """Prune only after a verified cold backup, with the caller holding the maintenance guard."""
    count = 0
    skipped = []
    with store._tx() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS version_retention_cleanup (
            version_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, frames TEXT NOT NULL)''')
        pending = [row[0] for row in db.execute('SELECT DISTINCT source_id FROM version_retention_cleanup')]
    cleaned = sum(_finish_cleanup(store, sid) for sid in pending)
    if retry_only:
        return {'pruned': count, 'cleaned': cleaned, 'skipped': skipped}
    with store._tx() as db:
        source_ids = [row[0] for row in db.execute('''SELECT id FROM sources
            WHERE deleted=0 AND current_version_id IS NOT NULL''')]
    for sid in source_ids:
        with store._tx() as db:
            source = db.execute('SELECT id,current_version_id FROM sources WHERE id=? AND deleted=0', (sid,)).fetchone()
            if source is None or source['current_version_id'] is None:
                continue
            candidates = _candidates(db, source, policy, store.quality_target)
            if not candidates:
                continue
            if store.content_root:
                try:
                    verify(store, sid, connection=db)
                except WorkflowError as error:
                    skipped.append({'source_id': sid, 'reason': error.code})
                    continue
            db.execute('PRAGMA secure_delete=ON')
            for version in candidates:
                result = json.loads(db.execute('SELECT result FROM versions WHERE id=?', (version['id'],)).fetchone()[0])
                frames = _frame_hashes(frame['sha256'] for frame in result.get('frames', []))
                db.execute('INSERT INTO version_retention_cleanup VALUES(?,?,?)',
                           (version['id'], sid, _json(sorted(frames))))
                db.execute("""UPDATE versions SET result=?, content_pruned_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE id=?""", (_json({'title': result['title']}), version['id']))
            db.execute('UPDATE content_sync SET generation=generation+1 WHERE source_id=?', (sid,))
            count += len(candidates)
        cleaned += _finish_cleanup(store, sid)
    return {'pruned': count, 'cleaned': cleaned, 'skipped': skipped}


def _finish_cleanup(store, sid):
    if store.content_root:
        store.sync_source(sid)
    with store._tx() as db:
        rows = db.execute('SELECT * FROM version_retention_cleanup WHERE source_id=?', (sid,)).fetchall()
        if store.content_root:
            _remove_files(store.content_root, db, sid, rows)
        db.execute('DELETE FROM version_retention_cleanup WHERE source_id=?', (sid,))
    return len(rows)


def _remove_files(root, db, sid, rows):
    retained = set()
    for row in db.execute('SELECT result FROM versions WHERE source_id=? AND content_pruned_at IS NULL', (sid,)):
        retained.update(_frame_hashes(frame['sha256'] for frame in json.loads(row['result']).get('frames', [])))
    removed = set()
    for row in rows:
        vid = row['version_id']
        if not all(re.fullmatch(r'[0-9a-f]{32}', ident) for ident in (sid, vid)):
            raise WorkflowError('content_path_invalid')
        for name in ('content.md', 'evidence.json', 'manifest.json'):
            safe(root, sid, 'versions', vid, name).unlink(missing_ok=True)
        directory = safe(root, sid, 'versions', vid)
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
        removed.update(_frame_hashes(json.loads(row['frames'])))
    for sha in sorted(removed - retained):
        safe(root, sid, 'frames', sha + '.jpg').unlink(missing_ok=True)
