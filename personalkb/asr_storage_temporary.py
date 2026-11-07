import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from .asr_storage import StorageError, PreparedAudio, check_file, positive

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

class HTTPTransport:
    def __init__(self, config):
        self.config = config

    def request(self, url, key=None, payload=None, data=None, content_type=None):
        cfg = self.config['temporary']
        try:
            p = urllib.parse.urlsplit(url)
            host = p.hostname or ''
            if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
                raise StorageError('unsafe_url')
            if key is not None:
                valid = host in cfg['allowed_api_hosts']
            else:
                valid = host.endswith(cfg['allowed_upload_suffix'])
            if not valid: raise StorageError('unapproved_host')
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise StorageError('non_public_host')
            headers = {}
            if key is not None: headers['Authorization'] = 'Bearer ' + key
            if payload is not None:
                data = json.dumps(payload).encode()
                headers['Content-Type'] = 'application/json'
            if content_type: headers['Content-Type'] = content_type
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=self.config['request_timeout_seconds']) as response:
                limit = int(self.config['response_max_bytes'])
                raw = response.read(limit + 1)
                if len(raw) > limit: raise StorageError('response_too_large')
                return response.status, json.loads(raw) if raw.strip() else {}
        except StorageError: raise
        except urllib.error.HTTPError as e:
            e.close()
            raise StorageError('http_error') from None
        except (OSError, TimeoutError): raise StorageError('network_unconfirmed') from None
        except (ValueError, TypeError, UnicodeError): raise StorageError('response_format') from None

class TemporaryStorage:
    def __init__(self, config, secrets, transport=None):
        self.config, self.secrets = config, secrets
        try:
            self.settings = config['temporary']
            if not isinstance(self.settings, dict) or not self.settings: raise KeyError()
            lifetime = self.settings['lifetime_seconds']
            if type(lifetime) is not int or not 0 < lifetime <= 172800: raise KeyError()
            base = self.settings['api_base_url']
            hosts = self.settings['allowed_api_hosts']
            suffix = self.settings['allowed_upload_suffix']
            if not isinstance(base, str) or not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) or not h or h != h.lower() for h in hosts): raise KeyError()
            if not isinstance(suffix, str) or not suffix.startswith('.') or len(suffix) < 2: raise KeyError()
            parsed = urllib.parse.urlsplit(base)
            if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.hostname not in hosts or parsed.query or parsed.fragment: raise KeyError()
            self.key = secrets[self.settings['api_key_env']]
            if not isinstance(self.key, str) or not self.key.strip(): raise KeyError()
        except (KeyError, TypeError, ValueError): raise StorageError('invalid_config') from None
        self.transport = transport or HTTPTransport(config)

    def prepare(self, path, model):
        path, digest, size = check_file(path, self.config)
        if not isinstance(model, str) or not model.strip(): raise StorageError('invalid_model')
        asset = str(uuid.uuid4())
        name = asset + '.wav'
        try:
            url = self.settings['api_base_url'].rstrip('/') + '/uploads?' + urllib.parse.urlencode({'action':'getPolicy', 'model':model})
            status, result = self.transport.request(url, key=self.key)
            if not 200 <= status < 300: raise StorageError('policy_failed')
            policy = result['data']
            required = ('upload_dir','upload_host','oss_access_key_id','signature','policy','x_oss_object_acl','x_oss_forbid_overwrite')
            if not isinstance(policy, dict) or any(not isinstance(policy.get(k), str) or not policy[k].strip() for k in required): raise StorageError('invalid_policy')
            object_key = policy['upload_dir'].rstrip('/') + '/' + name
            boundary = 'upload' + uuid.uuid4().hex
            pairs = {'OSSAccessKeyId':policy['oss_access_key_id'], 'Signature':policy['signature'], 'policy':policy['policy'], 'x-oss-object-acl':policy['x_oss_object_acl'], 'x-oss-forbid-overwrite':policy['x_oss_forbid_overwrite'], 'key':object_key, 'success_action_status':'200'}
            parts = [('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"\r\n\r\n'+str(v)+'\r\n').encode() for k,v in pairs.items()]
            parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+name+'"\r\nContent-Type: audio/wav\r\n\r\n').encode()+path.read_bytes()+b'\r\n')
            parts.append(('--'+boundary+'--\r\n').encode())
            status, _ = self.transport.request(policy['upload_host'], data=b''.join(parts), content_type='multipart/form-data; boundary='+boundary)
            if not 200 <= status < 300: raise StorageError('upload_failed')
            return PreparedAudio('temporary', model, asset, digest, size, time.time()+self.settings['lifetime_seconds'], 'oss://'+object_key, object_key)
        except StorageError: raise
        except (KeyError, TypeError, ValueError, OSError): raise StorageError('storage_failed') from None

    def cleanup(self, asset):
        if not isinstance(asset, PreparedAudio) or asset.backend != 'temporary': raise StorageError('backend_mismatch')
        return {'status':'provider_managed', 'deleted':False}
