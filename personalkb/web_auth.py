import base64, hashlib, hmac, json, os, re, secrets
from pathlib import Path
from urllib.parse import urlsplit
from personalkb.workflow_store import WorkflowError

ROOT = Path(__file__).resolve().parent.parent

def hash_password(password, iterations):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return 'pbkdf2_sha256${}${}${}'.format(iterations, base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())

def validate_hash(value):
    try:
        algorithm, count, salt, digest = value.split('$')
        n = int(count)
        if algorithm != 'pbkdf2_sha256' or not 100000 <= n <= 5000000 or len(base64.b64decode(salt, altchars=b'-_', validate=True)) < 16 or len(base64.b64decode(digest, altchars=b'-_', validate=True)) != 32: raise ValueError()
        return n, base64.urlsafe_b64decode(salt), base64.urlsafe_b64decode(digest)
    except (ValueError, TypeError): raise WorkflowError('invalid_config') from None

def verify_password(password, encoded):
    n, salt, expected = validate_hash(encoded)
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, n), expected)

def load_auth(c):
    try:
        mode = c.get('deployment_mode', 'development')
        if mode not in ('development', 'production') or type(c.get('dispatch_enabled', True)) is not bool: raise ValueError()
        cfg = json.loads((ROOT / c.get('auth_config', 'config/auth.json')).read_text(encoding='utf-8-sig'))
        if type(cfg['enabled']) is not bool: raise ValueError()
        if mode == 'production' and not cfg['enabled']: raise ValueError()
        if not cfg['enabled']: return cfg
        if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', cfg['password_hash_env']): raise ValueError()
        for key in ('login_limit','login_window_seconds','api_limit','api_window_seconds'):
            if type(cfg[key]) is not int or cfg[key] <= 0: raise ValueError()
        if mode == 'production':
            if c['host'] != '127.0.0.1' or c.get('dispatch_enabled', True): raise ValueError()
            for host in c['trusted_hosts']:
                if not re.fullmatch(r'[a-zA-Z0-9.-]+',host) or '*' in host: raise ValueError()
            for origin in c['trusted_origins']:
                u=urlsplit(origin)
                if u.scheme != 'https' or not u.hostname or u.hostname not in c['trusted_hosts'] or u.path or u.query or u.fragment or u.username or u.password or '*' in origin: raise ValueError()
        from tools.demo_setup import dotenv
        path=ROOT / c['env_file']
        values=dotenv(path) if path.exists() else {}
        values.update(os.environ)
        cfg['password_hash']=values[cfg['password_hash_env']]
        validate_hash(cfg['password_hash'])
        return cfg
    except (OSError, ValueError, KeyError, TypeError): raise WorkflowError('invalid_config') from None
