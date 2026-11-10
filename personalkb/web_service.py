import hashlib, json, threading, time, uuid
from pathlib import Path
from .workflow import make_store, run_once, _root, _hash, render_markdown
from .workflow_store import WorkflowError

class WebService:
    def __init__(self, workflow_config, pipeline_config, web_config, *, video_runner=None, suggestion_provider_factory=None, rag_provider_factory=None):
        self.wc, self.pc, self.webcfg = workflow_config, pipeline_config, web_config
        self.store = make_store(workflow_config)
        self.video_runner = video_runner
        self.suggestion_provider_factory = suggestion_provider_factory
        self.rag_provider_factory = rag_provider_factory
        self.owner = uuid.uuid4().hex
        self._stop = threading.Event()
        self._thread = None
        with self.store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS web_dispatch (task_id TEXT PRIMARY KEY, mode TEXT NOT NULL, state TEXT NOT NULL, requested REAL NOT NULL, claimed REAL, owner TEXT)')
        from .web_dispatch import WebDispatcher
        self.dispatcher = WebDispatcher(self)
    @property
    def rag(self):
        if not hasattr(self, '_rag'):
            from .rag_index import RagIndex, load_rag_config
            from .rag_provider import RagProvider
            from .workflow import ROOT
            cfg = load_rag_config(ROOT / self.webcfg.get('rag_config', 'config/rag.json'))
            cfg['env_file'] = str(ROOT / self.webcfg.get('env_file', '.env'))
            self._rag_cfg = cfg
            self._rag_provider = self.rag_provider_factory(self.store, cfg) if self.rag_provider_factory else RagProvider(self.store, cfg)
            self._rag = RagIndex(self.store, cfg, self._rag_provider)
        return self._rag
    @property
    def rag_answers(self):
        if not hasattr(self, '_rag_answers'):
            from .rag_answer import AnswerService
            index = self.rag
            self._rag_answers = AnswerService(self.store, index, self._rag_cfg, self._rag_provider)
        return self._rag_answers
    @property
    def suggestions(self):
        if not hasattr(self, '_suggestions'):
            from .classification_suggestions import SuggestionService
            from .workflow import ROOT
            try:
                cfg=json.loads((ROOT/self.webcfg.get('suggestions_config','config/classification-suggestions.json')).read_text(encoding='utf-8-sig'))
                cfg['budget']['ledger']=str(ROOT/cfg['budget']['ledger'])
                if cfg.get('enabled') and self.suggestion_provider_factory is None:
                    models=json.loads((ROOT/cfg['models_file']).read_text(encoding='utf-8-sig'))
                    model=models['models']['text']; provider=models['providers'][model['provider']]
                    safe={'provider':model['provider'],'model':model['model'],'base_url':provider['compatible_base_url']}
                    cfg['model_provenance']={'provider':model['provider'],'requested_model':model['model'],'configuration_sha256':hashlib.sha256(json.dumps(safe,sort_keys=True).encode()).hexdigest()}
            except (OSError, ValueError, KeyError, TypeError): raise WorkflowError('invalid_config') from None
            def real_factory():
                from .video_services import ProviderClient
                from tools.demo_setup import dotenv
                import os
                try:
                    models=json.loads((ROOT/cfg['models_file']).read_text(encoding='utf-8-sig'))
                    strategy=json.loads((ROOT/cfg['strategy_file']).read_text(encoding='utf-8-sig'))
                    strategy['text_max_tokens']=cfg['text_max_tokens']
                    transport=dict(cfg['transport']); transport.setdefault('allowed_oss_suffix','invalid')
                    env_path=ROOT/self.webcfg.get('env_file','.env')
                    keys=dotenv(env_path) if env_path.exists() else {}
                    keys.update(os.environ)
                    ref=models['providers'][models['models']['text']['provider']]['api_key_env']
                    if not keys.get(ref): raise WorkflowError('missing_model_credentials')
                    provider=ProviderClient(models,{'strategy':strategy,'transport':transport,'prices':cfg['prices']},keys)
                    return lambda messages: provider._chat('text',messages)
                except (OSError, ValueError, KeyError, TypeError): raise WorkflowError('invalid_config') from None
            self._suggestions=SuggestionService(self.store,cfg,self.suggestion_provider_factory or real_factory,classification_config=self.classifications.config)
        return self._suggestions
    @property
    def classifications(self):
        if not hasattr(self, '_classifications'):
            from .classification import ClassificationStore, load_classification_config
            root=Path(__file__).resolve().parent.parent
            self._classifications=ClassificationStore(self.store, load_classification_config(root/self.webcfg.get('classification_config','config/classification.json')))
        return self._classifications
    @property
    def obsidian(self):
        if not hasattr(self,'_obsidian'):
            from .obsidian import ObsidianService
            from .obsidian_export import load_obsidian_config
            from .workflow import ROOT
            self._obsidian=ObsidianService(self.wc, self.classifications.config, load_obsidian_config(ROOT/self.webcfg.get('obsidian_config','config/obsidian.json')))
        return self._obsidian
    @property
    def douyin(self):
        from .workflow import ROOT
        from .douyin import load_douyin_config
        from .douyin_import import DouyinImporter
        from tools.demo_setup import dotenv
        import os
        config_path=ROOT/self.webcfg.get('douyin_config','config/douyin.json')
        env_path=ROOT/self.webcfg.get('env_file','.env')
        stamp=(config_path.stat().st_mtime_ns,env_path.stat().st_mtime_ns if env_path.exists() else None)
        if not hasattr(self,'_douyin') or self._douyin_stamp!=stamp:
            cfg=load_douyin_config(config_path)
            keys=dotenv(env_path) if cfg['enabled'] and env_path.exists() else {}
            if cfg['enabled']: keys.update(os.environ)
            self._douyin=DouyinImporter(self.wc,cfg,{cfg['cookie_env']:keys.get(cfg['cookie_env'],'')})
            self._douyin_stamp=stamp
        return self._douyin
    def _task(self, t):
        from .web_dispatch import has_unknown_submission, task_stages
        d = {k:t[k] for k in ('id','source_id','status','stage','error_code','attempts','created_at','updated_at')}
        d['progress'] = dict(completed_stages=None,total_stages=None,completed_frames=None,total_frames=None)
        with self.store._tx() as c:
            dispatch=c.execute('SELECT state,error_code,processing_mode FROM web_dispatch WHERE task_id=?',(t['id'],)).fetchone()
            d['dispatch'] = dict(dispatch) if dispatch else None
            d['archived'] = c.execute('SELECT 1 FROM web_task_archive WHERE task_id=?',(t['id'],)).fetchone() is not None
            rows = task_stages(c, t['id'])
            if t['status']=='needs_attention':
                d['resume_blocked_reason'] = 'unknown_submission' if has_unknown_submission(t, rows) else None
            if rows:
                if any(r['name']=='html-text' for r in rows): d['progress']['total_stages']=1
                d['progress']['completed_stages']=sum(r['status']=='completed' for r in rows)
                if any(r['name'].startswith('vision-') for r in rows):
                    d['progress']['completed_frames']=sum(r['status']=='completed' and r['name'].startswith('vision-') for r in rows)
        manifest=_root(self.wc)/'video-work'/t['id']/'media-manifest.json'
        try:
            if manifest.is_file():
                d['progress']['total_frames']=len(json.loads(manifest.read_text(encoding='utf8'))['frames'])
                d['progress']['total_stages']=d['progress']['total_frames']+3
        except (OSError,ValueError,KeyError,TypeError): pass
        return d
    def tasks(self): return {'items':[self._task(t) for t in self.store.list_tasks()]}
    def trash(self):
        from datetime import datetime, timezone
        items = self.store.list_trash()
        for item in items:
            for field in ('deleted_at', 'expires_at'):
                item[field] = datetime.fromtimestamp(item[field], timezone.utc).isoformat()
        return {'items':items, 'retention_days':self.store.trash_retention_seconds // 86400}

    def sources(self, filters=None):
        filters=filters or {}
        eligible = {s['id'] for s in self.store.eligible_sources()}
        tasks = {t['source_id']:t for t in self.store.list_tasks()}
        classifications=self.classifications
        items=[]
        for s in self.store.list_sources():
            if s['deleted'] and filters.get('filter_deleted',True): continue
            d={k:s[k] for k in ('id','kind','original_name','current_version_id','created_at','deleted')}
            with self.store._tx() as c:
                metadata=classifications.snapshot(s['id'],connection=c)
                review=c.execute('SELECT decision,seq FROM reviews WHERE version_id=? ORDER BY seq DESC LIMIT 1',(s['current_version_id'],)).fetchone()
                title=self.store._row(c,'versions',s['current_version_id'])['result'].get('title','') if s['current_version_id'] else ''
            status=review[0] if review else 'pending'
            d.update(title=title,status=tasks.get(s['id'],{}).get('status'),eligible=s['id'] in eligible,content_status=self.store.content_status(s['id']),classification=metadata,review_status=status,review_revision=review['seq'] if review else None)
            if filters.get('kind') and s['kind']!=filters['kind']: continue
            if filters.get('q') and filters['q'].casefold() not in (s['original_name']+' '+title).casefold(): continue
            if filters.get('reviews') and status not in filters['reviews']: continue
            if any(filters.get(k) and not set(filters[k]).intersection(x['id'] for x in metadata[k]) for k in ('topics','tags')): continue
            items.append(d)
        return {'items':items}
    def detail(self, source_id):
        source=next((s for s in self.sources({'filter_deleted':False})['items'] if s['id']==source_id),None)
        if source is None: raise WorkflowError('source_not_found')
        if source['deleted']: raise WorkflowError('source_deleted')
        versions=self.store.list_versions(source_id)
        allowed=('id','source_id','content_sha256','output_kind','parent_version_id','created_at')
        metas=[{k:v[k] for k in allowed} for v in versions]
        current=next((v for v in versions if v['id']==source['current_version_id']),None)
        result_fields=('title','body','summary','notes','transcript','visual','warnings','evidence','provenance','scheme_id','scheme_version','output_kind','duration_seconds','frames','processing')
        if current: current={**{k:current[k] for k in allowed},'result':{k:current['result'][k] for k in result_fields if k in current['result']}}
        if current:
            result=current['result']
            if 'processing' in result and isinstance(result['processing'],dict): result['processing']={k:result['processing'][k] for k in ('mode','model','usage','estimated_cost_cny','reserved_cny','extractor_version','stats') if k in result['processing']}
            if 'evidence' in result: result['evidence']=[{k:e[k] for k in ('type','locator','text','start','end','start_seconds','end_seconds','seconds','image_sha256') if k in e} for e in result['evidence'] if isinstance(e,dict)]
            if 'frames' in result: result['frames']=[{k:f[k] for k in ('index','seconds','sha256') if k in f} for f in result['frames'] if isinstance(f,dict)]
        with self.store._tx() as c:
            row=c.execute('SELECT id FROM reviews WHERE version_id=? ORDER BY seq DESC LIMIT 1',(source['current_version_id'],)).fetchone()
            review=self.store._row(c,'reviews',row[0]) if row else None
        task=next((t for t in reversed(self.tasks()['items']) if t['source_id']==source_id),None)
        frames=[{'index':f['index'],'seconds':f['seconds'],'url':f"/api/sources/{source_id}/frames/{f['index']}"} for f in (current or {}).get('result',{}).get('frames',[])]
        from .maintenance import media_status
        media=media_status(self.store,source_id)
        return dict(source=source,current=current,versions=metas,review=review,task=task,eligible=source['eligible'],frames=frames,media=media,original_url=f'/api/sources/{source_id}/original' if media['available'] else None)
    def review(self, source_id, p):
        r=self.store.review(source_id,p.get('version_id'),p.get('content_sha256'),p.get('score'),p.get('decision'),p.get('reviewer'),review_id=p.get('review_id'),note=p.get('note',''),tags=p.get('tags'))
        return {'review':r,'eligible':any(s['id']==source_id for s in self.store.eligible_sources())}
    def revise(self, source_id, p):
        s=self.store.get_source(source_id)
        if not s['current_version_id']: raise WorkflowError('version_conflict')
        result=self.store.get_version(s['current_version_id'])['result'].copy()
        changed = {k for k in ('body','transcript','visual') if k in p and p[k] != result.get(k, '')}
        evidence = list(result.get('evidence') or [])
        if 'body' in changed:
            evidence = [{'type':'human_body','locator':'human-edit:body','text':p['body']}] if p['body'] else []
        else:
            for field, types in (('transcript', ('audio','transcript','human_transcript')), ('visual', ('visual','human_visual'))):
                if field in changed:
                    evidence = [e for e in evidence if not isinstance(e, dict) or (e.get('type') not in types and e.get('locator') != 'human-edit:'+field)]
                    if p[field]: evidence.append({'type':'human_'+field,'locator':'human-edit:'+field,'text':p[field]})
        result['evidence'] = evidence
        for k in ('title','notes','summary','body','transcript','visual'):
            if k in p: result[k]=p[k]
        result.update(output_kind='human_edited',provenance='human_edited')
        v=self.store.revise(source_id,p.get('expected_version_id'),result)
        return {k:v[k] for k in ('id','source_id','content_sha256','output_kind','parent_version_id','created_at')}
    def original(self, source_id):
        s=self.store.get_source(source_id)
        if s['deleted']: raise WorkflowError('source_deleted')
        from .maintenance import media_status
        if not media_status(self.store,source_id)['available']: raise WorkflowError('media_expired')
        root=_root(self.wc).resolve(); candidate=root/s['blob_relpath']; p=candidate.resolve()
        if candidate.is_symlink() or not p.is_relative_to(root) or not p.is_file() or _hash(p)!=s['sha256']: raise WorkflowError('source_integrity')
        return p,s['kind'],s['original_name']
    def frame(self, source_id, index):
        detail=self.detail(source_id); current=detail['current']; task=detail['task']
        frames=(current or {}).get('result',{}).get('frames',[])
        f=next((x for x in frames if x['index']==index),None)
        if not f or not task: raise WorkflowError('frame_not_found')
        if self.store.content_root:
            self.store.assert_synced(source_id)
            from .content_storage import safe, read, digest
            rel=f"{source_id}/frames/{f['sha256']}.jpg"
            try:
                if digest(read(self.store.content_root,rel))!=f['sha256']: raise WorkflowError('frame_integrity')
                return safe(self.store.content_root,rel)
            except OSError: raise WorkflowError('frame_integrity') from None
        root=_root(self.wc).resolve(); candidate=root/'video-work'/task['id']
        if any(p.is_symlink() for p in (candidate,candidate.parent)): raise WorkflowError('frame_integrity')
        work=candidate.resolve()
        if not work.is_relative_to(root): raise WorkflowError('frame_integrity')
        try:
            manifest=json.loads((work/'media-manifest.json').read_text(encoding='utf8'))
            entry=next(x for x in manifest['frames'] if x['index']==index)
            p=(work/entry['file']).resolve()
            if (work/entry['file']).is_symlink() or not p.is_relative_to(work) or p.suffix.lower() not in ('.jpg','.jpeg') or entry['sha256']!=f['sha256'] or _hash(p)!=f['sha256']: raise ValueError()
            return p
        except (OSError,ValueError,KeyError,StopIteration,TypeError): raise WorkflowError('frame_integrity') from None
    def export(self, version_id):
        v=self.store.get_version(version_id)
        return render_markdown(self.store, v).encode('utf8'), version_id+'.md'
    def enqueue(self, task_id, mode='run', allow_paid=False): return self.dispatcher.enqueue(task_id,mode=mode,allow_paid=allow_paid)
    def process_next(self): return self.dispatcher.process_next()
    def start(self): return self.dispatcher.start()
    def stop(self): return self.dispatcher.stop()
