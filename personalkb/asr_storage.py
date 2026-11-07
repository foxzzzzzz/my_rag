import hashlib
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

class StorageError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

@dataclass(frozen=True)
class PreparedAudio:
    backend: str
    model: str
    asset_id: str
    source_sha256: str
    size_bytes: int
    expires_at: float
    file_url: str = field(repr=False)
    object_key: str = field(default='', repr=False)

    def safe_metadata(self):
        return {k: getattr(self, k) for k in ('backend','model','asset_id','source_sha256','size_bytes','expires_at')}

    def asr_headers(self):
        result = {'X-DashScope-Async': 'enable'}
        if self.backend == 'temporary':
            result['X-DashScope-OssResourceResolve'] = 'enable'
        return result

    def is_expired(self, now=None):
        return (time.time() if now is None else now) >= self.expires_at

def positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise StorageError('invalid_config')
    return value

def check_file(path, config):
    limit = positive(config.get('max_upload_bytes'))
    try:
        path = Path(path)
        size = path.stat().st_size
        if not path.is_file(): raise OSError()
        if size == 0: raise StorageError('empty_file')
        if size > limit: raise StorageError('file_too_large')
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk)
        return path, digest.hexdigest(), size
    except StorageError: raise
    except (OSError, TypeError, ValueError): raise StorageError('file_unavailable') from None

def create_storage(config, secrets, transport=None, bucket_factory=None, ownership=None):
    if not isinstance(config, dict) or not isinstance(secrets, dict): raise StorageError('invalid_config')
    positive(config.get('max_upload_bytes'))
    positive(config.get('request_timeout_seconds'))
    positive(config.get('response_max_bytes'))
    backend = config.get('backend', 'temporary')
    if backend == 'temporary':
        from .asr_storage_temporary import TemporaryStorage
        return TemporaryStorage(config, secrets, transport)
    if backend == 'managed_oss':
        from .asr_storage_managed import ManagedOSSStorage
        return ManagedOSSStorage(config, secrets, bucket_factory=bucket_factory, ownership=ownership)
    raise StorageError('invalid_backend')
