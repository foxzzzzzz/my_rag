import json

import pytest

from personalkb.workflow_store import WorkflowError
from tools import douyin_favorites as favorites


def test_preserve_collection_order_across_pages_and_skip_non_videos():
    videos = {}
    first_page = [
        {'aweme_id': '20', 'video': {}, 'desc': 'First #tag', 'author': {'nickname': 'A'}},
        {'aweme_id': '30', 'images': [{}], 'video': {}},
    ]
    second_page = [
        {'aweme_id': '20', 'video': {}, 'desc': 'Duplicate'},
        {'aweme_id': 10, 'video': {}, 'title': 'Second'},
        {'aweme_id': '40', 'desc': 'Non-video'},
    ]
    favorites.append_videos(first_page, videos)
    favorites.append_videos(second_page, videos)
    assert list(videos) == ['20', '10']
    assert videos['20'] == {
        'id': '20', 'title': 'First', 'description': 'First #tag', 'author': 'A',
        'url': 'https://www.douyin.com/video/20',
    }
    assert videos['10']['title'] == 'Second'


def test_empty_collection_is_distinct_from_a_business_error():
    assert favorites.collection_items({'status_code': 0, 'aweme_list': [], 'has_more': 0}) == ([], False)
    with pytest.raises(WorkflowError, match='collection_invalid'):
        favorites.collection_items({'status_code': 403, 'aweme_list': [], 'has_more': 0})


def test_cli_missing_cookie_does_not_start_browser(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv('PERSONALKB_DOUYIN_COOKIE', raising=False)
    assert favorites.main(['--env-file', str(tmp_path / 'missing.env')]) == 1
    assert json.loads(capsys.readouterr().out) == {'status': 'missing_cookie', 'videos': []}


@pytest.mark.parametrize('status,http_statuses', [
    ('collection_http_error', [403]),
    ('pagination_incomplete', [200]),
])
def test_cli_reports_fetch_failure_without_leaking_credentials(tmp_path, capsys, monkeypatch, status, http_statuses):
    env_file = tmp_path / 'test.env'
    env_file.write_text('PERSONALKB_DOUYIN_COOKIE=sessionid=test-secret', encoding='utf-8')
    monkeypatch.delenv('PERSONALKB_DOUYIN_COOKIE', raising=False)

    def read_favorites(cookies, settings, limit, channel):
        assert cookies[0]['value'] == 'test-secret'
        assert limit == 3
        return {'status': status, 'http_statuses': http_statuses, 'videos': []}

    monkeypatch.setattr(favorites, 'read_favorites', read_favorites)
    assert favorites.main(['--env-file', str(env_file), '--limit', '3']) == 1
    output = capsys.readouterr().out
    assert 'test-secret' not in output
    assert json.loads(output)['http_statuses'] == http_statuses
