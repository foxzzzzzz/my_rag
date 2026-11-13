from datetime import datetime
from types import SimpleNamespace

import pytest

from personalkb.douyin_daily_sync import FavoritesSync, load_config
from personalkb.douyin_import import DouyinImporter
from personalkb.web_dispatch import WebDispatcher
from personalkb.workflow import load_config as load_workflow
from personalkb.workflow_store import WorkflowError

PAID = dict(rights_confirmed=True, allow_paid=True, video_budget_cny='4.05')

def page(account, ids, *, status='ok', exhausted=False):
    return dict(status=status, account_id=account, account_label=account, exhausted=exhausted,
                videos=[dict(id=str(i), title=f'video {i}') for i in ids])


@pytest.fixture
def sync_env(tmp_path):
    wc = load_workflow()
    wc['data_dir'] = str(tmp_path)
    downloader = DouyinImporter(wc, {}, {})
    dispatcher = WebDispatcher(SimpleNamespace(store=downloader.store,
                                               webcfg={'live_video_enabled': True, 'dispatch_recovery_seconds': 60}))
    cfg = load_config('config/douyin-daily-sync.json')
    cfg.update(enabled=True, schedule_enabled=True, auto_download=True)
    return FavoritesSync(downloader.store, cfg), downloader, dispatcher


def scan(env, result, *, cookie='cookie', day=13):
    sync, download, dispatch = env
    sync.request_scan()
    sync.tick(cookie, lambda *_: result, download, dispatch, now=datetime(2026, 11, day, 6))


def rows(env, table):
    with env[0].store._tx() as db:
        return [dict(r) for r in db.execute(f'SELECT * FROM {table}')]


def baseline(env, ids=range(100, 0, -1)):
    data = page('account-a', ids, exhausted=True)
    scan(env, data)
    env[0].confirm('account-a', 'cookie')
    scan(env, data)


def test_confirm_baseline_and_manual_all_select(sync_env):
    sync, _, _ = sync_env
    data = page('account-a', range(100, 0, -1))
    scan(sync_env, data)
    assert sync.status('cookie')['pending_account']['id'] == 'account-a'
    with pytest.raises(WorkflowError, match='favorites_account_conflict'):
        sync.confirm('account-a', 'changed')
    sync.confirm('account-a', 'cookie')
    scan(sync_env, data)
    items = sync.status('cookie')['items']
    assert [x['title'] for x in items] == [f'video {i}' for i in range(100, 0, -1)]
    assert all(x['selectable'] for x in items)
    assert rows(sync_env, 'douyin_jobs') == rows(sync_env, 'favorites_conversion') == []
    selected = [x['work_id'] for x in items]
    with pytest.raises(WorkflowError, match='rights_required'):
        sync.select('account-a', selected, 'cookie', rights_confirmed=False)
    with pytest.raises(WorkflowError, match='paid_consent_required'):
        sync.select('account-a', selected, 'cookie', rights_confirmed=True)
    with pytest.raises(WorkflowError, match='favorites_price_changed'):
        sync.select('account-a', selected, 'cookie', **(PAID | {'video_budget_cny': '3.99'}))
    assert rows(sync_env, 'favorites_queue') == rows(sync_env, 'favorites_manual_consent') == []
    assert sync.select('account-a', selected, 'cookie', **PAID) == {'queued': 100}
    assert sync.select('account-a', selected, 'cookie', **PAID) == {'queued': 0}
    assert not any(r['automatic'] for r in rows(sync_env, 'favorites_queue'))
    assert len(rows(sync_env, 'favorites_manual_consent')) == 100


def test_incomplete_then_same_account_and_switch_back(sync_env):
    sync, _, _ = sync_env
    scan(sync_env, page('account-a', [3, 2]))
    sync.confirm('account-a', 'cookie')
    scan(sync_env, page('account-a', [3, 2], status='pagination_incomplete'))
    assert sync.status('cookie')['state'] == 'paused'
    assert rows(sync_env, 'favorites_queue') == []
    scan(sync_env, page('account-a', [3, 2, 1], exhausted=True))
    assert len(sync.status('cookie')['items']) == 3
    assert sync.status('new-cookie')['state'] == 'paused'
    scan(sync_env, page('account-a', [4, 3, 2], exhausted=True), cookie='new-cookie')
    assert [r['work_id'] for r in rows(sync_env, 'favorites_queue')] == ['4']
    scan(sync_env, page('account-b', [4, 9], exhausted=True), cookie='cookie-b')
    sync.confirm('account-b', 'cookie-b')
    scan(sync_env, page('account-b', [4, 9], exhausted=True), cookie='cookie-b')
    assert sync.select('account-b', ['4'], 'cookie-b', **PAID) == {'queued': 0}
    scan(sync_env, page('account-a', [5, 4, 3], exhausted=True), cookie='new-cookie')
    sync.confirm('account-a', 'new-cookie')
    scan(sync_env, page('account-a', [5, 4, 3], exhausted=True), cookie='new-cookie')
    assert [r['work_id'] for r in rows(sync_env, 'favorites_queue')] == ['4', '5']


def test_daily_quota_and_no_tail_false_positive(sync_env, monkeypatch):
    sync, downloader, dispatcher = sync_env
    baseline(sync_env)
    scan(sync_env, page('account-a', list(range(105, 0, -1)) + [999]))
    monkeypatch.setattr(downloader, 'status', lambda: {'enabled': True})
    def download(*, job_id):
        with sync.store._tx() as db:
            db.execute("UPDATE douyin_jobs SET status='succeeded' WHERE id=?", (job_id,))
        return {'id': job_id, 'error_code': None}
    monkeypatch.setattr(downloader, 'process_next', download)
    for day, total in ((13, 3), (14, 5)):
        for _ in range(7):
            sync.tick('cookie', lambda *_: page('account-a', range(105, 0, -1)),
                      downloader, dispatcher, now=datetime(2026, 11, day, 6))
        assert len(rows(sync_env, 'douyin_jobs')) == total
    assert [r['work_id'] for r in rows(sync_env, 'favorites_queue')] == ['105', '104', '103', '102', '101']
    scan(sync_env, page('account-a', [], status='login_required'), day=14)
    assert sync.status('cookie')['state'] == 'paused'


def test_paid_backfill_and_daily_sync_have_separate_slots(sync_env, monkeypatch):
    sync, downloader, dispatcher = sync_env
    baseline(sync_env, range(11, 0, -1))
    scan(sync_env, page('account-a', range(15, 0, -1), exhausted=True))
    sync.config.update(conversion_enabled=True, daily_budget_cny='12', video_budget_cny='4')
    assert sync.select('account-a', [str(i) for i in range(10, 0, -1)], 'cookie', **PAID) == {'queued': 10}
    assert rows(sync_env, 'douyin_jobs') == []
    # The saved agreement applies even after the displayed quote changes.
    sync.config['manual_video_budget_cny'] = '4.25'
    monkeypatch.setattr(downloader, 'status', lambda: {'enabled': True})
    def download(*, job_id):
        with sync.store._tx() as db:
            work = db.execute('SELECT work_id FROM douyin_jobs WHERE id=?', (job_id,)).fetchone()[0]
        source = sync.store.import_source('video', work.zfill(64), f'douyin-{work}.mp4', work)['source']
        with sync.store._tx() as db:
            db.execute("UPDATE douyin_jobs SET status='succeeded',source_id=? WHERE id=?", (source['id'], job_id))
        return {'id': job_id, 'error_code': None}
    monkeypatch.setattr(downloader, 'process_next', download)
    for _ in range(30):
        sync.tick('cookie', lambda *_: page('account-a', range(15, 0, -1), exhausted=True),
                  downloader, dispatcher, now=datetime(2026, 11, 13, 6))
    queue = {r['work_id']: r for r in rows(sync_env, 'favorites_queue')}
    assert [queue[str(i)]['status'] for i in range(10, 0, -1)] == ['conversion_queued'] * 10
    assert len(rows(sync_env, 'favorites_download_slots')) == 3
    assert len(rows(sync_env, 'favorites_conversion_slots')) == 3
    assert queue['12']['status'] == 'queued'
    assert [r['amount'] for r in rows(sync_env, 'favorites_conversion')].count('4.05') == 10
    assert len(rows(sync_env, 'douyin_jobs')) == 13
    assert sync.status('cookie')['items'][1]['status'] == 'conversion_queued'
    with sync.store._tx() as db:
        reservation = db.execute('SELECT * FROM favorites_conversion WHERE task_id=?', (queue['10']['task_id'],)).fetchone()
        sync.config.update(conversion_enabled=False, daily_budget_cny='0')
        assert not sync.can_claim_conversion(db, reservation, 'changed')
        assert sync.can_claim_conversion(db, reservation, 'cookie')

    with sync.store._tx() as db:
        db.execute("INSERT INTO favorites_queue(account_id,work_id,automatic) VALUES ('account-a','11',0)")
    for _ in range(12):
        sync.tick('cookie', lambda *_: page('account-a', range(15, 0, -1), exhausted=True),
                  downloader, dispatcher, now=datetime(2026, 11, 14, 6))
    legacy = next(r for r in rows(sync_env, 'favorites_queue') if r['work_id'] == '11')
    assert legacy['status'] == 'downloaded' and legacy['task_id'] is None


def test_web_routes_and_review_gated_index(sync_env):
    from fastapi.testclient import TestClient

    from personalkb.web_app import create_app, load_web_config
    from personalkb.web_service import WebService

    sync, downloader, _ = sync_env

    class Service(WebService):
        favorites_sync = sync
        douyin = downloader

        def favorites_cookie(self):
            return 'cookie'

    web = load_web_config()
    web.update(dispatch_enabled=False, live_video_enabled=True)
    web['trusted_hosts'].append('testserver')
    service = Service(downloader.wc, {}, web)
    downloader.status = lambda: dict(enabled=True, cookie_configured=True, resolver_configured=True)
    data = page('account-a', [2, 1], exhausted=True)
    with TestClient(create_app(downloader.wc, {}, web, service)) as client:
        assert client.get('/api/douyin/favorites/sync').status_code == 401
        headers = {'x-csrf-token': client.get('/api/session').json()['csrf_token']}
        root = '/api/douyin/favorites'
        assert client.post(root + '/scan', json={}, headers=headers).json()['queued']
        sync.tick('cookie', lambda *_: data, downloader, service.dispatcher, now=datetime(2026, 11, 13, 6))
        assert client.get(root + '/sync').json()['state'] == 'confirm_account'
        assert client.post(root + '/confirm', json={'account_id': 'account-a'}, headers=headers).status_code == 200
        sync.tick('cookie', lambda *_: data, downloader, service.dispatcher, now=datetime(2026, 11, 13, 6))
        status = client.get(root + '/sync').json()
        assert status['items'][0]['title'] == 'video 2'
        assert status['manual_conversion_available'] and status['manual_video_budget_cny'] == '4.05'
        payload = dict(account_id='account-a', work_ids=['2'], **PAID)
        assert client.post(root + '/import', json=payload | {'allow_paid': False}, headers=headers).json() == {'error': 'paid_consent_required'}
        assert client.post(root + '/import', json=payload, headers=headers).json() == {'queued': 1}

    record = {}

    def download(*, job_id):
        record.update(sync.store.import_source('video', '1'*64, 'douyin-2.mp4', 'fixture.mp4'))
        with sync.store._tx() as db:
            db.execute("UPDATE douyin_jobs SET status='succeeded',source_id=? WHERE id=?", (record['source']['id'], job_id))
        return {'id': job_id, 'error_code': None}

    def run_video(*_, task_id, **kwargs):
        task = sync.store.claim_specific(task_id, 'fixture')
        fields = dict(title='Fixture', body='Body', summary='Summary', notes='Notes', scheme_id='fixture',
                      scheme_version='1', output_kind='machine_initial', provenance='provider',
                      transcript='Transcript', visual='Visual', evidence=[dict(type='audio', text='Transcript', start_seconds=0, end_seconds=1)])
        sync.store.finish(task_id, task['lease_token'], fields)

    downloader.process_next = download
    service.video_runner = run_video
    for _ in range(2):
        sync.tick('cookie', lambda *_: data, downloader, service.dispatcher, now=datetime(2026, 11, 13, 6))
    service.dispatcher.process_next()
    assert sync.store.get_task(record['task']['id'])['status'] == 'succeeded'
    source = record['source']['id']
    result = sync.store.get_version(sync.store.get_source(source)['current_version_id'])
    assert service.detail(source)['source']['review_status'] == 'pending'
    assert service.rag_auto_index.status()['state'] == 'idle'
    assert service.review(source, dict(version_id=result['id'], content_sha256=result['content_sha256'],
                                       score=100, decision='approve', reviewer='fixture'))['eligible']
    assert service.rag_auto_index.status()['state'] == 'queued'


def test_conversion_waits_for_verified_cookie_and_current_day(sync_env, monkeypatch):
    import personalkb.douyin_daily_sync as module

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz):
            return cls(2026, 11, 13, 6, tzinfo=tz)

    monkeypatch.setattr(module, 'datetime', FixedDateTime)
    sync, _, dispatcher = sync_env
    sync.config.update(conversion_enabled=True, daily_budget_cny='4', video_budget_cny='4')
    baseline(sync_env, [1])
    task = sync.store.import_source('video', '2'*64, 'clip.mp4', 'clip.mp4')['task']['id']
    with sync.store._tx() as db:
        db.execute('INSERT INTO favorites_conversion VALUES (?,?,?,?)', (task, 'account-a', '2026-11-13', '4'))
        db.execute('INSERT INTO favorites_conversion_slots VALUES (?,?,?)', (task, '2026-11-13', '4'))
        db.execute("INSERT INTO web_dispatch(task_id,mode,state,requested) VALUES (?,'run','pending',0)", (task,))
    dispatcher.service.favorites_sync = sync
    dispatcher.service.favorites_cookie = lambda: 'changed'
    assert dispatcher._claim() is None
    dispatcher.service.favorites_cookie = lambda: 'cookie'
    sync.request_scan()
    assert dispatcher._claim() is None
    scan(sync_env, page('account-a', [], status='collection_http_error'))
    assert dispatcher._claim() is None
    scan(sync_env, page('account-a', [1], exhausted=True))
    assert dispatcher._claim()['task_id'] == task
