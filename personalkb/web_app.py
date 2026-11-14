import json, secrets, time, uuid, shutil, math, threading
from collections import deque
from html.parser import HTMLParser
from personalkb.web_auth import load_auth, verify_password
from pathlib import Path, PureWindowsPath
from contextlib import asynccontextmanager, nullcontext
from personalkb.runtime_guard import runtime_guard
from urllib.parse import quote
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from personalkb.workflow_store import WorkflowError
from personalkb import workflow

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAG_STATUS_POLL_INTERVAL_MS = 10000

def load_web_config(path=None):
    try:
        c=json.loads(Path(path or ROOT/'config/web.json').read_text(encoding='utf-8-sig'))
        if c['host'] not in ('127.0.0.1','localhost'): raise ValueError()
        c.setdefault('rag_status_poll_interval_ms', DEFAULT_RAG_STATUS_POLL_INTERVAL_MS)
        for k in ('port','session_ttl_seconds','max_sessions','poll_interval_ms','upload_chunk_bytes','dispatch_poll_seconds','dispatch_recovery_seconds','shutdown_timeout_seconds'):
            if type(c[k]) not in (int,float) or not math.isfinite(c[k]) or c[k]<=0: raise ValueError()
        for k in ('port','max_sessions','upload_chunk_bytes','poll_interval_ms','rag_status_poll_interval_ms','max_json_bytes'):
            if type(c[k]) is not int or c[k]<=0: raise ValueError()
        if type(c['port']) is not int or c['port']>65535: raise ValueError()
        for k in ('trusted_hosts','trusted_origins'):
            if not isinstance(c[k],list) or not c[k] or any(not isinstance(x,str) or not x for x in c[k]): raise ValueError()
        if c.get('deployment_mode','development') != 'production' and any(x not in ('127.0.0.1','localhost','testserver') for x in c['trusted_hosts']): raise ValueError()
        for k in ('workflow_config','pipeline_config','frontend_dist','env_file','display_timezone'):
            if not isinstance(c[k],str) or not c[k] or '\x00' in c[k]: raise ValueError()
        if type(c['live_video_enabled']) is not bool: raise ValueError()
        c.setdefault('rag_auto_index_enabled', True)
        c.setdefault('rag_auto_index_reconcile_seconds', c['dispatch_recovery_seconds'])
        scan_seconds = c['rag_auto_index_reconcile_seconds']
        if type(c['rag_auto_index_enabled']) is not bool or type(scan_seconds) not in (int, float) or not math.isfinite(scan_seconds) or scan_seconds <= 0:
            raise ValueError()
        c.setdefault('classification_config','config/classification.json')
        c.setdefault('suggestions_config','config/classification-suggestions.json')
        if not isinstance(c['suggestions_config'],str) or not c['suggestions_config'].strip() or '\x00' in c['suggestions_config']: raise ValueError()
        c.setdefault('obsidian_config','config/obsidian.json')
        c.setdefault('douyin_config','config/douyin.json')
        if not isinstance(c['douyin_config'],str) or not c['douyin_config'].strip() or '\x00' in c['douyin_config']: raise ValueError()
        if not isinstance(c['obsidian_config'],str) or not c['obsidian_config'].strip() or '\x00' in c['obsidian_config']: raise ValueError()
        if not isinstance(c['classification_config'],str) or not c['classification_config'].strip() or '\x00' in c['classification_config']: raise ValueError()
        c.setdefault('live_html_enabled',False)
        c.setdefault('html_pipeline_config','config/html-pipeline.json')
        if type(c['live_html_enabled']) is not bool or not isinstance(c['html_pipeline_config'],str) or not c['html_pipeline_config'].strip(): raise ValueError()
        return c
    except (OSError,ValueError,KeyError,TypeError): raise WorkflowError('invalid_config') from None

def create_app(workflow_config=None,pipeline_config=None,web_config=None,service=None):
    c=web_config or load_web_config(); wc=workflow_config or workflow.load_config(ROOT/c['workflow_config'])
    auth=load_auth(c)
    auth_enabled=auth['enabled']
    production=c.get('deployment_mode','development')=='production'
    class Assets(HTMLParser):
        def __init__(self): super().__init__(); self.paths=set()
        def handle_starttag(self,tag,attrs):
            a=dict(attrs); value=a.get('src') if tag=='script' else a.get('href') if tag=='link' and a.get('rel')=='stylesheet' else None
            if value and value.startswith('/assets/') and '?' not in value and '#' not in value and '..' not in value: self.paths.add(value)
    assets=Assets()
    try: assets.feed((ROOT/c['frontend_dist']/'index.html').read_text(encoding='utf-8'))
    except OSError: pass
    login_attempts=deque(); api_attempts=deque()
    if service is None:
        from personalkb.web_service import WebService
        from personalkb.video_pipeline import load_pipeline_config
        with runtime_guard(wc['data_dir'],'web') if production else nullcontext():
            service=WebService(wc,pipeline_config or load_pipeline_config(ROOT/c['pipeline_config']),c)
    sessions={}
    session_lock=threading.RLock()
    @asynccontextmanager
    async def lifespan(app):
        with runtime_guard(wc['data_dir'],'web') if production else nullcontext():
            if c.get('dispatch_enabled',True): service.start()
            try: yield
            finally:
                if c.get('dispatch_enabled',True): service.stop()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    @app.middleware('http')
    async def security(req,call_next):
        host=req.headers.get('host','').split(':')[0].lower()
        if host not in c['trusted_hosts']: return JSONResponse({'error':'invalid_host'},400)
        if production:
            from urllib.parse import urlsplit
            if req.headers.get('host','').lower() not in {urlsplit(x).netloc.lower() for x in c['trusted_origins']}: return JSONResponse({'error':'invalid_host'},400)
        now=time.monotonic()
        with session_lock:
            for key in list(sessions):
                if sessions[key][1]<=now: del sessions[key]
        path=req.url.path
        session=None
        if auth_enabled:
            if production and req.url.scheme != 'https': return JSONResponse({'error':'https_required'},403,headers={'Cache-Control':'no-store'})
            if path.startswith('/api/'):
                with session_lock:
                    while api_attempts and api_attempts[0] <= now-auth['api_window_seconds']: api_attempts.popleft()
                    if len(api_attempts)>=auth['api_limit']: return JSONResponse({'error':'rate_limited'},429)
                    api_attempts.append(now)
            public=path in ('/','/healthz','/api/auth/status','/api/auth/login') or path in assets.paths
            if not public:
                with session_lock: session=sessions.get(req.cookies.get('pkb_session'))
                if not session: return JSONResponse({'error':'login_required'},401,headers={'Cache-Control':'no-store'})
            if req.method not in ('GET','HEAD','OPTIONS'):
                if req.headers.get('origin') not in c['trusted_origins']: return JSONResponse({'error':'csrf_invalid'},403,headers={'Cache-Control':'no-store'})
                if path != '/api/auth/login' and (not session or not secrets.compare_digest(req.headers.get('x-csrf-token','').encode(),session[0].encode())): return JSONResponse({'error':'csrf_invalid'},403,headers={'Cache-Control':'no-store'})
        elif req.url.path.startswith('/api/') and req.url.path not in ('/api/session','/api/auth/status','/api/auth/login'):
            with session_lock: session=sessions.get(req.cookies.get('pkb_session'))
            if not session: return JSONResponse({'error':'session_required'},401,headers={'Cache-Control':'no-store'})
            if req.method not in ('GET','HEAD','OPTIONS'):
                origin=req.headers.get('origin')
                if (origin and origin not in c['trusted_origins']) or not secrets.compare_digest(req.headers.get('x-csrf-token','').encode('utf-8'),session[0].encode('ascii')): return JSONResponse({'error':'csrf_invalid'},403,headers={'Cache-Control':'no-store'})
        try: response=await call_next(req)
        except WorkflowError as e:
            code=e.code
            status=413 if code=='body_too_large' else 404 if code.endswith('_not_found') else 409 if any(x in code for x in ('conflict','stale','state','lease')) else 503 if code in ('disk_low','invalid_config') else 400
            response=JSONResponse({'error':code},status)
        except Exception: response=JSONResponse({'error':'internal_error'},503)
        response.headers.setdefault('Content-Security-Policy',"default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'")
        response.headers['X-Content-Type-Options']='nosniff'
        if auth_enabled or req.url.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
        return response
    @app.get('/healthz')
    def health(): return {'ok':True}
    @app.get('/api/auth/status')
    def auth_status(req:Request):
        with session_lock: valid=bool(sessions.get(req.cookies.get('pkb_session')))
        return {'enabled':auth_enabled,'authenticated':valid if auth_enabled else True}
    @app.post('/api/auth/login')
    async def login(req:Request):
        if not auth_enabled: return JSONResponse({'error':'invalid_credentials'},400)
        now=time.monotonic()
        with session_lock:
            while login_attempts and login_attempts[0]<=now-auth['login_window_seconds']: login_attempts.popleft()
            if len(login_attempts)>=auth['login_limit']: return JSONResponse({'error':'rate_limited'},429)
            login_attempts.append(now)
        try:
            payload=await read_object(req)
            password=payload.get('password')
            if not isinstance(password,str) or len(password)>1024: raise ValueError()
            valid=await run_in_threadpool(verify_password,password,auth['password_hash'])
        except (ValueError,WorkflowError): return JSONResponse({'error':'invalid_credentials'},400)
        if not valid: return JSONResponse({'error':'invalid_credentials'},401)
        with session_lock:
            sessions.pop(req.cookies.get('pkb_session'),None)
            while len(sessions)>=int(c['max_sessions']): sessions.pop(next(iter(sessions)))
            sid=secrets.token_urlsafe(32); token=secrets.token_urlsafe(32)
            sessions[sid]=(token,time.monotonic()+c['session_ttl_seconds'])
        r=JSONResponse({'authenticated':True})
        r.set_cookie('pkb_session',sid,httponly=True,secure=True,samesite='strict',max_age=int(c['session_ttl_seconds']))
        return r
    @app.post('/api/auth/logout')
    def logout(req:Request):
        with session_lock: sessions.pop(req.cookies.get('pkb_session'),None)
        r=JSONResponse({'authenticated':False}); r.delete_cookie('pkb_session',secure=True,httponly=True,samesite='strict'); return r
    @app.get('/api/session')
    def session(req:Request):
        with session_lock:
            sid=req.cookies.get('pkb_session')
            existing=sessions.get(sid)
            if existing:
                token=existing[0]
            else:
                if auth_enabled: return JSONResponse({'error':'login_required'},401)
                while len(sessions)>=int(c['max_sessions']): sessions.pop(next(iter(sessions)))
                sid=secrets.token_urlsafe(32); token=secrets.token_urlsafe(32)
            if not auth_enabled: sessions[sid]=(token,time.monotonic()+c['session_ttl_seconds'])
        r=JSONResponse({'csrf_token':token,'config':{'quality_target':wc['quality_target'],'poll_interval_ms':c['poll_interval_ms'],
            'rag_status_poll_interval_ms':c.get('rag_status_poll_interval_ms', DEFAULT_RAG_STATUS_POLL_INTERVAL_MS),
            'max_upload_bytes':wc['max_upload_bytes'],'max_html_bytes':wc['max_html_bytes'],'live_video_enabled':c['live_video_enabled'],'live_html_enabled':c.get('live_html_enabled',False),'display_timezone':c['display_timezone'],'auth_enabled':auth_enabled}})
        r.set_cookie('pkb_session',sid,httponly=True,secure=auth_enabled,samesite='strict',max_age=int(c['session_ttl_seconds']))
        return r
    @app.get('/api/sources')
    def sources(req:Request):
        q=req.query_params
        return service.sources({'kind':q.get('kind'), 'q':q.get('q'), 'topics':q.getlist('topics'), 'tags':q.getlist('tags'), 'reviews':q.getlist('reviews')}) if q else service.sources()
    @app.get('/api/classifications')
    def classifications(): return {'items':service.classifications.catalog()}
    @app.get('/api/tasks')
    def tasks(): return service.tasks()
    @app.get('/api/douyin/status')
    def douyin_status(): return service.douyin.status()
    @app.get('/api/douyin/favorites/sync')
    def favorites_sync():
        sync = service.favorites_sync
        if not sync:
            return {'enabled': False, 'items': []}
        available = service.webcfg['live_video_enabled'] and all(service.douyin.status().values())
        return sync.status(service.favorites_cookie(), manual_conversion_available=available)
    @app.post('/api/douyin/favorites/{action}')
    async def favorites_action(action:str, req:Request):
        payload = await read_object(req)
        sync = service.favorites_sync
        if not sync: raise WorkflowError('favorites_disabled')
        if action == 'scan': return sync.request_scan()
        cookie = service.favorites_cookie()
        if action == 'confirm': return sync.confirm(payload.get('account_id'), cookie)
        if action == 'import':
            if not service.webcfg['live_video_enabled']:
                raise WorkflowError('video_disabled')
            service.douyin._ready()
            return sync.select(payload.get('account_id'), payload.get('work_ids'), cookie,
                               rights_confirmed=payload.get('rights_confirmed'), allow_paid=payload.get('allow_paid'),
                               video_budget_cny=payload.get('video_budget_cny'))
        raise WorkflowError('favorites_action_not_found')
    @app.get('/api/douyin/jobs')
    def douyin_jobs(): return {'items':service.douyin.jobs()}
    @app.post('/api/douyin/import')
    async def douyin_import(req:Request):
        p=await read_object(req)
        return service.douyin.enqueue(p.get('share_text'),p.get('rights_confirmed',False))
    @app.post('/api/douyin/jobs/{job_id}/retry')
    async def douyin_retry(job_id:str,req:Request):
        await read_object(req)
        return service.douyin.retry(job_id)
    @app.get('/api/sources/{source_id}')
    def detail(source_id:str, version_id:str|None=None): return service.detail(source_id,version_id)
    @app.put('/api/imports')
    async def upload(req:Request,filename:str,rights_confirmed:bool=False):
        if not rights_confirmed: raise WorkflowError('rights_required')
        if not filename or filename in ('.','..') or Path(filename).name!=filename or PureWindowsPath(filename).name!=filename or any(ord(x)<32 or ord(x)==127 for x in filename): raise WorkflowError('invalid_filename')
        ext=Path(filename).suffix.lower()
        if ext not in ('.html','.htm','.mp4'): raise WorkflowError('unsupported_format')
        limit=min(wc['max_upload_bytes'],wc['max_html_bytes']) if ext in ('.html','.htm') else wc['max_upload_bytes']
        try: length=int(req.headers.get('content-length','0'))
        except ValueError: raise WorkflowError('invalid_size')
        if length<0 or length>limit: return JSONResponse({'error':'too_large'},413)
        data=Path(wc['data_dir']); data.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(data).free - 2*(length or limit) < wc['min_free_bytes']: raise WorkflowError('disk_low')
        directory=ROOT/'tmp/web-uploads'; directory.mkdir(parents=True,exist_ok=True); path=directory/(uuid.uuid4().hex+ext)
        try:
            size=0
            with path.open('xb') as f:
                async for chunk in req.stream():
                    size+=len(chunk)
                    if shutil.disk_usage(data).free - size < wc['min_free_bytes']: raise WorkflowError('disk_low')
                    if size>limit: return JSONResponse({'error':'too_large'},413)
                    f.write(chunk)
            result=await run_in_threadpool(workflow.import_file,wc,path,rights_confirmed=True)
            source=result['source']; task=result['task']
            if not result['duplicate']:
                with service.store._tx() as db: db.execute('UPDATE sources SET original_name=? WHERE id=?',(filename,source['id']))
            return {'source_id':source['id'],'task_id':task['id'],'duplicate':result['duplicate'],'name':source['original_name'] if result['duplicate'] else filename,'kind':source['kind']}
        finally: path.unlink(missing_ok=True)
    async def read_object(req):
        try:
            body=bytearray()
            async for chunk in req.stream():
                body.extend(chunk)
                if len(body)>c['max_json_bytes']: raise WorkflowError('body_too_large')
            value=json.loads(body)
            if not isinstance(value,dict): raise ValueError()
            return value
        except (ValueError, TypeError): raise WorkflowError('invalid_json') from None
    def rag_args(p, question=True, *, answer=False):
        if type(p.get('allow_paid')) is not bool: raise WorkflowError('invalid_request')
        rid = p.get('request_id')
        if not isinstance(rid, str) or not rid or len(rid) > 128: raise WorkflowError('invalid_request')
        if not question: return {'allow_paid': p['allow_paid'], 'request_id': rid}
        q = p.get('question')
        if not isinstance(q, str) or not q.strip() or len(q) > c['max_json_bytes']: raise WorkflowError('invalid_request')
        mode = p.get('mode', 'hybrid')
        if mode not in ('lexical', 'hybrid'): raise WorkflowError('invalid_request')
        filters = p.get('filters', {})
        if not isinstance(filters, dict) or set(filters) - {'sources', 'topics', 'tags'}: raise WorkflowError('invalid_request')
        if any(not isinstance(v, list) or any(not isinstance(x, str) or not x for x in v) for v in filters.values()): raise WorkflowError('invalid_request')
        args = {'question': q, 'filters': filters, 'allow_paid': p['allow_paid'], 'request_id': rid, 'mode': mode}
        if answer and 'expected_source_ids' in p:
            ids = p['expected_source_ids']
            if not isinstance(ids, list) or not ids or any(not isinstance(s, str) or not s for s in ids):
                raise WorkflowError('invalid_request')
            args['expected_source_ids'] = ids
        return args
    @app.get('/api/rag/status')
    def rag_status(): return service.rag_status()
    @app.post('/api/rag/auto-index')
    async def rag_auto_index(req: Request):
        p = await read_object(req)
        if not service.rag.config['enabled']:
            raise WorkflowError('rag_disabled')
        return await run_in_threadpool(service.rag_auto_index.set_enabled, p.get('enabled'), allow_paid=p.get('allow_paid'))
    @app.post('/api/rag/index/retry')
    async def rag_index_retry(req: Request):
        p = await read_object(req)
        if not service.rag.config['enabled']:
            raise WorkflowError('rag_disabled')
        return await run_in_threadpool(service.rag_auto_index.retry, allow_paid=p.get('allow_paid'))
    @app.get('/api/rag/citations/{chunk_id}')
    def rag_citation(chunk_id: str):
        try: return service.rag.citation(chunk_id)
        except WorkflowError: return JSONResponse({'error':'rag_invalidated'}, status_code=409)
    @app.post('/api/rag/build')
    async def rag_build(req: Request):
        args = rag_args(await read_object(req), False)
        return await run_in_threadpool(service.rag.build, **args)
    @app.post('/api/rag/search')
    async def rag_search(req: Request):
        args = rag_args(await read_object(req))
        return {'items': await run_in_threadpool(service.rag.query, **args)}
    @app.post('/api/rag/ask')
    async def rag_ask(req: Request):
        args = rag_args(await read_object(req), answer=True)
        return await run_in_threadpool(service.rag_answers.ask, **args)
    @app.post('/api/rag/stream')
    async def rag_stream(req: Request):
        args = rag_args(await read_object(req), answer=True)
        def events():
            try:
                for event in service.rag_answers.stream(**args):
                    yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
            except Exception:
                yield 'data: {"type":"error","code":"internal_error"}\n\n'
        return StreamingResponse(events(), media_type='text/event-stream')
    @app.post('/api/classifications')
    async def create_classification(req:Request):
        p=await read_object(req)
        return service.classifications.create_label(p.get('kind'),p.get('name'),p.get('aliases',[]))
    @app.get('/api/sources/{source_id}/obsidian/{kind}')
    def obsidian_export(source_id:str,kind:str):
        if kind=='note': data,name=service.obsidian.export_note(source_id);mime='text/markdown'
        elif kind=='zip': data,name=service.obsidian.export_zip(source_id);mime='application/zip'
        else: raise WorkflowError('export_not_found')
        return Response(data,media_type=mime,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(name)})
    @app.post('/api/obsidian/preview')
    async def obsidian_preview(req:Request,filename:str):
        if not filename or Path(filename).name!=filename or PureWindowsPath(filename).name!=filename: raise WorkflowError('invalid_filename')
        limit=service.obsidian.config['max_input_bytes']
        declared=req.headers.get('content-length')
        if declared and (not declared.isdigit() or int(declared)>limit): raise WorkflowError('body_too_large')
        raw=bytearray()
        async for chunk in req.stream():
            raw.extend(chunk)
            if len(raw)>limit: raise WorkflowError('body_too_large')
        return await run_in_threadpool(service.obsidian.preview,bytes(raw),filename)
    @app.post('/api/obsidian/apply')
    async def obsidian_apply(req:Request):
        p=await read_object(req)
        return await run_in_threadpool(service.obsidian.apply,p.get('preview_id'),p.get('choice'))
    @app.post('/api/classifications/bulk')
    async def bulk_classification(req:Request):
        p=await read_object(req)
        return {'items':service.classifications.bulk(p.get('items'),p.get('operation','add'),p.get('topics',[]),p.get('tags',[]))}
    @app.post('/api/classifications/{label_id}')
    async def update_classification(label_id:str,req:Request):
        p=await read_object(req)
        return service.classifications.update_label(label_id,p.get('expected_revision'),p.get('name'),p.get('aliases',[]))
    @app.post('/api/sources/{source_id}/classification')
    async def update_source_classification(source_id:str,req:Request):
        p=await read_object(req)
        return service.classifications.update(source_id,p.get('expected_revision'),p.get('topics',[]),p.get('tags',[]))
    @app.get('/api/sources/{source_id}/classification/suggestions')
    def latest_suggestion(source_id:str): return service.suggestions.latest(source_id)
    @app.get('/api/classification-suggestions/status')
    def suggestion_status(): return {'enabled':service.suggestions.config.get('enabled') is True}
    @app.post('/api/sources/{source_id}/classification/suggestions')
    async def generate_suggestion(source_id:str,req:Request):
        p=await read_object(req)
        return await run_in_threadpool(service.suggestions.generate,source_id,p.get('expected_version_id'),p.get('expected_revision'),p.get('allow_paid',False))
    @app.post('/api/classification-suggestions/{suggestion_id}/apply')
    async def apply_suggestion(suggestion_id:str,req:Request):
        p=await read_object(req)
        return await run_in_threadpool(service.suggestions.apply,suggestion_id,p.get('existing_topics',[]),p.get('existing_tags',[]),p.get('confirmed_new_topics',[]),p.get('confirmed_new_tags',[]))
    @app.post('/api/classification-suggestions/{suggestion_id}/reject')
    async def reject_suggestion(suggestion_id:str,req:Request):
        await read_object(req)
        return await run_in_threadpool(service.suggestions.reject,suggestion_id)
    @app.post('/api/tasks/{task_id}/{action}')
    async def task_action(task_id:str,action:str,req:Request):
        payload=await read_object(req)
        if action in ('archive', 'unarchive'): return service.dispatcher.set_archived(task_id, action == 'archive')
        if action=='cancel': return service.dispatcher.cancel(task_id)
        if action=='recover-model': return service.dispatcher.recover_model(task_id, payload)
        if action=='retry': return service.dispatcher.retry(task_id,allow_paid=payload.get('allow_paid',False),processing_mode=payload.get('processing_mode'))
        elif action not in ('start','resume'): raise WorkflowError('task_not_found')
        return service.dispatcher.enqueue(task_id,mode='resume' if action=='resume' else 'run',allow_paid=payload.get('allow_paid',False),processing_mode=payload.get('processing_mode','preview'))
    @app.post('/api/sources/{source_id}/reviews')
    async def review(source_id:str,req:Request): return service.review(source_id,await read_object(req))
    @app.post('/api/sources/{source_id}/process')
    async def reprocess_source(source_id:str,req:Request):
        p=await read_object(req)
        return service.dispatcher.reprocess(source_id,p.get('expected_version_id'),p.get('allow_paid',False),request_id=p.get('request_id'))
    @app.post('/api/sources/{source_id}/revisions')
    async def revise(source_id:str,req:Request): return service.revise(source_id,await read_object(req))
    @app.delete('/api/sources/{source_id}')
    def delete(source_id:str): service.store.delete_source(source_id); return {'deleted':True}
    @app.get('/api/trash')
    def trash(): return service.trash()
    @app.post('/api/trash/{source_id}/restore')
    async def restore_source(source_id:str,req:Request):
        await read_object(req)
        service.store.restore_source(source_id)
        return {'restored':True}
    @app.get('/api/sources/{source_id}/original')
    def original(source_id:str):
        path,kind,name=service.original(source_id)
        r=FileResponse(path,media_type='text/html' if kind=='html' else 'video/mp4',filename=name,content_disposition_type='attachment' if kind=='html' else 'inline')
        if kind=='html': r.headers['Content-Security-Policy']="sandbox; default-src 'none'"
        return r
    @app.get('/api/sources/{source_id}/frames/{index}')
    def frame(source_id:str,index:int,version_id:str|None=None): return FileResponse(service.frame(source_id,index,version_id),media_type='image/jpeg')
    @app.get('/api/versions/{version_id}/export')
    def export(version_id:str):
        data,name=service.export(version_id)
        return Response(data,media_type='text/markdown',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(name)})
    @app.get('/{path:path}')
    def static(path:str):
        root=(ROOT/c['frontend_dist']).resolve()
        if path and not path.startswith('assets/'): return JSONResponse({'error':'not_found'},404)
        target=(root/(path or 'index.html')).resolve()
        if not target.is_relative_to(root) or not target.is_file(): return JSONResponse({'error':'frontend_unavailable' if not path else 'not_found'},503 if not path else 404)
        return FileResponse(target)
    return app
