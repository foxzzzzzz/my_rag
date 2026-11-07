"""Bounded DNS and pinned HTTPS transport with original-host TLS verification."""
import ipaddress
import io
import http.client
import queue
import re
import shutil
import socket
import time
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request
from .workflow_store import WorkflowError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def _resolve(host,deadline,timeout):
    result=queue.Queue(maxsize=1)
    def run():
        try:result.put(socket.getaddrinfo(host,443,type=socket.SOCK_STREAM))
        except Exception:result.put(None)
    threading.Thread(target=run,daemon=True,name='douyin-dns').start()
    remaining=min(timeout,deadline-time.monotonic())
    if remaining<=0:raise WorkflowError('douyin_timeout')
    try:addresses=result.get(timeout=remaining)
    except queue.Empty:raise WorkflowError('douyin_timeout') from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise WorkflowError('douyin_unsafe_url')
    return addresses[0][4][0]


def _validate(url, hosts, suffix=False):
    try:
        p = urlsplit(url)
        host = p.hostname
        if p.scheme != 'https' or not host or p.username is not None or p.password is not None or p.port not in (None, 443): raise ValueError()
        if not any(host == h or (suffix and host.endswith('.' + h)) for h in hosts): raise ValueError()
        return p
    except (ValueError, OSError):
        raise WorkflowError('douyin_unsafe_url') from None


class _DeadlineRaw(io.RawIOBase):
    def __init__(self,raw,sock,deadline,timeout):self.raw,self.sock,self.deadline,self.timeout=raw,sock,deadline,timeout
    def readable(self):return True
    def readinto(self,b):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise WorkflowError('douyin_timeout')
        self.sock.settimeout(min(self.timeout,remaining))
        return self.raw.readinto(b)
    def fileno(self):return self.raw.fileno()
    def close(self):
        try:self.raw.close()
        finally:super().close()


class _DeadlineSocket:
    def __init__(self,sock,deadline,timeout):self.sock,self.deadline,self.timeout=sock,deadline,timeout
    def __getattr__(self,name):return getattr(self.sock,name)
    def makefile(self,mode='rb',*args,**kwargs):
        if mode!='rb':raise OSError('unsupported_transport_mode')
        # The underlying SocketIO owns its normal socket reference, so closing
        # the HTTP connection does not invalidate a response still being read.
        raw=self.sock.makefile('rb',buffering=0)
        return io.BufferedReader(_DeadlineRaw(raw,self.sock,self.deadline,self.timeout))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self,host,*,ip,deadline,**kwargs):
        super().__init__(host,**kwargs);self.ip,self.deadline=ip,deadline
    def connect(self):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise WorkflowError('douyin_timeout')
        address=ipaddress.ip_address(self.ip)
        raw=socket.socket(socket.AF_INET6 if address.version==6 else socket.AF_INET,socket.SOCK_STREAM)
        try:
            raw.settimeout(min(self.timeout,remaining));raw.connect((self.ip,self.port))
            remaining=self.deadline-time.monotonic()
            if remaining<=0:raise WorkflowError('douyin_timeout')
            raw.settimeout(min(self.timeout,remaining))
            tls=self._context.wrap_socket(raw,server_hostname=self.host)
            self.sock=_DeadlineSocket(tls,self.deadline,self.timeout)
        except BaseException:raw.close();raise


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self,ip,deadline):super().__init__();self.ip,self.deadline=ip,deadline
    def https_open(self,req):
        def connection(host,**kwargs):return _PinnedHTTPSConnection(host,ip=self.ip,deadline=self.deadline,**kwargs)
        return self.do_open(connection,req,context=self._context)


def _open(url, cfg, hosts, suffix, deadline):
    for count in range(cfg['max_redirects'] + 1):
        parsed=_validate(url, hosts, suffix)
        address=_resolve(parsed.hostname,deadline,cfg.get('dns_timeout_seconds',cfg['request_timeout_seconds']))
        opener = build_opener(ProxyHandler({}),_NoRedirect(),_PinnedHTTPSHandler(address,deadline))
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise WorkflowError('douyin_timeout')
        headers = {'User-Agent': cfg['user_agent']}
        if suffix:
            if cfg.get('media_referer') != 'https://www.douyin.com/': raise WorkflowError('invalid_douyin_config')
            headers['Referer'] = cfg['media_referer']
        req = Request(url, headers=headers)
        try:
            response = opener.open(req, timeout=min(cfg['request_timeout_seconds'], remaining))
        except HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                e.close()
                raise WorkflowError('douyin_http_failed') from None
            response = e
        except OSError:
            raise WorkflowError('douyin_http_failed') from None
        if response.status in (301, 302, 303, 307, 308):
            location = response.headers.get('Location')
            response.close()
            if not location or count == cfg['max_redirects']: raise WorkflowError('douyin_redirect_limit')
            url = urljoin(url, location)
            continue
        if response.status != 200:
            response.close()
            raise WorkflowError('douyin_http_failed')
        return url, response
    raise WorkflowError('douyin_redirect_limit')


def resolve_share_url(url, cfg):
    deadline = time.monotonic() + cfg['resolve_timeout_seconds']
    # Parsing a canonical work ID is local and must not wait for DNS.
    p = _validate(url, cfg['share_hosts'])
    match = re.fullmatch(r'/video/([0-9]+)/?', p.path)
    if match and p.hostname in ('douyin.com', 'www.douyin.com'): return match.group(1)
    final, response = _open(url, cfg, cfg['share_hosts'], False, deadline)
    response.close()
    p = urlsplit(final)
    match = re.fullmatch(r'/video/([0-9]+)/?', p.path)
    if match and p.hostname in ('douyin.com', 'www.douyin.com'): return match.group(1)
    raise WorkflowError('invalid_share')


def download_stream(url, target, cfg):
    target = Path(target)
    deadline = time.monotonic() + cfg['download_timeout_seconds']
    created = False
    response = None
    try:
        _, response = _open(url, cfg, cfg['media_hosts'], True, deadline)
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > cfg['max_download_bytes']): raise WorkflowError('douyin_size_limit')
        if shutil.disk_usage(target.parent).free < cfg['min_free_bytes']: raise WorkflowError('disk_low')
        with target.open('xb') as out:
            created = True
            size = 0
            while True:
                if time.monotonic() >= deadline: raise WorkflowError('douyin_timeout')
                chunk = response.read(cfg['download_chunk_bytes'])
                if time.monotonic() >= deadline: raise WorkflowError('douyin_timeout')
                if not chunk: break
                size += len(chunk)
                if size > cfg['max_download_bytes']: raise WorkflowError('douyin_size_limit')
                if shutil.disk_usage(target.parent).free - len(chunk) < cfg['min_free_bytes']: raise WorkflowError('disk_low')
                out.write(chunk)
        if size==0 or (length is not None and size!=int(length)):raise WorkflowError('douyin_download_failed')
        return {'bytes': size}
    except WorkflowError:
        if created: target.unlink(missing_ok=True)
        raise
    except (OSError, ValueError):
        if created: target.unlink(missing_ok=True)
        raise WorkflowError('douyin_download_failed') from None
    finally:
        if response is not None: response.close()
