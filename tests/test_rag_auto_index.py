import pytest

from personalkb.rag_auto_index import RagAutoIndex
from personalkb.workflow_store import WorkflowError, WorkflowStore


class Index:
    config = {'enabled': True}

    def __init__(self):
        self.eligible = ['approved']
        self.indexed = []
        self.calls = []
        self.failure = None
        self.before_batch = lambda: None

    def status(self):
        return {'eligible_source_ids': self.eligible, 'indexed_source_ids': self.indexed,
                'unindexable_source_ids': []}

    def update(self, *, allow_paid, request_id, can_embed):
        assert allow_paid
        self.before_batch()
        if not can_embed():
            raise WorkflowError('rag_auto_index_paused')
        self.calls.append(request_id)
        if self.failure:
            raise WorkflowError(self.failure)
        self.indexed = list(self.eligible)


@pytest.fixture
def create_worker(tmp_path):
    index = Index()

    def create(*, enabled=True):
        store = WorkflowStore(tmp_path/'workflow.db', data_root=tmp_path, content_root=tmp_path/'knowledge')
        return RagAutoIndex(store, lambda: index, enabled=enabled, reconcile_seconds=1)

    return create, index


def test_default_on_backfills_existing_gap_and_persists_pause(create_worker):
    create, index = create_worker
    worker = create()
    assert worker.status()['enabled']
    assert worker.process_next()['state'] == 'idle'
    assert index.indexed == ['approved']
    assert worker.process_next() is None
    worker.set_enabled(False)
    worker.schedule()
    restarted = create()
    assert restarted.status()['state'] == 'paused'
    index.eligible.append('new approval')
    assert restarted.process_next() is None
    with pytest.raises(WorkflowError, match='paid_consent_required'):
        restarted.set_enabled(True)
    with pytest.raises(WorkflowError, match='paid_consent_required'):
        restarted.retry()
    restarted.retry(allow_paid=True)
    assert restarted.process_next()['state'] == 'idle'
    assert index.indexed == index.eligible
    assert restarted.status()['state'] == 'paused'


def test_budget_failure_restart_and_retry_keep_batch_identity(create_worker):
    create, index = create_worker
    worker = create()
    worker.schedule()
    index.failure = 'budget_invalid_or_exceeded'
    assert worker.process_next()['state'] == 'failed'
    restarted = create()
    assert restarted.status()['error_code'] == index.failure
    assert restarted.process_next() is None
    index.failure = None
    restarted.retry(allow_paid=True)
    assert restarted.process_next()['state'] == 'idle'
    assert len(index.calls) == 2 and index.calls[0] == index.calls[1]


def test_pause_stops_next_batch_and_new_approval_requeues(create_worker):
    create, index = create_worker
    worker = create()
    worker.schedule()
    index.before_batch = lambda: worker.set_enabled(False)
    assert worker.process_next() is None
    assert not index.calls
    assert worker.status()['state'] == 'paused'
    index.before_batch = worker.schedule
    worker.set_enabled(True, allow_paid=True)
    worker.process_next()
    assert worker.status()['state'] == 'queued'
    index.before_batch = lambda: None
    worker.process_next()
    assert worker.status()['state'] == 'idle'


def test_new_approval_expires_manual_authorization_while_paused(create_worker):
    create, index = create_worker
    worker = create(enabled=False)
    worker.retry(allow_paid=True)
    index.before_batch = worker.schedule
    assert worker.process_next() is None
    assert worker.status()['state'] == 'paused'
    assert index.calls == []
    index.before_batch = lambda: None
    assert create().process_next() is None
    worker.retry(allow_paid=True)
    assert worker.process_next()['state'] == 'idle'
    assert worker.status()['state'] == 'paused'
    assert len(index.calls) == 1


def test_shutdown_stops_new_batches_and_keeps_the_update_for_restart(create_worker, monkeypatch):
    from threading import Event

    create, index = create_worker
    worker = create()
    worker.schedule()
    stop = Event()
    update = index.update

    def update_until_shutdown(*, allow_paid, request_id, can_embed):
        assert can_embed()
        index.calls.append(request_id)
        stop.set()
        if not can_embed():
            raise WorkflowError('rag_auto_index_paused')
        pytest.fail('shutdown must stop the next batch')

    monkeypatch.setattr(index, 'update', update_until_shutdown)
    assert worker.process_next(stop_requested=stop.is_set) is None
    assert worker.status()['state'] == 'queued'
    assert worker.process_next(stop_requested=stop.is_set) is None
    assert len(index.calls) == 1

    monkeypatch.setattr(index, 'update', update)
    assert create().process_next()['state'] == 'idle'
    assert len(index.calls) == 2 and index.calls[0] == index.calls[1]
