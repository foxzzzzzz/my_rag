from contextlib import contextmanager
from pathlib import Path
import os
import threading

_registry_lock = threading.Lock()
_owners = {}

def _after_fork_child():
    global _registry_lock, _owners
    for entry in _owners.values():
        entry[1].close()
    _owners = {}
    _registry_lock = threading.Lock()

if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork_child)

@contextmanager
def execution_guard(store):
    from .workflow_store import WorkflowError
    path = str(Path(store.db_path).resolve()) + '.execution.lock'
    owner = threading.get_ident()
    with _registry_lock:
        entry = _owners.get(path)
        if entry:
            if entry[0] != owner:
                raise WorkflowError('worker_busy')
            entry[2] += 1
        else:
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
                raise WorkflowError('worker_busy') from None
            entry = [owner, f, 1]
            _owners[path] = entry
    try:
        yield
    finally:
        with _registry_lock:
            entry[2] -= 1
            if not entry[2]:
                f = entry[1]
                try:
                    if os.name == 'nt':
                        import msvcrt
                        f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                finally:
                    f.close(); del _owners[path]
