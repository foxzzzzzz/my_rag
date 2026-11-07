"""Persisted, explicit browser processing requests; no implicit paid scans."""
import os
import threading
import time
import uuid

from .workflow_store import WorkflowError


class WebDispatcher:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.config = service.webcfg
        self.stop_event = threading.Event()
        self.thread = None
        self.active = None
        with self.store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS web_dispatch (task_id TEXT PRIMARY KEY, mode TEXT NOT NULL, state TEXT NOT NULL, requested REAL NOT NULL, claimed REAL, owner TEXT)')
            if 'error_code' not in {r[1] for r in c.execute('PRAGMA table_info(web_dispatch)')}:
                c.execute('ALTER TABLE web_dispatch ADD COLUMN error_code TEXT')
            if 'processing_mode' not in {r[1] for r in c.execute('PRAGMA table_info(web_dispatch)')}:
                c.execute("ALTER TABLE web_dispatch ADD COLUMN processing_mode TEXT NOT NULL DEFAULT 'preview'")

    def enqueue(self, task_id, mode='run', allow_paid=False, processing_mode='preview'):
        if mode not in ('run', 'resume') or type(allow_paid) is not bool or processing_mode not in ('preview','model'):
            raise WorkflowError('invalid_request')
        with self.store._tx() as c:
            task = self.store._row(c, 'tasks', task_id)
            source = self.store._row(c, 'sources', task['source_id'])
            if source['deleted']: raise WorkflowError('source_deleted')
            if source['kind'] == 'video':
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
            elif source['kind']=='html' and processing_mode=='model':
                if not self.config.get('live_html_enabled',False): raise WorkflowError('html_model_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
            elif mode == 'resume': raise WorkflowError('invalid_state')
            old = c.execute('SELECT * FROM web_dispatch WHERE task_id=?', (task_id,)).fetchone()
            if old and old['state'] in ('pending', 'working') and old['mode'] == mode:
                if old['processing_mode'] != processing_mode: raise WorkflowError('dispatch_conflict')
                return {'task_id': task_id, 'dispatch_state': old['state'], 'duplicate': True}
            expected = 'needs_attention' if mode == 'resume' else 'queued'
            if task['status'] != expected: raise WorkflowError('invalid_state')
            c.execute("INSERT INTO web_dispatch(task_id,mode,state,requested,claimed,owner,error_code) VALUES(?,?,'pending',?,NULL,NULL,NULL) ON CONFLICT(task_id) DO UPDATE SET mode=excluded.mode,state='pending',requested=excluded.requested,claimed=NULL,owner=NULL,error_code=NULL", (task_id, mode, time.time()))
            c.execute('UPDATE web_dispatch SET processing_mode=? WHERE task_id=?',(processing_mode,task_id))
            return {'task_id': task_id, 'dispatch_state': 'pending', 'duplicate': False}

    def _claim(self):
        with self.store._tx() as c:
            now = time.time()
            self.store._recover(c, now)
            # Only a stale dispatch whose domain task never began can requeue.
            c.execute("UPDATE web_dispatch SET state='pending',owner=NULL WHERE state='working' AND claimed<=? AND task_id IN (SELECT id FROM tasks WHERE status='queued')", (now-self.config['dispatch_recovery_seconds'],))
            c.execute("UPDATE web_dispatch SET state='done' WHERE state='working' AND task_id IN (SELECT id FROM tasks WHERE status='succeeded')")
            c.execute("UPDATE web_dispatch SET state='error' WHERE state='working' AND task_id IN (SELECT id FROM tasks WHERE status IN ('failed','needs_attention','cancelled'))")
            if c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone() or c.execute('SELECT 1 FROM video_maintenance').fetchone():
                return None
            row = c.execute("SELECT * FROM web_dispatch WHERE state='pending' ORDER BY requested LIMIT 1").fetchone()
            if not row: return None
            job = dict(row)
            token = uuid.uuid4().hex
            c.execute("UPDATE web_dispatch SET state='working',owner=?,claimed=? WHERE task_id=? AND state='pending'", (token,now,job['task_id']))
            job['owner'] = token
            return job

    def reprocess_html(self, source_id, expected_version_id, allow_paid=False):
        """New explicit task and consent in one transaction; never revive a POST."""
        if type(allow_paid) is not bool: raise WorkflowError('invalid_request')
        if not self.config.get('live_html_enabled',False): raise WorkflowError('html_model_disabled')
        if not allow_paid: raise WorkflowError('paid_consent_required')
        with self.store._tx() as c:
            s=self.store._row(c,'sources',source_id)
            if s['deleted']: raise WorkflowError('source_deleted')
            if s['kind']!='html': raise WorkflowError('invalid_source')
            if not expected_version_id or s['current_version_id']!=expected_version_id: raise WorkflowError('version_conflict')
            if c.execute("SELECT 1 FROM tasks WHERE source_id=? AND status IN ('queued','running','needs_attention')",(source_id,)).fetchone(): raise WorkflowError('invalid_state')
            tid=uuid.uuid4().hex
            c.execute("INSERT INTO tasks(id,source_id,status) VALUES(?,?,'queued')",(tid,source_id))
            c.execute("INSERT INTO web_dispatch(task_id,mode,state,requested,processing_mode) VALUES(?,'run','pending',?,'model')",(tid,time.time()))
            c.execute('CREATE TABLE IF NOT EXISTS html_runs (task_id TEXT PRIMARY KEY, base_version_id TEXT)')
            c.execute('INSERT INTO html_runs(task_id,base_version_id) VALUES(?,?)',(tid,expected_version_id))
            return {'task_id':tid,'source_id':source_id,'dispatch_state':'pending','processing_mode':'model'}

    def cancel(self, task_id):
        # Revoke both the lease and the explicit web request atomically.
        with self.store._tx() as c:
            task = self.store._cancel(c, task_id)
            c.execute("UPDATE web_dispatch SET state='cancelled',owner=NULL WHERE task_id=?", (task_id,))
            return {'id':task_id,'source_id':task['source_id'],'status':'cancelled'}

    def retry(self, task_id, allow_paid=False, processing_mode=None):
        if type(allow_paid) is not bool or processing_mode not in (None,'preview','model'): raise WorkflowError('invalid_request')
        with self.store._tx() as c:
            task = self.store._row(c,'tasks',task_id)
            source = self.store._row(c,'sources',task['source_id'])
            if source['deleted']: raise WorkflowError('source_deleted')
            if source['kind']=='video':
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
            if task['status'] not in ('failed','cancelled') or task['external_started'] or task['attempts']>=self.store.max_attempts:
                raise WorkflowError('invalid_state')
            old=c.execute('SELECT processing_mode FROM web_dispatch WHERE task_id=?',(task_id,)).fetchone()
            chosen=processing_mode if processing_mode is not None else (old['processing_mode'] if old else 'preview')
            if source['kind']=='html' and chosen=='model':
                if not self.config.get('live_html_enabled',False): raise WorkflowError('html_model_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
            c.execute("UPDATE tasks SET status='queued',error_code=NULL WHERE id=?", (task_id,))
            c.execute("INSERT INTO web_dispatch(task_id,mode,state,requested,claimed,owner,error_code) VALUES(?,'run','pending',?,NULL,NULL,NULL) ON CONFLICT(task_id) DO UPDATE SET mode='run',state='pending',requested=excluded.requested,claimed=NULL,owner=NULL,error_code=NULL", (task_id,time.time()))
            c.execute('UPDATE web_dispatch SET processing_mode=? WHERE task_id=?',(chosen,task_id))
            return {'task_id':task_id,'dispatch_state':'pending','duplicate':False}

    def process_next(self, *args, **kwargs):
        from .execution_guard import execution_guard
        try:
            with execution_guard(self.store):
                return self._guarded_process_next(*args, **kwargs)
        except WorkflowError as exc:
            if exc.code == 'worker_busy': return None
            raise
    def _guarded_process_next(self):
        # Recover only locks proven to belong to expired download jobs, even
        # after the administrator disables downloads or removes credentials.
        from .douyin_import import recover_download_locks
        recover_download_locks(self.store)
        job = self._claim()
        if not job:
            try:
                downloader=self.service.douyin
                status=downloader.status()
                if all(status.values()): return downloader.process_next()
            except WorkflowError:
                pass  # Optional downloads do not block HTML/video work.
            return None
        tid, token = job['task_id'], job['owner']
        self.active = (tid, token)
        error = None
        try:
            task = self.store.get_task(tid)
            source = self.store.get_source(task['source_id'])
            if source['deleted']: raise WorkflowError('source_deleted')
            expected = 'needs_attention' if job['mode']=='resume' else 'queued'
            if task['status'] != expected: raise WorkflowError('invalid_state')
            if source['kind'] == 'html':
                if job['processing_mode']=='model':
                    if not self.config.get('live_html_enabled',False): raise WorkflowError('html_model_disabled')
                    from .html_pipeline import run_html, load_html_config
                    from .workflow import ROOT
                    from tools.demo_setup import dotenv
                    keys=dotenv(ROOT/self.config['env_file']);keys.update(os.environ)
                    run_html(self.service.wc,load_html_config(ROOT/self.config['html_pipeline_config']),keys,task_id=tid,resume=job['mode']=='resume')
                else:
                    from .workflow import run_once
                    result = run_once(self.service.wc, worker_id='web-html', task_id=tid)
                    if not result or 'error' in result: raise WorkflowError(result.get('error','invalid_state') if result else 'invalid_state')
            elif source['kind'] == 'video':
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                runner = self.service.video_runner
                if runner is None:
                    from .video_pipeline import run_video
                    runner = run_video
                    from .workflow import ROOT
                    from tools.demo_setup import dotenv
                    keys = dotenv(ROOT/self.config['env_file'])
                    keys.update(os.environ)
                else:
                    keys = {}  # Injected offline tests do not read secrets.
                runner(self.service.wc, self.service.pc, keys, task_id=tid, resume=job['mode']=='resume')
            else:
                raise WorkflowError('unsupported_format')
        except Exception as exc:
            error = exc.code if isinstance(exc, WorkflowError) else 'dispatch_failed'
        finally:
            self.active = None
            with self.store._tx() as c:
                c.execute('UPDATE web_dispatch SET state=?,error_code=? WHERE task_id=? AND owner=?', ('error' if error else 'done', error, tid, token))
        return {'task_id':tid, 'dispatch_state':'error' if error else 'done', 'error':error}

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try: self.process_next()
                except Exception: pass  # Persisted requests survive transient DB errors.
                self.stop_event.wait(self.config['dispatch_poll_seconds'])
        self.thread = threading.Thread(target=loop, name='personalkb-web-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=self.config['shutdown_timeout_seconds'])
        # An active external call is not pretended to have stopped. On process
        # exit its domain lease recovers using the Phase 2B unknown-call rules.
        return not (self.thread and self.thread.is_alive())
