import argparse, json, os, signal, sqlite3, stat, subprocess, sys, tempfile, time, urllib.request
from contextlib import closing, contextmanager
try:
    import fcntl
except ImportError:
    fcntl = None
from pathlib import Path
from urllib.parse import urlsplit
from deploy.preflight import probe
ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'personalkb'
IMAGE = 'personalkb:local'
CANDIDATE = 'personalkb:deploy-candidate'
ROLLBACK = 'personalkb:deploy-rollback'

class DeployError(Exception):
    pass

class DeploymentInterrupted(DeployError):
    pass

def run(args, *, stream=False, timeout=15, **kwargs):
    result = subprocess.run(args, check=True, text=True, stdout=None if stream else subprocess.PIPE, stderr=None if stream else subprocess.PIPE, timeout=timeout, **kwargs)
    return (result.stdout or '').strip()

def paths(root):
    root = Path(root).resolve()
    return {'CONFIG_DIR': root / 'config', 'STATE_DIR': root / 'state', 'SECRET_FILE': root / 'secrets/personalkb.env', 'BACKUP_DIR': root / 'backups'}

def compose(env, *args, stream=False, timeout=15):
    return run(['docker', 'compose', '--project-name', PROJECT, '-f', str(ROOT / 'deploy/compose.yaml'), *args], env=env, stream=stream, timeout=timeout)

def inspect_services(env, deadline=None, timeout=15):
    services = {}

    def remaining():
        if deadline is None:
            return timeout
        left = deadline - time.monotonic()
        if left <= 0:
            raise DeployError('Health verification timed out')
        return min(left, timeout)
    for service in ('web', 'worker'):
        ids = compose(env, 'ps', '--all', '-q', service, timeout=remaining()).splitlines()
        if len(ids) > 1:
            raise DeployError('Multiple containers for ' + service)
        if ids:
            obj = json.loads(run(['docker', 'inspect', ids[0]], timeout=remaining()))[0]
            labels = obj['Config']['Labels'] or {}
            if labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.service') != service:
                raise DeployError('Unexpected container ownership')
            services[service] = obj
    if len(services) not in (0, 2):
        raise DeployError('Partial deployment detected')
    return services

def validate_mounts(services, dirs):
    expected = {'/state': dirs['STATE_DIR'], '/app/tmp': dirs['STATE_DIR'] / 'tmp', '/tmp': dirs['STATE_DIR'] / 'tmp', '/app/config': dirs['CONFIG_DIR'], '/run/secrets/personalkb.env': dirs['SECRET_FILE'], '/backups': dirs['BACKUP_DIR']}
    statuses = {obj['State']['Status'] for obj in services.values()}
    if statuses and statuses != {'running'} and not statuses <= {'created', 'exited'}:
        raise DeployError('Existing containers are not consistently running or stopped')
    for obj in services.values():
        mounts = {m['Destination']: m for m in obj['Mounts']}
        for target, source in expected.items():
            m = mounts.get(target)
            readonly = target in ('/app/config', '/run/secrets/personalkb.env')
            if not m or m.get('Type') != 'bind' or Path(m['Source']).resolve() != source.resolve() or (m['RW'] == readonly):
                raise DeployError('Existing container mounts do not match: ' + target)
    if services and any((not p.is_file() for p in (dirs['STATE_DIR'] / 'workflow/workflow.sqlite3', dirs['STATE_DIR'] / 'budget.sqlite'))):
        raise DeployError('Existing workflow database or budget ledger missing')
    if services and len({obj['Image'] for obj in services.values()}) != 1:
        raise DeployError('Existing container images differ')

class NoRedirect(urllib.request.HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def url_ok(url, timeout, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        body = json.load(response)
        return response.status == 200 and isinstance(body, dict) and (body.get('ok') is True)

def health(env, origin, port, image_id, settings):
    deadline = time.monotonic() + settings['health_timeout_seconds']
    while True:
        try:
            services = inspect_services(env, deadline, settings['docker_timeout_seconds'])
            if len(services) == 2 and all((o['State']['Status'] == 'running' and o['Image'] == image_id for o in services.values())):
                host = urlsplit(origin).netloc
                remaining = max(0.001, deadline - time.monotonic())
                if url_ok(f'http://127.0.0.1:{port}/healthz', min(remaining, settings['request_timeout_seconds']), {'Host': host, 'X-Forwarded-Proto': 'https'}):
                    remaining = deadline - time.monotonic()
                    if remaining > 0 and url_ok(origin + '/healthz', min(remaining, settings['request_timeout_seconds'])):
                        return
        except DeploymentInterrupted:
            raise
        except (OSError, ValueError, KeyError, subprocess.SubprocessError, DeployError):
            pass
        if time.monotonic() >= deadline:
            raise DeployError('Health verification failed')
        time.sleep(min(settings['health_interval_seconds'], max(0, deadline - time.monotonic())))

def prepare(root):
    dirs = paths(root)
    for key in ('CONFIG_DIR', 'STATE_DIR', 'BACKUP_DIR'):
        if not dirs[key].is_dir():
            raise DeployError('Required directory missing: ' + key)
    if not (dirs['STATE_DIR'] / 'tmp').is_dir() or not dirs['SECRET_FILE'].is_file():
        raise DeployError('State tmp directory or secret file missing')
    database = (dirs['STATE_DIR'] / 'workflow/workflow.sqlite3').is_file()
    ledger = (dirs['STATE_DIR'] / 'budget.sqlite').is_file()
    if database != ledger:
        raise DeployError('Workflow database and budget ledger must both exist or both be absent')
    workflow_dir = dirs['STATE_DIR'] / 'workflow'
    if workflow_dir.is_symlink():
        raise DeployError('Workflow directory must not be a symlink')
    if not database and workflow_dir.exists() and (not workflow_dir.is_dir() or any(workflow_dir.iterdir())):
        raise DeployError('Workflow directory contains existing data')
    config = dirs['CONFIG_DIR'] / 'web.json'
    for file in dirs['CONFIG_DIR'].glob('*.json'):
        if not file.is_file() or stat.S_IMODE(file.stat().st_mode) & 18:
            raise DeployError('Configuration must not be group/world writable')
    web = json.loads(config.read_text(encoding='utf-8-sig'))
    if not isinstance(web, dict) or not isinstance(web.get('trusted_origins'), list) or (not web['trusted_origins']) or (not isinstance(web['trusted_origins'][0], str)) or (not isinstance(web.get('trusted_hosts'), list)):
        raise DeployError('Invalid web configuration structure')
    origin = web['trusted_origins'][0]
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or (parsed.hostname not in web['trusted_hosts']):
        raise DeployError('Invalid public origin')
    port = web['port']
    settings = json.loads((ROOT / 'config/deployment.json').read_text(encoding='utf-8-sig'))
    override = dirs['CONFIG_DIR'] / 'deployment.json'
    if override.exists():
        settings = json.loads(override.read_text(encoding='utf-8-sig'))
    if not isinstance(settings, dict):
        raise DeployError('Invalid deployment configuration structure')
    for key in ('health_timeout_seconds', 'health_interval_seconds', 'request_timeout_seconds', 'docker_timeout_seconds', 'switch_timeout_seconds'):
        if type(settings.get(key)) not in (int, float) or not 0 < settings[key] <= 3600:
            raise DeployError('Invalid deployment setting: ' + key)
    env = os.environ.copy()
    for key in ('COMPOSE_FILE', 'COMPOSE_PROJECT_NAME', 'COMPOSE_PROFILES', 'COMPOSE_ENV_FILES', 'COMPOSE_PATH_SEPARATOR'):
        env.pop(key, None)
    env.update({k: str(v) for k, v in dirs.items()})
    env['PERSONALKB_COMPOSE_PROJECT'] = PROJECT
    services = inspect_services(env)
    validate_mounts(services, dirs)
    report = probe(config, dirs['STATE_DIR'], dirs['SECRET_FILE'], port)
    required = ('config_valid', 'compose_available', 'secret_file_exists', 'auth_valid', 'secret_permissions_private')
    if report['system'] != 'Linux' or report['architecture'] not in ('x86_64', 'AMD64') or (not all((report[k] for k in required))) or (not report['disk_free_bytes']):
        raise DeployError('Preflight failed: ' + ','.join((k for k in required if not report[k])))
    workflow = json.loads((dirs['CONFIG_DIR'] / 'workflow.json').read_text(encoding='utf-8-sig'))
    if not isinstance(workflow, dict):
        raise DeployError('Invalid workflow configuration structure')
    if workflow['data_dir'] != '/state/workflow' or report['disk_free_bytes'] < int(workflow['min_free_bytes']):
        raise DeployError('State path or free space invalid')
    if services and all((obj['State']['Status'] == 'running' for obj in services.values())):
        old = next(iter(services.values()))['Image']
        health(env, origin, port, old, settings)
    elif not report['port_available']:
        raise DeployError('Port already occupied')
    compose(env, 'config', '--quiet')
    return (env, services, origin, port, settings)

def initialize_empty_state(state):
    from personalkb.workflow_store import WorkflowStore
    state = Path(state)
    if state.is_symlink() or (state / 'tmp').is_symlink():
        raise DeployError('Initialization directories must not be symlinks')
    workflow_dir = state / 'workflow'
    if workflow_dir.is_symlink():
        raise DeployError('Workflow directory must not be a symlink')
    db, ledger = workflow_dir / 'workflow.sqlite3', state / 'budget.sqlite'
    if db.exists() or ledger.exists():
        if db.is_file() and ledger.is_file():
            return
        raise DeployError('Workflow database and budget ledger must both exist or both be absent')
    if workflow_dir.exists() and (not workflow_dir.is_dir() or any(workflow_dir.iterdir())):
        raise DeployError('Workflow directory contains existing data')
    created_dir = False
    planned = []
    with tempfile.TemporaryDirectory(prefix='personalkb-init-', dir=state / 'tmp') as temporary:
        temp = Path(temporary)
        WorkflowStore(temp / 'workflow.sqlite3')
        with closing(sqlite3.connect(temp / 'budget.sqlite')) as conn:
            with conn:
                conn.execute('CREATE TABLE reservations (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, amount TEXT NOT NULL)')
        try:
            if not workflow_dir.exists():
                workflow_dir.mkdir()
                created_dir = True
            if any(workflow_dir.iterdir()):
                raise DeployError('Workflow directory contains existing data')
            for source, dest in ((temp / 'workflow.sqlite3', db), (temp / 'budget.sqlite', ledger)):
                original = source.stat()
                planned.append((dest, original))
                os.link(source, dest)
        except BaseException:
            for dest, original in reversed(planned):
                try:
                    actual = dest.lstat()
                    if stat.S_ISREG(actual.st_mode) and os.path.samestat(actual, original):
                        dest.unlink()
                except FileNotFoundError:
                    pass
            if created_dir:
                try:
                    workflow_dir.rmdir()
                except OSError:
                    pass
            raise

@contextmanager
def switch_signals():
    interrupted_once = False
    def interrupted(signum, frame):
        nonlocal interrupted_once
        if interrupted_once:
            return
        interrupted_once = True
        raise DeploymentInterrupted('Deployment interrupted by signal ' + str(signum))
    def suppress():
        nonlocal interrupted_once
        interrupted_once = True
    previous = {}
    try:
        for signum in (getattr(signal, 'SIGHUP', None), signal.SIGTERM):
            if signum is None:
                continue
            previous[signum] = signal.signal(signum, interrupted)
        yield suppress
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

def restore_stopped(env, old, settings):
    compose(env, 'up', '--no-start', '--no-build', '--pull', 'never', '--force-recreate', 'web', 'worker', timeout=settings['switch_timeout_seconds'])
    restored = inspect_services(env, timeout=settings['docker_timeout_seconds'])
    if len(restored) != 2 or any(obj['Image'] != old or obj['State']['Status'] not in ('created', 'exited') for obj in restored.values()):
        raise DeployError('Stopped service restoration failed')

def deploy(root, check=False):
    if check:
        prepare(root)
        return
    if fcntl is None:
        raise DeployError('Deployment requires Linux flock')
    lock_path = Path(root).resolve() / 'state/tmp/personalkb-deploy.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeployError('Deployment already running')
        env, services, origin, port, settings = prepare(root)
        old = next(iter(services.values()))['Image'] if services else None
        was_running = bool(services) and all(o['State']['Status'] == 'running' for o in services.values())
        print('Building candidate image; existing services stay running', flush=True)
        run(['docker', 'build', '-t', CANDIDATE, '-f', str(ROOT / 'deploy/Dockerfile'), str(ROOT)], stream=True, timeout=None)
        candidate = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', CANDIDATE])
        print('Checking candidate RAG configuration offline', flush=True)
        run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--mount', f"type=bind,src={env['CONFIG_DIR']},dst=/app/config,readonly", '--entrypoint', 'python', candidate, '-c', 'from personalkb.rag_index import load_rag_config; load_rag_config("/app/config/rag.json")'], stream=True, timeout=settings['docker_timeout_seconds'])
        print('Rechecking services and available space', flush=True)
        env2, services2, origin2, port2, settings2 = prepare(root)
        previous = {name: (obj['Image'], obj.get('Id'), obj['State']['Status']) for name, obj in services.items()}
        current = {name: (obj['Image'], obj.get('Id'), obj['State']['Status']) for name, obj in services2.items()}
        if previous != current or (origin, port) != (origin2, port2):
            raise DeployError('Existing deployment changed during build')
        env, settings = (env2, settings2)
        if old:
            run(['docker', 'tag', old, ROLLBACK])
            print('Previous image saved as ' + ROLLBACK, flush=True)
        switching = False
        with switch_signals() as suppress_signals:
            if not services:
                initialize_empty_state(Path(root).resolve() / 'state')
            try:
                run(['docker', 'tag', candidate, IMAGE])
                switching = True
                compose(env, 'up', '-d', '--no-build', '--pull', 'never', '--force-recreate', 'web', 'worker', stream=True, timeout=settings['switch_timeout_seconds'])
                health(env, origin, port, candidate, settings)
            except (Exception, KeyboardInterrupt) as exc:
                suppress_signals()
                for signum in (getattr(signal, 'SIGHUP', None), signal.SIGTERM):
                    if signum is not None:
                        signal.signal(signum, signal.SIG_IGN)
                try:
                    if old:
                        run(['docker', 'tag', ROLLBACK, IMAGE])
                        if was_running:
                            compose(env, 'up', '-d', '--no-build', '--pull', 'never', '--force-recreate', 'web', 'worker', timeout=settings['switch_timeout_seconds'])
                            health(env, origin, port, old, settings)
                        else:
                            restore_stopped(env, old, settings)
                    elif switching:
                        compose(env, 'rm', '-s', '-f', 'web', 'worker', timeout=settings['switch_timeout_seconds'])
                except Exception as rollback:
                    raise DeployError('Deployment and rollback failed; inspect services') from rollback
                raise DeployError('Deployment failed; previous service restored' if old else 'Deployment failed; new containers removed') from exc

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install-root', default=str(ROOT.parent))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        deploy(args.install_root, args.check)
        print('Preflight passed' if args.check else 'Deployment healthy')
    except (DeployError, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        print('Deployment error: ' + str(exc), file=sys.stderr)
        return 1
    return 0
if __name__ == '__main__':
    sys.exit(main())
