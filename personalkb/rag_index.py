import hashlib, json, math, re, sqlite3, struct, uuid
from contextlib import closing, nullcontext
from pathlib import Path, PurePosixPath, PureWindowsPath
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from .workflow_store import WorkflowError
from .content_storage import encoded, safe, verify, write
from .classification import ClassificationStore, snapshot_from_connection
from .execution_guard import execution_guard
from .rag_lock import index_guard, guarded
from .runtime_guard import runtime_guard

GENERATION_DB = re.compile(r'[0-9a-f]{32}\.sqlite')
GENERATION_FILE = re.compile(r'([0-9a-f]{32}\.sqlite)(?:-wal|-shm|-journal)?|\.?[0-9a-f]{32}\.tmp')
STAGING_FILE = re.compile(r'\.building-[0-9a-f]{32}\.sqlite(?:-wal|-shm|-journal)?')


def active_manifest(root):
    try:
        manifest = json.loads(safe(root, 'active.json').read_text(encoding='utf8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise WorkflowError('rag_index_invalid') from None
    if not isinstance(manifest, dict):
        raise WorkflowError('rag_index_invalid')
    name, space, models = (manifest.get(key) for key in ('file', 'space_id', 'returned_models'))
    if (not isinstance(name, str) or not GENERATION_DB.fullmatch(name)
            or not isinstance(space, str) or not re.fullmatch(r'[0-9a-f]{64}', space)
            or not isinstance(models, list) or any(not isinstance(model, str) or not model for model in models)):
        raise WorkflowError('rag_index_invalid')
    return manifest

def load_rag_config(path=None):
    try:
        c=json.loads(Path(path or Path(__file__).resolve().parent.parent/'config/rag.json').read_text(encoding='utf-8-sig'))
        assert type(c['enabled']) is bool
        def positive(obj,keys):
            for key in keys: assert type(obj[key]) is int and obj[key]>0
        def money(obj,keys):
            for key in keys:
                assert not isinstance(obj[key],bool)
                n=Decimal(str(obj[key])); assert n.is_finite() and n>=0
        def valid_path(value, allow_absolute=False):
            assert isinstance(value,str) and value and '\x00' not in value
            posix, windows = PurePosixPath(value), PureWindowsPath(value)
            assert '..' not in posix.parts and '..' not in windows.parts
            assert not value.startswith(('//', '\\\\'))
            assert not windows.drive or (allow_absolute and windows.is_absolute() and len(windows.drive)==2 and windows.drive[1]==':')
            assert allow_absolute or (not posix.is_absolute() and not windows.root)
            assert not (windows.root and not windows.is_absolute() and not posix.is_absolute())
        for key in ('index_dir','models_file'):
            valid_path(c[key])
        valid_path(c['env_file'], allow_absolute=True)
        e=c['embedding']; a=c['answer']; ch=c['chunking']; ret=c['retrieval']; lim=c['limits']; tr=c['transport']
        for obj,keys in ((e,('provider','model','revision')),(a,('provider','model','revision')),(ch,('version','tokenizer_version'))):
            for key in keys: assert isinstance(obj[key],str) and obj[key].strip()
        positive(e,('dimensions',)); positive(a,('max_tokens',)); positive(ch,('max_chars',)); positive(ret,('top_k','context_k')); positive(lim,('max_question_chars','max_context_bytes','max_answer_chars','embedding_batch_size','max_chunks','max_sources','stream_event_chars'))
        positive(tr,('request_timeout_seconds','response_max_bytes'))
        assert type(ch['overlap']) is int and 0<=ch['overlap']<ch['max_chars']
        assert type(ret['rrf_constant']) is int and ret['rrf_constant']>=0 and ret['context_k']<=ret['top_k'] and ret['mode'] in ('hybrid','lexical')
        money(e,('price_per_million',)); money(a,('input_price','output_price')); money(c['budget'],('run_limit','research_limit','embedding_reserve','answer_reserve'))
        valid_path(c['budget']['ledger'], allow_absolute=True)
        assert isinstance(tr['allowed_api_hosts'],list) and tr['allowed_api_hosts'] and all(isinstance(x,str) and re.fullmatch(r'[A-Za-z0-9.-]+',x) for x in tr['allowed_api_hosts'])
        assert isinstance(tr['allowed_oss_suffix'],str) and tr['allowed_oss_suffix']
        for key in ('price_date','answer_system_prompt','refusal_text'): assert isinstance(c[key],str) and c[key].strip()
        return c
    except (OSError, ValueError, KeyError, TypeError, AssertionError, InvalidOperation): raise WorkflowError('invalid_config') from None

def _hash(x): return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def _tokens(s):
    terms=[]
    for m in re.finditer(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+',s.lower()):
        t=m.group(); terms.extend(([t] if len(t)==1 else [t[i:i+2] for i in range(len(t)-1)]) if '\u4e00' <= t[0] <= '\u9fff' else [t])
    return terms

def _pack(v, n):
    if not isinstance(v,(list,tuple)) or len(v)!=n or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in v): raise WorkflowError('invalid_embedding')
    try: b=struct.pack(f'{n}f',*v); values=struct.unpack(f'{n}f',b)
    except (OverflowError,struct.error): raise WorkflowError('invalid_embedding') from None
    if not all(math.isfinite(x) for x in values) or not any(values): raise WorkflowError('invalid_embedding')
    return b

class RagIndex:
    def __init__(self,store,config,provider=None):
        if not store.content_root or not store.data_root: raise WorkflowError('content_storage_required')
        self.store,self.config,self.provider=store,config,provider
        self.root=safe(store.data_root,config['index_dir'])
        models_path=Path(config['models_file']); models_path=models_path if models_path.is_absolute() else Path(__file__).resolve().parent.parent/models_path
        try: models=json.loads(models_path.read_text(encoding='utf-8-sig')); endpoint=models['providers'][config['embedding']['provider']]
        except (OSError,ValueError,KeyError,TypeError): raise WorkflowError('invalid_config') from None
        self.space_id=_hash({'db':str(Path(store.db_path).resolve()),'root':str(store.content_root.resolve()),'embedding':config['embedding'],'endpoint':endpoint,'chunking':config['chunking']})
        ClassificationStore(store)
    def _provider(self):
        if self.provider is None:
            from .rag_provider import RagProvider
            self.provider=RagProvider(self.store,self.config)
        return self.provider
    def _db(self,path, *, create=False):
        import sqlite_vec
        c=sqlite3.connect(path) if create else self._open_existing(path)
        c.row_factory=sqlite3.Row
        try:
            c.enable_load_extension(True)
            sqlite_vec.load(c)
            c.enable_load_extension(False)
        except Exception:
            c.close()
            raise
        return c
    @staticmethod
    def _open_existing(path):
        try: return sqlite3.connect(path.resolve().as_uri()+'?mode=rw', uri=True)
        except sqlite3.OperationalError: raise WorkflowError('rag_invalidated') from None
    def _active(self, *, check_space=True):
        m=active_manifest(self.root)
        if m is None: return None
        if check_space and m['space_id']!=self.space_id: raise WorkflowError('rag_rebuild_required')
        path=safe(self.store.data_root,self.config['index_dir'],m['file'])
        if check_space and path.exists():
            with closing(self._open_existing(path)) as c:
                if 'vector' not in {r[1] for r in c.execute('PRAGMA table_info(chunks)')}: raise WorkflowError('rag_rebuild_required')
        return path
    def _snapshot(self,c,sid):
        s=c.execute('SELECT s.current_version_id,v.content_sha256,r.seq,r.decision,r.score,v.result FROM sources s JOIN versions v ON v.id=s.current_version_id JOIN reviews r ON r.seq=(SELECT MAX(seq) FROM reviews WHERE version_id=s.current_version_id) WHERE s.id=? AND s.deleted=0',(sid,)).fetchone()
        if not s or s['decision']!='approve' or s['score']<self.store.quality_target: raise WorkflowError('rag_invalidated')
        verify(self.store,sid,connection=c)
        return dict(version_id=s['current_version_id'],content_sha256=s['content_sha256'],review_seq=s['seq'],result=json.loads(s['result']),metadata=snapshot_from_connection(c,sid))
    def _chunks(self,sid,s):
        out=[]; size=self.config['chunking']['max_chars']; overlap=self.config['chunking']['overlap']
        for i,e in enumerate(s['result'].get('evidence',[])):
            text=e.get('text'); typ=e.get('type','')
            if not isinstance(text,str) or not text: continue
            loc={'evidence_index':i,'version_id':s['version_id']}
            human=typ in ('human_body','human_transcript','human_visual')
            if human:
                loc['temporal_status']='unavailable'; loc['has_time']=False
                loc['origin']='human_edit'
            else:
                for key in ('start','end','start_seconds','end_seconds','seconds','image_sha256'):
                    if key in e: loc[key]=e[key]
            if typ == 'visual' and (not isinstance(e.get('seconds'),(int,float)) or isinstance(e.get('seconds'),bool) or not math.isfinite(e['seconds']) or e['seconds']<0 or not isinstance(e.get('image_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',e['image_sha256'])): continue
            if typ in ('audio','transcript') and not (('start' in e and 'end' in e) or ('start_seconds' in e and 'end_seconds' in e)): continue
            if typ in ('audio','transcript'):
                a=e.get('start_seconds',e.get('start')); b=e.get('end_seconds',e.get('end'))
                if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (a,b)) or a<0 or b<a: continue
            loc['type']=typ or 'html'
            # Preserve evidence offsets while never merging across Markdown headings.
            boundaries=[0]+[m.start() for m in re.finditer(r'(?m)^#{1,6}\s+',text) if m.start()>0]+[len(text)]
            for left,right in zip(boundaries,boundaries[1:]):
                start=left
                while start<right:
                    end=min(start+size,right); locator=dict(loc,offset=start,end_offset=end)
                    if typ in ('html',''): locator['end']=end
                    identity=[sid,s['version_id'],s['content_sha256'],i,start,end,self.space_id]
                    out.append(dict(chunk_id=_hash(identity),source_id=sid,version_id=s['version_id'],content_sha256=s['content_sha256'],review_seq=s['review_seq'],space_id=self.space_id,text=text[start:end],locator=locator,metadata=s['metadata']))
                    if end==right: break
                    start=end-overlap
        return out
    def _enabled(self):
        if not self.config['enabled']: raise WorkflowError('rag_disabled')

    def build(self,*,allow_paid=False,request_id=None):
        with runtime_guard(self.store.data_root, 'rag-index-worker'):
            return self._build(allow_paid=allow_paid, request_id=request_id, incremental=False)

    def update(self,*,allow_paid=False,request_id=None,can_embed=None):
        return self._build(allow_paid=allow_paid, request_id=request_id, incremental=True, can_embed=can_embed)

    def _build(self,*,allow_paid=False,request_id=None,incremental=False,can_embed=None):
        self._enabled()
        with (nullcontext() if incremental else execution_guard(self.store)), (nullcontext() if incremental else index_guard(self)):
            sources=self.store.eligible_sources(); snapshots={}; chunks=[]
            if len(sources)>self.config['limits']['max_sources']: raise WorkflowError('rag_too_many_sources')
            run_id=request_id or uuid.uuid4().hex
            with self.store._tx() as c:
                for source in sources:
                    s=self._snapshot(c,source['id']); snapshots[source['id']]=s; chunks.extend(self._chunks(source['id'],s))
            if len(chunks)>self.config['limits']['max_chunks']: raise WorkflowError('rag_too_many_chunks')
            cache={}; returned_models=[]
            captured_manifest=None
            if incremental:
                with index_guard(self):
                    captured_manifest=active_manifest(self.root)
                    try: old_path=self._active()
                    except WorkflowError: old_path=None
                    if old_path and old_path.exists():
                        with closing(self._db(old_path)) as old_db:
                            for row in old_db.execute('SELECT payload,vector FROM chunks'):
                                item=json.loads(row['payload']); cache[item['text']]=row['vector']
            if incremental:
                self._incremental_embeddings(chunks, cache, run_id, allow_paid, can_embed)
            else:
                texts=[x['text'] for x in chunks]
                if texts and allow_paid is not True: raise WorkflowError('paid_consent_required')
                batch=self.config['limits']['embedding_batch_size']; vectors=[]
                for start in range(0,len(texts),batch):
                    part=texts[start:start+batch]
                    response=self._provider().embed(part,allow_paid=allow_paid,request_id=f'{run_id}:embedding:{start}',run_id=run_id)
                    if response.get('model') != self.config['embedding']['model']: raise WorkflowError('embedding_model_mismatch')
                    if len(response['vectors'])!=len(part): raise WorkflowError('invalid_embedding')
                    vectors.extend(_pack(v,self.config['embedding']['dimensions']) for v in response['vectors'])
            if incremental: vectors=[cache[x['text']] for x in chunks]
            if chunks: returned_models=[self.config['embedding']['model']]
            self.root.mkdir(parents=True,exist_ok=True)
            name=uuid.uuid4().hex+'.sqlite'
            path=safe(self.store.data_root,self.config['index_dir'],name)
            # Generation cleanup only matches final names, so another publisher
            # cannot remove this file while the new index is being assembled.
            staging=safe(self.store.data_root,self.config['index_dir'],'.building-'+name)
            published=False
            try:
                with closing(self._db(staging,create=True)) as c:
                    n=self.config['embedding']['dimensions']; c.execute('CREATE TABLE chunks(id INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE, source_id TEXT, payload TEXT, vector BLOB)'); c.execute('CREATE VIRTUAL TABLE fts USING fts5(text)'); c.execute(f'CREATE VIRTUAL TABLE vec USING vec0(id INTEGER PRIMARY KEY, embedding float[{n}] distance_metric=cosine)')
                    for i,(chunk,v) in enumerate(zip(chunks,vectors),1):
                        c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(i,chunk['chunk_id'],chunk['source_id'],json.dumps(chunk,ensure_ascii=False),v)); c.execute('INSERT INTO fts(rowid,text) VALUES (?,?)',(i,' '.join(_tokens(chunk['text'])))); c.execute('INSERT INTO vec VALUES (?,?)',(i,v))
                    c.commit()
                with execution_guard(self.store), index_guard(self):
                    if incremental and active_manifest(self.root)!=captured_manifest: raise WorkflowError('rag_invalidated')
                    with self.store._tx() as c:
                        current=set()
                        for row in c.execute("SELECT s.id FROM sources s JOIN reviews r ON r.seq=(SELECT MAX(seq) FROM reviews WHERE version_id=s.current_version_id) WHERE s.deleted=0 AND r.decision='approve' AND r.score>=?",(self.store.quality_target,)):
                            try: verify(self.store,row['id'],connection=c); current.add(row['id'])
                            except (WorkflowError,OSError): pass
                        if current != set(snapshots): raise WorkflowError('rag_invalidated')
                        for sid,old in snapshots.items():
                            if self._snapshot(c,sid)!=old: raise WorkflowError('rag_invalidated')
                        staging.replace(path)
                        write(self.root, 'active.json', encoded({'space_id':self.space_id,'file':name,'returned_models':sorted(set(returned_models))}))
                        published=True
                    try:
                        for stale in self.root.iterdir():
                            match=GENERATION_FILE.fullmatch(stale.name)
                            if match and match[1]!=name:
                                try: stale.unlink()
                                except OSError: pass
                    except OSError: pass  # A later rebuild can retry inaccessible files.
            finally:
                if not published:
                    staging.unlink(missing_ok=True)
                    path.unlink(missing_ok=True)
            return {'space_id':self.space_id,'chunks':len(chunks),'sources':len(snapshots)}
    def _incremental_embeddings(self, chunks, cache, run_id, allow_paid, can_embed):
        texts={_hash(x['text']):x['text'] for x in chunks}
        batch_size=self.config['limits']['embedding_batch_size']
        def store_vectors(response, hashes):
            if response.get('model')!=self.config['embedding']['model']:
                raise WorkflowError('embedding_model_mismatch')
            if len(response['vectors'])!=len(hashes):
                raise WorkflowError('invalid_embedding')
            for h, vector in zip(hashes, response['vectors']):
                if h in texts:
                    cache[texts[h]] = _pack(vector, self.config['embedding']['dimensions'])

        with self.store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS rag_requests (id TEXT PRIMARY KEY, input_sha TEXT NOT NULL, status TEXT NOT NULL, result TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS rag_index_batches (run_id TEXT, space_id TEXT, batch_id TEXT PRIMARY KEY, text_hashes TEXT NOT NULL)')
            batches = c.execute("""SELECT b.batch_id,b.text_hashes,r.status,r.result FROM rag_index_batches b
                LEFT JOIN rag_requests r ON r.id=b.batch_id WHERE b.space_id=?
                AND (b.run_id=? OR r.status IN ('in_flight','needs_attention'))
                ORDER BY CASE WHEN r.status='completed' THEN 0 ELSE 1 END""", (self.space_id,run_id)).fetchall()
        pending = []
        claimed = set()
        for row in batches:
            hashes = json.loads(row['text_hashes'])
            if not texts.keys() & set(hashes):
                continue
            if row['status']=='completed':
                store_vectors(json.loads(row['result']), hashes)
            elif row['status'] in ('in_flight','needs_attention'):
                if any(texts[h] not in cache for h in hashes if h in texts):
                    raise WorkflowError('request_needs_attention')
            elif all(h in texts for h in hashes):
                pending.append((row['batch_id'], hashes))
                claimed.update(hashes)
        missing = [h for h, text in texts.items() if text not in cache and h not in claimed]
        for start in range(0, len(missing), batch_size):
            hashes = missing[start:start+batch_size]
            pending.append((f'{run_id}:embedding:{self.space_id}:{_hash(hashes)}', hashes))
        for batch_id, hashes in pending:
            if all(texts[h] in cache for h in hashes):
                continue
            if allow_paid is not True:
                raise WorkflowError('paid_consent_required')
            with self.store._tx() as c:
                c.execute('INSERT OR IGNORE INTO rag_index_batches VALUES (?,?,?,?)',
                          (run_id,self.space_id,batch_id,json.dumps(hashes)))
            if can_embed is not None and not can_embed():
                raise WorkflowError('rag_auto_index_paused')
            response = self._provider().embed([texts[h] for h in hashes], allow_paid=allow_paid,
                                              request_id=batch_id, run_id=run_id, background=True)
            store_vectors(response, hashes)

    @guarded
    def status(self, filters=None):
        path=self._active(check_space=False); mismatch=False; count=0; rows=[]
        if path and path.exists():
            mismatch=active_manifest(self.root)['space_id']!=self.space_id
            with closing(self._db(path)) as db:
                mismatch=mismatch or 'vector' not in {r[1] for r in db.execute('PRAGMA table_info(chunks)')}
                if not mismatch: rows=db.execute('SELECT payload FROM chunks').fetchall()
                count=db.execute('SELECT count(*) FROM chunks').fetchone()[0]
        eligible=[]; indexed=[]; unindexable=[]
        by_source={}
        for row in rows:
            item=json.loads(row['payload']); by_source.setdefault(item['source_id'],[]).append(item)
        with self.store._tx() as c:
            candidates=c.execute("""SELECT s.id FROM sources s JOIN reviews r ON r.seq=(
                SELECT MAX(seq) FROM reviews WHERE version_id=s.current_version_id)
                WHERE s.deleted=0 AND r.decision='approve' AND r.score>=? ORDER BY s.id""",
                (self.store.quality_target,)).fetchall()
            for (sid,) in candidates:
                try:
                    snapshot=self._snapshot(c,sid)
                    if not self._matches_scope(sid, snapshot['metadata'], filters):
                        continue
                    eligible.append(sid)
                    expected=self._chunks(sid,snapshot)
                    if not expected: unindexable.append(sid); continue
                    actual=by_source.get(sid,[])
                    canonical={x['chunk_id']:x for x in expected}
                    if len(actual)==len(expected) and all(x['chunk_id'] in canonical and self._same_content(x,canonical[x['chunk_id']]) for x in actual): indexed.append(sid)
                except (WorkflowError,OSError): pass
        return {'enabled':bool(self.config['enabled']),'space_id':self.space_id,'ready':bool(path and path.exists() and not mismatch),'needs_rebuild':mismatch,'eligible_sources':len(eligible),'indexed_sources':len(indexed),'indexed_chunks':count,'eligible_source_ids':eligible,'indexed_source_ids':indexed,'unindexable_source_ids':unindexable}

    @staticmethod
    def _same_content(a,b):
        return {k:v for k,v in a.items() if k!='metadata'} == {k:v for k,v in b.items() if k!='metadata'}

    @staticmethod
    def _matches_scope(source_id, metadata, filters):
        filters = filters or {}
        return (not filters.get('sources') or source_id in filters['sources']) and all(
            not filters.get(key) or set(filters[key]).intersection(item['id'] for item in metadata[key])
            for key in ('topics', 'tags')
        )

    def _valid(self,c,item,filters,cache=None,require_metadata=True,require_current_review=True):
        cache={} if cache is None else cache
        sid=item['source_id']
        if sid not in cache:
            try: cache[sid]=self._snapshot(c,sid)
            except (WorkflowError,OSError): cache[sid]=None
        now=cache[sid]
        if now is None: return False
        if any(now[k]!=item[k] for k in ('version_id','content_sha256')) or (require_metadata and now['metadata']!=item.get('metadata')): return False
        if require_current_review and now['review_seq']!=item['review_seq']: return False
        key=(sid,'chunks')
        if key not in cache: cache[key]={x['chunk_id']:x for x in self._chunks(sid,now)}
        canonical=cache[key].get(item['chunk_id'])
        if not require_current_review: item={**item, 'review_seq':now['review_seq']}
        if canonical is None or not self._same_content(canonical,item): return False
        return self._matches_scope(sid, now['metadata'], filters)
    def query(self,question,*,filters=None,allow_paid=False,request_id=None,mode=None,run_id=None):
        self._enabled()
        if not isinstance(question,str) or not question.strip() or len(question)>self.config['limits']['max_question_chars']: raise WorkflowError('invalid_question')
        if filters is not None and (not isinstance(filters,dict) or set(filters)-{'sources','topics','tags'} or any(not isinstance(v,list) or any(not isinstance(x,str) or not x for x in v) for v in filters.values())): raise WorkflowError('invalid_filters')
        mode=mode or self.config['retrieval']['mode']
        if mode not in ('lexical','hybrid'): raise WorkflowError('invalid_mode')
        k=self.config['retrieval']['top_k']; hits=[]; terms=_tokens(question)
        with index_guard(self):
            path=self._active()
            if not path: return []
            with closing(self._db(path)) as db:
                valid=self._refresh_chunks(db, filters)
                if not valid: return []
                if terms:
                    self._allow_rows(db, valid)
                    expr=' OR '.join('"'+x+'"' for x in terms)
                    hits.append([r[0] for r in db.execute('SELECT fts.rowid FROM fts JOIN allowed_ids ON allowed_ids.id=fts.rowid WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?', (expr,k))])
                if mode=='lexical': return self._rank(db, hits, filters)

        if allow_paid is not True: raise WorkflowError('paid_consent_required')
        # A rebuild cannot publish while this paid operation holds the execution guard.
        with execution_guard(self.store):
            with index_guard(self):
                if self._active()!=path: raise WorkflowError('rag_invalidated')
                manifest=active_manifest(self.root)
            result=self._provider().embed([question],allow_paid=allow_paid,request_id=request_id,run_id=run_id or request_id)
            if result.get('model') != self.config['embedding']['model'] or manifest.get('returned_models') != [result.get('model')]: raise WorkflowError('embedding_model_mismatch')
            if len(result['vectors'])!=1: raise WorkflowError('invalid_embedding')
            vector=_pack(result['vectors'][0],self.config['embedding']['dimensions'])
            with index_guard(self), closing(self._db(path)) as db:
                self._allow_rows(db, valid)
                hits.append([r[0] for r in db.execute('SELECT chunks.id FROM chunks JOIN allowed_ids ON allowed_ids.id=chunks.id ORDER BY vec_distance_cosine(chunks.vector, ?) LIMIT ?', (vector,k))])
                return self._rank(db, hits, filters)

    def _refresh_chunks(self, db, filters):
        rows=db.execute('SELECT id,payload FROM chunks').fetchall(); valid=[]; invalid=[]; refreshed=[]
        with self.store._tx() as c:
            cache={}
            for row in rows:
                item=json.loads(row['payload'])
                if not self._valid(c,item,None,cache,require_metadata=False):
                    # A still-approved copy of this exact version may reuse the
                    # vector, but the old review is never eligible for retrieval.
                    if not self._valid(c,item,None,cache,require_metadata=False,require_current_review=False):
                        invalid.append(row['id'])
                    continue
                item['metadata']=cache[item['source_id']]['metadata']
                refreshed.append((json.dumps(item,ensure_ascii=False),row['id']))
                if self._valid(c,item,filters,cache): valid.append(row['id'])
        db.executemany('UPDATE chunks SET payload=? WHERE id=?',refreshed)
        for i in invalid:
            db.execute('DELETE FROM fts WHERE rowid=?',(i,)); db.execute('DELETE FROM vec WHERE id=?',(i,)); db.execute('DELETE FROM chunks WHERE id=?',(i,))
        db.commit()
        return valid

    @staticmethod
    def _allow_rows(db, valid):
        db.execute('CREATE TEMP TABLE allowed_ids(id INTEGER PRIMARY KEY)')
        db.executemany('INSERT INTO allowed_ids VALUES (?)',((i,) for i in valid))

    def _rank(self, db, hits, filters):
        scores={}
        for group in hits:
            for rank,i in enumerate(group,1): scores[i]=scores.get(i,0)+1/(self.config['retrieval']['rrf_constant']+rank)
        order=sorted(scores,key=lambda i:(-scores[i],i))[:self.config['retrieval']['top_k']]
        items=[]
        for i in order:
            row=db.execute('SELECT payload FROM chunks WHERE id=?',(i,)).fetchone()
            if not row: raise WorkflowError('rag_invalidated')
            items.append(json.loads(row[0]))
        self.validate_citations(items, filters=filters)
        return items
    @guarded
    def validate_citations(self,citations,filters=None):
        self._enabled()
        path=self._active()
        if not path and citations: raise WorkflowError('rag_invalidated')
        db=self._db(path) if path else None
        try:
            with self.store._tx() as c:
                cache={}
                for item in citations:
                    row=db.execute('SELECT payload FROM chunks WHERE chunk_id=?',(item.get('chunk_id'),)).fetchone()
                    if not row or not self._same_content(json.loads(row[0]),item) or not self._valid(c,item,filters,cache): raise WorkflowError('rag_invalidated')
        finally:
            if db: db.close()
        return True
    @guarded
    def citation(self,chunk_id):
        self._enabled()
        path=self._active()
        if not path: raise WorkflowError('rag_invalidated')
        db=self._db(path)
        try: row=db.execute('SELECT payload FROM chunks WHERE chunk_id=?',(chunk_id,)).fetchone()
        finally: db.close()
        if not row: raise WorkflowError('rag_invalidated')
        item=json.loads(row[0])
        with self.store._tx() as c:
            cache={}
            if not self._valid(c,item,None,cache,require_metadata=False): raise WorkflowError('rag_invalidated')
            item['metadata']=cache[item['source_id']]['metadata']
        self.validate_citations([item]); return item
