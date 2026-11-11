import hashlib, json, math, os, sqlite3, struct, uuid
from decimal import Decimal
from pathlib import Path
from .execution_guard import execution_guard
from .workflow_store import WorkflowError
from .video_services import ProviderClient
from tools.api_smoke import reserve

ROOT = Path(__file__).resolve().parent.parent

def _json(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

class RagProvider:
    def __init__(self, store, config, transport=None, secrets=None):
        self.store, self.cfg, self.transport, self.secrets = store, config, transport, secrets
        with store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS rag_requests (id TEXT PRIMARY KEY, input_sha TEXT NOT NULL, status TEXT NOT NULL, result TEXT)')

    def embed(self, texts, *, allow_paid=False, request_id=None, run_id=None, background=False):
        cfg = self.cfg
        if not isinstance(texts,list) or not texts or len(texts)>cfg['limits']['embedding_batch_size'] or any(not isinstance(t,str) or not t for t in texts):
            raise WorkflowError('invalid_embedding_input')
        if cfg['embedding']['model'] != 'text-embedding-v4' or cfg['embedding']['dimensions'] != 1024:
            raise WorkflowError('invalid_config')
        return self._execute('embedding', {'model':cfg['embedding']['model'],'input':texts,'dimensions':1024}, allow_paid, request_id, run_id, background=background)

    def answer(self, messages, *, allow_paid=False, request_id=None, run_id=None):
        if not isinstance(messages,list) or not messages or any(not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in ('system','user','assistant') or not isinstance(m['content'],str) for m in messages):
            raise WorkflowError('invalid_messages')
        cfg=self.cfg['answer']
        if cfg['model'] != 'deepseek-flash': raise WorkflowError('invalid_config')
        return self._execute('answer', {'model':cfg['model'],'messages':messages,'max_tokens':cfg['max_tokens'],'thinking':{'type':'disabled'},'response_format':{'type':'json_object'}}, allow_paid, request_id, run_id)

    def _execute(self, kind, payload, allow_paid, request_id, run_id, *, background=False):
        if self.cfg.get('enabled') is not True: raise WorkflowError('rag_disabled')
        if allow_paid is not True: raise WorkflowError('paid_consent_required')
        cfg=self.cfg; request_id=request_id or uuid.uuid4().hex; run_id=run_id or request_id
        if not isinstance(request_id,str) or not request_id or not isinstance(run_id,str) or not run_id: raise WorkflowError('invalid_request_id')
        try:
            raw=_json(payload).encode(); spec=cfg[kind]; budget=cfg['budget']
            if len(raw)>cfg['limits']['max_context_bytes']: raise ValueError()
            amount=Decimal(str(budget[kind+'_reserve']))
            prices=[Decimal(str(spec['price_per_million']))] if kind=='embedding' else [Decimal(str(spec['input_price'])),Decimal(str(spec['output_price']))]
            if any(isinstance(x,bool) for x in [budget[kind+'_reserve'], *([spec['price_per_million']] if kind=='embedding' else [spec['input_price'],spec['output_price']])]) or any(not p.is_finite() or p<=0 for p in [amount,*prices]): raise ValueError()
            worst=Decimal(len(raw))*prices[0]
            if kind=='answer':
                if type(spec['max_tokens']) is not int or spec['max_tokens']<=0: raise ValueError()
                worst+=Decimal(spec['max_tokens'])*prices[1]
            if worst/1000000>amount: raise ValueError()
            providers=json.loads((ROOT / cfg['models_file']).read_text(encoding='utf-8'))['providers']
            provider=providers[spec['provider']]
            receipt_config = cfg
            if background:
                receipt_config = {'embedding': cfg['embedding'], 'ledger': budget['ledger']}
            fingerprint=hashlib.sha256(_json({'kind':kind,'payload':payload,'config':receipt_config,'provider':provider,'db':str(Path(self.store.db_path).resolve()),'content_root':str(getattr(self.store,'content_root',None))}).encode()).hexdigest()
        except Exception: raise WorkflowError('invalid_config_or_input') from None
        # Validate credentials before any automatic batch can reserve funds.
        if background:
            keys = self._keys()
            if not keys.get(provider['api_key_env']):
                raise WorkflowError('missing_model_credentials')
        ledger=ROOT / budget['ledger']
        with execution_guard(self.store, background_rag=background):
            with self.store._tx() as c:
                row=c.execute('SELECT input_sha,status,result FROM rag_requests WHERE id=?',(request_id,)).fetchone()
                if row:
                    if row[0]!=fingerprint: raise WorkflowError('request_conflict')
                    if row[1]=='completed': return json.loads(row[2])
                    if not background or row[1]!='prepared':
                        raise WorkflowError('request_needs_attention')
                else:
                    c.execute('INSERT INTO rag_requests VALUES (?,?,?,NULL)',(request_id,fingerprint,'prepared'))
            try:
                ledger.parent.mkdir(parents=True,exist_ok=True)
                reserve(ledger,run_id,request_id,amount,budget['run_limit'],budget['research_limit'],reuse_prepared=bool(background and row))
            except Exception:
                if not background:
                    with self.store._tx() as c: c.execute("UPDATE rag_requests SET status='needs_attention' WHERE id=?",(request_id,))
                raise WorkflowError('budget_invalid_or_exceeded') from None
            with self.store._tx() as c: c.execute("UPDATE rag_requests SET status='in_flight' WHERE id=?",(request_id,))
            try:
                if not background:
                    keys=self._keys()
                key=keys[provider['api_key_env']]
                client=ProviderClient({'providers':providers,'models':{}},{'transport':cfg['transport']},keys,transport=self.transport)
                url=provider['compatible_base_url'].rstrip('/') + ('/embeddings' if kind=='embedding' else '/chat/completions')
                data=client._request(url,key,payload)
                u=data.get('usage'); usage={k:v for k,v in u.items() if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0} if isinstance(u,dict) else {}
                cost=None
                if kind=='embedding' and 'prompt_tokens' in usage: cost=Decimal(usage['prompt_tokens'])*prices[0]/1000000
                if kind=='answer' and {'prompt_tokens','completion_tokens'} <= usage.keys(): cost=(Decimal(usage['prompt_tokens'])*prices[0]+Decimal(usage['completion_tokens'])*prices[1])/1000000
                if cost is not None:
                    with sqlite3.connect(ledger,timeout=30) as db:
                        db.execute('UPDATE reservations SET amount=? WHERE request_id=? AND run_id=?',(str(cost),request_id,run_id))
                with self.store._tx() as c:
                    c.execute('UPDATE rag_requests SET result=? WHERE id=?',(_json({'usage':usage,'estimated_cost_cny':str(cost) if cost is not None else None}),request_id))
                if cost is not None and cost>amount:
                    raise ValueError()
                result=self._validate(kind,data,payload)
                result['estimated_cost_cny']=str(cost) if cost is not None else None
                with self.store._tx() as c: c.execute("UPDATE rag_requests SET status='completed',result=? WHERE id=?",(_json(result),request_id))
                if cost is not None:
                    with sqlite3.connect(ledger,timeout=30) as db: db.execute('UPDATE reservations SET amount=? WHERE request_id=? AND run_id=?',(str(cost),request_id,run_id))
                return result
            except Exception:
                with self.store._tx() as c: c.execute("UPDATE rag_requests SET status='needs_attention' WHERE id=? AND status!='completed'",(request_id,))
                raise WorkflowError('provider_request_failed') from None

    def _keys(self):
        if self.secrets is not None:
            return self.secrets
        from tools.demo_setup import dotenv
        path = ROOT / self.cfg['env_file']
        keys = dotenv(path) if path.exists() else {}
        keys.update(os.environ)
        return keys

    def _validate(self, kind, data, payload):
        model=data.get('model')
        if not isinstance(model,str) or not model or len(model)>128: raise ValueError()
        if kind=='embedding' and model != payload['model']: raise ValueError()
        u=data.get('usage'); usage={k:v for k,v in u.items() if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0} if isinstance(u,dict) else {}
        if kind=='answer':
            choice=data['choices'][0]; content=choice['message']['content']
            if not isinstance(content,str) or not content.strip() or len(content)>self.cfg['limits']['max_answer_chars'] or choice.get('finish_reason')=='length': raise ValueError()
            return {'content':content,'model':model,'usage':usage}
        rows=data['data']
        if not isinstance(rows,list) or len(rows)!=len(payload['input']): raise ValueError()
        vectors=[]
        for i,row in enumerate(rows):
            if type(row.get('index')) is not int or row['index']!=i: raise ValueError()
            v=row['embedding']
            if not isinstance(v,list) or len(v)!=1024: raise ValueError()
            converted=[]
            for x in v:
                if type(x) not in (int,float) or not math.isfinite(x): raise ValueError()
                converted.append(struct.unpack('f',struct.pack('f',x))[0])
            if not all(math.isfinite(x) for x in converted) or not any(converted): raise ValueError()
            vectors.append(converted)
        return {'vectors':vectors,'model':model,'usage':usage}
