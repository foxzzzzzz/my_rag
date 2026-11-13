import hashlib, json, math, os, re, secrets, sqlite3, time, uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath

class WorkflowError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def _id(): return uuid.uuid4().hex
def _json(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def _number(x, lo, hi=None):
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x) and x >= lo and (hi is None or x <= hi)

_UNSET = object()
ASR_UPLOAD_STAGES = ('asr_upload_policy', 'asr_audio_upload')
ASR_UPLOAD_TASK_STAGES = (*ASR_UPLOAD_STAGES, 'asr_upload_prepare')

class WorkflowStore:
    def __init__(self, db_path, *, quality_target=98, lease_seconds=300, max_attempts=3, busy_timeout_seconds=5, content_root=None, data_root=None, source_trash_days=7):
        if not _number(quality_target, 0, 100) or not _number(lease_seconds, 0.000001) or not _number(busy_timeout_seconds, 0) or not _number(max_attempts, 1) or int(max_attempts) != max_attempts:
            raise WorkflowError('invalid_config')
        if type(source_trash_days) is not int or not 1 <= source_trash_days <= 3650:
            raise WorkflowError('invalid_config')
        self.trash_retention_seconds = source_trash_days * 86400
        self.db_path, self.quality_target, self.lease_seconds, self.max_attempts, self.busy_timeout_seconds = str(db_path), quality_target, lease_seconds, int(max_attempts), busy_timeout_seconds
        self.content_root = Path(content_root).absolute() if content_root else None
        self.data_root = Path(data_root).absolute() if data_root else None
        with self._tx() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, kind TEXT NOT NULL, sha256 TEXT NOT NULL, original_name TEXT NOT NULL, blob_relpath TEXT NOT NULL, current_version_id TEXT, deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), UNIQUE(kind,sha256));
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, worker_id TEXT, lease_token TEXT, lease_until REAL, stage TEXT, remote_task_id TEXT, external_started INTEGER NOT NULL DEFAULT 0, error_code TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, content_sha256 TEXT NOT NULL, result TEXT NOT NULL, output_kind TEXT NOT NULL, parent_version_id TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS reviews (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, source_id TEXT NOT NULL, version_id TEXT NOT NULL, content_sha256 TEXT NOT NULL, score REAL NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL, tags TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS content_sync (source_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, synced_generation INTEGER NOT NULL DEFAULT 0, state_sha256 TEXT);
CREATE TRIGGER IF NOT EXISTS content_source_insert AFTER INSERT ON sources BEGIN INSERT INTO content_sync(source_id,generation) VALUES(NEW.id,1); END;
CREATE TRIGGER IF NOT EXISTS content_source_update AFTER UPDATE OF current_version_id,deleted ON sources BEGIN INSERT INTO content_sync(source_id,generation) VALUES(NEW.id,1) ON CONFLICT(source_id) DO UPDATE SET generation=generation+1; END;
CREATE TRIGGER IF NOT EXISTS content_version_insert AFTER INSERT ON versions BEGIN INSERT INTO content_sync(source_id,generation) VALUES(NEW.source_id,1) ON CONFLICT(source_id) DO UPDATE SET generation=generation+1; END;
CREATE TRIGGER IF NOT EXISTS content_review_insert AFTER INSERT ON reviews BEGIN INSERT INTO content_sync(source_id,generation) VALUES(NEW.source_id,1) ON CONFLICT(source_id) DO UPDATE SET generation=generation+1; END;
CREATE TABLE IF NOT EXISTS video_maintenance (id INTEGER PRIMARY KEY CHECK(id=1));
CREATE TABLE IF NOT EXISTS source_trash (source_id TEXT PRIMARY KEY, deleted_at REAL NOT NULL, purge_started INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS source_display_titles (source_id TEXT PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS video_reprocess (task_id TEXT PRIMARY KEY, base_version_id TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS tasks_updated AFTER UPDATE ON tasks BEGIN UPDATE tasks SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id; END;''')
            c.execute('INSERT OR IGNORE INTO source_trash(source_id,deleted_at) SELECT id,? FROM sources WHERE deleted=1', (time.time(),))
    @contextmanager
    def _tx(self):
        c=sqlite3.connect(self.db_path, timeout=self.busy_timeout_seconds, isolation_level=None)
        c.row_factory=sqlite3.Row
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception:
            c.rollback(); raise
        finally: c.close()
    def _row(self,c,table,id):
        r=c.execute('SELECT * FROM '+table+' WHERE id=?',(id,)).fetchone()
        if r is None: raise WorkflowError(table[:-1]+'_not_found')
        d=dict(r)
        if table=='versions': d['result']=json.loads(d['result'])
        if table=='reviews': d['tags']=json.loads(d['tags'])
        return d
    def import_source(self,kind,sha256,original_name,blob_relpath,*,commit_guard=None, install_blob=None):
        if not isinstance(kind,str) or not kind or not isinstance(sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',sha256) or not isinstance(original_name,str) or not original_name or not isinstance(blob_relpath,str) or not blob_relpath or PurePosixPath(blob_relpath).is_absolute() or PureWindowsPath(blob_relpath).is_absolute() or PureWindowsPath(blob_relpath).drive or '..' in PurePosixPath(blob_relpath.replace('\\','/')).parts:
            raise WorkflowError('invalid_source')
        with self._tx() as c:
            if commit_guard is not None: commit_guard(c)
            if kind in ('video', 'mp4'):
                row = c.execute("SELECT * FROM sources WHERE sha256=? AND kind IN ('video','mp4') ORDER BY CASE kind WHEN 'video' THEN 0 ELSE 1 END LIMIT 1", (sha256,)).fetchone()
            else:
                row = c.execute('SELECT * FROM sources WHERE kind=? AND sha256=?', (kind, sha256)).fetchone()
            if row:
                s=dict(row)
                if s['deleted']: raise WorkflowError('source_deleted')
                if install_blob is not None:
                    retiring = False
                    if s['kind'] in ('video', 'mp4') and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_retention'").fetchone():
                        marker = c.execute('SELECT * FROM media_retention WHERE source_id=?', (s['id'],)).fetchone()
                        if marker:
                            if marker['sha256'] != s['sha256'] or marker['blob_relpath'] != s['blob_relpath']: raise WorkflowError('retention_conflict')
                            retiring = marker['status'] in ('planned', 'removed')
                    if not retiring and s['blob_relpath'] == blob_relpath: install_blob()
                t=dict(c.execute('SELECT * FROM tasks WHERE source_id=? ORDER BY rowid LIMIT 1',(s['id'],)).fetchone())
                return dict(source=s,task=t,duplicate=True)
            if install_blob is not None: install_blob()
            sid,tid=_id(),_id()
            c.execute('INSERT INTO sources(id,kind,sha256,original_name,blob_relpath) VALUES(?,?,?,?,?)',(sid,kind,sha256,original_name,blob_relpath))
            c.execute("INSERT INTO tasks(id,source_id,status) VALUES(?,?,'queued')",(tid,sid))
            return dict(source=self._row(c,'sources',sid),task=self._row(c,'tasks',tid),duplicate=False)
    def get_source(self,id):
        with self._tx() as c: return self._row(c,'sources',id)
    def get_task(self,id):
        with self._tx() as c: return self._row(c,'tasks',id)
    def get_version(self,id):
        with self._tx() as c: return self._row(c,'versions',id)
    def list_sources(self):
        with self._tx() as c: return [dict(r) for r in c.execute('SELECT * FROM sources ORDER BY rowid')]
    def list_tasks(self):
        with self._tx() as c: return [dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY rowid')]
    def list_versions(self,source_id):
        with self._tx() as c:
            self._row(c,'sources',source_id)
            return [self._row(c,'versions',r[0]) for r in c.execute('SELECT id FROM versions WHERE source_id=? ORDER BY rowid',(source_id,))]
    def _recover(self,c,now):
        c.execute("""UPDATE tasks
            SET status=CASE WHEN external_started=1 OR stage IN (?,?,?) THEN 'needs_attention'
                            WHEN attempts>=? THEN 'failed' ELSE 'queued' END,
                error_code=CASE WHEN stage IN (?,?,?) THEN 'upload_interrupted' ELSE error_code END,
                lease_token=NULL, lease_until=NULL, worker_id=NULL
            WHERE status='running' AND lease_until<=?""",
            (*ASR_UPLOAD_TASK_STAGES, self.max_attempts, *ASR_UPLOAD_TASK_STAGES, now))
    def recover_expired(self,now=None):
        with self._tx() as c: self._recover(c,time.time() if now is None else now)
    def claim(self, *args, **kwargs):
        from .execution_guard import execution_guard
        try:
            with execution_guard(self):
                return self._guarded_claim(*args, **kwargs)
        except WorkflowError as exc:
            if exc.code == 'worker_busy': return None
            raise
    def _guarded_claim(self,worker_id,now=None):
        if not isinstance(worker_id,str) or not worker_id.strip(): raise WorkflowError('invalid_worker')
        now=time.time() if now is None else now
        with self._tx() as c:
            self._recover(c,now)
            if c.execute("SELECT 1 FROM video_maintenance").fetchone() or c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(): return None
            r=c.execute("""SELECT tasks.id FROM tasks JOIN sources ON sources.id=tasks.source_id
                WHERE tasks.status='queued' AND tasks.attempts<? AND sources.deleted=0
                AND NOT EXISTS (SELECT 1 FROM video_reprocess WHERE task_id=tasks.id)
                ORDER BY tasks.rowid LIMIT 1""",(self.max_attempts,)).fetchone()
            if not r: return None
            c.execute("UPDATE tasks SET status='running',attempts=attempts+1,worker_id=?,lease_token=?,lease_until=? WHERE id=?",(worker_id,secrets.token_urlsafe(32),now+self.lease_seconds,r[0]))
            return self._row(c,'tasks',r[0])
    def claim_specific(self, *args, **kwargs):
        from .execution_guard import execution_guard
        try:
            with execution_guard(self):
                return self._guarded_claim_specific(*args, **kwargs)
        except WorkflowError as exc:
            if exc.code == 'worker_busy': return None
            raise
    def _guarded_claim_specific(self,task_id,worker_id,now=None):
        if not isinstance(worker_id,str) or not worker_id.strip(): raise WorkflowError('invalid_worker')
        now=time.time() if now is None else now
        with self._tx() as c:
            self._recover(c,now)
            if c.execute("SELECT 1 FROM video_maintenance").fetchone() or c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(): return None
            r=c.execute("""SELECT tasks.id FROM tasks JOIN sources ON sources.id=tasks.source_id
                WHERE tasks.id=? AND tasks.status='queued' AND tasks.attempts<? AND sources.deleted=0
                AND NOT EXISTS (SELECT 1 FROM video_reprocess WHERE task_id=tasks.id)""",(task_id,self.max_attempts)).fetchone()
            if not r: return None
            c.execute("UPDATE tasks SET status='running',attempts=attempts+1,worker_id=?,lease_token=?,lease_until=? WHERE id=?",(worker_id,secrets.token_urlsafe(32),now+self.lease_seconds,r[0]))
            return self._row(c,'tasks',r[0])
    def _lease(self,c,id,token,now):
        t=self._row(c,'tasks',id)
        if t['status']!='running' or not isinstance(token,str) or not secrets.compare_digest(t['lease_token'] or '',token) or t['lease_until']<=now: raise WorkflowError('invalid_lease')
        if self._row(c,'sources',t['source_id'])['deleted']: raise WorkflowError('source_deleted')
        return t
    def heartbeat(self,task_id,token,now=None):
        now=time.time() if now is None else now
        with self._tx() as c:
            self._lease(c,task_id,token,now); c.execute('UPDATE tasks SET lease_until=? WHERE id=?',(now+self.lease_seconds,task_id)); return self._row(c,'tasks',task_id)
    def checkpoint(self,task_id,token,stage,*,remote_task_id=None,external_started=False,now=None):
        now=time.time() if now is None else now
        if not isinstance(stage,str) or not stage.strip() or (remote_task_id is not None and (not isinstance(remote_task_id,str) or not remote_task_id.strip())) or not isinstance(external_started,bool): raise WorkflowError('invalid_checkpoint')
        with self._tx() as c:
            t=self._lease(c,task_id,token,now)
            if t['remote_task_id'] and remote_task_id and t['remote_task_id']!=remote_task_id: raise WorkflowError('remote_task_conflict')
            c.execute('UPDATE tasks SET stage=?,remote_task_id=?,external_started=? WHERE id=?',(stage,remote_task_id or t['remote_task_id'],int(external_started or t['external_started'] or remote_task_id is not None),task_id)); return self._row(c,'tasks',task_id)
    def _version(self,c,sid,result,parent,human):
        if not isinstance(result,dict) or any(not isinstance(result.get(k),str) or not result[k].strip() for k in ('title','body','summary','notes','scheme_id','scheme_version','output_kind')) or result.get('output_kind') != ('human_edited' if human else 'machine_initial') or result.get('provenance') not in (('human_edited',) if human else ('local_extraction','provider')) or not isinstance(result.get('evidence'),list) or not result['evidence'] or any(not isinstance(e,dict) or not isinstance(e.get('text'),str) or not e['text'].strip() for e in result['evidence']): raise WorkflowError('invalid_result')
        s=self._row(c,'sources',sid)
        if s['kind'] in ('video','mp4') and any(not isinstance(result.get(k),str) or not result[k].strip() for k in ('transcript','visual')): raise WorkflowError('invalid_result')
        try: raw=_json(result)
        except (ValueError,TypeError): raise WorkflowError('invalid_result')
        vid=_id(); sha=hashlib.sha256(raw.encode()).hexdigest()
        c.execute('INSERT INTO versions(id,source_id,content_sha256,result,output_kind,parent_version_id) VALUES(?,?,?,?,?,?)',(vid,sid,sha,raw,result['output_kind'],parent)); c.execute('UPDATE sources SET current_version_id=? WHERE id=?',(vid,sid))
        return self._row(c,'versions',vid)
    def finish(self,task_id,token,result,now=None,*,expected_version_id=_UNSET):
        now=time.time() if now is None else now
        with self._tx() as c:
            t=self._lease(c,task_id,token,now); s=self._row(c,'sources',t['source_id'])
            reprocess=c.execute('SELECT base_version_id FROM video_reprocess WHERE task_id=?', (task_id,)).fetchone()
            if reprocess and s['current_version_id'] != reprocess[0]: raise WorkflowError('version_conflict')
            if expected_version_id is not _UNSET and s['current_version_id'] != expected_version_id: raise WorkflowError('version_conflict')
            v=self._version(c,s['id'],result,s['current_version_id'],False)
            c.execute("UPDATE tasks SET status='succeeded',lease_token=NULL,lease_until=NULL,error_code=NULL WHERE id=?",(task_id,)); return v
    def fail(self,task_id,token,code,*,needs_attention=False,now=None):
        now=time.time() if now is None else now
        if not isinstance(code,str) or not code.strip(): raise WorkflowError('invalid_error')
        with self._tx() as c:
            t=self._lease(c,task_id,token,now)
            status='needs_attention' if needs_attention or t['external_started'] else 'failed'
            c.execute('UPDATE tasks SET status=?,error_code=?,lease_token=NULL,lease_until=NULL WHERE id=?',(status,code,task_id)); return self._row(c,'tasks',task_id)
    def cancel(self,task_id):
        with self._tx() as c:
            return self._cancel(c, task_id)
    def _cancel(self, c, task_id):
        t=self._row(c,'tasks',task_id)
        if t['status'] not in ('queued','running'): raise WorkflowError('invalid_state')
        c.execute("UPDATE tasks SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE id=?",(task_id,))
        return self._row(c,'tasks',task_id)
    def retry(self,task_id):
        with self._tx() as c:
            t=self._row(c,'tasks',task_id)
            if self._row(c,'sources',t['source_id'])['deleted']: raise WorkflowError('source_deleted')
            if t['status'] not in ('failed','cancelled') or t['external_started'] or t['attempts']>=self.max_attempts: raise WorkflowError('invalid_state')
            c.execute("UPDATE tasks SET status='queued',error_code=NULL WHERE id=?",(task_id,)); return self._row(c,'tasks',task_id)
    def revise(self,source_id,expected_version_id,result):
        with self._tx() as c:
            s=self._row(c,'sources',source_id)
            if s['deleted']: raise WorkflowError('source_deleted')
            if not expected_version_id or s['current_version_id']!=expected_version_id: raise WorkflowError('version_conflict')
            return self._version(c,source_id,result,expected_version_id,True)
    def review(self,source_id,version_id,content_sha256,score,decision,reviewer,*,review_id=None,note='',tags=None):
        if not _number(score,0,100) or decision not in ('approve','reject','rework') or (decision=='approve' and score<self.quality_target) or not isinstance(reviewer,str) or not reviewer.strip() or not isinstance(note,str) or (tags is not None and (not isinstance(tags,list) or any(not isinstance(t,str) for t in tags))) or (review_id is not None and (not isinstance(review_id,str) or not review_id.strip())): raise WorkflowError('invalid_review')
        rid=review_id or _id(); tags=_json(tags or [])
        with self._tx() as c:
            s=self._row(c,'sources',source_id)
            if s['deleted']: raise WorkflowError('source_deleted')
            if s['current_version_id']!=version_id: raise WorkflowError('version_conflict')
            v=self._row(c,'versions',version_id)
            if v['source_id']!=source_id or v['content_sha256']!=content_sha256: raise WorkflowError('version_conflict')
            old=c.execute('SELECT * FROM reviews WHERE id=?',(rid,)).fetchone()
            vals=(source_id,version_id,content_sha256,score,decision,reviewer,note,tags)
            if old:
                if tuple(old[k] for k in ('source_id','version_id','content_sha256','score','decision','reviewer','note','tags'))!=vals: raise WorkflowError('review_conflict')
            else: c.execute('INSERT INTO reviews(id,source_id,version_id,content_sha256,score,decision,reviewer,note,tags) VALUES(?,?,?,?,?,?,?,?,?)',(rid,*vals))
            return self._row(c,'reviews',rid)
    def assert_synced(self, source_id):
        if not self.content_root: raise WorkflowError('content_storage_disabled')
        from .content_storage import verify
        return verify(self, source_id)
    def content_status(self, source_id):
        if not self.content_root: return 'disabled'
        try: self.assert_synced(source_id); return 'synced'
        except (WorkflowError, OSError) as exc: return getattr(exc, 'code', 'content_integrity')
    def sync_source(self, source_id):
        if not self.content_root: raise WorkflowError('content_storage_disabled')
        from .content_storage import sync
        return sync(self, source_id)
    def reconcile(self, source_id=None):
        if not self.content_root: raise WorkflowError('content_storage_disabled')
        with self._tx() as c:
            ids=[source_id] if source_id else [r[0] for r in c.execute('SELECT id FROM sources')]
            for sid in ids:
                self._row(c,'sources',sid)
                c.execute('INSERT OR IGNORE INTO content_sync(source_id,generation) VALUES(?,1)',(sid,))
        results={}
        for sid in ids:
            try: self.sync_source(sid); results[sid]='synced'
            except Exception as exc: results[sid]=getattr(exc,'code','content_write_failed')
        return results
    def eligible_sources(self):
        from .content_storage import verify
        with self._tx() as c:
            rows=[dict(r) for r in c.execute("SELECT s.* FROM sources s JOIN reviews r ON r.seq=(SELECT MAX(seq) FROM reviews WHERE version_id=s.current_version_id) WHERE s.deleted=0 AND r.decision='approve' AND r.score>=?",(self.quality_target,))]
            if not self.content_root: return rows
            eligible=[]
            for row in rows:
                try: verify(self,row['id'],connection=c); eligible.append(row)
                except (WorkflowError,OSError): pass
            return eligible
    def delete_source(self,id):
        with self._tx() as c:
            self._row(c,'sources',id)
            c.execute('UPDATE sources SET deleted=1 WHERE id=? AND deleted=0',(id,))
            c.execute('INSERT OR IGNORE INTO source_trash(source_id,deleted_at) VALUES(?,?)',(id,time.time()))
            c.execute("UPDATE tasks SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE source_id=? AND status IN ('queued','running')",(id,))
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='web_dispatch'").fetchone():
                c.execute("UPDATE web_dispatch SET state='cancelled',owner=NULL WHERE state IN ('pending','working') AND task_id IN (SELECT id FROM tasks WHERE source_id=?)", (id,))
            return self._row(c,'sources',id)

    def list_trash(self):
        now = time.time()
        with self._tx() as c:
            rows = c.execute("""SELECT s.id,s.original_name,t.deleted_at,t.purge_started,v.result
                                FROM source_trash t JOIN sources s ON s.id=t.source_id
                                LEFT JOIN versions v ON v.id=s.current_version_id
                                WHERE s.deleted=1 ORDER BY t.deleted_at DESC""").fetchall()
            items = []
            for row in rows:
                expires = row['deleted_at'] + self.trash_retention_seconds
                result = json.loads(row['result']) if row['result'] else {}
                items.append({'id':row['id'], 'original_name':row['original_name'], 'title':result.get('title',''),
                              'deleted_at':row['deleted_at'], 'expires_at':expires,
                              'can_restore':not row['purge_started'] and now < expires})
            return items

    def restore_source(self, source_id):
        from .execution_guard import execution_guard
        # Wait for any worker holding a dispatch from before deletion to exit.
        with execution_guard(self), self._tx() as c:
            source = self._row(c, 'sources', source_id)
            if not source['deleted']: return source
            marker = c.execute('SELECT deleted_at,purge_started FROM source_trash WHERE source_id=?', (source_id,)).fetchone()
            if not marker or marker['purge_started'] or time.time() >= marker['deleted_at'] + self.trash_retention_seconds:
                raise WorkflowError('trash_expired')
            c.execute('DELETE FROM source_trash WHERE source_id=?', (source_id,))
            c.execute('UPDATE sources SET deleted=0 WHERE id=?', (source_id,))
            return self._row(c, 'sources', source_id)


def _sync_after(method):
    def wrapped(self, *args, **kwargs):
        result=method(self, *args, **kwargs)
        if self.content_root:
            sid=result.get('source_id') if isinstance(result,dict) else None
            if method.__name__ in ('delete_source', 'restore_source'): sid=result['id']
            if sid:
                try: self.sync_source(sid)
                except Exception: pass  # Committed changes remain dirty for explicit replay.
        return result
    return wrapped

for _name in ('finish','revise','review','delete_source','restore_source'):
    setattr(WorkflowStore, _name, _sync_after(getattr(WorkflowStore, _name)))
