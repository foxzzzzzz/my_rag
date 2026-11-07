import re
import time
import uuid
from urllib.parse import urlsplit

from .asr_storage import PreparedAudio, StorageError, check_file, positive


class ManagedOSSStorage:
    def __init__(self, config, secrets, bucket_factory=None, ownership=None):
        if not isinstance(config, dict) or not isinstance(secrets, dict):
            raise StorageError('invalid_config')
        self.config = config
        self.settings = config.get('managed_oss', {})
        s = self.settings
        if not isinstance(s, dict):
            raise StorageError('invalid_config')
        region = s.get('region', '')
        endpoint = s.get('endpoint', '')
        bucket = s.get('bucket', '')
        prefix = s.get('prefix', '')
        if not isinstance(region, str) or not re.fullmatch(r'cn-[a-z0-9-]+', region):
            raise StorageError('invalid_config')
        if endpoint != f'https://oss-{region}.aliyuncs.com':
            raise StorageError('invalid_config')
        if not isinstance(bucket, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
            raise StorageError('invalid_config')
        if not isinstance(prefix, str) or not prefix.endswith('/') or '\\' in prefix or any(ord(c) < 32 for c in prefix) or any(part in ('', '.', '..') for part in prefix[:-1].split('/')):
            raise StorageError('invalid_config')
        ttl = positive(s.get('url_ttl_seconds'))
        if ttl > 604800 or int(ttl) != ttl:
            raise StorageError('invalid_config')
        positive(config.get('request_timeout_seconds'))
        env = s.get('credential_env', {})
        if not isinstance(env, dict) or any(not isinstance(v, str) for v in env.values()):
            raise StorageError('invalid_config')
        self.credentials = {k: secrets.get(env.get(k, ''), '') for k in ('access_key_id', 'access_key_secret', 'security_token')}
        if any(not isinstance(v, str) for v in self.credentials.values()):
            raise StorageError('invalid_config')
        if not self.credentials['access_key_id'] or not self.credentials['access_key_secret']:
            raise StorageError('missing_credentials')
        self.factory = bucket_factory or self._sdk_bucket
        self.owned = {}
        self.ownership = ownership

    @staticmethod
    def _sdk_bucket(config, credentials):
        try:
            import oss2
            from oss2.credentials import StaticCredentialsProvider
        except ImportError:
            raise StorageError('missing_sdk') from None
        s = config['managed_oss']
        provider = StaticCredentialsProvider(credentials['access_key_id'], credentials['access_key_secret'], credentials['security_token'] or None)
        auth = oss2.ProviderAuthV4(provider)
        return oss2.Bucket(auth, s['endpoint'], s['bucket'], region=s['region'], connect_timeout=config['request_timeout_seconds'])

    def prepare(self, path, model):
        if not isinstance(model, str) or not model.strip():
            raise StorageError('invalid_model')
        path, digest, size = check_file(path, self.config)
        asset_id = uuid.uuid4().hex
        key = self.settings['prefix'] + asset_id + '.wav'
        try:
            bucket = self.factory(self.config, self.credentials)
        except StorageError:
            raise
        except Exception:
            raise StorageError('managed_client_failed') from None
        expires = time.time() + self.settings['url_ttl_seconds']
        metadata = dict(asset_id=asset_id, backend='managed_oss', object_key=key, source_sha256=digest, size_bytes=size, model=model, expires_at=expires, scope={k:self.settings[k] for k in ('bucket','endpoint','region','prefix')})
        if self.ownership is not None:
            self.ownership.register(metadata)
        self.owned[asset_id] = key
        try:
            bucket.put_object_from_file(key, str(path), headers={'x-oss-object-acl': 'private'})
        except Exception:
            # The server may have accepted the object before the client timed out.
            # Only this attempt's unique key can be removed here.
            try:
                bucket.delete_object(key)
                del self.owned[asset_id]
                if self.ownership is not None: self.ownership.deleted(metadata)
            except Exception:
                raise StorageError('managed_upload_failed_cleanup_unconfirmed') from None
            raise StorageError('managed_upload_failed') from None
        try:
            url = bucket.sign_url('GET', key, int(self.settings['url_ttl_seconds']), slash_safe=True)
            parsed = urlsplit(url)
            host = self.settings['bucket'] + '.' + urlsplit(self.settings['endpoint']).hostname
            if parsed.scheme != 'https' or parsed.hostname != host or parsed.username or parsed.password or parsed.port:
                raise ValueError()
        except Exception:
            try:
                bucket.delete_object(key)
                del self.owned[asset_id]
                if self.ownership is not None: self.ownership.deleted(metadata)
            except Exception:
                raise StorageError('managed_sign_failed_cleanup_unconfirmed') from None
            raise StorageError('managed_sign_failed') from None
        return PreparedAudio('managed_oss', model, asset_id, digest, size, expires, url, key)

    def cleanup(self, asset):
        if not isinstance(asset, PreparedAudio) or asset.backend != 'managed_oss' or (self.ownership is None and self.owned.get(asset.asset_id) != asset.object_key) or (self.ownership is not None and not self.ownership.owns(asset)) or not asset.object_key.startswith(self.settings['prefix']):
            raise StorageError('invalid_asset')
        try:
            self.factory(self.config, self.credentials).delete_object(asset.object_key)
        except StorageError:
            raise
        except Exception:
            raise StorageError('managed_cleanup_failed') from None
        self.owned.pop(asset.asset_id, None)
        if self.ownership is not None: self.ownership.deleted(asset)
        return {'status': 'deleted', 'deleted': True}
