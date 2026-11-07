import math, os, re, secrets, threading, time, uuid
from pathlib import Path
from . import workflow
from .douyin import normalize_share, resolve_with_f2
from .douyin_http import resolve_share_url, download_stream
from .workflow_store import WorkflowError

ROOT=Path(__file__).resolve().parent.parent

def recover_download_locks(store):
    """Recovery must not depend on optional credentials or valid config files."""
    with store._tx() as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='douyin_jobs'").fetchone():
            DouyinImporter._expire(c,time.time())

class DouyinImporter:
    def __init__(self,wc,cfg,keys,*,resolver=None,downloader=None,share_resolver=None):
        self.wc,self.cfg,self.keys=wc,cfg,keys
        self.store=workflow.make_store(wc)
        self.resolver=resolver or resolve_with_f2
        self.downloader=downloader or download_stream
        self.share_resolver=share_resolver or resolve_share_url
        self.lease=cfg.get('lease_seconds',wc['lease_seconds'])
        self.max_attempts=cfg.get('max_attempts',wc['max_attempts'])
        if type(self.lease) not in (int,float) or not math.isfinite(self.lease) or self.lease<=0 or type(self.max_attempts) is not int or self.max_attempts<=0: raise WorkflowError('invalid_douyin_config')
        with self.store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS douyin_jobs (id TEXT PRIMARY KEY, canonical_url TEXT NOT NULL, work_id TEXT, status TEXT NOT NULL, token TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0, error_code TEXT, source_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS douyin_lock (id INTEGER PRIMARY KEY CHECK(id=1), job_id TEXT NOT NULL, token TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS douyin_cache (work_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL)')
    def status(self):
        return {'enabled':bool(self.cfg.get('enabled')), 'cookie_configured':bool(self.keys.get(self.cfg.get('cookie_env',''))), 'resolver_configured':bool(self.cfg.get('resolver_python') and Path(self.cfg['resolver_python']).is_file())}
    def _ready(self):
        s=self.status()
        for key,code in (('enabled','douyin_disabled'),('cookie_configured','missing_douyin_cookie'),('resolver_configured','douyin_resolver_unavailable')):
            if not s[key]: raise WorkflowError(code)
    @staticmethod
    def _safe(row):
        return {k:row[k] for k in ('id','work_id','status','attempts','error_code','source_id','created_at','updated_at')}
    def enqueue(self,text,rights_confirmed):
        self._ready()
        if rights_confirmed is not True: raise WorkflowError('rights_required')
        url=normalize_share(text); id=uuid.uuid4().hex; now=time.time()
        with self.store._tx() as c:
            c.execute("INSERT INTO douyin_jobs(id,canonical_url,status,created_at,updated_at) VALUES(?,?,'queued',?,?)",(id,url,now,now))
            return self._safe(c.execute('SELECT * FROM douyin_jobs WHERE id=?',(id,)).fetchone())
    def jobs(self):
        with self.store._tx() as c: return [self._safe(x) for x in c.execute('SELECT * FROM douyin_jobs ORDER BY created_at DESC')]
    def retry(self,id):
        self._ready()
        with self.store._tx() as c:
            r=c.execute('SELECT * FROM douyin_jobs WHERE id=?',(id,)).fetchone()
            if not r: raise WorkflowError('douyin_job_not_found')
            if r['status'] not in ('failed','needs_attention') or r['attempts']>=self.max_attempts: raise WorkflowError('douyin_state_conflict')
            c.execute("UPDATE douyin_jobs SET status='queued',error_code=NULL,updated_at=? WHERE id=?",(time.time(),id))
            return self._safe(c.execute('SELECT * FROM douyin_jobs WHERE id=?',(id,)).fetchone())
    @staticmethod
    def _expire(c,now):
        rows=c.execute("SELECT id,token FROM douyin_jobs WHERE status='running' AND lease_until<=?",(now,)).fetchall()
        for r in rows:
            lock=c.execute('SELECT job_id,token FROM douyin_lock WHERE id=1').fetchone()
            if lock and lock['job_id']==r['id'] and lock['token']==r['token']:
                c.execute('DELETE FROM douyin_lock WHERE id=1'); c.execute('DELETE FROM video_maintenance WHERE id=1')
            c.execute("UPDATE douyin_jobs SET status='needs_attention',error_code='douyin_lease_expired',token=NULL,lease_until=NULL,updated_at=? WHERE id=?",(now,r['id']))
    def recover_expired(self):
        with self.store._tx() as c: self._expire(c,time.time())
    def _heartbeat(self,id,token):
        with self.store._tx() as c:
            now=time.time()
            result=c.execute("UPDATE douyin_jobs SET lease_until=?,updated_at=? WHERE id=? AND token=? AND status='running' AND lease_until>?",(now+self.lease,now,id,token,now))
            return result.rowcount==1
    def _cache(self,work):
        with self.store._tx() as c:
            row=c.execute('SELECT * FROM douyin_cache WHERE work_id=?',(work,)).fetchone()
            if not row: return None
            try: source=self.store._row(c,'sources',row['source_id'])
            except WorkflowError: return None
            if source['deleted'] or source['sha256']!=row['source_sha256']: return None
        try:
            root=workflow._root(self.wc).resolve(); p=root/source['blob_relpath']
            if any(x.is_symlink() or (hasattr(x,'is_junction') and x.is_junction()) for x in (p,*p.parents)) or not p.resolve().is_relative_to(root) or workflow._hash(p)!=source['sha256']: return None
            return source['id']
        except OSError: return None
    def process_next(self, *args, **kwargs):
        from .execution_guard import execution_guard
        with execution_guard(self.store):
            return self._guarded_process_next(*args, **kwargs)
    def _guarded_process_next(self):
        self._ready(); now=time.time(); token=secrets.token_urlsafe(32)
        with self.store._tx() as c:
            self._expire(c,now)
            if c.execute('SELECT 1 FROM video_maintenance').fetchone() or c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(): return None
            job=c.execute("SELECT * FROM douyin_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not job: return None
            id=job['id']; c.execute('INSERT INTO video_maintenance VALUES(1)'); c.execute('INSERT INTO douyin_lock VALUES(1,?,?)',(id,token))
            c.execute("UPDATE douyin_jobs SET status='running',token=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=?",(token,now+self.lease,now,id))
        stop=threading.Event(); lost=threading.Event()
        def beat():
            while not stop.wait(max(.1,self.lease/3)):
                try:
                    if not self._heartbeat(id,token): lost.set(); return
                except Exception: lost.set(); return
        thread=threading.Thread(target=beat,daemon=True); thread.start()
        folder=None; target=None; source_id=None; work=None; error=None
        def fence(c):
            now=time.time()
            row=c.execute("SELECT 1 FROM douyin_jobs j JOIN douyin_lock l ON l.job_id=j.id AND l.token=j.token WHERE j.id=? AND j.token=? AND j.status='running' AND j.lease_until>? AND l.id=1",(id,token,now)).fetchone()
            if not row: raise WorkflowError('douyin_lease_expired')
        def check():
            if lost.is_set() or not self._heartbeat(id,token): raise WorkflowError('douyin_lease_expired')
        try:
            check()
            work=self.share_resolver(job['canonical_url'],self.cfg)
            if not isinstance(work,str) or not re.fullmatch(r'[0-9]+',work): raise WorkflowError('invalid_share')
            check()
            source_id=self._cache(work)
            if not source_id:
                check()
                data=self.resolver(work,self.keys[self.cfg['cookie_env']],self.cfg)
                check()
                base=ROOT/'tmp'/'douyin'
                if any(x.is_symlink() or (hasattr(x,'is_junction') and x.is_junction()) for x in (base,*base.parents)): raise WorkflowError('douyin_import_failed')
                base.mkdir(parents=True,exist_ok=True)
                folder=base/(id+'-'+uuid.uuid4().hex); folder.mkdir(exist_ok=False)
                if not folder.resolve().is_relative_to(base.resolve()): raise WorkflowError('douyin_import_failed')
                target=folder/'input.mp4'
                download_cfg=dict(self.cfg); download_cfg['min_free_bytes']=max(self.cfg['min_free_bytes'],self.wc['min_free_bytes'])
                self.downloader(data['media_url'],target,download_cfg)
                if lost.is_set() or not self._heartbeat(id,token): raise WorkflowError('douyin_lease_expired')
                imported=workflow.import_file(self.wc,target,rights_confirmed=True,commit_guard=fence)
                source_id=imported['source']['id']
                if not imported.get('duplicate',False):
                    with self.store._tx() as c: c.execute('UPDATE sources SET original_name=? WHERE id=?',(f'douyin-{work}.mp4',source_id))
        except Exception as exc:
            allowed={'invalid_share','douyin_unsafe_url','douyin_timeout','douyin_http_failed','douyin_redirect_limit','douyin_size_limit','disk_low','douyin_download_failed','douyin_resolver_failed','media_tool_missing','download_denied','download_permission_unknown','douyin_lease_expired'}
            error=exc.code if isinstance(exc,WorkflowError) and exc.code in allowed else 'douyin_import_failed'
        finally:
            stop.set(); thread.join()
            if target and folder and not folder.is_symlink() and not (hasattr(folder,'is_junction') and folder.is_junction()) and folder.resolve().is_relative_to((ROOT/'tmp'/'douyin').resolve()) and not any(x.is_symlink() or (hasattr(x,'is_junction') and x.is_junction()) for x in (folder,*folder.parents)):
                try: target.unlink(missing_ok=True)
                except OSError: pass
            if folder and not folder.is_symlink() and not (hasattr(folder,'is_junction') and folder.is_junction()) and not any(x.is_symlink() or (hasattr(x,'is_junction') and x.is_junction()) for x in folder.parents):
                try: folder.rmdir()
                except OSError: pass
        with self.store._tx() as c:
            now=time.time(); row=c.execute('SELECT * FROM douyin_jobs WHERE id=?',(id,)).fetchone()
            lock=c.execute('SELECT * FROM douyin_lock WHERE id=1').fetchone()
            if not row or row['status']!='running' or row['token']!=token or row['lease_until']<=now or not lock or lock['job_id']!=id or lock['token']!=token:
                self._expire(c,now)
                return self._safe(c.execute('SELECT * FROM douyin_jobs WHERE id=?',(id,)).fetchone())
            if source_id and not error:
                s=self.store._row(c,'sources',source_id)
                c.execute('INSERT OR REPLACE INTO douyin_cache VALUES(?,?,?)',(work,source_id,s['sha256']))
            c.execute('UPDATE douyin_jobs SET status=?,error_code=?,work_id=?,source_id=?,token=NULL,lease_until=NULL,updated_at=? WHERE id=?',('failed' if error else 'succeeded',error,work,source_id,now,id))
            c.execute('DELETE FROM douyin_lock WHERE id=1'); c.execute('DELETE FROM video_maintenance WHERE id=1')
            return self._safe(c.execute('SELECT * FROM douyin_jobs WHERE id=?',(id,)).fetchone())
