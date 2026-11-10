"""Cross-process serialization of index readers and generation publication."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import os
import threading
import time
import errno
from .workflow_store import WorkflowError

_registry = {}
_registry_guard = threading.Lock()
_local = threading.local()
_files = set()

def _reset():
    global _registry, _registry_guard, _local, _files
    for file in _files: file.close()
    _registry = {}; _registry_guard = threading.Lock(); _local = threading.local(); _files = set()
if hasattr(os, 'register_at_fork'): os.register_at_fork(after_in_child=_reset)

@contextmanager
def index_guard(index):
    # Outside the index directory so acquiring a read lock does not create it.
    path = str(Path(index.store.db_path).resolve()) + '.rag.lock'
    with _registry_guard: lock = _registry.setdefault(path, threading.RLock())
    deadline = time.monotonic() + index.store.busy_timeout_seconds
    if not lock.acquire(timeout=max(0, deadline-time.monotonic())): raise WorkflowError('worker_busy')
    try:
        held = getattr(_local, 'held', {})
        if path in held:
            yield
            return
        with _registry_guard:
            f = open(path, 'a+b')
            _files.add(f)
        try:
            if os.name == 'nt':
                import msvcrt
                if not f.tell(): f.write(b'\0'); f.flush()
                f.seek(0)
                # LK_LOCK retries a bounded number of times; wait explicitly.
                while True:
                    try: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1); break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
                        if time.monotonic() >= deadline: raise WorkflowError('worker_busy') from None
                        time.sleep(min(0.05, max(0, deadline-time.monotonic())))
            else:
                import fcntl
                while True:
                    try: fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); break
                    except BlockingIOError:
                        if time.monotonic() >= deadline: raise WorkflowError('worker_busy') from None
                        time.sleep(min(0.05, max(0, deadline-time.monotonic())))
            held[path] = True; _local.held = held
            try: yield
            finally:
                del held[path]
                if os.name == 'nt':
                    f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            with _registry_guard:
                f.close()
                _files.remove(f)
    finally: lock.release()

def guarded(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        with index_guard(self): return func(self, *args, **kwargs)
    return wrapper
