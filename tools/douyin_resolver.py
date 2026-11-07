"""Isolated Douyin bridge supporting minimal detail and F2. Never print diagnostics or credentials."""
import asyncio
import contextlib
import json
import logging
import sys
from unittest.mock import patch



def metadata(payload, work_id, policy='strict'):
    if not isinstance(payload, dict) or type(payload.get('status_code')) is bool or payload.get('status_code') not in (None, 0, '0'):
        raise ValueError('invalid_status')
    detail = payload.get('aweme_detail')
    if not isinstance(detail, dict) or str(detail.get('aweme_id')) != work_id:
        raise ValueError('invalid_detail')
    if policy not in ('strict', 'authorized_playback'):
        raise ValueError('invalid_policy')
    if policy == 'strict':
        control = detail.get('video_control')
        if control is None:
            control = {}
        if not isinstance(control, dict):
            raise ValueError('download_permission_unknown')
        allow = control.get('allow_download')
        prevent_type = control.get('prevent_download_type')
        prevent = detail.get('prevent_download')
        if allow is False or (type(prevent_type) is int and prevent_type != 0) or prevent is True:
            raise ValueError('download_denied')
        if ((allow is not None and type(allow) is not bool) or
                (prevent_type is not None and type(prevent_type) is not int) or
                (prevent is not None and type(prevent) is not bool)):
            raise ValueError('download_permission_unknown')
        if not (allow is True or (type(prevent_type) is int and prevent_type == 0) or prevent is False):
            raise ValueError('download_permission_unknown')
    video = detail.get('video') or {}
    addresses = [x.get('play_addr') for x in video.get('bit_rate', []) if isinstance(x, dict)]
    addresses.append(video.get('play_addr'))
    for address in addresses:
        if isinstance(address, dict):
            urls = address.get('url_list')
            if isinstance(urls, list):
                for url in urls:
                    if isinstance(url, str) and url.startswith('https://'):
                        return {'work_id': work_id, 'title': str(detail.get('desc') or ''), 'media_url': url}
    raise ValueError('missing_media')


def safe_parse_json(response):
    if response is None or response.status_code != 200:
        raise ValueError('invalid_response')
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError('invalid_response')
    return payload


def disable_logging():
    f2_logger = logging.getLogger('f2')
    f2_logger.addHandler(logging.NullHandler())
    f2_logger.disabled = True
    f2_logger.propagate = False
    logging.disable(logging.CRITICAL)
    try:
        from loguru import logger
        logger.remove()
        logger.disable('f2')
    except ImportError:
        pass


@contextlib.contextmanager
def network_guard(mode, timeout=None, user_agent=None):
    """Permit only the single request required by the current SDK phase."""
    import httpx
    sync_send, async_send = httpx.Client.send, httpx.AsyncClient.send
    count = 0

    def check(request, expected):
        nonlocal count
        host = 'mssdk.bytedance.com' if expected == 'token' else 'www.douyin.com'
        method = 'POST' if expected == 'token' else 'GET'
        if mode != expected or count or request.url.scheme != 'https' or request.url.host != host or request.url.port not in (None, 443) or request.url.username or request.url.password or request.method != method:
            raise ValueError('network_denied')
        count += 1
        if expected == 'token':
            request.headers.pop('cookie', None)
            if user_agent is not None:
                request.headers['User-Agent'] = user_agent
            request.extensions['timeout'] = dict.fromkeys(('connect', 'read', 'write', 'pool'), timeout)

    def sync(client, request, **kwargs):
        check(request, 'token')
        kwargs['follow_redirects'] = False
        response = sync_send(client, request, **kwargs)
        if response.is_redirect:
            raise ValueError('redirect_denied')
        return response

    async def asynchronous(client, request, **kwargs):
        check(request, 'detail')
        kwargs['follow_redirects'] = False
        response = await async_send(client, request, **kwargs)
        if response.is_redirect:
            raise ValueError('redirect_denied')
        return response

    with patch.object(httpx.Client, 'send', sync), patch.object(httpx.AsyncClient, 'send', asynchronous):
        yield


def secure_mount(self, async_mode=False):
    import httpx
    transport = httpx.AsyncHTTPTransport if async_mode else httpx.HTTPTransport
    return {'all://': transport(verify=True, limits=self.limits, retries=0)}


async def fetch(data):
    if data.get('policy') not in ('strict', 'authorized_playback'):
        raise ValueError('invalid_policy')
    disable_logging()
    if data.get('mode', 'f2') == 'minimal_detail':
        return await fetch_minimal(data)
    if data.get('mode', 'f2') != 'f2':
        raise ValueError('invalid_mode')
    with network_guard('none'):
        from f2.apps.douyin.utils import TokenManager
        from f2.crawlers.base_crawler import BaseCrawler
        with patch.object(TokenManager, 'gen_real_msToken', return_value=''):
            from f2.apps.douyin.crawler import DouyinCrawler
            from f2.apps.douyin.model import PostDetail
            from f2.apps.douyin.api import DouyinAPIEndpoints as dyendpoint

    with patch.object(BaseCrawler, '_create_mount', secure_mount):
        return await _fetch_sdk(data, TokenManager, DouyinCrawler, PostDetail, dyendpoint)


async def fetch_minimal(data):
    import httpx, re, zlib
    for key in ('work_id', 'detail_aid', 'detail_version_code'):
        if not isinstance(data.get(key), str) or not re.fullmatch(r'[0-9]+', data[key]):
            raise ValueError('invalid_parameter')
    limit = data.get('max_detail_response_bytes')
    if type(limit) is not int or limit <= 0:
        raise ValueError('invalid_parameter')
    chunk_size = data.get('download_chunk_bytes')
    if type(chunk_size) is not int or chunk_size <= 0 or chunk_size > limit:
        raise ValueError('invalid_parameter')
    headers = {'Cookie': data['cookie'], 'User-Agent': data['user_agent'],
               'Referer': 'https://www.douyin.com/', 'Accept': 'application/json',
               'Accept-Encoding': 'gzip, deflate'}
    transport = httpx.AsyncHTTPTransport(verify=True, retries=0, trust_env=False)
    async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=data['timeout'], follow_redirects=False) as client:
        with network_guard('detail'):
            async with client.stream('GET', 'https://www.douyin.com/aweme/v1/web/aweme/detail',
                                     params={'aid': data['detail_aid'], 'version_code': data['detail_version_code'], 'aweme_id': data['work_id']}, headers=headers) as response:
                if response.status_code != 200:
                    raise ValueError('invalid_response')
                encoding = response.headers.get('content-encoding', '').strip().lower()
                if encoding not in ('', 'identity', 'gzip', 'deflate'):
                    raise ValueError('invalid_encoding')
                decoder = zlib.decompressobj(31 if encoding == 'gzip' else zlib.MAX_WBITS) if encoding in ('gzip', 'deflate') else None
                body = bytearray()
                raw_size = 0
                async for chunk in response.aiter_raw(chunk_size):
                    raw_size += len(chunk)
                    if raw_size > limit:
                        raise ValueError('response_too_large')
                    body.extend(decoder.decompress(chunk, limit - len(body) + 1) if decoder else chunk)
                    if len(body) > limit or (decoder and decoder.unconsumed_tail):
                        raise ValueError('response_too_large')
                if decoder:
                    body.extend(decoder.flush(limit - len(body) + 1))
                    if len(body) > limit or not decoder.eof or decoder.unused_data:
                        raise ValueError('invalid_response')

    return metadata(json.loads(body), data['work_id'], data['policy'])


async def _fetch_sdk(data, TokenManager, DouyinCrawler, PostDetail, dyendpoint):
    tokens = [value.strip() for part in data['cookie'].split(';')
              for name, sep, value in [part.partition('=')]
              if sep and name.strip() == 'msToken' and value.strip()]
    if len(set(tokens)) > 1:
        raise ValueError('conflicting_token')
    token = tokens[0] if tokens else ''
    if not token:
        with network_guard('token', data['timeout'], data['user_agent']):
            token = TokenManager.gen_real_msToken()
    if not isinstance(token, str) or not token.strip() or token == 'None':
        raise ValueError('invalid_token')
    kwargs = {'headers': {'User-Agent': data['user_agent'], 'Referer': 'https://www.douyin.com/'}, 'proxies': {'http://': None, 'https://': None}, 'timeout': data['timeout'], 'max_retries': 1, 'cookie': data['cookie']}
    with network_guard('none'):
        params = PostDetail(aweme_id=data['work_id'], msToken=token)
        crawler = DouyinCrawler(kwargs=kwargs)
    with network_guard('none'):
        await crawler.__aenter__()
    try:
        crawler.parse_json = safe_parse_json
        with network_guard('none'):
            endpoint = crawler.bogus_manager.model_2_endpoint(
                crawler.headers.get('User-Agent'), dyendpoint.POST_DETAIL, params.model_dump())
        with network_guard('detail'):
            result = await crawler._fetch_get_json(endpoint)
    finally:
        with network_guard('none'):
            await crawler.__aexit__(None, None, None)
    return metadata(result, data['work_id'], data['policy'])


class _Discard:
    def write(self, value): return len(value)
    def flush(self): pass


def main():
    try:
        data = json.load(sys.stdin)
        with contextlib.redirect_stdout(_Discard()), contextlib.redirect_stderr(_Discard()):
            result = asyncio.run(fetch(data))
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:
        code = str(exc) if type(exc) is ValueError and str(exc) in ('download_denied', 'download_permission_unknown') else 'resolver_failed'
        print(json.dumps({'error': code}))

if __name__ == '__main__':
    main()
