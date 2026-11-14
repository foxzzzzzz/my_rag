import hashlib, json, secrets, time, math, re
from contextlib import contextmanager
from .workflow_store import ASR_UPLOAD_STAGES, WorkflowError, _json

CHAT_ATTEMPTS_SCHEMA = """CREATE TABLE IF NOT EXISTS video_chat_attempts (
    task_id TEXT NOT NULL, stage TEXT NOT NULL, attempt INTEGER NOT NULL,
    amount TEXT, response TEXT, response_sha256 TEXT, diagnostic TEXT, provider_request_id TEXT,
    started INTEGER NOT NULL DEFAULT 0, automatic INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(task_id,stage,attempt))"""


def initialize_chat_attempts(connection):
    connection.execute(CHAT_ATTEMPTS_SCHEMA)
    if 'automatic' not in {row[1] for row in connection.execute('PRAGMA table_info(video_chat_attempts)')}:
        connection.execute('ALTER TABLE video_chat_attempts ADD COLUMN automatic INTEGER NOT NULL DEFAULT 0')


def is_chat_stage(name):
    return name == 'text' or re.fullmatch(r'vision-[0-9]+', name) is not None


def legacy_upload_interruption(connection, task, stages):
    # Older workers only emitted this storage error before registering the
    # temporary asset and calling the transcription provider.
    return (
        task['stage'] == 'asr_submit' and task['error_code'] == 'network_unconfirmed'
        and not task['remote_task_id'] and len(stages) == 1
        and stages[0]['name'] == 'asr_submit' and stages[0]['status'] == 'in_flight'
        and not stages[0]['remote_task_id']
        and not connection.execute('SELECT 1 FROM video_assets WHERE task_id=?', (task['id'],)).fetchone()
    )


class VideoJournal:
    def __init__(self, store):
        self.store=store
        self._cleanup=None
        with store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS video_runs (task_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS video_stages (task_id TEXT, name TEXT, input_sha256 TEXT, status TEXT, remote_task_id TEXT, result TEXT, result_sha256 TEXT, PRIMARY KEY(task_id,name))')
            c.execute('CREATE TABLE IF NOT EXISTS video_assets (asset_id TEXT PRIMARY KEY, task_id TEXT, metadata TEXT, status TEXT)')
            initialize_chat_attempts(c)
    def _lease(self,c,t,token): self.store._lease(c,t,token,time.time())
    def _claim(self, *args, **kwargs):
        from .execution_guard import execution_guard
        with execution_guard(self.store):
            return self._guarded__claim(*args, **kwargs)
    def _guarded__claim(self,task_id,worker_id,status):
        if not isinstance(worker_id,str) or not worker_id.strip(): raise WorkflowError('invalid_worker')
        with self.store._tx() as c:
            self.store._recover(c,time.time())
            t=self.store._row(c,'tasks',task_id)
            source=self.store._row(c,'sources',t['source_id'])
            if t['status']!=status or source['kind'] not in ('video','mp4') or (status=='queued' and t['attempts']>=self.store.max_attempts) or source['deleted'] or c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone() or c.execute('SELECT 1 FROM video_maintenance').fetchone(): raise WorkflowError('invalid_state')
            c.execute("UPDATE tasks SET status='running',attempts=attempts+1,worker_id=?,lease_token=?,lease_until=? WHERE id=?",(worker_id,secrets.token_urlsafe(32),time.time()+self.store.lease_seconds,task_id))
            return self.store._row(c,'tasks',task_id)
    def claim_task(self,task_id,worker_id): return self._claim(task_id,worker_id,'queued')
    def resume_claim(self,task_id,worker_id): return self._claim(task_id,worker_id,'needs_attention')
    def bind(self,task_id,token,fingerprint,legacy_fingerprint=None):
        with self.store._tx() as c:
            self._lease(c,task_id,token)
            r=c.execute('SELECT fingerprint FROM video_runs WHERE task_id=?',(task_id,)).fetchone()
            if r and r[0] not in (fingerprint, legacy_fingerprint): raise WorkflowError('fingerprint_conflict')
            c.execute('INSERT OR IGNORE INTO video_runs VALUES(?,?)',(task_id,fingerprint))
            return r[0] if r else fingerprint
    def stage(self,task_id,name):
        with self.store._tx() as c:
            r=c.execute('SELECT * FROM video_stages WHERE task_id=? AND name=?',(task_id,name)).fetchone()
            if not r: return None
            d=dict(r)
            if d['result'] is not None:
                if hashlib.sha256(d['result'].encode()).hexdigest()!=d['result_sha256']: raise WorkflowError('stage_corrupt')
                d['result']=json.loads(d['result'])
            return d
    def list_stages(self,task_id):
        with self.store._tx() as c: return [dict(r) for r in c.execute('SELECT name,input_sha256,status,remote_task_id,result_sha256 FROM video_stages WHERE task_id=?',(task_id,))]

    def chat_attempt(self, task_id, name):
        with self.store._tx() as c:
            return c.execute("""SELECT * FROM video_chat_attempts WHERE task_id=? AND stage=?
                       ORDER BY (response_sha256 IS NOT NULL) DESC, attempt DESC LIMIT 1""", (task_id, name)).fetchone()

    def start_chat_retry(self, task_id, token, name, attempt):
        with self.store._tx() as c:
            self._lease(c, task_id, token)
            if c.execute("""SELECT 1 FROM video_chat_attempts WHERE task_id=? AND stage=?
                AND response_sha256 IS NOT NULL""", (task_id, name)).fetchone():
                raise WorkflowError('chat_response_available')
            if c.execute("""UPDATE video_chat_attempts SET started=1
                WHERE task_id=? AND stage=? AND attempt=? AND amount IS NOT NULL AND started=0""",
                         (task_id, name, attempt)).rowcount != 1:
                raise WorkflowError('unknown_submission')
            c.execute('UPDATE tasks SET stage=? WHERE id=?', (name, task_id))

    def automatic_retry_count(self, task_id, name):
        with self.store._tx() as c:
            return c.execute("""SELECT COUNT(*) FROM video_chat_attempts
                WHERE task_id=? AND stage=? AND automatic=1""", (task_id, name)).fetchone()[0]

    def authorize_timeout_retry(self, task_id, token, name, amount, maximum):
        with self.store._tx() as c:
            self._lease(c, task_id, token)
            attempts = c.execute("""SELECT attempt,automatic,diagnostic,response_sha256 FROM video_chat_attempts
                WHERE task_id=? AND stage=? ORDER BY attempt DESC""", (task_id, name)).fetchall()
            if (not attempts or attempts[0]['diagnostic'] != 'provider_timeout'
                    or any(row['response_sha256'] for row in attempts)
                    or sum(row['automatic'] for row in attempts) >= maximum):
                return None
            attempt = attempts[0]['attempt'] + 1
            c.execute("""INSERT INTO video_chat_attempts(task_id,stage,attempt,amount,automatic)
                VALUES(?,?,?,?,1)""", (task_id, name, attempt, str(amount)))
            return attempt

    def record_chat_outcome(self, task_id, name, attempt, *, response=None, diagnostic=None, provider_request_id=None):
        raw = _json(response) if response is not None else None
        digest = hashlib.sha256(raw.encode()).hexdigest() if raw is not None else None
        # A provider reply can arrive after lease loss. Keep it with the
        # exact attempt so that recovery can check it without sending again.
        with self.store._tx() as c:
            c.execute("""INSERT INTO video_chat_attempts(task_id,stage,attempt,response,response_sha256,diagnostic,provider_request_id)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(task_id,stage,attempt) DO UPDATE SET
                response=excluded.response,response_sha256=excluded.response_sha256,diagnostic=excluded.diagnostic,
                provider_request_id=excluded.provider_request_id
                WHERE video_chat_attempts.response IS NULL""", (task_id, name, attempt, raw, digest, diagnostic, provider_request_id))
    def begin(self,task_id,token,name,input_sha256):
        with self.store._tx() as c:
            self._lease(c,task_id,token)
            r=c.execute('SELECT input_sha256 FROM video_stages WHERE task_id=? AND name=?',(task_id,name)).fetchone()
            if r and r[0]!=input_sha256: raise WorkflowError('stage_conflict')
            c.execute("INSERT OR IGNORE INTO video_stages(task_id,name,input_sha256,status) VALUES(?,?,?,'prepared')",(task_id,name,input_sha256))
    def upload_progress(self, task_id, token, name, digest, completed):
        if name not in ASR_UPLOAD_STAGES:
            raise WorkflowError('invalid_state')
        if completed:
            self.complete(task_id, token, name, {})
            return
        self.begin(task_id, token, name, digest)
        with self.store._tx() as c:
            self._lease(c, task_id, token)
            c.execute("UPDATE video_stages SET status='in_flight',result=NULL,result_sha256=NULL WHERE task_id=? AND name=?", (task_id, name))
            c.execute('UPDATE tasks SET stage=?,error_code=NULL WHERE id=?', (name, task_id))

    def restore_legacy_upload(self, task_id, token):
        with self.store._tx() as c:
            task = self.store._lease(c, task_id, token, time.time())
            stages = c.execute('SELECT name,status,remote_task_id FROM video_stages WHERE task_id=?', (task_id,)).fetchall()
            if not legacy_upload_interruption(c, task, stages):
                return False
            c.execute("UPDATE video_stages SET status='prepared' WHERE task_id=? AND name='asr_submit'", (task_id,))
            c.execute("UPDATE tasks SET stage='asr_upload_prepare',external_started=0,error_code=NULL WHERE id=?", (task_id,))
            return True
    def mark_started(self,task_id,token,name):
        with self.store._tx() as c:
            self._lease(c,task_id,token)
            if c.execute("UPDATE video_stages SET status='in_flight' WHERE task_id=? AND name=? AND status='prepared'",(task_id,name)).rowcount!=1: raise WorkflowError('invalid_state')
            c.execute('UPDATE tasks SET external_started=1,stage=? WHERE id=?',(name,task_id))
    def save_remote(self,task_id,token,name,remote_task_id):
        if not isinstance(remote_task_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',remote_task_id): raise WorkflowError('invalid_remote_task_id')
        with self.store._tx() as c:
            task=self.store._lease(c,task_id,token,time.time())
            if task['remote_task_id'] and task['remote_task_id'] != remote_task_id: raise WorkflowError('remote_task_conflict')
            r=c.execute('SELECT status,remote_task_id FROM video_stages WHERE task_id=? AND name=?',(task_id,name)).fetchone()
            if not r or r[0]!='in_flight' or (r[1] and r[1]!=remote_task_id): raise WorkflowError('invalid_state')
            c.execute('UPDATE video_stages SET remote_task_id=? WHERE task_id=? AND name=?',(remote_task_id,task_id,name))
            c.execute('UPDATE tasks SET remote_task_id=?,stage=?,external_started=1 WHERE id=?',(remote_task_id,name,task_id))
    def complete(self,task_id,token,name,result):
        raw=_json(result); sha=hashlib.sha256(raw.encode()).hexdigest()
        with self.store._tx() as c:
            self._lease(c,task_id,token)
            r=c.execute('SELECT status,result_sha256 FROM video_stages WHERE task_id=? AND name=?',(task_id,name)).fetchone()
            if not r or r[0] not in ('in_flight','completed') or (r[0]=='completed' and r[1]!=sha): raise WorkflowError('invalid_state')
            c.execute("UPDATE video_stages SET status='completed',result=?,result_sha256=? WHERE task_id=? AND name=?",(raw,sha,task_id,name))
            if is_chat_stage(name):
                c.execute("""UPDATE video_chat_attempts SET response=NULL,response_sha256=NULL
                    WHERE task_id=? AND stage=?""", (task_id, name))
    def register_asset(self,task_id,token,metadata):
        allowed=('asset_id','backend','object_key','source_sha256','size_bytes','model','expires_at','scope')
        if not isinstance(metadata,dict) or set(metadata)!=set(allowed): raise WorkflowError('invalid_asset')
        m=metadata; scope=m['scope']
        if (m['backend'] not in ('managed_oss','temporary') or not isinstance(m['asset_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',m['asset_id']) or not isinstance(m['model'],str) or not m['model'].strip() or not isinstance(m['source_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',m['source_sha256']) or isinstance(m['size_bytes'],bool) or not isinstance(m['size_bytes'],int) or m['size_bytes']<=0 or isinstance(m['expires_at'],bool) or not isinstance(m['expires_at'],(int,float)) or not math.isfinite(m['expires_at']) or m['expires_at']<=0 or not isinstance(m['object_key'],str) or not isinstance(scope,dict)):
            raise WorkflowError('invalid_asset')
        if m['backend']=='managed_oss':
            if set(scope)!={'bucket','endpoint','region','prefix'} or any(not isinstance(v,str) for v in scope.values()): raise WorkflowError('invalid_asset')
            region=scope['region']; prefix=scope['prefix']; key=m['object_key']
            if not re.fullmatch(r'cn-[a-z0-9-]+',region) or scope['endpoint']!=f'https://oss-{region}.aliyuncs.com' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',scope['bucket']) or not prefix.endswith('/') or '\\' in prefix or any(x in ('','.','..') for x in prefix[:-1].split('/')) or not re.fullmatch(r'[A-Za-z0-9_./-]+',key) or not key.startswith(prefix) or not key[len(prefix):] or any(x in ('','.','..') for x in key.split('/')) or any(ord(x)<32 for x in key): raise WorkflowError('invalid_asset')
        elif scope or m['object_key']: raise WorkflowError('invalid_asset')
        raw=_json(m)
        with self.store._tx() as c:
            self._lease(c,task_id,token)
            old=c.execute('SELECT task_id,metadata FROM video_assets WHERE asset_id=?',(m['asset_id'],)).fetchone()
            if old and (old[0]!=task_id or old[1]!=raw): raise WorkflowError('asset_conflict')
            if not old: c.execute("INSERT INTO video_assets VALUES(?,?,?,'registered')",(m['asset_id'],task_id,raw))
    def assets(self,task_id):
        def read(c): return [dict(json.loads(r['metadata']),status=r['status']) for r in c.execute('SELECT * FROM video_assets WHERE task_id=?',(task_id,))]
        if self._cleanup is not None: return read(self._cleanup[0])
        with self.store._tx() as c: return read(c)
    def asset_terminal(self,task_id,token,asset_id):
        with self.store._tx() as c:
            self._lease(c,task_id,token)
            if c.execute("UPDATE video_assets SET status='remote_terminal' WHERE task_id=? AND asset_id=? AND status='registered'",(task_id,asset_id)).rowcount!=1: raise WorkflowError('invalid_asset')
    def asset_rolled_back(self,task_id,token,asset_id):
        with self.store._tx() as c:
            self._lease(c,task_id,token)
            row=c.execute('SELECT status FROM video_assets WHERE task_id=? AND asset_id=?',(task_id,asset_id)).fetchone()
            if not row or row[0] not in ('registered','deleted'): raise WorkflowError('invalid_asset')
            if row[0]=='registered': c.execute("UPDATE video_assets SET status='deleted' WHERE task_id=? AND asset_id=?",(task_id,asset_id))
    @contextmanager
    def cleanup_claim(self,task_id):
        with self.store._tx() as c:
            self.store._recover(c,time.time()); self.store._row(c,'tasks',task_id)
            if c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(): raise WorkflowError('invalid_state')
            c.execute('INSERT INTO video_maintenance VALUES(1)'); self._cleanup=(c,task_id)
            try: yield self
            finally: self._cleanup=None; c.execute('DELETE FROM video_maintenance')
    def mark_cleaned(self,asset_id,status):
        if self._cleanup is None: raise WorkflowError('invalid_state')
        if status not in ('deleted','provider_managed'): raise WorkflowError('invalid_asset')
        c,t=self._cleanup
        if c.execute("UPDATE video_assets SET status=? WHERE asset_id=? AND task_id=? AND status='remote_terminal'",(status,asset_id,t)).rowcount!=1: raise WorkflowError('invalid_asset')
