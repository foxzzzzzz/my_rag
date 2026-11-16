from tools.douyin_favorites import append_videos


def test_mixed_scan_preserves_order_and_excludes_images_by_default():
    raw = [
        {'aweme_id': '1', 'video': {}, 'desc': 'one'},
        {'aweme_id': '2', 'images': [{'url_list': ['https://example.com/1']},
                                      {'url_list': ['https://example.com/2']}], 'desc': 'two'},
        {'aweme_id': '3', 'video': {}, 'desc': 'three'},
    ]
    videos = {}
    append_videos(raw, videos)
    assert list(videos) == ['1', '3']
    videos = {}
    append_videos(raw, videos, include_images=True)
    assert list(videos) == ['1', '2', '3']
    assert videos['2']['kind'] == 'image'
    assert videos['2']['image_urls'] == ['https://example.com/1', 'https://example.com/2']

def test_migration_marks_existing_images_as_baseline_and_queues_new_video(tmp_path):
    from datetime import datetime
    from types import SimpleNamespace
    from personalkb.douyin_daily_sync import FavoritesSync, load_config
    from personalkb.douyin_import import DouyinImporter
    from personalkb.web_dispatch import WebDispatcher
    from personalkb.workflow import load_config as load_workflow

    wc = load_workflow()
    wc['data_dir'] = str(tmp_path)
    downloader = DouyinImporter(wc, {}, {})
    dispatcher = WebDispatcher(SimpleNamespace(store=downloader.store,
                                               webcfg={'live_video_enabled': True, 'dispatch_recovery_seconds': 60}))
    config = load_config('config/douyin-daily-sync.json')
    config.update(enabled=True, schedule_enabled=True, baseline_limit=3)
    sync = FavoritesSync(downloader.store, config, image_quote=lambda count, **kwargs: '1.20')
    def tick(payload):
        sync.request_scan()
        sync.tick('cookie', lambda *args, **kwargs: payload, downloader, dispatcher,
                  now=datetime(2026, 11, 16, 6))
    original = {'status': 'ok', 'account_id': 'a', 'account_label': 'a', 'exhausted': True,
                'videos': [{'id': '3', 'title': 'three'}, {'id': '2', 'title': 'two'}, {'id': '1', 'title': 'one'}]}
    tick(original)
    sync.confirm('a', 'cookie')
    tick(original)
    config['mixed_enabled'] = True
    mixed = {'status': 'ok', 'account_id': 'a', 'account_label': 'a', 'exhausted': True,
             'videos': [{'id': '4', 'title': 'new video'},
                        {'id': '5', 'title': 'historical image', 'kind': 'image',
                         'image_urls': ['https://example.com/image'], 'description': 'caption'},
                        {'id': '3', 'title': 'three'}, {'id': '2', 'title': 'two'}]}
    tick(mixed)
    with sync.store._tx() as db:
        assert [(x['work_id'], x['automatic']) for x in db.execute('select * from favorites_queue')] == [('4', 1)]
        image = db.execute("select * from favorites_items where work_id='5'").fetchone()
        assert (image['baseline'], image['kind'], image['description']) == (1, 'image', 'caption')

def test_incomplete_or_disjoint_migration_preserves_previous_snapshot(tmp_path):
    from personalkb.douyin_daily_sync import FavoritesSync, load_config
    from personalkb.douyin_import import DouyinImporter
    from personalkb.workflow import load_config as load_workflow
    wc = load_workflow()
    wc['data_dir'] = str(tmp_path)
    store = DouyinImporter(wc, {}, {}).store
    config = load_config('config/douyin-daily-sync.json')
    config.update(enabled=True, mixed_enabled=True, baseline_limit=1)
    sync = FavoritesSync(store, config)
    with store._tx() as db:
        db.execute("INSERT INTO favorites_accounts(id,label,snapshot,mixed) VALUES(?,?,?,?)", ('a','a','["1"]',0))
        db.execute("UPDATE favorites_state SET active='a'")
        db.execute("INSERT INTO favorites_items(account_id,work_id,title,position,baseline) VALUES('a','1','old',0,1)")
        payload = {'status': 'ok', 'account_id': 'a', 'exhausted': True,
                   'videos': [{'id': '2', 'title': 'unseen', 'kind': 'image', 'image_urls': ['https://example.com/a']}]}
        sync._accept_scan(db, payload, 'credential')
        assert db.execute("select state,error_code from favorites_state").fetchone()[:] == ('paused', 'snapshot_gap')
        assert db.execute("select snapshot,mixed from favorites_accounts where id='a'").fetchone()[:] == ('["1"]', 0)
        assert db.execute("select work_id from favorites_items").fetchone()[0] == '1'
        assert db.execute("select count(*) from favorites_queue").fetchone()[0] == 0
        payload['videos'] = [{'id': '1', 'title': 'a'}, {'id': '1', 'title': 'b'}]
        sync._accept_scan(db, payload, 'credential')
        assert db.execute("select error_code from favorites_state").fetchone()[0] == 'collection_invalid'


def test_image_refresh_updates_url_without_changing_baseline_order(tmp_path):
    import json
    from personalkb.douyin_daily_sync import FavoritesSync, load_config
    from personalkb.douyin_import import DouyinImporter
    from personalkb.workflow import load_config as load_workflow
    wc = load_workflow()
    wc['data_dir'] = str(tmp_path)
    store = DouyinImporter(wc, {}, {}).store
    config = load_config('config/douyin-daily-sync.json')
    config.update(enabled=True, mixed_enabled=True, baseline_limit=2)
    sync = FavoritesSync(store, config)
    with store._tx() as db:
        db.execute("INSERT INTO favorites_accounts(id,label,snapshot,mixed) VALUES(?,?,?,?)", ('a','a','["1","2"]',1))
        db.execute("UPDATE favorites_state SET active='a'")
        db.execute("INSERT INTO favorites_items(account_id,work_id,title,position,baseline,kind,image_urls) VALUES(?,?,?,?,?,?,?)", ('a','1','old',0,1,'image','["https://example.com/old"]'))
        db.execute("INSERT INTO favorites_items(account_id,work_id,title,position,baseline) VALUES('a','2','v',1,1)")
        payload = {'status': 'ok', 'account_id': 'a', 'exhausted': True,
                   'videos': [{'id': '2', 'title': 'v'}, {'id': '1', 'title': 'new', 'kind': 'image',
                               'image_urls': ['https://example.com/new'], 'description': 'new caption'}]}
        sync._accept_scan(db, payload, 'credential')
        rows = db.execute("select work_id,position,image_urls,description from favorites_items order by position").fetchall()
        assert [row['work_id'] for row in rows] == ['1', '2']
        assert json.loads(rows[0]['image_urls']) == ['https://example.com/new']
        assert rows[0]['description'] == 'new caption'
