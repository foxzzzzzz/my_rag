import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from deploy import deploy


def wait_for_services(env, services):
    config = Path(env['CONFIG_DIR'])
    settings_file = config / 'deployment.json'
    if not settings_file.exists():
        settings_file = deploy.ROOT / 'config/deployment.json'
    settings = json.loads(settings_file.read_text(encoding='utf-8-sig'))
    if 'web' in services:
        web = json.loads((config / 'web.json').read_text(encoding='utf-8-sig'))
        origin = web['trusted_origins'][0]
    deadline = time.monotonic() + settings['health_timeout_seconds']
    previous = None

    def timeout(key):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Service restoration timed out')
        return min(settings[key], remaining)

    while time.monotonic() < deadline:
        try:
            current = []
            for service in services:
                ids = deploy.compose(env, 'ps', '--all', '-q', service, timeout=timeout('docker_timeout_seconds')).splitlines()
                if len(ids) != 1:
                    raise ValueError('Expected one container for ' + service)
                obj = json.loads(deploy.run(['docker', 'inspect', ids[0]], timeout=timeout('docker_timeout_seconds')))[0]
                labels = obj['Config']['Labels'] or {}
                state = obj['State']
                if (labels.get('com.docker.compose.project') != env['PERSONALKB_COMPOSE_PROJECT']
                        or labels.get('com.docker.compose.service') != service
                        or state['Status'] != 'running'
                        or state.get('Health', {}).get('Status', 'healthy') != 'healthy'):
                    raise ValueError('Service is not running: ' + service)
                current.append((ids[0], state['StartedAt']))
            # Allow startup to settle and reject a container that restarted between checks.
            if previous == current:
                if 'web' in services:
                    headers = {'Host': urlsplit(origin).netloc, 'X-Forwarded-Proto': 'https'}
                    if not deploy.url_ok(f"http://127.0.0.1:{web['port']}/healthz", timeout('request_timeout_seconds'), headers):
                        raise ValueError('Loopback health failed')
                    if not deploy.url_ok(origin + '/healthz', timeout('request_timeout_seconds')):
                        raise ValueError('HTTPS health failed')
                return
            previous = current
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            previous = None
        time.sleep(min(settings['health_interval_seconds'], max(0, deadline - time.monotonic())))
    raise deploy.DeployError('Service restoration health verification failed')


if __name__ == '__main__':
    try:
        deploy.PROJECT = os.environ['PERSONALKB_COMPOSE_PROJECT']
        wait_for_services(os.environ.copy(), sys.argv[1:])
    except (OSError, ValueError, TypeError, KeyError, IndexError, deploy.DeployError):
        print('Service restoration health verification failed', file=sys.stderr)
        sys.exit(1)
