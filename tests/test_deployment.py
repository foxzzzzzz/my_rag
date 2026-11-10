import importlib.util, json, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def _check_frontend_docker_layout(dockerfile, tmp_path):
    import re, shlex, shutil
    from pathlib import PurePosixPath
    stage = None
    workdir = PurePosixPath('/')
    final_source = None
    for line in dockerfile.splitlines():
        parts = shlex.split(line, comments=True)
        if not parts:
            continue
        if parts[0] == 'FROM':
            stage = 'frontend' if parts[-1] == 'frontend' else 'final'
        elif parts[0] == 'WORKDIR' and stage == 'frontend':
            workdir = PurePosixPath(parts[1])
        elif parts[0] == 'COPY' and stage == 'frontend':
            source, dest = parts[1:]
            destination = PurePosixPath(dest) if dest.startswith('/') else workdir / dest
            target = tmp_path / str(destination).lstrip('/')
            for item in ROOT.glob(source):
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('node_modules', 'dist'))
                else:
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target / item.name)
        elif parts[0] == 'COPY' and parts[1] == '--from=frontend':
            final_source = PurePosixPath(parts[2])
    refs = []
    for source in (ROOT / 'web/src').rglob('*'):
        if source.is_file() and source.suffix in ('.js', '.jsx', '.ts', '.tsx'):
            refs.extend((source.relative_to(ROOT / 'web'), ref) for ref in re.findall(r"['\"](\.\./\.\./config/[^'\"]+)['\"]", source.read_text(encoding='utf-8')))
    assert refs, 'No frontend config references found'
    for source, ref in refs:
        assert (tmp_path / str(workdir).lstrip('/') / source.parent / ref).resolve().is_file(), ref
    assert final_source == workdir / 'dist', 'Final COPY must use the frontend build output'

def test_frontend_docker_layout(tmp_path):
    dockerfile = (ROOT / 'deploy/Dockerfile').read_text(encoding='utf-8')
    _check_frontend_docker_layout(dockerfile, tmp_path)

def test_debian_mirror_is_signed_and_packaged(tmp_path):
    source = (ROOT / 'config/debian.sources').read_text(encoding='utf-8')
    paragraphs = []
    for block in source.strip().split('\n\n'):
        fields = dict(line.split(':', 1) for line in block.splitlines() if line and not line.startswith('#'))
        paragraphs.append({key: value.strip() for key, value in fields.items()})
    expected = [('https://mirrors.tuna.tsinghua.edu.cn/debian', 'bookworm bookworm-updates'),
                ('https://mirrors.tuna.tsinghua.edu.cn/debian-security', 'bookworm-security')]
    assert [(p['URIs'], p['Suites']) for p in paragraphs] == expected
    for p in paragraphs:
        assert p == {'Types': 'deb', 'URIs': p['URIs'], 'Suites': p['Suites'], 'Components': 'main',
                     'Signed-By': '/usr/share/keyrings/debian-archive-keyring.gpg'}
    docker = (ROOT / 'deploy/Dockerfile').read_text(encoding='utf-8')
    assert docker.index('FROM python:') < docker.index('COPY config/debian.sources /etc/apt/sources.list.d/debian.sources') < docker.index('RUN apt-get update')
    output = tmp_path / 'kit.zip'
    module('kit_mirror', 'tools/build_deployment_kit.py').build(output)
    with zipfile.ZipFile(output) as z:
        assert z.read('config/debian.sources').decode('utf-8') == source
        assert '  config/debian.sources\n' in z.read('SHA256SUMS').decode()

def test_pip_build_config_scope_and_bundle(tmp_path):
    import configparser, re
    config = configparser.ConfigParser()
    config.read(ROOT / 'config/pip-build.conf', encoding='utf-8')
    assert config.sections() == ['global']
    assert dict(config['global']) == {'index-url': 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple'}
    docker = (ROOT / 'deploy/Dockerfile').read_text(encoding='utf-8')
    lines = docker.splitlines()
    runs = [line for line in lines if line.startswith('RUN ') and 'pip install' in line]
    assert len(runs) == 1
    run = runs[0]
    assert run.startswith('RUN export PIP_CONFIG_FILE=/app/config/pip-build.conf && ')
    assert len(re.findall(r'\bpip install\b', run)) == 3
    assert 'COPY config/ /app/config/' in lines and lines.index('COPY config/ /app/config/') < lines.index(run)
    assert not any('PIP_CONFIG_FILE' in line for line in lines if line != run)
    assert '/opt/douyin/bin/pip install --no-cache-dir --no-deps -r config/douyin-resolver-f2.txt' in run
    output = tmp_path / 'kit.zip'
    module('kit_pip', 'tools/build_deployment_kit.py').build(output)
    with zipfile.ZipFile(output) as z:
        assert z.read('config/pip-build.conf') == (ROOT / 'config/pip-build.conf').read_bytes()
        assert '  config/pip-build.conf\n' in z.read('SHA256SUMS').decode()

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def test_configuration(tmp_path):
    c=module('configure','deploy/configure.py'); c.configure('kb.yuanzhll.top',tmp_path)
    web=json.loads((tmp_path/'web.json').read_text(encoding='utf-8'))
    assert web['deployment_mode']=='production' and not web['dispatch_enabled'] and not web['live_video_enabled']
    assert web['env_file']=='/run/secrets/personalkb.env'
    assert json.loads((tmp_path/'auth.json').read_text(encoding='utf-8'))['enabled']
    assert json.loads((tmp_path/'workflow.json').read_text(encoding='utf-8'))['data_dir']=='/state/workflow'
    assert json.loads((tmp_path/'maintenance.json').read_text(encoding='utf-8'))['keep_snapshots'] == 4
def test_bundle_excludes_private_files(tmp_path):
    b=module('kit','tools/build_deployment_kit.py'); dest=tmp_path/'kit.zip'; b.build(dest)
    with zipfile.ZipFile(dest) as z:
        names=z.namelist(); assert 'deploy/Dockerfile' in names and 'web/package-lock.json' in names and 'docs/phase-4-server-guide.md' in names
        assert not any('/node_modules/' in n or n.startswith(('tmp/','reports/','data/','sources/')) or n.endswith('.env') for n in names)
    assert dest.with_suffix('.zip.sha256').exists()

def test_generated_web_config_loads(tmp_path):
    c=module('configure_real','deploy/configure.py'); c.configure('kb.yuanzhll.top',tmp_path)
    from personalkb.web_app import load_web_config
    cfg=load_web_config(tmp_path/'web.json')
    assert cfg['host']=='127.0.0.1' and cfg['port']==8768 and not cfg['dispatch_enabled']

def test_generated_rag_config_accepts_production_paths(tmp_path):
    import pytest
    from personalkb.rag_index import load_rag_config
    from personalkb.workflow_store import WorkflowError
    c=module('configure_rag_paths','deploy/configure.py'); c.configure('kb.yuanzhll.top',tmp_path)
    path=tmp_path/'rag.json'; cfg=json.loads(path.read_text(encoding='utf-8'))
    assert cfg['env_file']=='/run/secrets/personalkb.env' and cfg['budget']['ledger']=='/state/budget.sqlite'
    assert load_rag_config(path)==cfg
    for key in ('env_file','ledger','index_dir','models_file'):
        for value in ('../escape', '/state/../escape', '//server/share', r'\\server\share', r'C:\state\..\escape'):
            bad=json.loads(json.dumps(cfg)); (bad['budget'] if key=='ledger' else bad)[key]=value
            path.write_text(json.dumps(bad),encoding='utf-8')
            with pytest.raises(WorkflowError): load_rag_config(path)
    for key in ('index_dir','models_file'):
        bad=json.loads(json.dumps(cfg)); bad[key]='/absolute/path'; path.write_text(json.dumps(bad),encoding='utf-8')
        with pytest.raises(WorkflowError): load_rag_config(path)
    assert load_rag_config(ROOT/'config/rag.json')

def test_worker_stops_claiming_after_sigterm(monkeypatch):
    import sys, signal
    from contextlib import nullcontext
    w=module('worker_test','tools/worker.py'); handlers={}; calls=[]
    monkeypatch.setattr(sys,'argv',['worker','--config','test'])
    monkeypatch.setattr(w.signal,'signal',lambda sig,fn: handlers.setdefault(sig,fn))
    monkeypatch.setattr(w,'load_web_config',lambda _: {'workflow_config':'x','pipeline_config':'y','dispatch_poll_seconds':0.001})
    monkeypatch.setattr(w.workflow,'load_config',lambda _: {'data_dir':'x'})
    monkeypatch.setattr(w,'load_pipeline_config',lambda _: {})
    monkeypatch.setattr(w,'runtime_guard',lambda *args: nullcontext())
    class Service:
        def __init__(self,*args): calls.append('init')
        def process_next(self): calls.append('claim'); handlers[signal.SIGTERM](signal.SIGTERM,None)
    monkeypatch.setattr(w,'WebService',Service)
    w.main()
    assert calls==['init','claim']

def test_config_rejects_bad_port_and_overwrite(tmp_path):
    import pytest
    c=module('config_safety','deploy/configure.py')
    for port in (0,65536):
        with pytest.raises(ValueError): c.configure('KB.YUANZHLL.TOP',tmp_path,port)
    c.configure('KB.YUANZHLL.TOP',tmp_path)
    cfg=json.loads((tmp_path/'web.json').read_text(encoding='utf-8'))
    assert cfg['trusted_hosts'][0]=='kb.yuanzhll.top'
    with pytest.raises(FileExistsError): c.configure('kb.yuanzhll.top',tmp_path)
    c.configure('kb.yuanzhll.top',tmp_path,force=True)
    assert json.loads((tmp_path/'maintenance.json').read_text(encoding='utf-8'))['ledger_paths']==['/state/budget.sqlite']

def test_bundle_manifest_and_overwrite(tmp_path):
    import hashlib, pytest
    b=module('kit_integrity','tools/build_deployment_kit.py'); output=tmp_path/'kit.zip'; b.build(output)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        for line in z.read('SHA256SUMS').decode().splitlines():
            digest,name=line.split('  ',1)
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
    with pytest.raises(FileExistsError): b.build(output)

def test_preflight_missing_auth(tmp_path):
    c=module('config_preflight','deploy/configure.py'); c.configure('kb.yuanzhll.top',tmp_path)
    pre=module('preflight_test','deploy/preflight.py'); result=pre.probe(tmp_path/'web.json',tmp_path,tmp_path/'missing.env')
    assert result['auth_valid'] is False and result['auth_hash_present'] is False and result['ready'] is False

def test_daily_backup_modes(tmp_path, monkeypatch):
    import subprocess
    d=module('daily_test','deploy/daily.py'); calls=[]
    class Done:
        def __init__(self,stdout): self.stdout=stdout
    def run(cmd, **kwargs):
        operation=cmd[cmd.index('/app/config/maintenance.json')+1]; calls.append(operation)
        return Done('{"snapshot":"abc"}' if operation=='create' else '{}')
    monkeypatch.setattr(subprocess,'run',run)
    cfg=tmp_path/'maintenance.json'; report=tmp_path/'report.json'
    for mode,expected in [('manual',['create','verify','purge-trash']),('oss',['create','verify','purge-trash','push'])]:
        calls.clear(); cfg.write_text(json.dumps({'storage_mode':mode,'oss':{'access_key_id_env':'TEST_ID','access_key_secret_env':'TEST_SECRET'}})); d.daily(cfg,report)
        assert calls==expected and json.loads(report.read_text())['state']=='success'
    def fail(*a,**kw): raise subprocess.CalledProcessError(1,'docker')
    monkeypatch.setattr(subprocess,'run',fail)
    import pytest
    with pytest.raises(subprocess.CalledProcessError): d.daily(cfg,report)
    assert json.loads(report.read_text())['state']=='failed'

def test_timer_and_worker_oss_dependency():
    timer=(ROOT/'deploy/systemd/personalkb-backup.timer.template').read_text(encoding='utf-8-sig')
    assert [line for line in timer.splitlines() if line.startswith('OnCalendar=')] == [
        'OnCalendar=Sun *-*-* 03:30:00 Asia/Shanghai',
    ]
    assert 'Persistent=true' in timer and 'Unit=personalkb-backup.service' in timer
    docker=(ROOT/'deploy/Dockerfile').read_text(encoding='utf-8-sig')
    assert '-r config/oss-requirements.txt' in docker and '/opt/oss' not in docker

def test_bundle_file_permissions(tmp_path):
    b=module('kit_modes','tools/build_deployment_kit.py'); output=tmp_path/'kit.zip'; b.build(output)
    with zipfile.ZipFile(output) as z:
        for name in ('deploy/operate.sh','deploy/README.md','SHA256SUMS'):
            info=z.getinfo(name)
            assert info.create_system==3
            assert ((info.external_attr >> 16) & 0o777)==(0o755 if name.endswith('.sh') else 0o644)

def test_daily_forwards_only_present_credential_names(tmp_path,monkeypatch,capsys):
    import subprocess
    d=module('daily_env_test','deploy/daily.py'); commands=[]
    class Done:
        def __init__(self,stdout): self.stdout=stdout
    def run(cmd,**kwargs):
        commands.append(cmd)
        return Done('{"snapshot":"abc"}' if 'create' in cmd else '{}')
    monkeypatch.setattr(subprocess,'run',run)
    monkeypatch.setenv('TEST_ID','sensitive-value')
    monkeypatch.delenv('TEST_SECRET',raising=False)
    cfg=tmp_path/'config.json'; report=tmp_path/'report.json'
    cfg.write_text(json.dumps({'storage_mode':'oss','oss':{'access_key_id_env':'TEST_ID','access_key_secret_env':'TEST_SECRET'}}))
    d.daily(cfg,report)
    push=commands[-1]
    assert push[push.index('-e')+1]=='TEST_ID' and 'TEST_SECRET' not in push
    assert 'sensitive-value' not in str(commands) and 'sensitive-value' not in report.read_text() and 'sensitive-value' not in capsys.readouterr().out
    monkeypatch.delenv('TEST_ID'); commands.clear(); d.daily(cfg,report)
    assert '-e' not in commands[-1]

def test_nginx_streaming_and_configurable_port():
    nginx=(ROOT/'deploy/nginx.conf.template').read_text(encoding='utf-8')
    assert '127.0.0.1:__APP_PORT__' in nginx
    assert 'proxy_http_version 1.1;' in nginx
    assert 'proxy_request_buffering off;' in nginx
    assert 'proxy_buffering off;' in nginx
    assert 'proxy_next_upstream off;' in nginx

def test_compose_project_is_explicit_and_validated(tmp_path,monkeypatch):
    import subprocess, pytest
    shell=(ROOT/'deploy/operate.sh').read_text(encoding='utf-8')
    assert 'docker compose ' not in shell.replace('docker compose --project-name "$project" ', '')
    assert 'name: ${PERSONALKB_COMPOSE_PROJECT:-personalkb}' in (ROOT/'deploy/compose.yaml').read_text(encoding='utf-8')
    d=module('daily_project','deploy/daily.py'); calls=[]
    class Done:
        stdout='{"snapshot":"abc"}'
    monkeypatch.setattr(subprocess,'run',lambda cmd,**kw: calls.append(cmd) or Done())
    cfg=tmp_path/'config.json'; cfg.write_text('{"storage_mode":"manual"}')
    monkeypatch.setenv('COMPOSE_PROJECT_NAME','other')
    monkeypatch.setenv('PERSONALKB_COMPOSE_PROJECT','personalkb-test')
    d.daily(cfg,tmp_path/'report.json')
    assert all(cmd[2:4]==['--project-name','personalkb-test'] for cmd in calls)
    monkeypatch.setenv('PERSONALKB_COMPOSE_PROJECT','Bad Project')
    with pytest.raises(ValueError): d.daily(cfg,tmp_path/'report.json')

def test_daily_retention_opt_in_and_failure(tmp_path,monkeypatch):
    import subprocess, pytest
    d=module('daily_retention_test','deploy/daily.py'); calls=[]
    class Done:
        def __init__(self,stdout): self.stdout=stdout
    def run(cmd,**kwargs):
        op=cmd[cmd.index('/app/config/maintenance.json')+1]; calls.append(op)
        return Done('{"snapshot":"abc"}' if op=='create' else '{}')
    monkeypatch.setattr(subprocess,'run',run)
    cfg=tmp_path/'config.json'; report=tmp_path/'report.json'
    for enabled,expected in [(False,['create','verify','purge-trash']),(True,['create','verify','purge-trash','retention'])]:
        calls.clear(); cfg.write_text(json.dumps({'storage_mode':'manual','auto_retention_enabled':enabled}))
        d.daily(cfg,report); assert calls==expected
        assert json.loads(report.read_text())['retention']['applied'] is enabled
    calls.clear()
    cfg.write_text(json.dumps({'storage_mode':'manual','auto_retention_enabled':'invalid'}))
    with pytest.raises(ValueError, match='invalid retention setting'): d.daily(cfg,report)
    assert calls == []
    cfg.write_text(json.dumps({'storage_mode':'manual','auto_retention_enabled':True}))
    def fail(cmd,**kwargs):
        op=cmd[cmd.index('/app/config/maintenance.json')+1]
        if op=='retention': raise subprocess.CalledProcessError(1,'docker')
        return Done('{"snapshot":"abc"}' if op=='create' else '{}')
    monkeypatch.setattr(subprocess,'run',fail)
    with pytest.raises(subprocess.CalledProcessError): d.daily(cfg,report)
    assert json.loads(report.read_text())['state']=='failed'
    assert 'trap restore_services EXIT' in (ROOT/'deploy/operate.sh').read_text(encoding='utf-8')

def test_production_enables_daily_retention(tmp_path):
    c=module('production_retention','deploy/configure.py'); c.configure('kb.yuanzhll.top',tmp_path)
    assert json.loads((ROOT/'config/maintenance.json').read_text(encoding='utf-8-sig'))['auto_retention_enabled'] is False
    assert json.loads((tmp_path/'maintenance.json').read_text(encoding='utf-8'))['auto_retention_enabled'] is True

def _restore_health_fixture(tmp_path, monkeypatch):
    from types import SimpleNamespace
    h=module('restore_health_test','deploy/restore_health.py')
    (tmp_path/'web.json').write_text(json.dumps({'port':8000,'trusted_origins':['https://example.org']}))
    (tmp_path/'deployment.json').write_text(json.dumps({'health_timeout_seconds':3,'health_interval_seconds':1,'request_timeout_seconds':1,'docker_timeout_seconds':1}))
    env = {'CONFIG_DIR': str(tmp_path), 'PERSONALKB_COMPOSE_PROJECT': 'personalkb'}
    clock = [0]
    def sleep(seconds):
        clock[0] += seconds
    monkeypatch.setattr(h, 'time', SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    monkeypatch.setattr(h.deploy,'compose',lambda env,*args,**kw: args[-1])
    return h, env


def _restored_container(service, status='running', started_at='start'):
    return json.dumps([{'Config': {'Labels': {'com.docker.compose.project': 'personalkb', 'com.docker.compose.service': service}},
                        'State': {'Status': status, 'StartedAt': started_at}}])


def test_restore_health_checks_selected_services_and_endpoints(tmp_path, monkeypatch):
    h, env = _restore_health_fixture(tmp_path, monkeypatch)
    checked = []
    def inspect(args, **kwargs):
        checked.append(args[-1])
        return _restored_container(args[-1])
    monkeypatch.setattr(h.deploy, 'run', inspect)
    urls=[]
    monkeypatch.setattr(h.deploy,'url_ok',lambda url,*args: urls.append((url, args[1:])) or True)
    h.wait_for_services(env, ['web', 'worker'])
    assert checked == ['web', 'worker', 'web', 'worker']
    assert urls == [('http://127.0.0.1:8000/healthz', ({'Host': 'example.org', 'X-Forwarded-Proto': 'https'},)),
                    ('https://example.org/healthz', ())]
    checked.clear(); urls.clear()
    h.wait_for_services(env, ['worker'])
    assert checked == ['worker', 'worker'] and not urls


def test_restore_health_rejects_restarting_worker_and_failed_https(tmp_path, monkeypatch):
    import pytest
    h, env = _restore_health_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(h.deploy, 'run', lambda args, **kwargs: _restored_container(args[-1], 'restarting' if args[-1] == 'worker' else 'running'))
    monkeypatch.setattr(h.deploy, 'url_ok', lambda *args: pytest.fail('Unstable services must not pass health verification'))
    with pytest.raises(h.deploy.DeployError):
        h.wait_for_services(env, ['web', 'worker'])
    monkeypatch.setattr(h.deploy, 'run', lambda args, **kwargs: _restored_container(args[-1]))
    monkeypatch.setattr(h.deploy, 'url_ok', lambda url, *args: url.startswith('http:'))
    with pytest.raises(h.deploy.DeployError):
        h.wait_for_services(env, ['web', 'worker'])


def test_maintenance_holds_deployment_lock_through_service_restore(tmp_path, monkeypatch):
    import os, subprocess, sys, time
    import pytest
    pytest.importorskip('fcntl')
    state = tmp_path / 'state'
    (state / 'tmp').mkdir(parents=True)
    commands = tmp_path / 'bin'
    commands.mkdir()
    docker = commands / 'docker'
    docker.write_text('''#!/bin/sh
echo "$*" >> "$STATE_DIR/docker.log"
case "$*" in
  *'ps --services'*) printf 'web\\nworker\\n';;
esac
''')
    python = commands / 'python3'
    python.write_text('''#!/bin/sh
case "$1" in
  daily.py) printf '%s\\n' '{"state":"success","snapshot":"verified"}' > "$STATE_DIR/backup-status.json";;
  -m)
    touch "$STATE_DIR/restoring"
    while [ ! -f "$STATE_DIR/release" ]; do sleep 0.05; done
    exit 1;;
  *) exec "$TEST_PYTHON" "$@";;
esac
''')
    docker.chmod(0o700)
    python.chmod(0o700)
    env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'], STATE_DIR=str(state),
               CONFIG_DIR=str(tmp_path), TEST_PYTHON=sys.executable)
    script = ['sh', str(ROOT / 'deploy/operate.sh')]
    deployment = module('deploy_contention', 'deploy/deploy.py')
    monkeypatch.setattr(deployment, 'prepare', lambda root: pytest.fail('Deploy must fail before preflight'))
    with subprocess.Popen([*script, 'daily'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as daily:
        try:
            deadline = time.monotonic() + 10
            while not (state / 'restoring').exists():
                assert daily.poll() is None and time.monotonic() < deadline
                time.sleep(0.05)
            docker_calls = (state / 'docker.log').read_text()
            report = (state / 'backup-status.json').read_bytes()
            for command in ('daily', 'verify', 'restart'):
                contender = subprocess.run([*script, command], env=env, capture_output=True, timeout=10)
                assert contender.returncode != 0 and b'already running' in contender.stderr
            with pytest.raises(deployment.DeployError, match='already running'):
                deployment.deploy(tmp_path)
            assert (state / 'docker.log').read_text() == docker_calls
            assert (state / 'backup-status.json').read_bytes() == report
        finally:
            (state / 'release').touch()
            daily.communicate(timeout=10)
    assert daily.returncode == 1
    assert json.loads((state / 'backup-status.json').read_text()) == {
        'state': 'failed', 'snapshot': 'verified', 'services_restored': False,
    }
    assert subprocess.run([*script, 'verify', 'verified'], env=env, timeout=10).returncode == 0


def test_restore_health_module_entry_from_operate(tmp_path):
    import os, subprocess, sys
    import pytest
    pytest.importorskip('fcntl')
    state = tmp_path / 'state'
    (state / 'tmp').mkdir(parents=True)
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'deployment.json').write_text(json.dumps({
        'health_timeout_seconds': 3, 'health_interval_seconds': 0.01,
        'docker_timeout_seconds': 1, 'request_timeout_seconds': 1}))
    commands = tmp_path / 'bin'
    commands.mkdir()
    docker = commands / 'docker'
    container = _restored_container('worker')
    docker.write_text("#!/bin/sh\ncase \"$*\" in\n  *'ps --services'*) echo worker;;\n  *'ps --all -q worker'*) echo worker;;\n  inspect*) printf '%s' '" + container + "';;\nesac\n")
    docker.chmod(0o700)
    python = commands / 'python3'
    python.write_text("#!/bin/sh\nif [ \"$1\" = daily.py ]; then printf '%s' '{\"state\":\"success\"}' > \"$STATE_DIR/backup-status.json\"; else exec \"$TEST_PYTHON\" \"$@\"; fi\n")
    python.chmod(0o700)
    env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'],
               STATE_DIR=str(state), CONFIG_DIR=str(config), TEST_PYTHON=sys.executable)
    result = subprocess.run(['sh', str(ROOT / 'deploy/operate.sh'), 'daily'],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads((state / 'backup-status.json').read_text())['services_restored'] is True
