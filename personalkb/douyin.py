"""Strict parsing for Douyin share text."""
import re
from urllib.parse import urlsplit
from .workflow_store import WorkflowError

_URL = re.compile(r'https?://[^\s\u4e00-\u9fff<>"\'，。！？、]+', re.I)

def normalize_share(text):
    if not isinstance(text, str):
        raise WorkflowError('invalid_share')
    urls = _URL.findall(text)
    if len(urls) != 1:
        raise WorkflowError('invalid_share')
    raw = urls[0].rstrip('.,!?;，。！？；')
    try:
        p = urlsplit(raw)
        if p.scheme != 'https' or p.username is not None or p.password is not None or p.port is not None or p.fragment:
            raise ValueError()
        host = p.hostname
        if host in ('www.douyin.com', 'douyin.com') and re.fullmatch(r'/video/[0-9]+/?', p.path):
            return 'https://www.douyin.com/video/' + p.path.split('/')[2]
        if host == 'v.douyin.com' and re.fullmatch(r'/[A-Za-z0-9]+/?', p.path):
            return 'https://v.douyin.com/' + p.path.strip('/') + '/'
    except ValueError:
        pass
    raise WorkflowError('invalid_share')


def load_douyin_config(path):
    import json, math
    try:
        with open(path, encoding='utf-8-sig') as f: cfg = json.load(f)
        def require(condition):
            if not condition: raise ValueError()
        require(type(cfg['enabled']) is bool)
        require(cfg['resolver_mode'] in ('minimal_detail', 'f2'))
        require(cfg['download_policy'] in ('strict', 'authorized_playback'))
        require(cfg['media_referer'] == 'https://www.douyin.com/')
        for key in ('detail_aid', 'detail_version_code'):
            require(isinstance(cfg[key], str) and re.fullmatch(r'[0-9]+', cfg[key]) is not None)
        require(type(cfg['max_detail_response_bytes']) is int and cfg['max_detail_response_bytes'] > 0)
        for key in ('resolver_python', 'cookie_env', 'user_agent'):
            require(isinstance(cfg[key], str))
        for key in ('dns_timeout_seconds', 'resolve_timeout_seconds', 'api_timeout_seconds', 'download_timeout_seconds', 'request_timeout_seconds'):
            value = cfg[key]
            require(type(value) in (int, float) and math.isfinite(value) and value > 0)
        for key in ('max_resolver_output_bytes', 'max_download_bytes', 'min_free_bytes', 'download_chunk_bytes'):
            require(type(cfg[key]) is int and cfg[key] > 0)
        require(cfg['download_chunk_bytes'] <= cfg['max_download_bytes'])
        require(cfg['download_chunk_bytes'] <= cfg['max_detail_response_bytes'])
        require(type(cfg['max_redirects']) is int and cfg['max_redirects'] >= 0)
        for key in ('share_hosts', 'media_hosts'):
            hosts = cfg[key]
            require(isinstance(hosts, list) and bool(hosts))
            for host in hosts:
                require(isinstance(host, str) and len(host) <= 253 and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in host.split('.')))
        return cfg
    except (OSError, ValueError, TypeError, KeyError):
        raise WorkflowError('invalid_douyin_config') from None


def resolve_with_f2(work_id, cookie, cfg):
    import json, os, subprocess, threading
    from pathlib import Path
    if not cfg.get('enabled'):
        raise WorkflowError('douyin_disabled')
    if not isinstance(cookie, str) or not cookie.strip():
        raise WorkflowError('missing_douyin_cookie')
    if not cfg.get('resolver_python'):
        raise WorkflowError('douyin_resolver_unavailable')
    if not isinstance(work_id, str) or not re.fullmatch(r'[0-9]+', work_id):
        raise WorkflowError('invalid_share')
    payload = json.dumps({'work_id': work_id, 'cookie': cookie, 'timeout': cfg['api_timeout_seconds'], 'user_agent': cfg['user_agent'], 'policy': cfg['download_policy'], 'mode': cfg['resolver_mode'], 'detail_aid': cfg['detail_aid'], 'detail_version_code': cfg['detail_version_code'], 'max_detail_response_bytes': cfg['max_detail_response_bytes'], 'download_chunk_bytes': cfg['download_chunk_bytes']}).encode()
    proc = None
    try:
        env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH') if k in os.environ}
        helper = Path(__file__).resolve().parent.parent / 'tools' / 'douyin_resolver.py'
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        proc = subprocess.Popen([cfg['resolver_python'], '-I', str(helper)], cwd=str(helper.parent.parent), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        limit = cfg['max_resolver_output_bytes']
        output = bytearray()
        exceeded = threading.Event()
        def read(stream, capture):
            total = 0
            while True:
                chunk = stream.read(4096)
                if not chunk: break
                total += len(chunk)
                if total > limit:
                    exceeded.set()
                    proc.kill()
                    break
                if capture: output.extend(chunk)
        readers = [threading.Thread(target=read, args=(proc.stdout, True), daemon=True), threading.Thread(target=read, args=(proc.stderr, False), daemon=True)]
        for thread in readers: thread.start()
        def send():
            try:
                proc.stdin.write(payload)
                proc.stdin.close()
            except (OSError, ValueError): pass
        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        proc.wait(timeout=cfg['resolve_timeout_seconds'])
        for thread in readers: thread.join(timeout=1)
        if proc.returncode or exceeded.is_set() or any(t.is_alive() for t in readers): raise ValueError()
        result = json.loads(output)
        if isinstance(result, dict) and set(result) == {'error'} and result['error'] in ('download_denied', 'download_permission_unknown'):
            raise WorkflowError(result['error'])
        if not isinstance(result, dict) or result.get('work_id') != work_id or not isinstance(result.get('title'), str) or not isinstance(result.get('media_url'), str): raise ValueError()
        return result
    except WorkflowError:
        raise
    except Exception:
        if proc is not None:
            try: proc.kill()
            except OSError: pass
            try: proc.wait(timeout=1)
            except Exception: pass
        raise WorkflowError('douyin_resolver_failed') from None

    finally:
        if proc is not None:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try: stream.close()
                except (OSError, ValueError): pass
            for thread in locals().get('readers', []): thread.join(timeout=1)
