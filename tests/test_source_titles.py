import pytest

from personalkb.workflow_store import WorkflowError, title_metadata
from test_content_storage import setup


def test_source_title_retry_reset_and_conflicts(tmp_path):
    store, item, task, result = setup(tmp_path)
    sid = item['source']['id']
    version = store.finish(task['id'], task['lease_token'], result)
    vid = version['id']
    review = (sid, vid, version['content_sha256'], 99, 'approve', 'tester')
    first = store.review(*review, review_id='first', display_title='精简标题', expected_title_revision=0)
    store.set_display_title(sid, '之后的标题', 1, expected_version_id=vid)
    assert store.review(*review, review_id='first', display_title=' 精简标题 ', expected_title_revision=0) == first
    with pytest.raises(WorkflowError, match='review_conflict'):
        store.review(*review, review_id='first', display_title='其他标题', expected_title_revision=1)
    with pytest.raises(WorkflowError, match='title_conflict'):
        store.set_display_title(sid, '其他标题', 0, expected_version_id=vid)
    with pytest.raises(WorkflowError, match='invalid_title'):
        store.set_display_title(sid, 'bad\nname', 1, expected_version_id=vid)
    with store._tx() as db:
        assert title_metadata(db, sid)['title_revision'] == 2
        assert title_metadata(db, sid)['display_title'] == '之后的标题'
        assert db.execute('SELECT count(*) FROM reviews WHERE version_id=?', (vid,)).fetchone()[0] == 1
    assert store.set_display_title(sid, '', 2, expected_version_id=vid)['display_title'] is None
    assert store.get_version(vid) == version
    assert store.eligible_sources()[0]['id'] == sid
    store.delete_source(sid)
    with pytest.raises(WorkflowError, match='source_deleted'):
        store.set_display_title(sid, '其他标题', 2, expected_version_id=vid)


def test_current_note_uses_original_title_for_legacy_filename(tmp_path):
    store, item, task, result = setup(tmp_path)
    source = item['source']
    sid = source['id']
    result['title'] = source['original_name']
    version = store.finish(task['id'], task['lease_token'], result)
    with store._tx() as db:
        db.execute('INSERT INTO source_display_titles VALUES (?,?)', (sid, '来源原标题'))
    store.set_display_title(sid, '精简标题', 0, expected_version_id=version['id'])
    store.set_display_title(sid, '', 1, expected_version_id=version['id'])
    note = (store.content_root / sid / 'note.md').read_text(encoding='utf-8')
    assert '# 来源原标题\n' in note
    assert store.get_version(version['id']) == version


def test_title_file_failure_retries_without_disabling_approved_source(tmp_path, monkeypatch):
    from personalkb import content_storage

    store, item, task, result = setup(tmp_path)
    sid = item['source']['id']
    vid = store.finish(task['id'], task['lease_token'], result)
    store.review(sid, vid['id'], vid['content_sha256'], 99, 'approve', 'tester')
    note = store.content_root / sid / 'note.md'
    previous = note.read_bytes()
    original_write = content_storage.write

    def fail(*args):
        raise OSError('simulated disk write failure')

    monkeypatch.setattr(content_storage, 'write', fail)
    saved = store.set_display_title(sid, '新标题', 0, expected_version_id=vid['id'])
    assert saved['title_sync_status'] == 'pending' and saved['display_title'] == '新标题'
    assert note.read_bytes() == previous
    assert store.eligible_sources()[0]['id'] == sid
    monkeypatch.setattr(content_storage, 'write', original_write)
    saved = store.set_display_title(sid, '新标题', 1, expected_version_id=vid['id'])
    assert saved['title_revision'] == 1 and saved['title_sync_status'] == 'synced'
    assert '# 新标题\n' in note.read_text(encoding='utf-8')
    assert store.assert_synced(sid)
    note.write_text('tampered', encoding='utf-8')
    assert not store.eligible_sources()
