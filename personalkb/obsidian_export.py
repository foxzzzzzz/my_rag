"""Editable Obsidian export and database-anchored read-only assets."""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from .workflow import make_store
from .workflow_store import WorkflowError
from .classification import ClassificationStore
from .content_storage import SAFE_EVIDENCE, encoded, read, digest

_KEYS = ('max_input_bytes', 'max_uncompressed_bytes', 'max_members', 'max_note_bytes', 'preview_ttl_seconds')

def _validate(config):
    if not isinstance(config, dict) or any(type(config.get(k)) is not int or config[k] <= 0 for k in _KEYS):
        raise WorkflowError('invalid_config')
    return config

def load_obsidian_config(path=None):
    try:
        return _validate(json.loads(Path(path or Path(__file__).resolve().parent.parent / 'config/obsidian.json').read_text(encoding='utf-8-sig')))
    except (OSError, ValueError, TypeError):
        raise WorkflowError('invalid_config') from None

def readonly_files(store, source, version):
    """Derive allowed attachment bytes from a specific immutable DB version."""
    if version['source_id'] != source['id']:
        raise WorkflowError('version_conflict')
    result = version['result']
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    if digest(raw) != version['content_sha256']:
        raise WorkflowError('version_integrity')
    evidence = {k: result[k] for k in ('body', 'summary', 'transcript', 'visual') if k in result}
    evidence['evidence'] = [{k: e[k] for k in SAFE_EVIDENCE if k in e} for e in result['evidence']]
    files = {'evidence.json': encoded(evidence)}
    for frame in result.get('frames', []):
        sha = frame.get('sha256')
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) or not store.content_root:
            raise WorkflowError('frame_integrity')
        data = read(store.content_root, f"{source['id']}/frames/{sha}.jpg")
        if digest(data) != sha: raise WorkflowError('frame_integrity')
        files[f'frames/{sha}.jpg'] = data
    return files

class EditableExport:
    def __init__(self, workflow_config, classification_config=None, config=None):
        self.config = _validate(config) if config is not None else load_obsidian_config()
        self.store = make_store(workflow_config)
        self.classification = ClassificationStore(self.store, classification_config)

    def _snapshot(self, sid):
        with self.store._tx() as c:
            source = self.store._row(c, 'sources', sid)
            if source['deleted']: raise WorkflowError('source_deleted')
            if not source['current_version_id']: raise WorkflowError('version_not_found')
            version = self.store._row(c, 'versions', source['current_version_id'])
            metadata = self.classification.snapshot(sid, connection=c)
            if self.store.content_root:
                from .content_storage import verify
                verify(self.store, sid, connection=c)
            return source, version, metadata

    def _note(self, source, version, metadata):
        fields = dict(pkb_format='pkb-obsidian-v1', note_id=source['id'], source_id=source['id'],
                      base_version_id=version['id'], base_content_sha256=version['content_sha256'],
                      title=version['result']['title'], classification_revision=metadata['revision'],
                      topic_ids=[x['id'] for x in metadata['topics']], tag_ids=[x['id'] for x in metadata['tags']])
        note = ('---\n' + ''.join(k + ': ' + json.dumps(v, ensure_ascii=False) + '\n' for k, v in fields.items()) + '---\n\n' + version['result']['notes']).encode('utf8')
        if len(note) > self.config['max_note_bytes']: raise WorkflowError('note_too_large')
        return note

    def export_note(self, sid):
        source, version, metadata = self._snapshot(sid)
        return self._note(source, version, metadata), source['id']+'.md'

    def export_zip(self, sid):
        source, version, metadata = self._snapshot(sid)
        files = readonly_files(self.store, source, version)
        manifest = dict(pkb_format='pkb-obsidian-v1', source_id=sid, base_version_id=version['id'],
                        note='note.md', files={k: hashlib.sha256(v).hexdigest() for k,v in files.items()})
        links = '\n'.join(f'- [{name}]({name})' for name in sorted(files))
        files.update({'note.md': self._note(source, version, metadata), 'manifest.json': encoded(manifest),
                      'README.md': ('# Obsidian export\n\nEdit note.md only. Evidence and frames are read-only.\n\n' + links + '\n').encode('utf8')})
        if len(files) > self.config['max_members'] or sum(map(len, files.values())) > self.config['max_uncompressed_bytes']:
            raise WorkflowError('export_too_large')
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items(): z.writestr(name, data)
        if out.tell() > self.config['max_input_bytes']: raise WorkflowError('export_too_large')
        return out.getvalue(), 'obsidian-'+sid+'.zip'

