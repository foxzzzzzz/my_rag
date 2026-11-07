import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from personalkb.douyin import load_douyin_config
from personalkb.douyin_http import resolve_share_url, download_stream
from personalkb.workflow_store import WorkflowError

PUBLIC = [(2, 1, 6, '', ('8.8.8.8', 443))]
PRIVATE = [(2, 1, 6, '', ('127.0.0.1', 443))]
class Response(io.BytesIO):
    def __init__(self, content=b'', status=200, headers=None):
        super().__init__(content); self.status=status; self.headers=headers or {}
class HTTPTests(unittest.TestCase):
    def setUp(self): self.cfg=load_douyin_config('config/douyin.json')
    @patch('personalkb.douyin_http.socket.getaddrinfo', return_value=PRIVATE)
    def test_private_rejected(self, dns):
        with self.assertRaises(WorkflowError): resolve_share_url('https://v.douyin.com/a/', self.cfg)
    @patch('personalkb.douyin_http.socket.getaddrinfo', return_value=PUBLIC)
    def test_canonical(self, dns): self.assertEqual(resolve_share_url('https://www.douyin.com/video/123', self.cfg), '123')
    @patch('personalkb.douyin_http.socket.getaddrinfo', return_value=PUBLIC)
    @patch('personalkb.douyin_http.build_opener')
    def test_redirect_bad_host(self, opener, dns):
        opener.return_value.open.return_value=Response(status=302,headers={'Location':'https://evil.example/a'})
        with self.assertRaises(WorkflowError): resolve_share_url('https://v.douyin.com/a/',self.cfg)
    @patch('personalkb.douyin_http.socket.getaddrinfo', return_value=PUBLIC)
    @patch('personalkb.douyin_http.build_opener')
    def test_size_and_cleanup(self, opener, dns):
        self.cfg['max_download_bytes']=3
        opener.return_value.open.return_value=Response(b'1234')
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'raw.mp4'
            with self.assertRaises(WorkflowError): download_stream('https://x.douyinvod.com/a',target,self.cfg)
            self.assertFalse(target.exists())
        request=opener.return_value.open.call_args.args[0]
        self.assertNotIn('Cookie',dict(request.header_items()))
    @patch('personalkb.douyin_http.socket.getaddrinfo', return_value=PUBLIC)
    @patch('personalkb.douyin_http.build_opener')
    def test_declared_size(self, opener, dns):
        self.cfg['max_download_bytes']=3
        opener.return_value.open.return_value=Response(b'',headers={'Content-Length':'4'})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(WorkflowError): download_stream('https://douyinvod.com/a',Path(d)/'raw.mp4',self.cfg)

    @patch('personalkb.douyin_http.socket.getaddrinfo', return_value=PUBLIC)
    @patch('personalkb.douyin_http.build_opener')
    def test_media_referer_no_credentials(self, opener, dns):
        opener.return_value.open.return_value=Response(b'abc',headers={'Content-Length':'3'})
        with tempfile.TemporaryDirectory() as d:
            download_stream('https://douyinvod.com/a',Path(d)/'v',self.cfg)
        headers=dict(opener.return_value.open.call_args.args[0].header_items())
        self.assertEqual(headers.get('Referer'),'https://www.douyin.com/')
        self.assertNotIn('Cookie',headers); self.assertNotIn('Authorization',headers)
        self.cfg['media_referer']='https://evil/\r\nCookie: secret'
        with tempfile.TemporaryDirectory() as d, self.assertRaises(WorkflowError):
            download_stream('https://douyinvod.com/a',Path(d)/'v',self.cfg)
