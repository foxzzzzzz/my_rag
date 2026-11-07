#!/usr/bin/env python3
"""Collect a minimal, non-secret Linux readiness report using only Python's standard library."""
import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

ALLOWED_URLS = frozenset(("https://dashscope.aliyuncs.com/compatible-mode/v1/models", "https://api.deepseek.com/models", "https://pypi.org/simple/sqlite-vec/"))

def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read(16384).strip()
    except OSError:
        return None

def parse_mem(data):
    result = {}
    for line in (data or '').splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].rstrip(':') in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            try:
                result[parts[0][:-1]] = int(parts[1]) * 1024
            except ValueError:
                pass
    return result

def parse_cpu(value):
    try:
        quota, period = value.split()
        return int(quota) / int(period) if int(quota) > 0 and int(period) > 0 else None
    except (ValueError, AttributeError, ZeroDivisionError):
        return None

def parse_limit(value):
    try:
        n = int(value)
        return n if 0 < n < 2 ** 60 else None
    except (TypeError, ValueError):
        return None

def cgroups():
    root = '/sys/fs/cgroup'
    membership = read('/proc/self/cgroup')
    relative = None
    for line in (membership or '').splitlines():
        if line.startswith('0::'):
            relative = line[3:]
            break
    result = {'cpu_quota_cores': None, 'memory_limit_bytes': None, 'reliable': False}
    if relative is None or not relative.startswith('/') or '..' in relative.split('/'):
        return result
    root_real = os.path.realpath(root)
    current = os.path.realpath(os.path.join(root, relative.lstrip('/')))
    if current != root_real and not current.startswith(root_real + os.sep):
        return result
    cpu_values, memory_values = [], []
    while True:
        cpu_text = read(current + '/cpu.max')
        mem_text = read(current + '/memory.max')
        # Missing files mean we cannot establish that this hierarchy was inspected.
        if cpu_text is None or mem_text is None:
            return result
        cpu = parse_cpu(cpu_text)
        memory = parse_limit(mem_text)
        if cpu is not None:
            cpu_values.append(cpu)
        if memory is not None:
            memory_values.append(memory)
        if current == root_real:
            break
        current = os.path.dirname(current)
    result.update(cpu_quota_cores=min(cpu_values) if cpu_values else None,
                  memory_limit_bytes=min(memory_values) if memory_values else None, reliable=True)
    return result

def effective_cpu(host, affinity, cg):
    if not cg['reliable'] or host is None or affinity is None:
        return None
    return min([host, affinity] + ([cg['cpu_quota_cores']] if cg['cpu_quota_cores'] is not None else []))

def disk_ok(total, available, minimum_total, minimum_available):
    return total >= minimum_total and available >= minimum_available

def command_version(name, arg):
    path = shutil.which(name)
    if not path:
        return None
    try:
        result = subprocess.run([path, arg], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5, check=False)
        return result.stdout.decode('utf-8', 'replace').splitlines()[0][:300] if result.stdout else None
    except (OSError, subprocess.TimeoutExpired):
        return None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def http_status(url, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=timeout) as response:
            response.read(1024)
            return response.status
    except urllib.error.HTTPError as exc:
        try:
            return exc.code
        finally:
            exc.close()

def network_result(url, timeout):
    try:
        status = http_status(url, timeout)
        return {'url': url, 'reachable': True, 'http_status': status, 'authentication_verified': False}
    except (OSError, urllib.error.URLError, ValueError):
        return {'url': url, 'reachable': False, 'http_status': None, 'authentication_verified': False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--network-check', action='store_true')
    parser.add_argument('--data-path', help='Existing directory on the target data filesystem')
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('Linux is required')
    with open(args.config, encoding='utf-8-sig') as f:
        config = json.load(f)
    urls = config['network_urls']
    if not isinstance(urls, list) or any(u not in ALLOWED_URLS for u in urls):
        parser.error('network URLs must match the supported official endpoints')
    timeout = min(10, max(0.1, float(config['network_timeout_seconds'])))
    mem = parse_mem(read('/proc/meminfo'))
    cg = cgroups()
    cpus = os.cpu_count()
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = None
    usable_cpu = effective_cpu(cpus, affinity, cg)
    total_mem = mem.get('MemTotal')
    effective_mem = (min(total_mem, cg['memory_limit_bytes']) if cg['memory_limit_bytes'] is not None else total_mem) if cg['reliable'] and total_mem is not None else None
    path = os.path.realpath(args.data_path or config['data_path'])
    if not os.path.isdir(path):
        parser.error('data path must be an existing directory')
    disk = shutil.disk_usage(path)
    os_info = {}
    for line in (read('/etc/os-release') or '').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in ('ID', 'VERSION_ID', 'PRETTY_NAME'):
                os_info[key] = value.strip('"')
    report = {'scope': 'environment_only_not_resource_acceptance', 'peak_3gib_actual_usage': 'unknown',
              'os_release': os_info, 'architecture': platform.machine(), 'cpu_count': cpus, 'cpu_affinity_count': affinity, 'resource_limits_reliable': cg['reliable'],
              'memory_bytes': mem, 'cgroup': cg, 'data_disk': {'path': path, 'total_bytes': disk.total, 'available_bytes': disk.free},
              'python_version': platform.python_version(), 'sqlite_version': sqlite3.sqlite_version,
              'docker_version': command_version('docker', '--version'), 'ffmpeg_version': command_version('ffmpeg', '-version'),
              'readiness': {'cpu': usable_cpu >= config['min_cpu_cores'] if usable_cpu is not None else None,
                            'memory': effective_mem >= config['min_memory_bytes'] if effective_mem is not None else None,
                            'disk': disk_ok(disk.total, disk.free, config['min_disk_total_bytes'], config['min_disk_available_bytes'])},
              'network': [network_result(url, timeout) for url in urls] if args.network_check else 'not_checked'}
    with open(args.output, 'x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')

if __name__ == '__main__':
    main()
