"""Local file ingestion and offline workflow; never fetches remote content."""
import hashlib
import codecs
import math
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    from personalkb.workflow_store import WorkflowError
    try:
        with open(path or ROOT / 'config/workflow.json', encoding='utf-8-sig') as f:
            c = json.load(f)
        if not isinstance(c, dict): raise ValueError()
        for k in ('data_dir', 'html_encoding', 'ffmpeg', 'scheme_id', 'scheme_version'):
            if not isinstance(c[k], str) or not c[k].strip() or '\x00' in c[k]: raise ValueError()
        for k in ('max_upload_bytes', 'max_html_bytes', 'min_free_bytes', 'quality_target', 'lease_seconds', 'max_attempts', 'busy_timeout_seconds', 'preview_chars', 'probe_timeout_seconds'):
            v = c[k]
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0: raise ValueError()
        for k in ('max_upload_bytes', 'max_html_bytes', 'max_attempts', 'preview_chars'):
            if not isinstance(c[k], int) or isinstance(c[k], bool) or c[k] <= 0: raise ValueError()
        if c['quality_target'] > 100 or c['lease_seconds'] <= 0 or c['probe_timeout_seconds'] <= 0: raise ValueError()
        if not codecs.lookup(c['html_encoding'])._is_text_encoding: raise ValueError()
        content=c.get('content', {'enabled': False, 'directory': 'knowledge'})
        if not isinstance(content, dict) or type(content.get('enabled')) is not bool or not isinstance(content.get('directory'), str): raise ValueError()
        directory=Path(content['directory'])
        if not content['directory'] or directory.is_absolute() or '..' in directory.parts or directory.drive: raise ValueError()
        c['content']=content
        data = ROOT / c['data_dir']
        if any(x.is_symlink() for x in (data, *data.parents)): raise ValueError()
        c['data_dir'] = str(data.resolve())
        return c
    except (OSError, ValueError, KeyError, TypeError, LookupError, OverflowError):
        raise WorkflowError('invalid_config') from None


def _hash(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def _root(config):
    from personalkb.workflow_store import WorkflowError
    root = Path(config['data_dir']).absolute()
    originals = root / 'originals'
    if any(x.is_symlink() for x in (originals, root, *root.parents)):
        raise WorkflowError('invalid_data_path')
    return root


def make_store(config):
    from personalkb.workflow_store import WorkflowStore
    root = _root(config)
    root.mkdir(parents=True, exist_ok=True)
    return WorkflowStore(root / 'workflow.sqlite3', quality_target=config['quality_target'],
                         lease_seconds=config['lease_seconds'], max_attempts=config['max_attempts'],
                         busy_timeout_seconds=config['busy_timeout_seconds'],
                         content_root=(root / config.get('content', {}).get('directory', 'knowledge')) if config.get('content', {}).get('enabled', False) else None, data_root=root)


def import_file(config, path, rights_confirmed=False, *, commit_guard=None):
    from personalkb.workflow_store import WorkflowError
    if rights_confirmed is not True:
        raise WorkflowError('rights_required')
    p = Path(path).absolute()
    if any(x.is_symlink() for x in (p, *p.parents)) or not p.is_file():
        raise WorkflowError('invalid_file')
    size = p.stat().st_size
    if size <= 0 or size > config['max_upload_bytes'] or (p.suffix.lower() in ('.html', '.htm') and size > config['max_html_bytes']):
        raise WorkflowError('invalid_size')
    suffix = p.suffix.lower()
    if suffix not in ('.html', '.htm', '.mp4'):
        raise WorkflowError('unsupported_format')
    root = _root(config)
    originals = root / 'originals'
    originals.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free - size < config['min_free_bytes']:
        raise WorkflowError('disk_low')
    temp = originals / ('.' + uuid.uuid4().hex + '.tmp')
    h = hashlib.sha256()
    try:
        with p.open('rb') as src, temp.open('xb') as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                if dst.tell() + len(chunk) > size: raise WorkflowError('file_changed')
                h.update(chunk)
                dst.write(chunk)
        if temp.stat().st_size != size:
            raise WorkflowError('file_changed')
        if suffix == '.mp4':
            with temp.open('rb') as f:
                if f.read(8)[4:8] != b'ftyp':
                    raise WorkflowError('invalid_media')
            exe = shutil.which(config['ffmpeg'])
            if not exe:
                raise WorkflowError('media_tool_missing')
            result = subprocess.run([exe, '-hide_banner', '-i', str(temp)], capture_output=True,
                                    timeout=config['probe_timeout_seconds'])
            if not re.search(rb'Stream.*Video:', result.stderr):
                raise WorkflowError('invalid_media')
            kind = 'video'
        else:
            text = temp.read_text(encoding=config['html_encoding'])
            if not re.search(r'<(?:html|body|main)\b', text, re.I):
                raise WorkflowError('invalid_html')
            kind = 'html'
        digest = h.hexdigest()
        target = originals / digest
        if target.exists():
            if target.is_symlink() or not target.is_file() or _hash(target) != digest:
                raise WorkflowError('source_integrity')
        else:
            os.replace(temp, target)
        return make_store(config).import_source(kind, digest, p.name, 'originals/' + digest, commit_guard=commit_guard)
    finally:
        temp.unlink(missing_ok=True)

class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
        self.title = []
        self.in_title = False
        self.warnings = set()

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'template', 'svg'):
            self.skip += 1
            if tag == 'script': self.warnings.add('JavaScript 动态内容未提取')
        if tag == 'title': self.in_title = True
        if tag in ('img', 'svg', 'canvas'): self.warnings.add('图片或图表未提取')
        if tag in ('math',): self.warnings.add('公式结构未完整提取')
        if not self.skip and tag in ('p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n')
        if not self.skip and tag in ('td', 'th'): self.parts.append(' | ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template', 'svg') and self.skip: self.skip -= 1
        if tag == 'title': self.in_title = False
        if not self.skip and tag in ('tr', 'p', 'li'): self.parts.append('\n')

    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        elif not self.skip: self.parts.append(data)


def run_once(*args, **kwargs):
    from .execution_guard import execution_guard
    with execution_guard(make_store(args[0] if args else kwargs["config"])):
        return _guarded_run_once(*args, **kwargs)

def _guarded_run_once(config, worker_id='local', bundle_path=None, task_id=None):
    from personalkb.workflow_store import WorkflowError
    store = make_store(config)
    task = store.claim(worker_id) if task_id is None else store.claim_specific(task_id, worker_id)
    if task is None: return None
    tid, token = task['id'], task['lease_token']
    try:
        store.checkpoint(tid, token, 'verifying_source')
        source = store.get_source(task['source_id'])
        root = _root(config).resolve()
        blob = (root / source['blob_relpath']).resolve()
        if not blob.is_relative_to(root) or _hash(blob) != source['sha256']:
            raise WorkflowError('source_integrity')
        if source['kind'] == 'html':
            store.checkpoint(tid, token, 'extracting_html')
            parser = _HTML()
            parser.feed(blob.read_text(encoding=config['html_encoding']))
            body = ''.join(parser.parts).strip()
            if not body: raise WorkflowError('empty_output')
            warnings = sorted(parser.warnings | {'外链资源未获取', '图片与公式可能未完整提取'})
            result = dict(title=''.join(parser.title).strip() or source['original_name'], body=body,
                          summary='正文预览：' + body[:config['preview_chars']], notes=body, warnings=warnings,
                          evidence=[{'text': body}], provenance='local_extraction',
                          scheme_id=config['scheme_id'], scheme_version=config['scheme_version'], output_kind='machine_initial')
        else:
            store.checkpoint(tid, token, 'loading_provider_result')
            if not bundle_path: raise WorkflowError('video_bundle_required')
            from tools.personal_review import FIELDS
            with open(bundle_path, encoding='utf-8-sig') as f: bundle = json.load(f)
            items = bundle.get('items', []) if isinstance(bundle, dict) else []
            matches = [x for x in items if isinstance(x, dict) and x.get('source_sha256') == source['sha256']]
            if len(matches) != 1: raise WorkflowError('invalid_bundle')
            item = matches[0]
            required = ('id', 'source_path', 'source_sha256', 'scheme_id', 'scheme_version', 'run_id', 'output_version', 'transcript', 'visual', 'body', 'summary', 'notes')
            if set(item) != FIELDS or any(not isinstance(item.get(k), str) or not item[k].strip() for k in required) or item['status'] != 'completed' or item['provenance'] != 'provider' or item['output_kind'] != 'machine_initial':
                raise WorkflowError('invalid_bundle')
            for key in ('duration_seconds', 'cost_cny'):
                value = item[key]
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0): raise WorkflowError('invalid_bundle')
            if item['duration_seconds'] is not None and item['duration_seconds'] <= 0: raise WorkflowError('invalid_bundle')
            result = dict(title=source['original_name'], body=item['body'], summary=item['summary'], notes=item['notes'],
                          transcript=item['transcript'], visual=item['visual'], evidence=[{'type': 'audio', 'locator': 'transcript', 'text': item['transcript']}, {'type': 'visual', 'locator': 'visual', 'text': item['visual']}],
                          provenance='provider', scheme_id=item['scheme_id'], scheme_version=item['scheme_version'], output_kind='machine_initial', provider_item=item)
        return store.finish(tid, token, result)
    except Exception as exc:
        code = exc.code if isinstance(exc, WorkflowError) else 'processing_failed'
        try:
            store.fail(tid, token, code)
        except WorkflowError as failure:
            code = failure.code
        return {'task_id': tid, 'error': code}


def export_version(config, version_id, output_dir):
    from personalkb.workflow_store import WorkflowError
    store = make_store(config)
    version = store.get_version(version_id)
    raw = json.dumps(version['result'], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if hashlib.sha256(raw.encode()).hexdigest() != version['content_sha256']:
        raise WorkflowError('version_integrity')
    root = _root(config).resolve()
    out = Path(output_dir).resolve()
    if not out.is_relative_to(root): raise WorkflowError('invalid_output_path')
    out.mkdir(parents=True, exist_ok=True)
    target = out / (version['id'] + '.md')
    content = render_markdown(store, version)
    temp = out / ('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as f: f.write(content.encode('utf8'))
        os.link(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return {'path': str(target), 'version_id': version['id'], 'content_sha256': version['content_sha256']}


def render_markdown(store, version):
    """Render the same version and review state for each export surface."""
    from personalkb.workflow_store import WorkflowError
    raw = json.dumps(version['result'], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if hashlib.sha256(raw.encode()).hexdigest() != version['content_sha256']:
        raise WorkflowError('version_integrity')
    source = store.get_source(version['source_id'])
    if source['deleted']: raise WorkflowError('source_deleted')
    from .content_storage import render
    approved = any(x['id'] == source['id'] and x['current_version_id'] == version['id'] for x in store.eligible_sources())
    from .classification import ClassificationStore
    classification=ClassificationStore(store).snapshot(source['id'])
    return render(source, version, 'approved' if approved else 'draft_or_inactive', classification=classification)
