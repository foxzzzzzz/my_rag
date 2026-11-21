from datetime import datetime, timedelta
from decimal import Decimal
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from personalkb import workflow
from personalkb.douyin_album import DouyinAlbum
from personalkb.douyin_album_processing import run_album
from personalkb.douyin_daily_sync import FavoritesSync, load_config
from personalkb.douyin_import import DouyinImporter
from personalkb.video_pipeline import load_pipeline_config
from personalkb.video_services import ProviderError
from personalkb.web_app import create_app, load_web_config
from personalkb.web_service import WebService
from personalkb.workflow_store import WorkflowError


COOKIE = 'test-cookie'
AUTHORIZED_WORK = '7707297968927829478'
EXTENDED_WORK = '7683044048454544229'
LARGE_WORK = '7700865500990255594'


def work(number, kind='video', image_count=2):
    item = {'id': str(number), 'title': f'Title {number}', 'kind': kind}
    if kind == 'image':
        item.update(description='测试作品文案', image_urls=[
            f'https://p3.douyinpic.com/{number}-page-{page}' for page in range(1, image_count + 1)
        ])
    return item


@pytest.fixture
def system(tmp_path, monkeypatch):
    wc = workflow.load_config()
    wc.update(data_dir=str(tmp_path / 'workflow'), min_free_bytes=0)
    pc = load_pipeline_config()
    pc['budget'] = {**pc['budget'], 'ledger': str(tmp_path / 'ledger.sqlite')}
    web = load_web_config()
    web['trusted_hosts'].append('testserver')
    web['live_video_enabled'] = True
    service = WebService(wc, pc, web)
    downloader = DouyinImporter(wc, {}, {})
    downloads = []

    def video_download(*, job_id):
        with service.store._tx() as db:
            job = db.execute('SELECT work_id FROM douyin_jobs WHERE id=?', (job_id,)).fetchone()
        entry = service.store.import_source('video', job['work_id'].zfill(64),
                                            f'douyin-{job["work_id"]}.mp4', 'originals/video.mp4')
        with service.store._tx() as db:
            db.execute("UPDATE douyin_jobs SET status='succeeded',source_id=? WHERE id=?", (entry['source']['id'], job_id))
        return {'status': 'succeeded', 'error_code': None}

    def image_download(url, path, config):
        downloads.append(url)
        path.write_bytes(b'\xff\xd8\xff' + url.encode())

    downloader.cfg = {'media_hosts': [], 'max_download_bytes': 4096, 'download_chunk_bytes': 1024, 'min_free_bytes': 0}
    downloader.status = lambda: {'enabled': True, 'cookie_configured': True, 'resolver_configured': True}
    downloader.process_next = video_download
    monkeypatch.setattr(WebService, 'douyin', property(lambda _: downloader))
    album = DouyinAlbum(service, downloader=image_download)
    config = load_config('config/douyin-daily-sync.json')
    config.update(enabled=True, mixed_enabled=True, schedule_enabled=True, auto_download=True, conversion_enabled=True)
    sync = FavoritesSync(service.store, config, image_quote=album.quote, image_limits=album.limit_details)
    monkeypatch.setattr(WebService, 'favorites_sync', property(lambda _: sync))
    monkeypatch.setattr(WebService, 'douyin_album', property(lambda _: album))
    monkeypatch.setattr(WebService, 'favorites_cookie', lambda _: COOKIE)
    now = datetime.now(ZoneInfo(config['timezone'])).replace(hour=6, minute=0)

    def tick(items, *, day=now, account='a', refresh_image=None):
        def read(*args, **kwargs):
            return {'status': 'ok', 'account_id': account, 'videos': items, 'exhausted': True}
        return sync.tick(COOKIE, read, downloader, service.dispatcher, album=album, refresh_image=refresh_image, now=day)

    return service, album, sync, tick, now, downloads


def establish(sync, tick, items, day, account='a'):
    sync.request_scan()
    tick(items, day=day, account=account)
    sync.confirm(account, COOKIE)
    tick(items, day=day, account=account)


@pytest.mark.parametrize('budget_case', ('complete', 'cumulative_limit', 'missing_consent'))
@pytest.mark.parametrize('work_id,image_count,ceiling', (
    (AUTHORIZED_WORK, 37, '8.54'),
    (EXTENDED_WORK, 45, '10.08'),
))
def test_manual_work_budget_quote_and_ledger(system, monkeypatch, budget_case, work_id, image_count, ceiling):
    from fastapi.testclient import TestClient
    from personalkb import douyin_album_processing
    from tools.api_smoke import reserve

    service, album, sync, tick, now, downloads = system
    extended = image_count > album.config['max_images']
    items = [work(work_id, 'image', image_count), work(100, 'image', 37), work(LARGE_WORK, 'image', 99)]
    establish(sync, tick, items, now)
    regular_error = 'album_image_limit' if extended else 'album_quote_over_run_budget'
    with pytest.raises(WorkflowError, match=regular_error):
        album.quote(image_count, work_id=work_id)
    calls = {}

    def timeout_once(stage):
        calls[stage] = calls.get(stage, 0) + 1
        if calls[stage] == 1:
            raise ProviderError('provider_timeout')

    class Models:
        def vision(self, path, *, mime):
            stage = path.read_bytes().rsplit(b'-', 1)[-1]
            timeout_once(stage)
            return {'content': '图文证据'}

        def summarize(self, body, title):
            timeout_once('text')
            return {'structured': {'summary': {'overview': '概述', 'key_points': [], 'limitations': ''},
                                   'notes': f'参见图 {image_count}'}}

    monkeypatch.setattr(douyin_album_processing, 'run_album', lambda *a, **kw: run_album(*a, **kw, services=Models()))
    monkeypatch.setattr(service, 'start', lambda: None)
    monkeypatch.setattr(service, 'stop', lambda: None)
    with TestClient(create_app(service.wc, service.pc, service.webcfg, service)) as client:
        headers = {'x-csrf-token': client.get('/api/session').json()['csrf_token']}
        rows = {row['work_id']: row for row in client.get('/api/douyin/favorites/sync').json()['items']}
        if extended:
            assert not rows[work_id]['selectable'] and rows[work_id]['image_quote_cny'] is None
            assert rows[work_id]['image_limits'] == dict(max_images=40, manual_max_images=45, manual_quote_cny=ceiling,
                                                       estimate_cny=ceiling, can_import=True)
            limits = client.get('/api/budget').json()['favorites_limits']
            assert (limits['max_images'], limits['download_limit'], limits['downloads_used']) == (40, 3, 0)
            assert limits['revision'] == 0 and limits['changes'] == []
        else:
            assert rows[work_id]['selectable'] and rows[work_id]['image_quote_cny'] == ceiling
        assert not rows['100']['selectable'] and rows['100']['image_quote_error'] == 'album_quote_over_run_budget'
        assert not rows[LARGE_WORK]['selectable'] and rows[LARGE_WORK]['image_quote_error'] == 'album_image_limit'
        assert rows[LARGE_WORK]['image_limits']['manual_quote_cny'] is None
        assert not rows[LARGE_WORK]['image_limits']['can_import']
        url = '/api/douyin/favorites/import'
        consent = {'account_id': 'a', 'work_ids': [work_id], 'rights_confirmed': True,
                   'allow_paid': True, 'video_budget_cny': '4.05', 'image_quotes': {work_id: ceiling}}
        if extended:
            assert client.post(url, json=consent, headers=headers).json()['error'] == 'album_image_limit'
            consent['extended_image_count'] = image_count
            assert client.post(url, json={**consent, 'extended_image_count': image_count - 1},
                               headers=headers).json()['error'] == 'favorites_price_changed'
            assert client.post(url, json={**consent, 'work_ids': [work_id, LARGE_WORK]},
                               headers=headers).json()['error'] == 'invalid_request'
            assert client.post(url, json={**consent, 'work_ids': [LARGE_WORK], 'extended_image_count': 99},
                               headers=headers).json()['error'] == 'album_image_limit'
        assert client.post(url, json={**consent, 'rights_confirmed': False}, headers=headers).json()['error'] == 'rights_required'
        assert client.post(url, json={**consent, 'allow_paid': False}, headers=headers).json()['error'] == 'paid_consent_required'
        assert client.post(url, json={**consent, 'image_quotes': {work_id: '10.09'}}, headers=headers).json()['error'] == 'favorites_price_changed'
        assert client.post(url, json={**consent, 'work_ids': ['100'], 'image_quotes': {'100': '8.54'}, 'extended_image_count': None},
                           headers=headers).json()['error'] == 'album_quote_over_run_budget'
        with service.store._tx() as db:
            assert not db.execute('SELECT 1 FROM favorites_queue').fetchone()
        assert client.post(url, json=consent, headers=headers).json() == {'queued': 1}
        assert client.post(url, json=consent, headers=headers).json() == {'queued': 0}
    tick(items)
    tick(items)
    with service.store._tx() as db:
        assert db.execute('SELECT COUNT(*) FROM favorites_queue').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM favorites_download_slots').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM favorites_conversion_slots').fetchone()[0] == 0
        assert db.execute('SELECT amount FROM favorites_conversion').fetchone()[0] == ceiling
        counts = [row[0] for row in db.execute('SELECT image_count FROM favorites_manual_album_extensions')]
        assert counts == ([image_count] if extended else [])
        if budget_case == 'missing_consent':
            db.execute('DELETE FROM favorites_manual_consent')
    budget = service.pc['budget']
    if budget_case == 'cumulative_limit':
        reserve(budget['ledger'], 'prior-task', 'prior-request', '96', '96', budget['research_limit'])
    result = service.dispatcher.process_next()
    if budget_case == 'cumulative_limit':
        assert result['error'] == 'budget_invalid_or_exceeded' and not calls
    elif budget_case == 'missing_consent':
        assert result['error'] == regular_error and not calls
    else:
        assert result['dispatch_state'] == 'done'
        source_id = service.store.get_task(result['task_id'])['source_id']
        document = service.detail(source_id)
        assert not document['eligible']
        assert [image['index'] for image in document['current']['result']['images']] == list(range(1, image_count + 1))
        with sqlite3.connect(budget['ledger']) as db:
            amounts = [Decimal(row[0]) for row in db.execute('SELECT amount FROM reservations WHERE run_id=?', (result['task_id'],))]
        assert len(amounts) == sum(calls.values()) == 2 * (image_count + 1)
        assert sum(amounts) == 2 * (image_count * Decimal('0.096256') + Decimal('0.705536')) < Decimal(ceiling)
    assert len(downloads) == image_count and budget['run_limit'] == '5'


@pytest.mark.parametrize('work_id,image_count,status,error', (
    (AUTHORIZED_WORK, 37, 'downloaded', 'album_quote_over_run_budget'),
    (EXTENDED_WORK, 45, 'download_failed', 'album_image_limit'),
))
def test_scheduled_work_does_not_use_manual_budget(system, work_id, image_count, status, error):
    service, _, sync, tick, now, _ = system
    baseline = [work(100)]
    establish(sync, tick, baseline, now - timedelta(days=1))
    items = [work(work_id, 'image', image_count), *baseline]
    tick(items)
    tick(items)
    assert tick(items) is None
    with service.store._tx() as db:
        row = db.execute('SELECT automatic,status FROM favorites_queue WHERE work_id=?', (work_id,)).fetchone()
        assert tuple(row) == (1, status)
        assert db.execute('SELECT COUNT(*) FROM favorites_conversion').fetchone()[0] == 0
    row = next(item for item in sync.status(COOKIE)['items'] if item['work_id'] == work_id)
    assert row['image_quote_error'] == error and not row['selectable']


def test_budget_limits_save_with_revision_and_apply_to_existing_album(system, monkeypatch):
    from fastapi.testclient import TestClient

    service, album, sync, tick, now, downloads = system
    items = [work(101, 'image', 4), work(EXTENDED_WORK, 'image', 45), work(LARGE_WORK, 'image', 99)]
    establish(sync, tick, items, now)
    monkeypatch.setattr(service, 'start', lambda: None)
    monkeypatch.setattr(service, 'stop', lambda: None)
    with TestClient(create_app(service.wc, service.pc, service.webcfg, service)) as client:
        url = '/api/budget/favorites-limits'
        headers = {'x-csrf-token': client.get('/api/session').json()['csrf_token']}
        before = client.get('/api/budget').json()
        assert before['favorites_limits']['day'] == now.date().isoformat()
        update = dict(max_images=3, download_limit=0, expected_revision=0)
        assert client.patch(url, json=update).status_code == 403
        for invalid in ({'max_images': 0}, {'max_images': True}, {'max_images': 2**53}, {'download_limit': -1},
                        {'download_limit': 0.5}, {'expected_revision': False}):
            result = client.patch(url, json={**update, **invalid}, headers=headers)
            assert result.json()['error'] == 'invalid_favorites_limits'
        assert client.get('/api/budget').json()['favorites_limits'] == before['favorites_limits']
        result = client.patch(url, json=update, headers=headers)
        assert result.status_code == 200
        saved = result.json()
        assert (saved['max_images'], saved['download_limit'], saved['revision']) == (3, 0, 1)
        assert saved['downloads_used'] == 0
        assert len(saved['changes']) == 1
        change = saved['changes'][0]
        assert (change['previous_max_images'], change['max_images']) == (40, 3)
        assert (change['previous_download_limit'], change['download_limit']) == (3, 0)
        assert client.patch(url, json={**update, 'download_limit': 6}, headers=headers).status_code == 409
        assert client.patch(url, json={**update, 'expected_revision': 1}, headers=headers).json() == saved
        after = client.get('/api/budget').json()
        assert after['favorites_limits'] == saved
        assert {key: value for key, value in after.items() if key != 'favorites_limits'} == {
            key: value for key, value in before.items() if key != 'favorites_limits'
        }
        status = client.get('/api/douyin/favorites/sync').json()
        assert status['download_limit'] == 0
        rows = {row['work_id']: row for row in status['items']}
        assert rows['101']['image_quote_error'] == 'album_image_limit'
        assert rows[EXTENDED_WORK]['image_limits']['manual_quote_cny'] == '10.08'
        assert rows[EXTENDED_WORK]['image_limits']['can_import']
        with pytest.raises(WorkflowError, match='album_image_limit'):
            album.download('101', items[0]['title'], items[0]['image_urls'])
        assert downloads == []
        raised = client.patch(url, json={**update, 'max_images': 99, 'expected_revision': 1}, headers=headers).json()
        assert raised['revision'] == 2
        assert album.quote(4) == Decimal('2.19')
        with pytest.raises(WorkflowError, match='album_quote_over_run_budget'):
            album.quote(45, work_id=EXTENDED_WORK)
        with pytest.raises(WorkflowError, match='album_single_import_required'):
            album.quote(45, manual=True, work_id=EXTENDED_WORK)
        rows = {row['work_id']: row for row in client.get('/api/douyin/favorites/sync').json()['items']}
        assert not rows[EXTENDED_WORK]['selectable'] and rows[EXTENDED_WORK]['image_limits']['can_import']
        assert rows[LARGE_WORK]['image_quote_error'] == 'album_quote_over_run_budget'
        assert not rows[LARGE_WORK]['image_limits']['can_import'] and not rows[LARGE_WORK]['selectable']
    reopened = FavoritesSync(workflow.make_store(service.wc), sync.config)
    assert reopened.limits(40)['revision'] == 2


def test_changed_count_can_be_reconfirmed_on_original_download(system):
    service, _, sync, tick, now, downloads = system
    initial = [work(EXTENDED_WORK, 'image', 45)]
    establish(sync, tick, initial, now)
    rights = dict(rights_confirmed=True, allow_paid=True, video_budget_cny='4.05')
    assert sync.select('a', [EXTENDED_WORK], COOKIE, **rights,
                       image_quotes={EXTENDED_WORK: '10.08'}, extended_image_count=45) == {'queued': 1}
    latest = [work(EXTENDED_WORK, 'image', 44)]
    sync.request_scan()
    tick(latest)
    assert tick(latest)['error_code'] == 'favorites_price_changed'
    assert not downloads
    with service.store._tx() as db:
        original = tuple(db.execute('SELECT seq,job_id FROM favorites_queue').fetchone())
    item = sync.status(COOKIE, manual_conversion_available=True)['items'][0]
    assert item['image_limits']['can_import'] and item['image_limits']['manual_quote_cny'] == '9.89'
    with pytest.raises(WorkflowError, match='invalid_state'):
        sync.retry_image_download('a', EXTENDED_WORK, COOKIE)
    with pytest.raises(WorkflowError, match='favorites_price_changed'):
        sync.select('a', [EXTENDED_WORK], COOKIE, **rights,
                    image_quotes={EXTENDED_WORK: '10.08'}, extended_image_count=44)
    consent = dict(**rights, image_quotes={EXTENDED_WORK: '9.89'}, extended_image_count=44)
    assert sync.select('a', [EXTENDED_WORK], COOKIE, **consent) == {'queued': 1}
    assert sync.select('a', [EXTENDED_WORK], COOKIE, **consent) == {'queued': 0}
    assert tick(latest)['favorites'] == 'downloaded'
    assert tick(latest)['favorites'] == 'conversion_queued'
    assert len(downloads) == 44
    with service.store._tx() as db:
        assert [tuple(row) for row in db.execute('SELECT seq,job_id FROM favorites_queue')] == [original]
        assert db.execute('SELECT amount FROM favorites_conversion').fetchone()[0] == '9.89'
        assert db.execute('SELECT COUNT(*) FROM favorites_download_slots').fetchone()[0] == 0


def test_video_only_favorites_without_album_config_preserve_budget(system, monkeypatch):
    service, _, sync, *_ = system
    sync.config['mixed_enabled'] = False

    def missing_album(_):
        raise WorkflowError('invalid_album_config')

    monkeypatch.setattr(WebService, 'douyin_album', property(missing_album))
    before = service.budget()
    result = service.change_budget({'limit_cny': '110', 'expected_revision': before['revision']})
    assert result['limit_cny'] == '110' and 'favorites_limits' not in result
    assert service.budget()['limit_cny'] == '110'
    with pytest.raises(WorkflowError, match='invalid_album_config'):
        service.change_favorites_limits({'max_images': 40, 'download_limit': 3, 'expected_revision': 0})


def test_lower_download_limit_preserves_dispatched_jobs_and_manual_import(system, monkeypatch):
    service, album, sync, tick, now, _ = system
    historical = [work(EXTENDED_WORK, 'image', 45), work(100)]
    establish(sync, tick, historical, now - timedelta(days=1))
    items = [work(101), work(102), *historical]
    tick(items)
    downloader = service.douyin
    finish = downloader.process_next
    monkeypatch.setattr(downloader, 'process_next', lambda **_: {'error_code': None})
    tick(items)
    with service.store._tx() as db:
        pending = db.execute('SELECT job_id FROM favorites_queue WHERE work_id=?', ('101',)).fetchone()[0]
        assert db.execute('SELECT status FROM douyin_jobs WHERE id=?', (pending,)).fetchone()[0] == 'queued'
    update = dict(max_images=40, download_limit=0, expected_revision=0)
    assert sync.limits(40, payload=update)['downloads_used'] == 1
    monkeypatch.setattr(downloader, 'process_next', finish)
    assert tick(items)['status'] == 'succeeded'
    assert tick(items)['favorites'] == 'conversion_queued'
    assert tick(items) is None
    assert sync.select('a', [EXTENDED_WORK], COOKIE, rights_confirmed=True, allow_paid=True,
                       video_budget_cny='4.05', image_quotes={EXTENDED_WORK: '10.08'}, extended_image_count=45) == {'queued': 1}
    assert tick(items)['favorites'] == 'downloaded'
    assert tick(items)['favorites'] == 'conversion_queued'
    with service.store._tx() as db:
        assert db.execute('SELECT COUNT(*) FROM favorites_download_slots').fetchone()[0] == 1
        assert db.execute('SELECT job_id FROM favorites_queue WHERE work_id=?', ('102',)).fetchone()[0] is None
    sync.limits(40, payload={**update, 'download_limit': 1, 'expected_revision': 1})
    assert tick(items) is None
    tomorrow = now + timedelta(days=1)
    assert tick(items, day=tomorrow)['favorites'] == 'scanned'
    assert tick(items, day=tomorrow)['status'] == 'succeeded'
    with service.store._tx() as db:
        assert [row[0] for row in db.execute('SELECT day FROM favorites_download_slots ORDER BY seq')] == [
            now.date().isoformat(), tomorrow.date().isoformat()
        ]


def test_mixed_daily_count_budget_and_continuation(system):
    service, album, sync, tick, now, downloads = system
    baseline = [work(i, 'image' if i == 100 else 'video') for i in range(100, 0, -1)]
    establish(sync, tick, baseline, now - timedelta(days=1))
    assert len(sync.status(COOKIE)['items']) == 100 and not downloads
    assert service.store.list_sources() == []
    new = [work(101), work(102, 'image'), work(103), work(104, 'image'), work(105)]
    items = new + baseline
    tick(items)
    for _ in range(12):
        tick(items)
    day = now.date().isoformat()
    with service.store._tx() as db:
        assert [r['work_id'] for r in db.execute('SELECT work_id FROM favorites_queue WHERE download_day=? ORDER BY seq', (day,))] == ['101', '102', '103']
        assert [Decimal(r['amount']) for r in db.execute('SELECT amount FROM favorites_conversion_slots WHERE day=? ORDER BY rowid', (day,))] == [
            Decimal('4.05'), album.quote(2), Decimal('4.05'),
        ]
    tomorrow = now + timedelta(days=1)
    for _ in range(8):
        tick(items, day=tomorrow)
    with service.store._tx() as db:
        assert [r['work_id'] for r in db.execute('SELECT work_id FROM favorites_queue WHERE download_day=? ORDER BY seq', (tomorrow.date().isoformat(),))] == ['104', '105']
        assert db.execute('SELECT COUNT(*) FROM favorites_queue').fetchone()[0] == 5


def test_insufficient_combined_budget_defers_conversion(system):
    service, album, sync, tick, now, _ = system
    sync.config['daily_budget_cny'] = '4.05'
    baseline = [work(100)]
    establish(sync, tick, baseline, now - timedelta(days=1))
    items = [work(101), work(102, 'image'), *baseline]
    for _ in range(8):
        tick(items)
    with service.store._tx() as db:
        assert [(x['work_id'], x['status']) for x in db.execute('SELECT work_id,status FROM favorites_queue ORDER BY seq')] == [
            ('101', 'conversion_queued'), ('102', 'downloaded'),
        ]
        assert [Decimal(x[0]) for x in db.execute('SELECT amount FROM favorites_conversion_slots')] == [Decimal('4.05')]
    for _ in range(4):
        tick(items, day=now + timedelta(days=1))
    with service.store._tx() as db:
        assert [Decimal(x[0]) for x in db.execute('SELECT amount FROM favorites_conversion_slots ORDER BY day')] == [
            Decimal('4.05'), album.quote(2),
        ]


def test_enqueues_new_image_and_rejects_unknown_works_beyond_boundary(system):
    service, _, sync, tick, now, _ = system
    baseline = [work(100), work(99)]
    establish(sync, tick, baseline, now - timedelta(days=1))
    tick([work(101, 'image'), baseline[0], work(97, 'image'), baseline[1], work(98, 'image')])
    with service.store._tx() as db:
        assert [row[0] for row in db.execute('SELECT work_id FROM favorites_queue')] == ['101']


def test_automatic_album_failed_download_retry_reuses_slot_and_image(system, monkeypatch):
    service, album, sync, tick, now, downloads = system
    baseline = [work(100)]
    establish(sync, tick, baseline, now - timedelta(days=1))
    download = album.downloader
    failed = False

    def interrupt_once(url, path, config):
        nonlocal failed
        if url.endswith('page-2') and not failed:
            failed = True
            raise WorkflowError('douyin_timeout')
        download(url, path, config)

    monkeypatch.setattr(album, 'downloader', interrupt_once)
    items = [work(101, 'image'), *baseline]
    tick(items)
    assert tick(items)['error_code'] == 'douyin_timeout'
    row = next(item for item in sync.status(COOKIE)['items'] if item['work_id'] == '101')
    assert row['status'] == 'download_failed' and row['image_download_error'] == 'douyin_timeout'
    assert sync.retry_image_download('a', '101', COOKIE) == {'queued': True}
    assert tick(items)['favorites'] == 'downloaded'
    assert len(downloads) == 2
    with service.store._tx() as db:
        assert db.execute('SELECT COUNT(*) FROM favorites_download_slots').fetchone()[0] == 1


def test_expired_image_urls_refresh_without_fetching_completed_image(system, monkeypatch):
    _, album, sync, tick, now, downloads = system
    baseline = [work(100)]
    establish(sync, tick, baseline, now - timedelta(days=1))
    image = work(101, 'image')
    fresh = [url + '?x-expires=2&x-signature=fresh' for url in image['image_urls']]
    image['image_urls'] = [url + '?x-expires=1&x-signature=old' for url in image['image_urls']]
    download = album.downloader

    def expires_on_second_image(url, path, config):
        if 'page-2?' in url and 'old' in url:
            raise WorkflowError('douyin_http_failed')
        download(url, path, config)

    def refresh(account, work_id):
        assert (account, work_id) == ('a', '101')
        return fresh

    monkeypatch.setattr(album, 'downloader', expires_on_second_image)
    items = [image, *baseline]
    tick(items)
    assert tick(items, refresh_image=refresh)['favorites'] == 'downloaded'
    assert downloads == [image['image_urls'][0], fresh[1]]


@pytest.mark.parametrize('case', ('success', 'budget', 'changed_config', 'incomplete', 'timeout'))
def test_cancelled_album_text_only_retry(system, monkeypatch, case):
    from fastapi.testclient import TestClient
    from personalkb import douyin_album_processing
    from personalkb.model_budget import update_budget_limit
    from personalkb.video_journal import VideoJournal
    from personalkb.video_services import ProviderClient

    service, album, sync, tick, now, downloads = system
    items = [work(100, 'image')]
    establish(sync, tick, items, now)
    sync.select('a', ['100'], COOKIE, rights_confirmed=True, allow_paid=True, video_budget_cny='4.05',
                image_quotes={'100': str(album.quote(2))})
    tick(items)
    tick(items)
    vision_calls = []
    text_calls = []

    class InitialModels:
        def vision(self, path, *, mime):
            vision_calls.append(path)
            return {'content': '已保存图文证据'}

        def summarize(self, body, title):
            raise ProviderError('model_output_truncated', 'initial-text', metrics={'finish_reason': 'length'})

    def fake_request(_client, url, key=None, payload=None):
        assert url.endswith('/chat/completions')
        assert '不超过 1500 字' in payload['messages'][0]['content']
        assert '## 图 1' in payload['messages'][1]['content'] and '## 图 2' in payload['messages'][1]['content']
        text_calls.append(payload['max_tokens'])
        if case == 'timeout':
            raise ProviderError('provider_timeout')
        return {'choices': [{'finish_reason': 'stop', 'message': {'content':
            '{"summary":{"overview":"精简概述","key_points":[],"limitations":""},"notes":"参见图 1 和图 2"}'}}]}

    def fake_services(_album, pc, kinds):
        assert kinds == ('text',)
        provider = pc['models']['models']['text']['provider']
        ref = pc['models']['providers'][provider]['api_key_env']
        return ProviderClient(pc['models'], pc, {ref: 'test-key'})

    monkeypatch.setattr(douyin_album_processing, 'run_album', lambda *a, **kw: run_album(*a, **kw, services=InitialModels()))
    monkeypatch.setattr(douyin_album_processing, '_album_services', fake_services)
    monkeypatch.setattr(ProviderClient, '_request', fake_request)
    result = service.dispatcher.process_next()
    assert result['error'] == 'model_output_truncated'
    tid = result['task_id']
    journal = VideoJournal(service.store)
    journal.resume_claim(tid, 'douyin-album')
    service.dispatcher.cancel(tid)
    ledger = service.pc['budget']['ledger']

    def reservations():
        with sqlite3.connect(ledger) as db:
            return set(db.execute('SELECT request_id,amount FROM reservations WHERE run_id=?', (tid,)).fetchall())

    baseline = reservations()
    if case == 'incomplete':
        with service.store._tx() as db:
            db.execute("UPDATE video_stages SET result=NULL WHERE task_id=? AND name='vision-2'", (tid,))
        assert service.tasks()['items'][0]['model_recovery'] is None
        assert reservations() == baseline and not text_calls
        return
    monkeypatch.setattr(service, 'start', lambda: None)
    monkeypatch.setattr(service, 'stop', lambda: None)
    with TestClient(create_app(service.wc, service.pc, service.webcfg, service)) as client:
        headers = {'x-csrf-token': client.get('/api/session').json()['csrf_token']}
        row = next(item for item in client.get('/api/tasks').json()['items'] if item['id'] == tid)
        recovery = row['model_recovery']
        assert (row['status'], recovery['mode'], recovery['stage'], recovery['image_count']) == (
            'cancelled', 'retry-album-text', 'text', 2)
        assert recovery['ceiling_cny'] == '0.71'
        url = f'/api/tasks/{tid}/recover-model'
        assert client.post(url, json=recovery, headers=headers).json()['error'] == 'paid_consent_required'
        assert client.post(url, json={**recovery, 'allow_paid': True, 'quote_key': 'old'}, headers=headers).status_code == 409
        consent = {**recovery, 'allow_paid': True}
        assert client.post(url, json=consent, headers=headers).json()['dispatch_state'] == 'pending'
        assert client.post(url, json=consent, headers=headers).status_code == 409
    assert reservations() == baseline and not text_calls
    if case == 'changed_config':
        album.config['text_retry_prompt'] += ' 汇总时优先保留可执行步骤。'
        assert service.dispatcher.process_next()['error'] == 'model_recovery_conflict'
        assert service.tasks()['items'][0]['model_recovery']['quote_key'] != recovery['quote_key']
        assert reservations() == baseline and not text_calls
        return
    if case == 'budget':
        limit = str(sum(Decimal(amount) for _, amount in baseline).quantize(Decimal('.01')))
        update_budget_limit(ledger, '100', limit, 0)
        assert service.dispatcher.process_next()['error'] == 'budget_invalid_or_exceeded'
        assert reservations() == baseline and not text_calls
        update_budget_limit(ledger, '100', '100', 1)
        assert service.dispatcher.recover_model(tid, consent)['dispatch_state'] == 'pending'
    execution = service.dispatcher.process_next()
    assert text_calls == [8192] and len(vision_calls) == len(downloads) == 2
    assert reservations()-baseline == {(tid+f':text:retry:{recovery["attempt"]}', recovery['amount'])}
    if case == 'timeout':
        assert execution['error'] == 'provider_timeout'
        assert service.tasks()['items'][0]['model_recovery'] is None
        return
    assert execution['dispatch_state'] == 'done'
    detail = service.detail(row['source_id'])
    assert not detail['eligible']
    assert [image['index'] for image in detail['current']['result']['images']] == [1, 2]


def test_manual_quote_model_recovery_approved_index_and_cross_account_dedupe(system, monkeypatch):
    from fastapi.testclient import TestClient
    from personalkb import douyin_album_processing

    service, album, sync, tick, now, downloads = system
    items = [work(100, 'image')]
    establish(sync, tick, items, now)
    row = sync.status(COOKIE)['items'][0]
    quote = format(album.quote(2), '.2f')
    assert (row['kind'], row['image_count'], row['image_quote_cny']) == ('image', 2, quote)
    calls = []

    class Models:
        def vision(self, path, *, mime):
            page = path.read_text(encoding='latin-1')[-1]
            calls.append(page)
            if page == '2' and calls.count('2') == 1:
                raise ProviderError('model_output_truncated', 'request-2',
                                    metrics={'finish_reason': 'length', 'usage': {'prompt_tokens': 20, 'completion_tokens': 10}})
            return {'content': f'OCR {page}', 'response_metrics': {'usage': {'prompt_tokens': 20, 'completion_tokens': 2}}}

        def summarize(self, body, title):
            assert body.index('## 图 1') < body.index('## 图 2')
            assert '测试作品文案' in body
            calls.append('summary')
            return {'structured': {'summary': {'overview': '概述', 'key_points': [], 'limitations': ''}, 'notes': '参见图 2'},
                    'response_metrics': {'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}}

    models = Models()
    monkeypatch.setattr(douyin_album_processing, 'run_album', lambda *a, **kw: run_album(*a, **kw, services=models))
    monkeypatch.setattr(service, 'start', lambda: None)
    monkeypatch.setattr(service, 'stop', lambda: None)
    with TestClient(create_app(service.wc, service.pc, service.webcfg, service)) as client:
        headers = {'x-csrf-token': client.get('/api/session').json()['csrf_token']}
        manual = {'account_id': 'a', 'work_ids': ['100'], 'rights_confirmed': True,
                  'allow_paid': True, 'video_budget_cny': '4.05', 'image_quotes': {'100': '0.01'}}
        assert client.post('/api/douyin/favorites/import', json=manual, headers=headers).status_code >= 400
        manual['image_quotes']['100'] = quote
        assert client.post('/api/douyin/favorites/import', json=manual, headers=headers).json() == {'queued': 1}
        assert client.post('/api/douyin/favorites/import', json=manual, headers=headers).json() == {'queued': 0}
        tick(items)
        tick(items)
        with service.store._tx() as db:
            assert db.execute('SELECT COUNT(*) FROM favorites_conversion_slots').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM favorites_download_slots').fetchone()[0] == 0
            assert db.execute('SELECT amount FROM favorites_conversion').fetchone()[0] == quote
        tid = service.dispatcher.process_next()['task_id']
        sid = service.store.get_task(tid)['source_id']
        assert service.store.get_task(tid)['status'] == 'needs_attention'
        task = next(t for t in service.tasks()['items'] if t['id'] == tid)
        recovery = task['model_recovery']
        assert recovery['stage'] == 'vision-2' and recovery['mode'] == 'retry'
        with pytest.raises(WorkflowError, match='paid_consent_required'):
            service.dispatcher.recover_model(tid, recovery)
        service.dispatcher.recover_model(tid, {**recovery, 'allow_paid': True})
        assert service.dispatcher.process_next()['dispatch_state'] == 'done'
        assert calls == ['1', '2', '2', 'summary'] and len(downloads) == 2
        raw = client.get(f'/api/sources/{sid}/album/2')
        assert raw.headers['content-type'] == 'image/jpeg'
        assert raw.content.endswith(b'page-2')
        detail = service.detail(sid)
        version = detail['current']
        assert not detail['eligible'] and [i['index'] for i in version['result']['images']] == [1, 2]
        assert version['result']['processing']['reserved_cny'] == quote
        assert Decimal(version['result']['processing']['estimated_cost_cny']) > 0
        assert not service.store.eligible_sources()
        from personalkb.rag_index import RagIndex, load_rag_config
        class Embedding:
            def embed(self, texts, **kwargs):
                return {'vectors': [[1., 0.] for _ in texts], 'model': 'text-embedding-v4', 'usage': {}}

        rag_config = load_rag_config()
        rag_config['embedding']['dimensions'] = 2
        index = RagIndex(service.store, rag_config, Embedding())
        assert index.build(allow_paid=True)['sources'] == 0
        assert service.review(sid, {'version_id': version['id'], 'content_sha256': version['content_sha256'],
                                    'score': 100, 'decision': 'approve', 'reviewer': 'test'})['eligible']
        assert service.store.eligible_sources()[0]['id'] == sid
        assert index.build(allow_paid=True)['sources'] == 1
        hits = index.query('OCR', mode='lexical', filters={'sources': [sid]})
        assert {hit['locator']['page'] for hit in hits} == {1, 2}
        service.store.delete_source(sid)
        assert client.get(f'/api/sources/{sid}/album/2').status_code >= 400
        establish(sync, tick, items, now, account='b')
        assert sync.status(COOKIE)['items'][0]['status'] == 'deleted'
        assert sync.select('b', ['100'], COOKIE, rights_confirmed=True, allow_paid=True,
                           video_budget_cny='4.05', image_quotes={'100': quote}) == {'queued': 0}
