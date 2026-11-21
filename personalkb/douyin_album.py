"""Download, verify, and quote Douyin image albums."""
import hashlib
import json
import os
import re
import uuid
from decimal import Decimal, ROUND_CEILING
from urllib.parse import parse_qsl, urlencode, urlsplit

from .douyin_http import download_stream
from .favorites_limits import image_limit
from .workflow import ROOT, _hash, _root
from .workflow_store import WorkflowError


def stage_amounts(pipeline_config):
    """Upper bound per model request in CNY."""
    try:
        strategy = pipeline_config['strategy']
        prices = pipeline_config['prices']
        vision_input = pipeline_config['vision_input_token_bound']
        vision_output = strategy['vision_max_tokens']
        text_input = pipeline_config['album_text_input_token_bound']
        text_output = strategy['text_max_tokens']
        if any(type(value) is not int or value <= 0 for value in (vision_input, vision_output, text_input, text_output)):
            raise ValueError()
        rates = [Decimal(str(value)) for kind in ('vision', 'text') for value in prices[kind]]
        if len(rates) != 4 or any(not value.is_finite() or value <= 0 for value in rates):
            raise ValueError()
        return {'vision': (Decimal(vision_input) * rates[0] + Decimal(vision_output) * rates[1]) / 1000000,
                'text': (Decimal(text_input) * rates[2] + Decimal(text_output) * rates[3]) / 1000000}
    except (KeyError, ValueError, TypeError, ArithmeticError):
        raise WorkflowError('invalid_album_config') from None


def quote(image_count, pipeline_config):
    """Return a CNY ceiling for all model calls, including timeout retries."""
    if type(image_count) is not int or image_count < 1:
        raise WorkflowError('invalid_album_image_count')
    retries = pipeline_config.get('chat_timeout_retries')
    if type(retries) is not int or retries < 0:
        raise WorkflowError('invalid_album_config')
    amounts = stage_amounts(pipeline_config)
    return ((amounts['vision'] * image_count + amounts['text']) * (1 + retries)).quantize(Decimal('0.01'), rounding=ROUND_CEILING)


def _image_mime(path):
    with path.open('rb') as stream:
        head = stream.read(16)
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    raise WorkflowError('album_invalid_image')


class DouyinAlbum:
    def __init__(self, service, *, downloader=download_stream, config=None):
        self.service = service
        self.store = service.store
        self.wc = service.wc
        self.downloader = downloader
        path = ROOT / service.webcfg.get('douyin_album_config', 'config/douyin-album.json')
        try:
            self.config = config or json.loads(path.read_text(encoding='utf-8-sig'))
            for key in ('max_images', 'max_image_bytes', 'max_album_bytes', 'album_text_input_token_bound'):
                if type(self.config[key]) is not int or self.config[key] <= 0:
                    raise ValueError()
            for key in ('vision_prompt', 'text_prompt_suffix'):
                if not isinstance(self.config[key], str) or not self.config[key].strip():
                    raise ValueError()
            hosts = self.config['media_hosts']
            if not isinstance(hosts, list) or not hosts or any(not isinstance(host, str) or not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', host) for host in hosts):
                raise ValueError()
            work_budgets = self.config.get('manual_work_budgets_cny', {})
            if not isinstance(work_budgets, dict) or any(
                not isinstance(work_id, str) or not re.fullmatch(r'[0-9]+', work_id)
                or not isinstance(amount, str) or not re.fullmatch(r'[0-9]+\.[0-9]{2}', amount)
                or Decimal(amount) <= 0 for work_id, amount in work_budgets.items()
            ):
                raise ValueError()
            self.manual_work_budgets = {work_id: Decimal(amount) for work_id, amount in work_budgets.items()}
            self.manual_work_image_limits = self.config.get('manual_work_image_limits', {})
            if not isinstance(self.manual_work_image_limits, dict) or any(
                work_id not in self.manual_work_budgets or type(limit) is not int or limit <= 0
                for work_id, limit in self.manual_work_image_limits.items()
            ):
                raise ValueError()
        except (OSError, KeyError, TypeError, ValueError, ArithmeticError):
            raise WorkflowError('invalid_album_config') from None

    def manual_work_budget(self, work_id):
        amount = self.manual_work_budgets.get(work_id)
        if amount is not None:
            return min(amount, Decimal(str(self.service.pc['budget']['research_limit'])))
        return None

    def _check_image_limit(self, work_id, image_count, extended_image_count):
        limit = image_limit(self.store, self.config['max_images'])
        if extended_image_count is not None:
            if image_count != extended_image_count:
                raise WorkflowError('favorites_price_changed')
            limit = self.manual_work_image_limits.get(work_id)
            if limit is None:
                raise WorkflowError('album_image_limit')
        if image_count > limit:
            raise WorkflowError('album_image_limit')

    def limit_details(self, image_count, *, work_id):
        max_images = image_limit(self.store, self.config['max_images'])
        manual_limit = self.manual_work_image_limits.get(work_id)
        estimate = quote(image_count, {**self.service.pc, **self.config})
        try:
            manual_quote = self.quote(image_count, work_id=work_id, manual=True, extended_image_count=image_count)
        except WorkflowError:
            manual_quote = None
        return dict(max_images=max_images, manual_max_images=manual_limit,
                    manual_quote_cny=str(manual_quote) if manual_quote is not None else None,
                    estimate_cny=str(estimate))

    def quote(self, image_count, *, work_id=None, manual=False, extended_image_count=None):
        if type(image_count) is not int or image_count < 1:
            raise WorkflowError('invalid_album_image_count')
        self._check_image_limit(work_id, image_count, extended_image_count if manual else None)
        if manual and extended_image_count is None and work_id in self.manual_work_image_limits:
            raise WorkflowError('album_single_import_required')
        amount = quote(image_count, {**self.service.pc, **self.config})
        if 'budget' in self.service.pc:
            limit = self.manual_work_budget(work_id) if manual else None
            if limit is None:
                limit = Decimal(str(self.service.pc['budget']['run_limit']))
            if amount > limit:
                raise WorkflowError('album_quote_over_run_budget')
        return amount

    def _root(self):
        root = _root(self.wc)
        albums = root / 'albums'
        if any(p.is_symlink() for p in (albums, root, *root.parents)):
            raise WorkflowError('invalid_data_path')
        albums.mkdir(parents=True, exist_ok=True)
        return root

    def _verified_image(self, root, image):
        try:
            path = root / image['blob_relpath']
            if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to((root / 'albums').resolve()):
                raise ValueError()
            if not path.is_file() or path.stat().st_size != image['size'] or _hash(path) != image['sha256']:
                raise ValueError()
            if _image_mime(path) != image['mime']:
                raise ValueError()
            return path
        except (KeyError, ValueError, OSError, TypeError):
            raise WorkflowError('source_integrity') from None

    def manifest(self, source_id):
        return self._manifest(self.store.get_source(source_id))

    def _manifest(self, source):
        if source['kind'] != 'douyin_album' or source['deleted']:
            raise WorkflowError('invalid_source')
        root = self._root()
        blob = root / source['blob_relpath']
        if any(p.is_symlink() for p in (blob, *blob.parents)) or not blob.resolve().is_relative_to(root.resolve()) or not blob.is_file() or _hash(blob) != source['sha256']:
            raise WorkflowError('source_integrity')
        try:
            manifest = json.loads(blob.read_text(encoding='utf-8'))
            if not isinstance(manifest['images'], list) or not manifest['images']:
                raise ValueError()
            return manifest
        except (OSError, ValueError, TypeError, KeyError):
            raise WorkflowError('source_integrity') from None

    def original_image(self, source_id, page):
        manifest = self.manifest(source_id)
        if type(page) is not int or not 1 <= page <= len(manifest['images']):
            raise WorkflowError('album_image_not_found')
        image = manifest['images'][page - 1]
        if image.get('index') != page:
            raise WorkflowError('source_integrity')
        return self._verified_image(self._root(), image), image['mime']

    def download(self, work_id, title, image_urls, description='', author='', *, extended_image_count=None):
        if not isinstance(work_id, str) or not re.fullmatch(r'[0-9]+', work_id):
            raise WorkflowError('invalid_share')
        if not isinstance(title, str) or not title.strip() or not isinstance(description, str) or not isinstance(author, str):
            raise WorkflowError('invalid_album_metadata')
        if not isinstance(image_urls, list) or not image_urls:
            raise WorkflowError('album_image_limit')
        self._check_image_limit(work_id, len(image_urls), extended_image_count)
        if any(not isinstance(url, str) or not url for url in image_urls):
            raise WorkflowError('invalid_album_metadata')
        source_name = f'douyin-{work_id}.album.json'
        with self.store._tx() as db:
            existing = db.execute('SELECT id,deleted FROM sources WHERE kind=? AND original_name=?', ('douyin_album', source_name)).fetchone()
            if existing:
                if existing['deleted']:
                    raise WorkflowError('source_deleted')
                task = db.execute('SELECT id FROM tasks WHERE source_id=? ORDER BY rowid LIMIT 1', (existing['id'],)).fetchone()
                db.execute('INSERT OR IGNORE INTO source_display_titles(source_id,title) VALUES (?,?)', (existing['id'], title))
                return {'source': self.store._row(db, 'sources', existing['id']), 'task': self.store._row(db, 'tasks', task['id']), 'duplicate': True}
        root = self._root()
        folder = root / 'albums' / work_id
        if folder.is_symlink():
            raise WorkflowError('invalid_data_path')
        folder.mkdir(parents=True, exist_ok=True)
        download_config = dict(self.service.douyin.cfg)
        download_config['max_download_bytes'] = self.config['max_image_bytes']
        download_config['media_hosts'] = self.config['media_hosts']
        download_config['download_chunk_bytes'] = min(download_config['download_chunk_bytes'], self.config['max_image_bytes'])
        download_config['min_free_bytes'] = max(download_config['min_free_bytes'], self.wc['min_free_bytes'])
        images = []
        total = 0
        for index, url in enumerate(image_urls, 1):
            # A renewed signature should not invalidate an already verified image.
            parts = urlsplit(url)
            query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                               if k.lower() not in ('x-expires', 'x-signature', 'expires', 'signature')])
            identity = parts._replace(query=query, fragment='').geturl()
            fingerprint = hashlib.sha256(identity.encode('utf-8')).hexdigest()
            checkpoint = folder / f'{index}-{fingerprint}.json'
            image = None
            if checkpoint.is_file() and not checkpoint.is_symlink():
                try:
                    candidate = json.loads(checkpoint.read_text(encoding='utf-8'))
                    self._verified_image(root, candidate)
                    image = candidate
                except (ValueError, OSError, WorkflowError):
                    image = None
            if image is None:
                temporary = folder / f'.{uuid.uuid4().hex}.tmp'
                try:
                    remaining = self.config['max_album_bytes'] - total
                    if remaining <= 0:
                        raise WorkflowError('album_size_limit')
                    download_config['max_download_bytes'] = min(self.config['max_image_bytes'], remaining)
                    download_config['download_chunk_bytes'] = min(download_config['download_chunk_bytes'], download_config['max_download_bytes'])
                    self.downloader(url, temporary, download_config)
                    mime = _image_mime(temporary)
                    digest = _hash(temporary)
                    size = temporary.stat().st_size
                    target = folder / digest
                    if target.exists():
                        if target.is_symlink() or _hash(target) != digest:
                            raise WorkflowError('source_integrity')
                    else:
                        os.replace(temporary, target)
                    image = {'index': index, 'blob_relpath': f'albums/{work_id}/{digest}', 'sha256': digest, 'mime': mime, 'size': size}
                    tmp_checkpoint = folder / f'.{uuid.uuid4().hex}.json'
                    try:
                        tmp_checkpoint.write_text(json.dumps(image), encoding='utf-8')
                        os.replace(tmp_checkpoint, checkpoint)
                    finally:
                        tmp_checkpoint.unlink(missing_ok=True)
                finally:
                    temporary.unlink(missing_ok=True)
            total += image['size']
            if total > self.config['max_album_bytes']:
                raise WorkflowError('album_size_limit')
            images.append(image)
        manifest = {'work_id': work_id, 'title': title, 'description': description, 'author': author, 'images': images}
        data = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        originals = root / 'originals'
        originals.mkdir(parents=True, exist_ok=True)
        target = originals / digest
        def install():
            if target.exists():
                if target.is_symlink() or _hash(target) != digest:
                    raise WorkflowError('source_integrity')
            else:
                temp = originals / f'.{uuid.uuid4().hex}.tmp'
                try:
                    temp.write_bytes(data)
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
        def no_duplicate(db):
            if db.execute('SELECT 1 FROM sources WHERE kind=? AND original_name=?', ('douyin_album', source_name)).fetchone():
                raise WorkflowError('album_import_conflict')
        result = self.store.import_source('douyin_album', digest, source_name, f'originals/{digest}', commit_guard=no_duplicate, install_blob=install)
        with self.store._tx() as db:
            db.execute('INSERT OR IGNORE INTO source_display_titles(source_id,title) VALUES (?,?)', (result['source']['id'], title))
        return result
