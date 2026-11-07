"""Untrusted Obsidian upload -> durable preview -> explicit atomic revision."""
import hashlib
import io
import json
import re
import stat
import time
import unicodedata
import uuid
import zipfile
from pathlib import PurePosixPath, PureWindowsPath
from .workflow_store import WorkflowError, _json
from .obsidian_export import EditableExport, readonly_files


def _sha(data): return hashlib.sha256(data).hexdigest()


def _scalar(value):
    value=value.strip()
    try:return json.loads(value)
    except ValueError:
        if len(value)>=2 and value.startswith("'") and value.endswith("'"):
            return value[1:-1].replace("''", "'")
        if not value or value in ('|','>') or value.startswith(('!','&','*','[','{','"')):
            raise ValueError()
        return value


class ObsidianService(EditableExport):
    def __init__(self, workflow_config, classification_config=None, config=None):
        super().__init__(workflow_config, classification_config, config)
        with self.store._tx() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS obsidian_previews (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL, candidate TEXT NOT NULL,
                candidate_sha256 TEXT NOT NULL, current_version_id TEXT NOT NULL,
                metadata_revision INTEGER NOT NULL, expires_at REAL NOT NULL,
                applied_choice TEXT, receipt TEXT)''')

    def _parse_note(self, raw):
        if len(raw)>self.config['max_note_bytes']: raise WorkflowError('note_too_large')
        try:
            text=raw.decode('utf-8-sig').replace('\r\n','\n')
            lines=text.split('\n')
            if lines[0]!='---': raise ValueError()
            end=lines.index('---',1); fields={}; sequence=None
            for line in lines[1:end]:
                if not line.strip() or line.lstrip().startswith('#'):continue
                if line.lstrip().startswith('- '):
                    if sequence is None:raise ValueError()
                    fields[sequence].append(_scalar(line.lstrip()[2:]));continue
                key,sep,value=line.partition(':')
                if not sep or key in fields or not re.fullmatch('[a-z_][a-z_0-9]*',key): raise ValueError()
                if not value.strip():fields[key]=[];sequence=key
                else:fields[key]=_scalar(value);sequence=None
            if fields.get('pkb_format')!='pkb-obsidian-v1': raise ValueError()
            for k in ('note_id','source_id','base_version_id'):
                if not isinstance(fields.get(k),str) or not re.fullmatch('[0-9a-f]{32}',fields[k]): raise ValueError()
            if fields['note_id']!=fields['source_id'] or not isinstance(fields.get('base_content_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',fields['base_content_sha256']): raise ValueError()
            if not isinstance(fields.get('title'),str) or not fields['title'].strip(): raise ValueError()
            if type(fields.get('classification_revision')) is not int or fields['classification_revision']<0: raise ValueError()
            for k in ('topic_ids','tag_ids'):
                values=fields[k]
                if not isinstance(values,list) or any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{32}',x) for x in values) or len(set(values))!=len(values): raise ValueError()
            notes='\n'.join(lines[end+1:])
            if notes.startswith('\n'): notes=notes[1:]
            if not notes.strip(): raise ValueError()
            # No other properties (including review_status) confer authority.
            return {k:fields[k] for k in ('source_id','base_version_id','base_content_sha256','title','classification_revision','topic_ids','tag_ids')}|{'notes':notes}
        except (ValueError,KeyError,TypeError,UnicodeError,RecursionError): raise WorkflowError('invalid_obsidian_note') from None

    def _read_upload(self, data, filename):
        if not isinstance(data,bytes) or not data or len(data)>self.config['max_input_bytes']: raise WorkflowError('invalid_size')
        if not isinstance(filename,str): raise WorkflowError('invalid_filename')
        suffix=PurePosixPath(filename).suffix.lower()
        if suffix=='.md': return self._parse_note(data),None,None
        if suffix!='.zip': raise WorkflowError('unsupported_format')
        try:
            files={}; seen=set(); total=0
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                members=z.infolist()
                if not members or len(members)>self.config['max_members']: raise WorkflowError('zip_limits')
                for info in members:
                    name=info.filename; parts=PurePosixPath(name).parts
                    collision=unicodedata.normalize('NFKC',name).casefold()
                    if not name or '\\' in name or ':' in name or '\x00' in name or name.startswith('/') or PureWindowsPath(name).drive or any(p in ('..','.') for p in name.split('/')) or any(ord(ch)<32 for ch in name) or collision in seen: raise WorkflowError('unsafe_zip')
                    if stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1: raise WorkflowError('unsafe_zip')
                    if info.is_dir():
                        if name!='frames/': raise WorkflowError('unsafe_zip')
                        seen.add(collision)
                        continue
                    if not parts or str(PurePosixPath(name))!=name: raise WorkflowError('unsafe_zip')
                    seen.add(collision)
                    if info.file_size<0 or info.file_size>self.config['max_uncompressed_bytes']-total: raise WorkflowError('zip_limits')
                    with z.open(info) as src:
                        raw=src.read(self.config['max_uncompressed_bytes']-total+1)
                    total+=len(raw)
                    if total>self.config['max_uncompressed_bytes'] or len(raw)!=info.file_size: raise WorkflowError('zip_limits')
                    files[name]=raw
            if 'note.md' not in files or 'manifest.json' not in files: raise WorkflowError('invalid_obsidian_zip')
            if len(files['note.md'])>self.config['max_note_bytes'] or len(files['manifest.json'])>self.config['max_note_bytes']: raise WorkflowError('zip_limits')
            note=self._parse_note(files['note.md']);manifest=json.loads(files['manifest.json'])
            if not isinstance(manifest,dict): raise WorkflowError('invalid_obsidian_zip')
            return note,files,manifest
        except WorkflowError: raise
        except (zipfile.BadZipFile,ValueError,TypeError,KeyError,RuntimeError,OSError,EOFError,NotImplementedError): raise WorkflowError('invalid_obsidian_zip') from None

    def preview(self,data,filename):
        candidate,files,manifest=self._read_upload(data,filename)
        sid=candidate['source_id']
        with self.store._tx() as c:
            source=self.store._row(c,'sources',sid)
            if source['deleted']: raise WorkflowError('source_deleted')
            base=self.store._row(c,'versions',candidate['base_version_id'])
            if base['source_id']!=sid or base['content_sha256']!=candidate['base_content_sha256']: raise WorkflowError('version_conflict')
            if files is not None:
                expected=readonly_files(self.store,source,base)
                expected_hashes={k:_sha(v) for k,v in expected.items()}
                if manifest.get('pkb_format')!='pkb-obsidian-v1' or manifest.get('source_id')!=sid or manifest.get('base_version_id')!=base['id'] or manifest.get('note')!='note.md' or manifest.get('files')!=expected_hashes: raise WorkflowError('attachment_integrity')
                if set(files)-{'note.md','manifest.json','README.md'}!=set(expected) or any(files.get(k)!=v for k,v in expected.items()): raise WorkflowError('attachment_integrity')
            metadata=self.classification.snapshot(sid,connection=c)
            # Validate assignments without mutation, including limits and kinds.
            for kind,key in (('topic','topic_ids'),('tag','tag_ids')):
                ids=candidate[key]
                if len(ids)>self.classification.config['max_labels_per_kind']: raise WorkflowError('invalid_classification')
                for ident in ids:
                    label=c.execute('SELECT kind FROM classification_labels WHERE id=?',(ident,)).fetchone()
                    if not label or label[0]!=kind: raise WorkflowError('classification_not_found')
            current=self.store._row(c,'versions',source['current_version_id'])
            preview_id=uuid.uuid4().hex;raw=_json(candidate)
            c.execute('INSERT INTO obsidian_previews(id,source_id,candidate,candidate_sha256,current_version_id,metadata_revision,expires_at) VALUES(?,?,?,?,?,?,?)',(preview_id,sid,raw,_sha(raw.encode()),current['id'],metadata['revision'],time.time()+self.config['preview_ttl_seconds']))
            labels={r['id']:dict(r) for r in c.execute('SELECT id,name FROM classification_labels')}
            incoming_meta={'topics':[labels[x] for x in candidate['topic_ids']],'tags':[labels[x] for x in candidate['tag_ids']]}
            return {'preview_id':preview_id,'source_id':sid,'base_version_id':base['id'],'current_version_id':current['id'],
                    'conflict':base['id']!=current['id'] or candidate['classification_revision']!=metadata['revision'],
                    'content_conflict':base['id']!=current['id'],
                    'classification_conflict':candidate['classification_revision']!=metadata['revision'],
                    'incoming_metadata_revision':candidate['classification_revision'],'current_metadata_revision':metadata['revision'],
                    'current':{'title':current['result']['title'],'notes':current['result']['notes'],'classification':metadata},
                    'incoming':{'title':candidate['title'],'notes':candidate['notes'],'classification':incoming_meta}}

    def apply(self,preview_id,choice):
        if not isinstance(preview_id,str) or choice not in ('keep_server','use_uploaded'): raise WorkflowError('invalid_request')
        with self.store._tx() as c:
            row=c.execute('SELECT * FROM obsidian_previews WHERE id=?',(preview_id,)).fetchone()
            if not row: raise WorkflowError('preview_not_found')
            sid=row['source_id']
            if row['receipt']:
                if row['applied_choice']!=choice: raise WorkflowError('preview_conflict')
                result=json.loads(row['receipt'])
            else:
                if time.time()>row['expires_at']: raise WorkflowError('preview_expired')
                source=self.store._row(c,'sources',sid)
                if source['deleted']: raise WorkflowError('source_deleted')
                candidate=json.loads(row['candidate'])
                if _sha(row['candidate'].encode())!=row['candidate_sha256']: raise WorkflowError('preview_integrity')
                result={'source_id':sid,'version_id':source['current_version_id'],'changed':False,'content_changed':False,'classification_changed':False,'review_required':False}
                if choice=='use_uploaded':
                    if source['current_version_id']!=row['current_version_id']: raise WorkflowError('version_conflict')
                    before=self.classification.snapshot(sid,connection=c)
                    if before['revision']!=row['metadata_revision']: raise WorkflowError('classification_conflict')
                    old=self.store._row(c,'versions',source['current_version_id'])
                    if old['result']['notes'].replace('\r\n','\n')!=candidate['notes'] or old['result']['title']!=candidate['title']:
                        material={**old['result'],'title':candidate['title'],'notes':candidate['notes'],'provenance':'human_edited','output_kind':'human_edited'}
                        version=self.store._version(c,sid,material,old['id'],True)
                        result.update(version_id=version['id'],content_changed=True,review_required=True)
                    after=self.classification.update_in_transaction(c,sid,row['metadata_revision'],candidate['topic_ids'],candidate['tag_ids'])
                    result['classification_changed']=before['revision']!=after['revision']
                    result['changed']=result['content_changed'] or result['classification_changed']
                c.execute('UPDATE obsidian_previews SET applied_choice=?,receipt=? WHERE id=?',(choice,_json(result),preview_id))
        if self.store.content_root:
            try:self.store.sync_source(sid)
            except Exception:pass
        return {**result,'content_status':self.store.content_status(sid)}
