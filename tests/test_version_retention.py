import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from personalkb import maintenance, version_retention, workflow
from personalkb.workflow_store import WorkflowError


@pytest.fixture
def library(tmp_path, request):
    cfg = json.loads(Path('config/workflow.json').read_text(encoding='utf-8-sig'))
    cfg['data_dir'] = str(tmp_path / 'workflow')
    workflow_path = tmp_path / 'workflow.json'
    workflow_path.write_text(json.dumps(cfg), encoding='utf-8')
    ledger = tmp_path / 'budget.sqlite'
    with sqlite3.connect(ledger) as db:
        db.execute('CREATE TABLE ledger (entry TEXT)')
    config_path = tmp_path / 'maintenance.json'
    config_path.write_text(json.dumps({
        'workflow_config': str(workflow_path), 'backup_root': str(tmp_path / 'backups'),
        'ledger_paths': [str(ledger)], 'keep_snapshots': 4, 'min_free_bytes': 0,
        'version_history_retention': {'enabled': True, 'approved_history': 1, 'other_history': 1},
    }), encoding='utf-8')
    config = maintenance.load_config(config_path)
    store = workflow.make_store(config['_workflow'])
    item = store.import_source('html', 'a' * 64, 'source.html', 'originals/a')
    source = item['source']['id']
    task = store.claim_specific(item['task']['id'], 'test')
    frame_dir = store.content_root / source / 'frames'
    frame_dir.mkdir(parents=True)
    frames = []
    for blob in (b'shared', b'unique'):
        sha = hashlib.sha256(blob).hexdigest()
        (frame_dir / (sha + '.jpg')).write_bytes(blob)
        frames.append({'sha256': sha, 'index': len(frames), 'seconds': len(frames)})
    result = dict(title='Title', body='Body', summary='Summary', notes='Notes', scheme_id='s', scheme_version='1',
                  output_kind='machine_initial', provenance='local_extraction', evidence=[{'text': 'evidence'}],
                  frames=frames)
    versions = [store.finish(task['id'], task['lease_token'], result)]
    revised = {**result, 'output_kind': 'human_edited', 'provenance': 'human_edited', 'frames': frames[:1]}
    for index in range(1, 5):
        versions.append(store.revise(source, versions[-1]['id'], {**revised, 'body': f'Body {index}'}))
        if getattr(request, 'param', False) and index in (1, 2, 4):
            review(store, source, versions[-1])
            if index == 2:
                review(store, source, versions[-1], 'rework', 90)
    return config, store, source, versions, frames


def review(store, sid, version, decision='approve', score=99):
    return store.review(sid, version['id'], version['content_sha256'], score, decision, 'tester')


@pytest.mark.parametrize('library', [True], indirect=True)
def test_verified_backup_preserves_old_content_before_pruning(library, tmp_path):
    config, store, sid, versions, frames = library
    old_root = store.content_root / sid / 'versions' / versions[2]['id']
    old_content = (old_root / 'content.md').read_bytes()

    result = maintenance.create_and_prune_version_history(config)
    assert result['version_history_retention'] == {'pruned': 2, 'cleaned': 2, 'skipped': []}
    assert [v['id'] for v in store.list_versions(sid) if not v['content_pruned_at']] == [versions[i]['id'] for i in (1, 3, 4)]
    for v in (versions[0], versions[2]):
        pruned = store.get_version(v['id'])
        assert pruned['result'] == {'title': 'Title'}
        for key in ('id', 'created_at', 'output_kind', 'content_sha256', 'parent_version_id'):
            assert pruned[key] == v[key]
    with store._tx() as db:
        assert list(map(tuple, db.execute('SELECT decision, score FROM reviews WHERE version_id=? ORDER BY seq',
                                         (versions[2]['id'],)))) == [('approve', 99), ('rework', 90)]
    assert not old_root.exists()
    assert (store.content_root / sid / 'frames' / (frames[0]['sha256'] + '.jpg')).exists()
    assert not (store.content_root / sid / 'frames' / (frames[1]['sha256'] + '.jpg')).exists()
    assert store.assert_synced(sid)
    assert store.eligible_sources()[0]['current_version_id'] == versions[4]['id']
    with pytest.raises(WorkflowError, match='version_content_pruned'):
        workflow.export_version(config['_workflow'], versions[2]['id'], store.data_root)

    target = tmp_path / 'restored'
    maintenance.restore(config, result['snapshot'], target)
    restored = workflow.make_store({**config['_workflow'], 'data_dir': str(target / 'workflow')})
    assert restored.assert_synced(sid)
    assert (restored.content_root / old_root.relative_to(store.content_root) / 'content.md').read_bytes() == old_content
    assert all(not v['content_pruned_at'] for v in restored.list_versions(sid))


def test_failed_verification_leaves_all_content(library, monkeypatch):
    config, store, sid, _, _ = library

    def fail(*args):
        raise WorkflowError('corrupt_object')

    monkeypatch.setattr(maintenance, '_verify_objects', fail)
    with pytest.raises(WorkflowError, match='corrupt_object'):
        maintenance.create_and_prune_version_history(config)
    assert all(not v['content_pruned_at'] for v in store.list_versions(sid))
    assert store.assert_synced(sid)
    assert not list((Path(config['backup_root']) / 'snapshots').glob('*.json'))


def test_retry_preserves_pre_prune_snapshot_until_next_normal_rotation(library, monkeypatch, tmp_path):
    config, store, sid, versions, frames = library
    config['keep_snapshots'] = 1
    original = version_retention._remove_files
    old_version = versions[0]
    old_file = store.content_root / sid / 'versions' / old_version['id'] / 'content.md'
    old_content = old_file.read_bytes()
    unique_frame = store.content_root / sid / 'frames' / (frames[1]['sha256'] + '.jpg')
    checkpoint = Path(config['backup_root']) / 'version-history-pending'

    def interrupt(_root, _db, _source, rows):
        assert old_version['id'] in {row['version_id'] for row in rows}
        assert checkpoint.exists()
        old_file.unlink(missing_ok=True)
        raise OSError('interrupted')

    monkeypatch.setattr(version_retention, '_remove_files', interrupt)
    result = maintenance.create_and_prune_version_history(config)
    assert result['version_history_error'] == 'OSError'
    pre_prune = result['snapshot']
    assert result['version_history_recovery_snapshot'] == pre_prune
    assert checkpoint.read_text(encoding='ascii').strip() == pre_prune
    assert maintenance.verify(config, pre_prune)
    assert not old_file.exists()
    assert store.assert_synced(sid)

    result = maintenance.create_and_prune_version_history(config)
    assert result['version_history_error'] == 'OSError'
    assert result['version_history_recovery_snapshot'] == pre_prune
    assert maintenance.verify(config, result['snapshot'])
    assert maintenance.verify(config, pre_prune)
    assert maintenance.verify(config, maintenance.create(config))
    assert maintenance.verify(config, pre_prune)

    monkeypatch.setattr(version_retention, '_remove_files', original)
    result = maintenance.create_and_prune_version_history(config)
    assert result['version_history_retention'] == {'pruned': 0, 'cleaned': 2, 'skipped': []}
    assert result['version_history_recovery_snapshot'] == pre_prune
    assert not checkpoint.exists()
    assert [v['id'] for v in store.list_versions(sid) if not v['content_pruned_at']] == [v['id'] for v in versions[-3:]]
    assert not unique_frame.exists()
    assert store.assert_synced(sid)

    target = tmp_path / 'restored'
    maintenance.restore(config, pre_prune, target)
    restored = workflow.make_store({**config['_workflow'], 'data_dir': str(target / 'workflow')})
    assert restored.get_version(old_version['id'])['result'] == old_version['result']
    assert (restored.content_root / old_file.relative_to(store.content_root)).read_bytes() == old_content
    assert (restored.content_root / unique_frame.relative_to(store.content_root)).read_bytes() == b'unique'
    assert restored.assert_synced(sid)

    latest = maintenance.create(config)
    snapshot_dir = Path(config['backup_root']) / 'snapshots'
    assert {path.stem for path in snapshot_dir.glob('*.json')} == {latest}
    assert maintenance.verify(config, latest)


def test_ordinary_snapshot_does_not_prune(library):
    config, store, sid, _, _ = library
    assert maintenance.verify(config, maintenance.create(config))
    assert all(not v['content_pruned_at'] for v in store.list_versions(sid))


def test_cleanup_skips_a_source_with_corrupt_content(library):
    config, store, sid, versions, _ = library
    old_file = store.content_root / sid / 'versions' / versions[0]['id'] / 'content.md'
    old_file.write_bytes(b'broken')
    result = maintenance.create_and_prune_version_history(config)
    assert result['version_history_retention'] == {
        'pruned': 0, 'cleaned': 0, 'skipped': [{'source_id': sid, 'reason': 'content_integrity'}],
    }
    assert all(not v['content_pruned_at'] for v in store.list_versions(sid))
    assert old_file.read_bytes() == b'broken'


@pytest.mark.parametrize(('decisions', 'quotas', 'kept'), [
    (['rework', 'approve', 'approve', 'approve'], (1, 1), {'v0', 'v3'}),
    (['approve', 'approve', 'approve', 'rework'], (1, 1), {'v3', 'v2'}),
    (['approve', 'approve', 'approve', 'approve'], (1, 1), {'v3'}),
    (['rework', None, 'rework', None], (1, 1), {'v3', 'v2'}),
    (['rework', 'approve', 'approve', 'low'], (1, 1), {'v2', 'v3'}),
    (['rework', 'approve', 'approve', 'rework'], (0, 1), {'v3'}),
    (['rework', 'rework', 'rework', 'rework'], (0, 1), {'v3'}),
])
def test_independent_history_quotas_and_latest_review(decisions, quotas, kept):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE versions (id TEXT, source_id TEXT, created_at TEXT, content_pruned_at TEXT);"
                     "CREATE TABLE reviews (seq INTEGER PRIMARY KEY, version_id TEXT, decision TEXT, score INTEGER);")
    for i, decision in enumerate(decisions):
        vid = f'v{i}'
        db.execute('INSERT INTO versions VALUES (?, ?, ?, NULL)', (vid, 's', str(i)))
        if decision:
            db.execute('INSERT INTO reviews(version_id,decision,score) VALUES (?, ?, ?)',
                       (vid, 'approve' if decision == 'low' else decision, 97 if decision == 'low' else 99))
    # Latest review supersedes an earlier approval.
    if decisions[0] == 'rework':
        db.execute('INSERT INTO reviews(version_id,decision,score) VALUES (?, ?, 99)', ('v0', 'approve'))
        db.execute('INSERT INTO reviews(version_id,decision,score) VALUES (?, ?, 90)', ('v0', 'rework'))
    db.execute("INSERT INTO versions VALUES ('current', 's', '9', NULL)")
    candidates = version_retention._candidates(db, {'id': 's', 'current_version_id': 'current'},
        {'approved_history': quotas[0], 'other_history': quotas[1]}, 98)
    assert {f'v{i}' for i in range(4)} - {row['id'] for row in candidates} == kept
