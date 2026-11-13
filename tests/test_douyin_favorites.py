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


def test_collection_author_is_not_the_account_identity():
    videos = {}
    favorites.append_videos([{'aweme_id': '1', 'video': {}, 'author': {'sec_uid': 'author-id'}}], videos)
    assert 'account_id' not in videos['1']


def test_authenticated_account_requires_login_and_stable_user_id():
    from urllib.parse import quote
    user = {'app': {'user': {'isLogin': True, 'info': {'secUid': 'MS4wLj'+'a'*20, 'nickname': 'A'}}}}
    assert favorites.authenticated_account(quote(json.dumps(user))) == {'account_id': 'MS4wLj'+'a'*20, 'account_label': 'A'}
    user['app']['user']['isLogin'] = False
    assert favorites.authenticated_account(json.dumps(user)) is None
    user['app']['user']['isLogin'] = True
    user['app']['user']['info']['secUid'] = 'self'
    assert favorites.authenticated_account(json.dumps(user)) is None
    assert favorites.authenticated_account('invalid') is None


def test_pagination_scrolls_until_response_arrives():
    responses = []
    class Mouse:
        def move(self, x, y): pass
        def wheel(self, x, y): pass
    class Page:
        mouse = Mouse()
        count = 0
        def wait_for_timeout(self, timeout):
            self.count += 1
            if self.count == 3:
                responses.append(object())
    page = Page()
    settings = {'viewport': {'width': 1440, 'height': 1400}, 'scroll_pixels': 1700, 'page_timeout_ms': 7500}
    assert favorites.scroll_for_collection(page, responses, 0, settings)
    assert page.count == 3


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
