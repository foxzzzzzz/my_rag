from contextlib import contextmanager, ExitStack
from pathlib import Path
import os
import threading

from .workflow_store import WorkflowError
from .execution_guard import execution_guard

_lock = threading.Lock()
_held = {}

def _reset():
    global _lock, _held
    for f in _held.values():
        f.close()
    _held = {}
    _lock = threading.Lock()

if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset)

@contextmanager
def runtime_guard(data_dir, role):
    if role not in ('web', 'worker'):
        raise ValueError('invalid runtime role')
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = str(root / ('.' + role + '.runtime.lock'))
    with _lock:
        if path in _held:
            raise WorkflowError('maintenance_busy')
        f = open(path, 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                f.seek(0); f.write(b'\0'); f.flush(); f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            raise WorkflowError('maintenance_busy') from None
        _held[path] = f
    try:
        yield
    finally:
        with _lock:
            try:
                if os.name == 'nt':
                    import msvcrt
                    f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            finally:
                f.close(); del _held[path]

@contextmanager
def maintenance_guard(store):
    root = store.data_root or Path(store.db_path).parent
    with ExitStack() as stack:
        stack.enter_context(runtime_guard(root, 'web'))
        stack.enter_context(runtime_guard(root, 'worker'))
        stack.enter_context(execution_guard(store))
        yield
