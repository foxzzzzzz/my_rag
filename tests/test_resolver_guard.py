import asyncio
import unittest
from unittest.mock import patch

try:
    import httpx
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tmp' / 'web-deps'))
    import httpx

try:
    import f2
except ImportError:
    f2 = None
from tools.douyin_resolver import network_guard


class NetworkGuardTests(unittest.TestCase):
    def test_secure_transport_factory(self):
        from types import SimpleNamespace
        from tools.douyin_resolver import secure_mount
        limits = object()
        with patch.object(httpx, 'HTTPTransport') as sync_factory, patch.object(httpx, 'AsyncHTTPTransport') as async_factory:
            secure_mount(SimpleNamespace(limits=limits))
            secure_mount(SimpleNamespace(limits=limits), async_mode=True)
        sync_factory.assert_called_once_with(verify=True, limits=limits, retries=0)
        async_factory.assert_called_once_with(verify=True, limits=limits, retries=0)

    def test_sync_allowlist_timeout_cookie_redirect_and_limit(self):
        requests = []
        def send(client, request, **kwargs):
            requests.append((request, kwargs))
            return httpx.Response(200, request=request)
        with patch.object(httpx.Client, 'send', send):
            with network_guard('token', 3):
                client = httpx.Client()
                client.post('https://mssdk.bytedance.com/test', headers={'Cookie': 'secret=x'})
                with self.assertRaises(ValueError):
                    client.post('https://mssdk.bytedance.com/test')
        request, kwargs = requests[0]
        self.assertNotIn('cookie', request.headers)
        self.assertEqual(request.extensions['timeout']['read'], 3)
        self.assertFalse(kwargs['follow_redirects'])

    def test_denied_and_redirect(self):
        def send(client, request, **kwargs):
            return httpx.Response(302, headers={'location': 'https://evil.example'}, request=request)
        with patch.object(httpx.Client, 'send', send):
            with network_guard('none'):
                with self.assertRaises(ValueError):
                    httpx.Client().post('https://mssdk.bytedance.com/test')
            with network_guard('token', 1):
                with self.assertRaises(ValueError):
                    httpx.Client().post('https://evil.example/test')
            with network_guard('token', 1):
                with self.assertRaises(ValueError):
                    httpx.Client().post('https://mssdk.bytedance.com/test')

    def test_async_detail_once(self):
        async def run():
            async def send(client, request, **kwargs):
                self.assertFalse(kwargs['follow_redirects'])
                return httpx.Response(200, request=request)
            with patch.object(httpx.AsyncClient, 'send', send):
                with network_guard('detail'):
                    async with httpx.AsyncClient() as client:
                        await client.get('https://www.douyin.com/test')
                        with self.assertRaises(ValueError):
                            await client.get('https://www.douyin.com/test')
        asyncio.run(run())

@unittest.skipIf(f2 is None, 'F2 SDK is optional')
class FetchIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_offline_token_paths(self):
        import socket
        from tools.douyin_resolver import fetch, disable_logging
        disable_logging()
        calls = []
        def sync(client, request, **kwargs):
            calls.append(('sync', request.url.host, request.method, request.headers.get('cookie'), request.headers.get('user-agent')))
            return httpx.Response(200, headers={'set-cookie': 'msToken=' + 'x' * 120}, request=request)
        async def async_send(client, request, **kwargs):
            calls.append(('async', request.url.host, request.method))
            return httpx.Response(200, json={'status_code': 0, 'aweme_detail': {'aweme_id': '123', 'video_control': {'allow_download': True}, 'video': {'play_addr': {'url_list': ['https://example.com/video']}}}}, request=request)
        def blocked(*args, **kwargs):
            raise AssertionError('socket blocked')
        data = {'policy': 'strict', 'cookie': 'bare; msToken=synthetic', 'user_agent': 'test-agent', 'timeout': 3, 'work_id': '123'}
        with patch.object(socket.socket, 'connect', blocked), patch.object(httpx.Client, 'send', sync), patch.object(httpx.AsyncClient, 'send', async_send):
            from f2.apps.douyin.utils import TokenManager
            original = TokenManager.gen_real_msToken
            await fetch(data)
            self.assertEqual([x[0] for x in calls], ['async'])
            self.assertEqual(TokenManager.gen_real_msToken, original)
            calls.clear()
            data['cookie'] = 'bare; other=1'
            await fetch(data)
            self.assertEqual([x[0] for x in calls], ['sync', 'async'])
            self.assertEqual(calls[0][1:], ('mssdk.bytedance.com', 'POST', None, 'test-agent'))
            calls.clear()
            with patch.object(TokenManager, 'gen_real_msToken', return_value=''):
                with self.assertRaises(ValueError):
                    await fetch(data)
            self.assertEqual(calls, [])
            data['cookie'] = 'msToken=one; msToken=two'
            with self.assertRaises(ValueError):
                await fetch(data)

class MinimalDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_get_and_limits(self):
        import json, gzip
        from tools.douyin_resolver import fetch
        data={'policy':'strict','mode':'minimal_detail','work_id':'123','detail_aid':'6383','detail_version_code':'190500','cookie':'secret','user_agent':'test','timeout':3,'max_detail_response_bytes':1024,'download_chunk_bytes':64}
        payload=json.dumps({'aweme_detail':{'aweme_id':'123','video_control':{'allow_download':False}}}).encode()
        calls=[]
        class Stream(httpx.AsyncByteStream):
            def __init__(self, content): self.content=content
            async def __aiter__(self): yield self.content
        async def send(client,request,**kwargs):
            calls.append(request)
            return httpx.Response(200,headers={'content-encoding':'gzip'},stream=Stream(gzip.compress(payload)),request=request)
        with patch.object(httpx.AsyncClient,'send',send):
            with self.assertRaisesRegex(ValueError,'download_denied'): await fetch(data)
        self.assertEqual(len(calls),1); self.assertEqual(calls[0].method,'GET')
        self.assertEqual(calls[0].url.path,'/aweme/v1/web/aweme/detail')
        self.assertEqual(dict(calls[0].url.params),{'aid':'6383','version_code':'190500','aweme_id':'123'})
        data['max_detail_response_bytes']=64
        with patch.object(httpx.AsyncClient,'send',send):
            with self.assertRaises(ValueError): await fetch(data)
        data['detail_aid']='https://evil'
        with patch.object(httpx.AsyncClient,'send',send):
            with self.assertRaisesRegex(ValueError,'invalid_parameter'): await fetch(data)

    async def test_redirect_and_transport_security(self):
        from tools.douyin_resolver import fetch
        data={'policy':'strict','mode':'minimal_detail','work_id':'1','detail_aid':'1','detail_version_code':'2','cookie':'secret','user_agent':'test','timeout':3,'max_detail_response_bytes':1024,'download_chunk_bytes':64}
        original=httpx.AsyncHTTPTransport
        async def redirect(client,request,**kwargs):
            self.assertFalse(kwargs['follow_redirects'])
            return httpx.Response(302,headers={'location':'https://evil.example'},request=request)
        with patch.object(httpx,'AsyncHTTPTransport',wraps=original) as transport, patch.object(httpx.AsyncClient,'send',redirect):
            with self.assertRaisesRegex(ValueError,'redirect_denied'): await fetch(data)
        transport.assert_called_once_with(verify=True,retries=0,trust_env=False)

    async def test_gzip_expansion_and_truncation(self):
        import gzip
        from tools.douyin_resolver import fetch
        data={'policy':'strict','mode':'minimal_detail','work_id':'1','detail_aid':'1','detail_version_code':'2','cookie':'secret','user_agent':'test','timeout':3,'max_detail_response_bytes':128,'download_chunk_bytes':32}
        class Stream(httpx.AsyncByteStream):
            def __init__(self, content): self.content=content
            async def __aiter__(self): yield self.content
        compressed=gzip.compress(b'x'*1000)
        self.assertLess(len(compressed),128)
        for content in (compressed, gzip.compress(b'{}')[:-3]):
            async def send(client,request,**kwargs):
                return httpx.Response(200,headers={'content-encoding':'gzip'},stream=Stream(content),request=request)
            with self.subTest(size=len(content)), patch.object(httpx.AsyncClient,'send',send), self.assertRaises(ValueError):
                await fetch(data)
