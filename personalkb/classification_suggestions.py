import hashlib, json, sqlite3, uuid
from decimal import Decimal
from pathlib import Path
from .classification import ClassificationStore, snapshot_from_connection
from .execution_guard import execution_guard
from .workflow_store import WorkflowError
from tools.api_smoke import reserve


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def catalog(c):
    return [tuple(r) for r in c.execute('SELECT kind,normalized,label_id,name,is_alias FROM classification_names ORDER BY kind,normalized')]


class SuggestionService:
    def __init__(self, store, config, provider_factory=None, classification_config=None):
        self.store, self.config, self.provider_factory = store, config, provider_factory
        self.classifications = ClassificationStore(store, classification_config)
        with store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS classification_suggestions (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, version_id TEXT NOT NULL, content_sha256 TEXT NOT NULL, revision INTEGER NOT NULL, catalog_hash TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT, receipt TEXT, error_code TEXT)')
            if 'selection_hash' not in {r[1] for r in c.execute('PRAGMA table_info(classification_suggestions)')}:
                c.execute('ALTER TABLE classification_suggestions ADD COLUMN selection_hash TEXT')

    def _row(self,c,id):
        r=c.execute('SELECT * FROM classification_suggestions WHERE id=?',(id,)).fetchone()
        if not r: raise WorkflowError('suggestion_not_found')
        d=dict(r)
        for k in ('result','receipt'):
            if d[k] is not None: d[k]=json.loads(d[k])
        return d

    def latest(self, source_id):
        try:
            with execution_guard(self.store):
                with self.store._tx() as c:
                    c.execute("UPDATE classification_suggestions SET status='needs_attention',error_code='unknown_submission' WHERE status='running'")
        except WorkflowError as exc:
            if exc.code!='worker_busy': raise
        with self.store._tx() as c:
            self.store._row(c,'sources',source_id)
            r=c.execute('SELECT id FROM classification_suggestions WHERE source_id=? ORDER BY rowid DESC LIMIT 1',(source_id,)).fetchone()
            return self._row(c,r[0]) if r else None

    def generate(self, source_id, expected_version_id, expected_revision, allow_paid=False):
        cfg=self.config
        if allow_paid is not True: raise WorkflowError('paid_consent_required')
        if not cfg.get('enabled') or self.provider_factory is None: raise WorkflowError('suggestions_disabled')
        try:
            limits=[Decimal(str(cfg['budget'][k])) for k in ('run_limit','research_limit')]
            if any(not n.is_finite() or n <= 0 for n in limits) or limits[0]>limits[1] or limits[1]>100: raise ValueError()
            for key in ('max_context_bytes','max_catalog_entries','max_output_bytes','max_items_per_kind','max_name_length','text_max_tokens'):
                if type(cfg[key]) is not int or cfg[key]<=0: raise ValueError()
            amount=Decimal(str(cfg['reserve_cny']))
            prices=cfg['prices']['text']
            if not amount.is_finite() or amount<=0 or not isinstance(prices,list) or len(prices)!=2: raise ValueError()
            if any(isinstance(x,bool) or not Decimal(str(x)).is_finite() or Decimal(str(x))<=0 for x in prices): raise ValueError()
            if not isinstance(cfg['system_prompt'],str) or not cfg['system_prompt'].strip(): raise ValueError()
        except (KeyError, ValueError, TypeError, ArithmeticError): raise WorkflowError('invalid_config') from None
        with execution_guard(self.store):
            with self.store._tx() as c:
                c.execute("UPDATE classification_suggestions SET status='needs_attention',error_code='unknown_submission' WHERE status='running'")
                s=self.store._row(c,'sources',source_id)
                if s['deleted'] or s['current_version_id'] != expected_version_id: raise WorkflowError('version_conflict')
                v=self.store._row(c,'versions',expected_version_id)
                meta=snapshot_from_connection(c,source_id)
                if type(expected_revision) is not int or meta['revision']!=expected_revision: raise WorkflowError('classification_conflict')
                cats=catalog(c)
                if len(cats)>cfg['max_catalog_entries']: raise WorkflowError('catalog_too_large')
                content={k:v['result'].get(k,'') for k in ('summary','notes','body')}
                if any(not isinstance(x,str) for x in content.values()): raise WorkflowError('invalid_content')
                prompt=json.dumps({'content':content,'catalog':cats},ensure_ascii=False)
                if len(prompt.encode())>cfg['max_context_bytes']: raise WorkflowError('context_too_large')
                amount=Decimal(str(cfg['reserve_cny']))
                worst=(Decimal(len((cfg['system_prompt']+prompt).encode()))*Decimal(str(cfg['prices']['text'][0]))+Decimal(cfg['text_max_tokens'])*Decimal(str(cfg['prices']['text'][1])))/1000000
                if worst>amount: raise WorkflowError('text_reservation_too_small')
                sid=uuid.uuid4().hex
                c.execute('INSERT INTO classification_suggestions(id,source_id,version_id,content_sha256,revision,catalog_hash,fingerprint,status) VALUES(?,?,?,?,?,?,?,?)',(sid,source_id,expected_version_id,v['content_sha256'],expected_revision,digest(cats),digest(cfg),'running'))
            try:
                ledger=Path(cfg['budget']['ledger']); ledger.parent.mkdir(parents=True,exist_ok=True)
                reserve(ledger,sid,sid,amount,cfg['budget']['run_limit'],cfg['budget']['research_limit'])
            except Exception:
                with self.store._tx() as c: c.execute("UPDATE classification_suggestions SET status='failed',error_code='budget_invalid_or_exceeded' WHERE id=?",(sid,))
                raise WorkflowError('budget_invalid_or_exceeded') from None
            try:
                provider=self.provider_factory()
                response=provider([{'role':'system','content':cfg['system_prompt']},{'role':'user','content':prompt}])
                raw=response['content']
                if not isinstance(raw,str) or len(raw.encode())>cfg['max_output_bytes']: raise ValueError()
                obj=json.loads(raw)
                keys=('existing_topics','existing_tags','new_topics','new_tags')
                if not isinstance(obj,dict) or set(obj)!=set(keys): raise ValueError()
                known={'existing_topics':{x[2] for x in cats if x[0]=='topic'},'existing_tags':{x[2] for x in cats if x[0]=='tag'}}
                for key in keys:
                    values=obj[key]
                    if not isinstance(values,list) or len(values)>cfg['max_items_per_kind'] or any(not isinstance(x,str) or not x.strip() or len(x)>cfg['max_name_length'] for x in values) or len(set(values))!=len(values): raise ValueError()
                    if key in known and not set(values)<=known[key]: raise ValueError()
                    if key.startswith('new_'):
                        kind='topic' if key=='new_topics' else 'tag'
                        norms=[self.classifications._names(x,[])[0][1] for x in values]
                        if len(set(norms))!=len(norms) or any((kind,n) in {(x[0],x[1]) for x in cats} for n in norms): raise ValueError()
                usage=response.get('usage',{})
                usage={k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0} if isinstance(usage,dict) else {}
                cost=response.get('estimated_cost_cny')
                if not {'prompt_tokens','completion_tokens'} <= usage.keys(): cost=None
                elif cost is not None:
                    cost=(Decimal(usage['prompt_tokens'])*Decimal(str(cfg['prices']['text'][0]))+Decimal(usage['completion_tokens'])*Decimal(str(cfg['prices']['text'][1])))/Decimal(1000000)
                if cost is not None:
                    cost=Decimal(str(cost))
                    if not cost.is_finite() or cost<0: raise ValueError()
                    if cost>amount:
                        with sqlite3.connect(ledger, timeout=30) as db:
                            db.execute('UPDATE reservations SET amount=? WHERE request_id=? AND run_id=?',(str(cost),sid,sid))
                        raise ValueError()
                result={'suggestions':obj,'model':str(response.get('model',''))[:128],'provider':cfg.get('model_provenance',{}),'usage':usage,'estimated_cost_cny':str(cost) if cost is not None else None}
                with self.store._tx() as c: c.execute("UPDATE classification_suggestions SET status='ready',result=? WHERE id=?",(json.dumps(result,ensure_ascii=False),sid))
                # Only a known, validated usage charge can reduce the reservation.
                # A crash between databases leaves the conservative reservation intact.
                if cost is not None:
                    with sqlite3.connect(ledger, timeout=30) as db:
                        db.execute('UPDATE reservations SET amount=? WHERE request_id=? AND run_id=?',(str(cost),sid,sid))
            except Exception:
                with self.store._tx() as c: c.execute("UPDATE classification_suggestions SET status='needs_attention',error_code='suggestion_generation_failed' WHERE id=?",(sid,))
                raise WorkflowError('suggestion_generation_failed') from None
            with self.store._tx() as c: return self._row(c,sid)

    def apply(self,id,existing_topics,existing_tags,confirmed_new_topics,confirmed_new_tags):
        with self.store._tx() as c:
            row=self._row(c,id)
            selections=[existing_topics,existing_tags,confirmed_new_topics,confirmed_new_tags]
            if row['status']=='applied':
                if row['selection_hash'] != digest(selections): raise WorkflowError('suggestion_conflict')
                return row
            if row['status']!='ready': raise WorkflowError('invalid_suggestion_state')
            s=self.store._row(c,'sources',row['source_id'])
            if s['deleted'] or s['current_version_id']!=row['version_id']: raise WorkflowError('version_conflict')
            v=self.store._row(c,'versions',row['version_id'])
            old=snapshot_from_connection(c,row['source_id'])
            if v['content_sha256']!=row['content_sha256'] or old['revision']!=row['revision'] or digest(catalog(c))!=row['catalog_hash']: raise WorkflowError('classification_conflict')
            choices=[existing_topics,existing_tags,confirmed_new_topics,confirmed_new_tags]
            keys=['existing_topics','existing_tags','new_topics','new_tags']
            for choice,key in zip(choices,keys):
                if not isinstance(choice,list) or any(not isinstance(x,str) for x in choice) or len(set(choice))!=len(choice) or not set(choice)<=set(row['result']['suggestions'][key]): raise WorkflowError('invalid_suggestion_selection')
            newids=[[],[]]
            for idx,(kind,names) in enumerate((('topic',confirmed_new_topics),('tag',confirmed_new_tags))):
                for name in names:
                    name,norm=self.classifications._names(name,[])[0]; lid=uuid.uuid4().hex
                    c.execute('INSERT INTO classification_labels VALUES(?,?,?,1)',(lid,kind,name))
                    c.execute('INSERT INTO classification_names VALUES(?,?,?,?,0)',(kind,norm,lid,name)); newids[idx].append(lid)
            topics=list(dict.fromkeys([x['id'] for x in old['topics']]+existing_topics+newids[0]))
            tags=list(dict.fromkeys([x['id'] for x in old['tags']]+existing_tags+newids[1]))
            receipt=self.classifications.update_in_transaction(c,row['source_id'],row['revision'],topics,tags)
            c.execute("UPDATE classification_suggestions SET status='applied',receipt=?,selection_hash=? WHERE id=?",(json.dumps(receipt,ensure_ascii=False),digest(selections),id))
            result=self._row(c,id)
        self.classifications._sync([row['source_id']]); return result

    def reject(self,id):
        with self.store._tx() as c:
            row=self._row(c,id)
            if row['status']=='rejected': return row
            if row['status']!='ready': raise WorkflowError('invalid_suggestion_state')
            c.execute("UPDATE classification_suggestions SET status='rejected' WHERE id=?",(id,))
            return self._row(c,id)
