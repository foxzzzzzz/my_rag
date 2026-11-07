import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from personalkb.workflow import import_file, load_config, make_store, run_once
from personalkb.workflow_store import WorkflowError
from personalkb.obsidian import ObsidianService
from personalkb.web_service import WebService

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def scenario(tmp_path):
    config = load_config()
    config.update(data_dir=str(tmp_path / 'data'), min_free_bytes=0,
                  content={'enabled': True, 'directory': 'knowledge'})
    html = tmp_path / 'synthetic.html'
    html.write_text('<html><title>Synthetic</title><body><p>Evidence text</p><script>secret_script()</script></body></html>', encoding='utf8')
    imported = import_file(config, html, rights_confirmed=True)
    store = make_store(config)
    service = ObsidianService(config)
    return config, html, imported, store, service


def code(expected, fn, *args, **kwargs):
    with pytest.raises(WorkflowError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == expected


def process(scenario):
    config, html, item, store, service = scenario
    sid = item['source']['id']
    assert store.get_source(sid)['current_version_id'] is None
    assert store.eligible_sources() == []
    assert import_file(config, html, True)['source']['id'] == sid
    run_once(config)
    version = store.get_version(store.get_source(sid)['current_version_id'])
    assert 'Evidence text' in version['result']['body']
    assert 'secret_script' not in version['result']['body']
    assert store.eligible_sources() == []
    return sid, version


def approve(store, sid, version):
    store.review(sid, version['id'], version['content_sha256'], 99, 'approve', 'synthetic-test-only')


def test_synthetic_lifecycle_and_roundtrip(scenario):
    config, html, item, store, service = scenario
    sid, first = process(scenario)
    approve(store, sid, first)
    assert [x['id'] for x in store.eligible_sources()] == [sid]
    label = service.classification.create_label('topic', 'Synthetic topic', ['Synthetic alias'])
    meta = service.classification.update(sid, 0, [label['id']], [])
    service.classification.update_label(label['id'], label['revision'], 'Renamed topic', ['Synthetic alias'])
    meta = service.classification.snapshot(sid)
    assert meta['topics'][0]['name'] == 'Renamed topic'
    assert store.get_source(sid)['current_version_id'] == first['id']
    assert len(store.eligible_sources()) == 1
    note, _ = service.export_note(sid)
    archive, _ = service.export_zip(sid)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert z.read('note.md') == note
        assert b'Evidence text' in z.read('evidence.json')
        assert b'secret_script' not in z.read('evidence.json')
    edited = note.replace(('topic_ids: ' + json.dumps([label['id']])).encode(), b'topic_ids: []') + b'\nSynthetic edit\n'
    preview = service.preview(edited, 'note.md')
    assert not preview['conflict']
    assert store.get_source(sid)['current_version_id'] == first['id']
    receipt = service.apply(preview['preview_id'], 'use_uploaded')
    assert receipt['content_changed'] and receipt['classification_changed'] and receipt['review_required']
    assert service.classification.snapshot(sid)['topics'] == []
    second = store.get_version(receipt['version_id'])
    assert second['parent_version_id'] == first['id']
    assert 'Synthetic edit' in second['result']['notes']
    assert store.eligible_sources() == []
    assert service.apply(preview['preview_id'], 'use_uploaded')['version_id'] == second['id']
    approve(store, sid, second)
    assert len(store.eligible_sources()) == 1
    store.review(sid, second['id'], second['content_sha256'], 0, 'reject', 'synthetic-test-only')
    assert store.eligible_sources() == []
    store.delete_source(sid)
    assert store.get_source(sid)['deleted'] == 1
    code('source_deleted', import_file, config, html, True)
    code('source_deleted', service.export_note, sid)


def test_preview_cas_and_atomic_rollback(scenario):
    _, _, _, store, service = scenario
    sid, first = process(scenario)
    label = service.classification.create_label('topic', 'Before', [])
    service.classification.update(sid, 0, [label['id']], [])
    note, _ = service.export_note(sid)
    preview = service.preview(note + b'\nChanged\n', 'note.md')
    service.classification.update_label(label['id'], 1, 'After', [])
    before = service.classification.snapshot(sid)
    code('classification_conflict', service.apply, preview['preview_id'], 'use_uploaded')
    assert store.get_source(sid)['current_version_id'] == first['id']
    assert service.classification.snapshot(sid) == before
    note, _ = service.export_note(sid)
    preview = service.preview(note + b'\nChanged\n', 'note.md')
    with patch.object(service.classification, 'update_in_transaction', side_effect=WorkflowError('injected_failure')):
        code('injected_failure', service.apply, preview['preview_id'], 'use_uploaded')
    assert store.get_source(sid)['current_version_id'] == first['id']
    assert len(store.list_versions(sid)) == 1
    assert service.classification.snapshot(sid) == before
    assert service.apply(preview['preview_id'], 'use_uploaded')['content_changed']


def test_sync_failure_recovery_and_limits(scenario):
    config, html, item, store, service = scenario
    sid, version = process(scenario)
    with patch.object(store, 'sync_source', side_effect=OSError('synthetic failure')):
        approve(store, sid, version)
    assert store.eligible_sources() == []
    assert store.reconcile(sid)[sid] == 'synced'
    assert len(store.eligible_sources()) == 1
    too_small = dict(config, max_upload_bytes=html.stat().st_size - 1)
    code('invalid_size', import_file, too_small, html, True)
    disk_low = dict(config, min_free_bytes=10**30)
    code('disk_low', import_file, disk_low, html, True)
    assert store.get_source(sid)['current_version_id'] == version['id']
    assert len(store.eligible_sources()) == 1


def test_listing_filters_detail_and_export_agree(scenario):
    config, _, _, store, obsidian = scenario
    sid, version = process(scenario)
    web = WebService(config, {}, {})
    topic = obsidian.classification.create_label('topic', 'Old name', ['alias'])
    tag = obsidian.classification.create_label('tag', 'Test tag', [])
    obsidian.classification.update(sid, 0, [topic['id']], [tag['id']])
    filt = {'topics': [topic['id']], 'tags': [tag['id']], 'reviews': ['pending']}
    item = web.sources(filt)['items'][0]
    assert item['id'] == sid and not item['eligible']
    assert web.sources({**filt, 'tags': ['missing']})['items'] == []
    assert web.sources({**filt, 'reviews': ['approve']})['items'] == []
    detail = web.detail(sid)
    assert detail['task']['status'] == 'succeeded'
    assert detail['current']['id'] == version['id']
    approve(store, sid, version)
    assert web.sources(filt)['items'] == []
    item = web.sources({**filt, 'reviews': ['approve']})['items'][0]
    assert item['eligible'] and [s['id'] for s in store.eligible_sources()] == [sid]
    obsidian.classification.update_label(topic['id'], 1, 'New name', ['alias'])
    item = web.sources({**filt, 'reviews': ['approve']})['items'][0]
    assert item['classification']['topics'][0]['name'] == 'New name'
    note = (Path(config['data_dir']) / 'knowledge' / sid / 'note.md').read_text(encoding='utf8')
    assert 'New name' in note and 'Old name' not in note
    exported, _ = obsidian.export_note(sid)
    assert topic['id'].encode() in exported and tag['id'].encode() in exported
