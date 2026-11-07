import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from personalkb.asr_storage import create_storage, StorageError, PreparedAudio
from personalkb.asr_storage_temporary import HTTPTransport, NoRedirect

C = json.loads((Path(__file__).resolve().parents[1]/'config/asr-storage.json').read_text(encoding='utf-8'))
class Fake:
    def __init__(self): self.calls=[]
    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if len(self.calls)==1:
            return 200, {'data':dict(upload_dir='dir', upload_host='https://upload.oss-cn-beijing.aliyuncs.com', oss_access_key_id='id', signature='sig', policy='policy', x_oss_object_acl='private', x_oss_forbid_overwrite='true')}
        return 200, {}
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'user.wav'; self.path.write_bytes(b'audio'); self.fake=Fake()
    def tearDown(self): self.tmp.cleanup()
    def store(self, config=C): return create_storage(config, {'DASHSCOPE_API_KEY':'secret'}, self.fake)
    def test_default(self): self.assertEqual(type(self.store()).__name__, 'TemporaryStorage')
    def test_invalid_backend(self):
        with self.assertRaises(StorageError): self.store({**C,'backend':'wrong'})
        self.assertFalse(self.fake.calls)
    def test_upload(self):
        asset=self.store().prepare(self.path,'model name')
        self.assertIn('model=model+name',self.fake.calls[0][0]); self.assertNotIn('key',self.fake.calls[1][1]); self.assertTrue(asset.file_url.startswith('oss://')); self.assertEqual(asset.asr_headers()['X-DashScope-OssResourceResolve'],'enable'); self.assertNotIn(b'user.wav',self.fake.calls[1][1]['data'])
    def test_oversize(self):
        with self.assertRaises(StorageError): self.store({**C,'max_upload_bytes':1}).prepare(self.path,'m')
        self.assertFalse(self.fake.calls)
    def test_missing(self):
        with self.assertRaises(StorageError): self.store().prepare(self.path/'missing','m')
        self.assertFalse(self.fake.calls)
    def test_redaction(self):
        a=self.store().prepare(self.path,'m'); self.assertNotIn(a.file_url,repr(a)); self.assertNotIn('file_url',a.safe_metadata())
    def test_expiry(self):
        a=self.store().prepare(self.path,'m'); self.assertTrue(a.is_expired(a.expires_at))
    def test_cleanup(self):
        a=PreparedAudio('managed_oss','m','id','hash',1,1,'url')
        with self.assertRaises(StorageError): self.store().cleanup(a)
    def test_unsafe_host(self):
        with self.assertRaises(StorageError) as cm: HTTPTransport(C).request('https://evil.example/', key='secret')
        self.assertNotIn('secret',str(cm.exception))

    def test_upload_domain_rejected_before_dns(self):
        with patch('personalkb.asr_storage_temporary.socket.getaddrinfo') as dns:
            with self.assertRaises(StorageError):
                HTTPTransport(C).request('https://evil.example/file', data=b'audio')
            dns.assert_not_called()

    def test_private_dns_rejected_before_http(self):
        address = [(2, 1, 6, '', ('127.0.0.1', 443))]
        with patch('personalkb.asr_storage_temporary.socket.getaddrinfo', return_value=address), patch('personalkb.asr_storage_temporary.urllib.request.build_opener') as opener:
            with self.assertRaises(StorageError) as error:
                HTTPTransport(C).request('https://dashscope.aliyuncs.com/api/v1/uploads', key='secret')
            self.assertEqual(error.exception.code, 'non_public_host')
            opener.assert_not_called()

    def test_redirects_disabled(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example'))

    def test_malformed_secrets(self):
        for secrets in (None, [], {'DASHSCOPE_API_KEY':123}):
            with self.assertRaises(StorageError): create_storage(C, secrets, self.fake)
        self.assertFalse(self.fake.calls)
if __name__=='__main__': unittest.main()

class ConfigurationTests(unittest.TestCase):
    def test_bad_config(self):
        for config in (None, [], {**C,'temporary':None}, {**C,'temporary':{}}, *[{**C,'temporary':{**C['temporary'],k:v}} for k,v in [('api_base_url',3),('api_base_url','http://example.com'),('allowed_api_hosts','example.com'),('allowed_upload_suffix',[]),('lifetime_seconds',172801),('lifetime_seconds',1.5)]]):
            with self.subTest(config=config), self.assertRaises(StorageError): create_storage(config, {'DASHSCOPE_API_KEY':'x'}, Fake())
    def test_blank_model(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'a'); f.flush(); fake=Fake()
            with self.assertRaises(StorageError): create_storage(C, {'DASHSCOPE_API_KEY':'x'},fake).prepare(f.name,'   ')
            self.assertFalse(fake.calls)
    def test_bad_policy(self):
        class Bad(Fake):
            def request(self, url, **kwargs): return 200, {'data':{'upload_dir':123}}
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'a'); f.flush()
            with self.assertRaises(StorageError): create_storage(C, {'DASHSCOPE_API_KEY':'x'},Bad()).prepare(f.name,'m')
