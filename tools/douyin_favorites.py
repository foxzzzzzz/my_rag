"""Read video metadata from the account's signed-in Douyin favorites page."""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from personalkb.douyin import load_douyin_config
from personalkb.workflow_store import WorkflowError
from tools.demo_setup import ConfigError, dotenv

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://www.douyin.com'
FAVORITES = ORIGIN + '/user/self?from_tab_name=main&showTab=favorite_collection'
COLLECTION_PATH = '/aweme/v1/web/aweme/listcollection'


def browser_cookies(header):
    cookies = {}
    for field in header.split(';'):
        name, separator, value = field.strip().partition('=')
        if separator and name:
            cookies.setdefault(name, {'name': name, 'value': value, 'url': ORIGIN, 'secure': True})
    return list(cookies.values())


def is_collection(response):
    url = urlsplit(response.url)
    return url.scheme == 'https' and url.netloc == 'www.douyin.com' and url.path.rstrip('/') == COLLECTION_PATH


def collection_items(payload):
    if not isinstance(payload, dict) or type(payload.get('status_code')) is not int or payload['status_code'] != 0:
        raise WorkflowError('collection_invalid')
    items = payload.get('aweme_list')
    has_more = payload.get('has_more')
    if type(has_more) not in (bool, int) or has_more not in (0, 1) or not isinstance(items, list):
        raise WorkflowError('collection_invalid')
    return items, bool(has_more)


def append_videos(items, videos):
    for item in items:
        if not isinstance(item, dict) or item.get('images') or not isinstance(item.get('video'), dict):
            continue
        work_id = str(item.get('aweme_id', ''))
        if not re.fullmatch(r'[0-9]+', work_id) or work_id in videos:
            continue
        author = item.get('author')
        description = item.get('desc')
        description = description if isinstance(description, str) else ''
        title = item.get('title')
        if not isinstance(title, str) or not title.strip():
            caption = description.split('#', 1)[0].splitlines()
            title = caption[0].strip() if caption else ''
        videos[work_id] = {
            'id': work_id,
            'title': title,
            'description': description,
            'author': author.get('nickname') if isinstance(author, dict) else None,
            'url': f'{ORIGIN}/video/{work_id}',
        }


def read_favorites(cookies, settings, limit, browser_channel):
    try:
        from playwright.sync_api import Error, TimeoutError, sync_playwright
    except ImportError:
        return {'status': 'browser_dependency_missing', 'videos': []}

    responses = []
    statuses = []
    videos = {}

    def result(status):
        return {'status': status, 'http_statuses': statuses, 'videos': list(videos.values())[:limit]}

    def record(response):
        if is_collection(response):
            responses.append(response)

    timeout = settings['initial_timeout_ms']
    viewport = settings['viewport']
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=browser_channel, headless=True, timeout=timeout)
            try:
                context = browser.new_context(locale='zh-CN', viewport=viewport)
                context.add_cookies(cookies)
                page = context.new_page()
                page.on('response', record)
                try:
                    with page.expect_response(is_collection, timeout=timeout):
                        page.goto(FAVORITES, wait_until='domcontentloaded', timeout=timeout)
                except TimeoutError:
                    login_visible = page.get_by_text('登录', exact=True).filter(visible=True).count() > 0
                    return result('login_required' if login_visible else 'collection_timeout')

                for index in range(settings['max_pages']):
                    if index >= len(responses):
                        try:
                            with page.expect_response(is_collection, timeout=settings['page_timeout_ms']):
                                page.mouse.move(viewport['width'] * 0.7, viewport['height'] * 0.8)
                                page.mouse.wheel(0, settings['scroll_pixels'])
                        except TimeoutError:
                            return result('pagination_incomplete')

                    response = responses[index]
                    statuses.append(response.status)
                    if response.status != 200:
                        return result('collection_http_error')
                    items, has_more = collection_items(response.json())
                    append_videos(items, videos)
                    if len(videos) >= limit or not has_more:
                        return result('ok')
                return result('pagination_incomplete')
            finally:
                browser.close()
    except (ValueError, WorkflowError):
        return result('collection_invalid')
    except Error:
        return result('browser_error')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--douyin-config', type=Path, default=ROOT / 'config/douyin.json')
    parser.add_argument('--settings', type=Path, default=ROOT / 'config/douyin-favorites.json')
    parser.add_argument('--browser-channel', choices=('chromium', 'msedge', 'chrome'))
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(argv)

    try:
        settings = json.loads(args.settings.read_text(encoding='utf-8-sig'))
        limit = settings['limit'] if args.limit is None else args.limit
        if type(limit) is not int or limit < 1:
            parser.error('--limit must be a positive integer')
        cookie_env = load_douyin_config(args.douyin_config)['cookie_env']
        cookies = browser_cookies(os.environ.get(cookie_env, dotenv(args.env_file).get(cookie_env, '')))
        if cookies:
            result = read_favorites(cookies, settings, limit, args.browser_channel or settings['browser_channel'])
        else:
            result = {'status': 'missing_cookie', 'videos': []}
    except (ConfigError, WorkflowError, OSError, ValueError, KeyError, TypeError):
        result = {'status': 'invalid_config', 'videos': []}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
