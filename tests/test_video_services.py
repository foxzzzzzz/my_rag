import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from personalkb.video_services import ProviderClient

class Transport:
    def __init__(self, response): self.response, self.calls = response, []
    def request(self, url, key=None, payload=None, headers=None):
        self.calls.append((url, key, payload, headers)); return 200, self.response

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.model = json.loads(Path('config/demo-models.json').read_text(encoding='utf8'))
        self.strategy = json.loads(Path('config/demo-run.json').read_text(encoding='utf8'))
        self.cfg = {'strategy': self.strategy, 'transport': {'allowed_api_hosts': ['dashscope.aliyuncs.com', 'api.deepseek.com'], 'allowed_oss_suffix': 'aliyuncs.com', 'request_timeout_seconds': 90, 'response_max_bytes': 4194304}, 'prices': {'text': [2,8], 'vision': [1,10], 'asr_per_second': '0.00008'}}
    def client(self, result):
        transport = Transport(result)
        return ProviderClient(self.model, self.cfg, {'DASHSCOPE_API_KEY':'secret', 'DEEPSEEK_API_KEY':'secret'}, transport), transport
    def test_submit(self):
        c,t = self.client({'output': {'task_id':'abc-1'}})
        self.assertEqual(c.submit_asr(SimpleNamespace(file_url='https://test', asr_headers=lambda: {'X-DashScope-Async':'enable'})), 'abc-1')
        self.assertTrue(t.calls[0][2]['parameters']['timestamp_alignment_enabled'])
    def test_query(self):
        c,_ = self.client({'output': {'task_status':'RUNNING'}})
        self.assertEqual(c.query_asr('abc')['task_status'], 'RUNNING')
    def test_download_no_key(self):
        c,t = self.client({'transcripts':[{'sentences':[{'begin_time':0,'end_time':1000,'text':'hello'}]}]})
        self.assertEqual(c.download_asr('https://bucket.aliyuncs.com/a', 2)['segments'][0]['end_seconds'], 1)
        self.assertIsNone(t.calls[0][1])
    def test_reject_download_host(self):
        c,_ = self.client({})
        with self.assertRaises(RuntimeError): c.download_asr('https://evil.com/a', 2)
    def test_reject_timestamp(self):
        c,_ = self.client({'transcripts':[{'sentences':[{'begin_time':2,'end_time':1,'text':'x'}]}]})
        with self.assertRaises(RuntimeError): c.download_asr('https://bucket.aliyuncs.com/a', 2)
    def test_summary_invalid(self):
        c,_ = self.client({'choices':[{'message':{'content':'bad'},'finish_reason':'stop'}]})
        with self.assertRaises(RuntimeError): c.summarize('body','title')
    def test_truncated(self):
        c,_ = self.client({'choices':[{'message':{'content':'x'},'finish_reason':'length'}]})
        with self.assertRaises(RuntimeError): c.summarize('body','title')
    def test_vision(self):
        c,t = self.client({'choices':[{'message':{'content':'画面'},'finish_reason':'stop'}], 'usage':{'prompt_tokens':100,'completion_tokens':20}})
        with TemporaryDirectory(dir='tmp') as directory:
            image = Path(directory) / 'frame.jpg'
            image.write_bytes(b'jpeg')
            result = c.vision(image)
        self.assertEqual(result['content'], '画面')
        self.assertFalse(t.calls[0][2]['enable_thinking'])
        self.assertEqual(result['estimated_cost_cny'], '0.0003')
    def test_insecure_url_rejected_before_transport(self):
        c,t = self.client({})
        with self.assertRaises(RuntimeError): c.download_asr('http://bucket.aliyuncs.com/a', 2)
        self.assertEqual(t.calls, [])
    def test_summary_success_and_thinking_disabled(self):
        c,t = self.client({'choices':[{'message':{'content':'{"summary":"s","notes":"n"}'},'finish_reason':'stop'}]})
        self.assertEqual(c.summarize('body','title')['structured']['notes'], 'n')
        self.assertEqual(t.calls[0][2]['thinking'], {'type':'disabled'})
    def test_managed_headers(self):
        c,t = self.client({'output': {'task_id':'abc'}})
        c.submit_asr(SimpleNamespace(file_url='https://test', asr_headers=lambda: {'X-DashScope-Async':'enable'}))
        self.assertNotIn('X-DashScope-OssResourceResolve', t.calls[0][3])
    def test_private_dns_rejected(self):
        from unittest.mock import patch
        from personalkb.video_services import _Transport
        with patch('personalkb.video_services.socket.getaddrinfo', return_value=[(0,0,0,'',('127.0.0.1',443))]), patch('personalkb.video_services.build_opener') as opener:
            with self.assertRaises(RuntimeError): _Transport(self.cfg['transport']).request('https://dashscope.aliyuncs.com')
            opener.assert_not_called()
