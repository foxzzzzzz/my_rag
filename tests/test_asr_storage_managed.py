import copy
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from personalkb.asr_storage import StorageError
from personalkb.asr_storage_managed import ManagedOSSStorage

class Bucket:
    def __init__(self): self.calls = []
    def put_object_from_file(self, *a, **kw): self.calls.append(('put', a, kw))
    def sign_url(self, *a, **kw):
        self.calls.append(('sign', a, kw))
        return 'https://test-bucket.oss-cn-beijing.aliyuncs.com/a?secret=hidden'
    def delete_object(self, key): self.calls.append(('delete', key))

class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path('config/asr-storage.json').read_text(encoding='utf-8'))
        self.config['managed_oss']['bucket'] = 'test-bucket'
        self.secrets = {'PERSONALKB_OSS_ACCESS_KEY_ID':'id', 'PERSONALKB_OSS_ACCESS_KEY_SECRET':'secret'}
        self.bucket = Bucket()
        self.tmp = tempfile.TemporaryDirectory(dir='tmp')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'a.wav'
        self.path.write_bytes(b'audio')
    def storage(self): return ManagedOSSStorage(self.config, self.secrets, lambda c, s: self.bucket)
    def test_upload_and_cleanup(self):
        s = self.storage(); a = s.prepare(self.path, 'model')
        self.assertEqual(self.bucket.calls[0][2]['headers'], {'x-oss-object-acl':'private'})
        self.assertEqual(self.bucket.calls[1][1][0], 'GET')
        self.assertEqual(self.bucket.calls[1][1][2], 3600)
        self.assertNotIn('secret', repr(a)); self.assertNotIn('object_key', a.safe_metadata())
        self.assertTrue(s.cleanup(a)['deleted'])
        with self.assertRaises(StorageError): s.cleanup(a)
    def test_credentials(self):
        with self.assertRaises(StorageError): ManagedOSSStorage(self.config, {}, None)
    def test_config_validation(self):
        for key, value in [('endpoint','http://oss-cn-beijing.aliyuncs.com'), ('prefix','../'), ('prefix',''), ('url_ttl_seconds',604801), ('url_ttl_seconds',float('nan'))]:
            original = self.config['managed_oss'][key]; self.config['managed_oss'][key] = value
            with self.assertRaises(StorageError): self.storage()
            self.config['managed_oss'][key] = original
    def test_oversize(self):
        self.config['max_upload_bytes'] = 1
        with self.assertRaises(StorageError): self.storage().prepare(self.path, 'model')
        self.assertFalse(self.bucket.calls)
    def test_wrong_asset(self):
        s = self.storage(); a = s.prepare(self.path, 'model')
        for bad in (replace(a, backend='temporary'), replace(a, object_key='other'), replace(a, asset_id='unknown')):
            with self.assertRaises(StorageError): s.cleanup(bad)
        self.assertEqual(len(self.bucket.calls), 2)
    def test_sign_failure_cleanup(self):
        self.bucket.sign_url = lambda *a, **kw: 'https://evil.invalid/secret'
        with self.assertRaises(StorageError) as e: self.storage().prepare(self.path, 'model')
        self.assertEqual(e.exception.code, 'managed_sign_failed')
        self.assertEqual(self.bucket.calls[-1][0], 'delete')
    def test_cleanup_failure_redacted(self):
        s = self.storage(); a = s.prepare(self.path, 'model')
        def fail(*a): raise RuntimeError('secret url and key')
        self.bucket.delete_object = fail
        with self.assertRaises(StorageError) as e: s.cleanup(a)
        self.assertEqual(str(e.exception), 'managed_cleanup_failed')
        self.assertIn(a.asset_id, s.owned)
    def test_missing_model(self):
        with self.assertRaises(StorageError): self.storage().prepare(self.path, '')
        self.assertFalse(self.bucket.calls)

    def test_malformed_config(self):
        for value in (None, []):
            config = copy.deepcopy(self.config)
            config['managed_oss'] = value
            with self.assertRaises(StorageError):
                ManagedOSSStorage(config, self.secrets)
            config = copy.deepcopy(self.config)
            config['managed_oss']['credential_env'] = value
            with self.assertRaises(StorageError):
                ManagedOSSStorage(config, self.secrets)

    def test_upload_timeout_cleans_own_key(self):
        def timeout(key, *args, **kwargs):
            self.bucket.calls.append(('put', key))
            raise TimeoutError('private url credential')
        self.bucket.put_object_from_file = timeout
        s = self.storage()
        with self.assertRaises(StorageError) as error:
            s.prepare(self.path, 'model')
        self.assertEqual(error.exception.code, 'managed_upload_failed')
        self.assertEqual(self.bucket.calls[0][1], self.bucket.calls[1][1])
        self.assertEqual(self.bucket.calls[1][0], 'delete')
        self.assertFalse(s.owned)

    def test_upload_timeout_cleanup_unconfirmed(self):
        def fail(*args, **kwargs): raise TimeoutError('private url credential')
        self.bucket.put_object_from_file = fail
        self.bucket.delete_object = fail
        s = self.storage()
        with self.assertRaises(StorageError) as error:
            s.prepare(self.path, 'model')
        self.assertEqual(str(error.exception), 'managed_upload_failed_cleanup_unconfirmed')
        self.assertEqual(len(s.owned), 1)
        self.assertFalse(self.bucket.calls)

    def test_client_failure_does_not_delete(self):
        def fail(*args): raise StorageError('missing_sdk')
        s = ManagedOSSStorage(self.config, self.secrets, fail)
        with self.assertRaises(StorageError) as error: s.prepare(self.path, 'model')
        self.assertEqual(error.exception.code, 'missing_sdk')
        self.assertFalse(s.owned)
        self.assertFalse(self.bucket.calls)

if __name__ == '__main__': unittest.main()
