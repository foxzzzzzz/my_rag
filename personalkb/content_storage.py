import hashlib, json, os, re, uuid
from pathlib import Path
from .workflow_store import WorkflowError

SAFE_EVIDENCE = ('type', 'locator', 'text', 'start', 'end', 'start_seconds', 'end_seconds', 'seconds', 'image_sha256')

def digest(data): return hashlib.sha256(data).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode('utf8')
def clean(value):
    # Free text is knowledge content; only the surrounding metadata is allowlisted.
    return value

def safe(root, *parts):
    if any(Path(str(part)).is_absolute() or '..' in Path(str(part).replace('\\','/')).parts or Path(str(part)).drive for part in parts): raise WorkflowError('content_path_invalid')
    p = root.joinpath(*parts)
    if not p.absolute().is_relative_to(root.absolute()) or any(x.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(x)) for x in (p, *p.parents)):
        raise WorkflowError('content_path_invalid')
    return p

def write(root, relative, data):
    p=safe(root, relative); p.parent.mkdir(parents=True, exist_ok=True)
    safe(root, relative)
    tmp=p.parent/('.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('xb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
    finally: tmp.unlink(missing_ok=True)

def read(root, relative):
    p=safe(root,relative)
    if not p.is_file(): raise WorkflowError('content_integrity')
    return p.read_bytes()

def render(source, version, status, *, location=None, classification=None):
    r=version['result']
    fields={'note_id':source['id'], 'source_id':source['id'], 'version_id':version['id'], 'source_sha256':source['sha256'], 'content_sha256':version['content_sha256'], 'review_status':status, 'scheme_id':clean(r['scheme_id']), 'scheme_version':clean(r['scheme_version']), 'output_kind':r['output_kind']}
    if classification is not None: fields.update(classification_revision=classification['revision'], topics=classification['topics'], tags=classification['tags'])
    front='---\n'+''.join(k+': '+json.dumps(v,ensure_ascii=False)+'\n' for k,v in fields.items())+'---\n\n'
    text=front+'# '+r['title']+'\n\n'+r['notes']+'\n\n## Body\n\n'+r['body']+'\n\n## Summary\n\n'+r['summary']+'\n'
    for key, title in (('transcript','Transcript'),('visual','Visual')):
        if r.get(key): text+='\n## '+title+'\n\n'+r[key]+'\n'
    if location:
        evidence='evidence.json' if location=='version' else f"versions/{version['id']}/evidence.json"
        text+='\n[Evidence]('+evidence+')\n'
        for frame in r.get('frames',[]):
            prefix='../../frames/' if location=='version' else 'frames/'
            text+='\n![Frame '+str(frame['index'])+']('+prefix+frame['sha256']+'.jpg)\n'
    return text

def sync(store, sid):
    root=store.content_root
    from .classification import ClassificationStore
    ClassificationStore(store)
    with store._tx() as c:
        source=store._row(c,'sources',sid)
        dirty=c.execute('SELECT generation FROM content_sync WHERE source_id=?',(sid,)).fetchone()
        if not dirty: raise WorkflowError('content_not_tracked')
        generation=dirty[0]; entries={}
        versions=[store._row(c,'versions',x[0]) for x in c.execute('SELECT id FROM versions WHERE source_id=? ORDER BY rowid',(sid,)).fetchall()]
        for v in versions:
            raw=json.dumps(v['result'],ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()
            if digest(raw)!=v['content_sha256']: raise WorkflowError('version_integrity')
            base=f"{sid}/versions/{v['id']}"
            md=render(source,v,'immutable',location='version').encode('utf8')
            evidence=encoded([clean({k:e[k] for k in SAFE_EVIDENCE if k in e}) for e in v['result']['evidence']])
            files={'content.md':md,'evidence.json':evidence}
            for frame in v['result'].get('frames',[]):
                sha=frame['sha256']
                if not re.fullmatch(r'[0-9a-f]{64}',sha): raise WorkflowError('frame_integrity')
                rel=f'{sid}/frames/{sha}.jpg'
                try:
                    data=read(root,rel)
                    if digest(data)!=sha: raise WorkflowError('frame_integrity')
                except (OSError,WorkflowError):
                    data=None
                    for task in c.execute('SELECT id FROM tasks WHERE source_id=? ORDER BY rowid DESC',(sid,)).fetchall():
                        work=safe(store.data_root,'video-work',task[0])
                        try:
                            manifest=json.loads(read(store.data_root,str(work.relative_to(store.data_root)/'media-manifest.json')))
                            entry=next(x for x in manifest['frames'] if x['index']==frame['index'] and x['sha256']==sha)
                            candidate=safe(work,entry['file'])
                            data=candidate.read_bytes()
                            if digest(data)!=sha: data=None; continue
                            break
                        except (OSError,ValueError,KeyError,TypeError,StopIteration,WorkflowError): continue
                    if data is None: raise WorkflowError('frame_integrity')
                if digest(data)!=sha: raise WorkflowError('frame_integrity')
                write(root,rel,data); entries[rel]=sha
            for name,data in files.items():
                rel=f'{base}/{name}'; write(root,rel,data); entries[rel]=digest(data)
            manifest=encoded({'source_id':sid,'version_id':v['id'],'content_sha256':v['content_sha256'],'files':{k:digest(x) for k,x in files.items()},'frames':[x['sha256'] for x in v['result'].get('frames',[])]})
            rel=f'{base}/manifest.json'; write(root,rel,manifest); entries[rel]=digest(manifest)
        review=c.execute('SELECT decision FROM reviews WHERE version_id=? ORDER BY seq DESC LIMIT 1',(source['current_version_id'],)).fetchone()
        status='deleted' if source['deleted'] else ({'approve':'approved','reject':'rejected','rework':'rework'}[review[0]] if review else 'pending')
        if source['current_version_id']:
            current=next(v for v in versions if v['id']==source['current_version_id'])
            from .classification import snapshot_from_connection
            note=render(source,current,status,location='current',classification=snapshot_from_connection(c,sid)).encode('utf8')
            rel=f'{sid}/note.md'; write(root,rel,note); entries[rel]=digest(note)
        state=encoded({'note_id':sid,'source_id':sid,'current_version_id':source['current_version_id'],'status':status,'generation':generation,'files':entries})
        write(root,f'{sid}/current.json',state)
        c.execute('UPDATE content_sync SET synced_generation=?, state_sha256=? WHERE source_id=? AND generation=?',(generation,digest(state),sid,generation))

def verify(store,sid,connection=None):
    if connection is None:
        with store._tx() as c:
            return verify(store,sid,c)
    c=connection
    row=c.execute('SELECT generation,synced_generation,state_sha256 FROM content_sync WHERE source_id=?',(sid,)).fetchone()
    if not row or row[0]!=row[1] or not row[2]: raise WorkflowError('content_unsynced')
    try:
        state=read(store.content_root,f'{sid}/current.json')
        if digest(state)!=row[2]: raise ValueError()
        obj=json.loads(state)
        if obj['note_id']!=sid or obj['generation']!=row[0]: raise ValueError()
        for path,sha in obj['files'].items():
            if not path.startswith(sid+'/') or digest(read(store.content_root,path))!=sha: raise ValueError()
    except (OSError,ValueError,KeyError,TypeError,WorkflowError): raise WorkflowError('content_integrity') from None
    return True
