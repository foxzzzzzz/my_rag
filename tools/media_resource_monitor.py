import os
import signal
import subprocess
import time
from pathlib import Path

import psutil


def sample_resources(path):
    memory = psutil.virtual_memory()
    process = psutil.Process()
    rss = 0
    for child in [process] + process.children(recursive=True):
        try:
            rss += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {'time': time.time(), 'host_total': memory.total,
            'host_available': memory.available, 'host_cpu_percent': psutil.cpu_percent(interval=None),
            'host_used_proxy': memory.total - memory.available,
            'swap_used': psutil.swap_memory().used,
            'disk_free': psutil.disk_usage(str(path)).free, 'tree_rss': rss}


def run_command(command: list[str], log_path: Path, data_path: Path, limits: dict,
                cancel_after_seconds: float | None = None) -> dict:
    start = time.monotonic()
    samples = []
    result = {'status': 'failed', 'returncode': None, 'elapsed_seconds': 0,
              'samples': samples, 'stop_reason': None, 'command': list(command),
              'termination': {'requested': False, 'leader_exited': True,
                              'owned_descendants_stopped': True, 'verified': True}}
    process = None
    children = {}

    def sample():
        if process is not None:
            try:
                for child in psutil.Process(process.pid).children(recursive=True):
                    children[child.pid] = child
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        value = sample_resources(data_path)
        samples.append(value)
        for key, field, op in [('min_available_memory_bytes', 'host_available', 'min'),
                               ('min_free_disk_bytes', 'disk_free', 'min'),
                               ('max_host_used_bytes', 'host_used_proxy', 'max')]:
            if (value[field] < limits[key] if op == 'min' else value[field] > limits[key]):
                return key
        return None

    def stop():
        if process is None:
            return
        termination = result['termination']
        termination['requested'] = True
        try:
            if os.name == 'nt':
                try:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        children[child.pid] = child
                except psutil.NoSuchProcess:
                    pass
                owned = list(children.values())
                if process.poll() is None:
                    owned.append(psutil.Process(process.pid))
                for item in owned:
                    try:
                        item.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(owned, timeout=limits['terminate_grace_seconds'])
                for item in alive:
                    try:
                        item.kill()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(alive, timeout=limits['terminate_grace_seconds'])
                termination['owned_descendants_stopped'] = not alive
            else:
                def group_exists():
                    try:
                        os.killpg(process.pid, 0)
                        return True
                    except ProcessLookupError:
                        return False
                if group_exists():
                    os.killpg(process.pid, signal.SIGTERM)
                    deadline = time.monotonic() + limits['terminate_grace_seconds']
                    while time.monotonic() < deadline and group_exists():
                        process.poll()
                        time.sleep(min(limits['interval_seconds'], max(0, deadline - time.monotonic())))
                    if group_exists():
                        os.killpg(process.pid, signal.SIGKILL)
                    deadline = time.monotonic() + limits['terminate_grace_seconds']
                    while time.monotonic() < deadline and group_exists():
                        process.poll()
                        time.sleep(min(limits['interval_seconds'], max(0, deadline - time.monotonic())))
                termination['owned_descendants_stopped'] = not group_exists()
            process.poll()
            termination['leader_exited'] = process.returncode is not None
            termination['verified'] = termination['leader_exited'] and termination['owned_descendants_stopped']
        except (OSError, psutil.Error):
            termination['verified'] = False
        if not termination['verified']:
            result.update(status='failed', stop_reason='termination_unverified')

    try:
        reason = sample()
        if reason:
            result.update(status='resource_stop', stop_reason=reason)
        else:
            with Path(log_path).open('x', encoding='utf-8') as log:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log,
                                           start_new_session=(os.name != 'nt'))
                while process.poll() is None:
                    elapsed = time.monotonic() - start
                    reason = sample()
                    if reason:
                        result.update(status='resource_stop', stop_reason=reason)
                    elif elapsed >= limits['timeout_seconds']:
                        result.update(status='timeout', stop_reason='timeout_seconds')
                    elif cancel_after_seconds is not None and elapsed >= cancel_after_seconds:
                        result.update(status='interrupted', stop_reason='cancel_after_seconds')
                    else:
                        time.sleep(limits['interval_seconds'])
                        continue
                    break
                if result['stop_reason'] is not None:
                    stop()
                reason = sample()
                result['returncode'] = process.poll()
                if result['stop_reason'] is None:
                    if reason:
                        result.update(status='resource_stop', stop_reason=reason)
                    elif cancel_after_seconds is not None:
                        result.update(status='failed', stop_reason='failed_cancel_not_exercised')
                    elif process.returncode == 0:
                        result['status'] = 'completed'
                    else:
                        result['stop_reason'] = 'nonzero_exit'
    except KeyboardInterrupt:
        result.update(status='interrupted_by_user', stop_reason='keyboard_interrupt')
    finally:
        if process is not None and not result['termination']['requested']:
            stop()
        if process is not None:
            result['returncode'] = process.poll()
        result['elapsed_seconds'] = time.monotonic() - start
    return result
