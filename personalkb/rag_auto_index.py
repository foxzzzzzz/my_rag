"""Persisted reconciliation of approved evidence and the active index."""
import time
import uuid

from .runtime_guard import runtime_guard
from .workflow_store import WorkflowError


class RagAutoIndex:
    def __init__(self, store, index, *, enabled, reconcile_seconds):
        self.store = store
        self.index = index
        self.reconcile_seconds = reconcile_seconds
        self.next_scan = 0
        with store._tx() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rag_index_update (
                id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'idle', manual INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0, request_id TEXT, error_code TEXT
            )""")
            db.execute("INSERT OR IGNORE INTO rag_index_update(id, enabled) VALUES(1, ?)", (int(enabled),))

    def _job(self):
        with self.store._tx() as db:
            return dict(db.execute("SELECT * FROM rag_index_update WHERE id=1").fetchone())

    def status(self):
        job = self._job()
        state = job['state']
        if not job['enabled'] and not job['manual'] and state != 'failed':
            state = 'paused'
        return {'enabled': bool(job['enabled']), 'state': state, 'error_code': job['error_code']}

    def schedule(self):
        with self.store._tx() as db:
            # An explicit one-off update does not authorize later approvals.
            db.execute("""UPDATE rag_index_update SET revision=revision+1, manual=0,
                state=CASE WHEN state='idle' THEN 'queued' ELSE state END WHERE id=1""")

    def set_enabled(self, enabled, *, allow_paid=False):
        if type(enabled) is not bool:
            raise WorkflowError('invalid_request')
        if enabled and allow_paid is not True:
            raise WorkflowError('paid_consent_required')
        with self.store._tx() as db:
            db.execute("""UPDATE rag_index_update SET enabled=?,
                revision=revision+CASE WHEN enabled=0 AND ?=1 THEN 1 ELSE 0 END,
                state=CASE WHEN enabled=0 AND ?=1 AND state!='running' THEN 'queued' ELSE state END,
                error_code=CASE WHEN enabled=0 AND ?=1 AND state!='running' THEN NULL ELSE error_code END
                WHERE id=1""", (enabled, enabled, enabled, enabled))
        return self.status()

    def retry(self, *, allow_paid=False):
        if allow_paid is not True:
            raise WorkflowError('paid_consent_required')
        with self.store._tx() as db:
            db.execute("""UPDATE rag_index_update SET manual=1, revision=revision+1,
                state=CASE WHEN state='running' THEN state ELSE 'queued' END,
                error_code=NULL WHERE id=1""")
        return self.status()

    def _allowed(self):
        job = self._job()
        return bool(job['enabled'] or job['manual'])

    def process_next(self, *, stop_requested=lambda: False):
        if stop_requested() or not self.store.content_root:
            return None
        job = self._job()
        if not (job['enabled'] or job['manual']) or job['state']=='failed':
            return None
        if job['state']=='idle' and time.monotonic()<self.next_scan:
            return None
        try:
            with runtime_guard(self.store.data_root, 'rag-index-worker'):
                return self._process(stop_requested)
        except WorkflowError as exc:
            if exc.code in ('maintenance_busy', 'worker_busy'):
                return None
            raise

    def _process(self, stop_requested):
        job = self._job()
        if not (job['enabled'] or job['manual']) or job['state']=='failed':
            return None
        if job['state']=='idle':
            self.next_scan = time.monotonic()+self.reconcile_seconds
        request_id = job['request_id']
        try:
            index = self.index()
            if not index.config['enabled']:
                return None
            if job['state']=='idle':
                coverage = index.status()
                missing = set(coverage['eligible_source_ids']) - set(coverage['indexed_source_ids']) - set(coverage['unindexable_source_ids'])
                if not missing:
                    return None
            request_id = request_id or 'auto-index-' + uuid.uuid4().hex
            with self.store._tx() as db:
                updated = db.execute("""UPDATE rag_index_update SET state='running', request_id=?, error_code=NULL
                    WHERE id=1 AND revision=? AND (enabled=1 OR manual=1)""", (request_id, job['revision']))
                if updated.rowcount!=1:
                    return None
            index.update(allow_paid=True, request_id=request_id,
                         can_embed=lambda: not stop_requested() and self._allowed())
        except Exception as exc:
            code = exc.code if isinstance(exc, WorkflowError) else 'rag_index_update_failed'
            if code in ('worker_busy', 'rag_invalidated', 'rag_auto_index_paused'):
                if request_id:
                    with self.store._tx() as db:
                        db.execute("UPDATE rag_index_update SET state='queued' WHERE id=1 AND request_id=?", (request_id,))
                return None
            with self.store._tx() as db:
                db.execute("""UPDATE rag_index_update SET state='failed', manual=0, error_code=?
                    WHERE id=1 AND revision=?""", (code, job['revision']))
            return {'state': 'failed', 'error_code': code}

        with self.store._tx() as db:
            db.execute("""UPDATE rag_index_update SET request_id=NULL, error_code=NULL,
                state=CASE WHEN revision=? THEN 'idle' ELSE 'queued' END,
                manual=CASE WHEN revision=? THEN 0 ELSE manual END
                WHERE id=1 AND request_id=?""", (job['revision'], job['revision'], request_id))
        self.next_scan = time.monotonic() + self.reconcile_seconds
        return {'state': 'idle'}
