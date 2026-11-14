"""Persistent video stage primitives. Live orchestration is provided separately."""
import hashlib
import json
import math
import sqlite3
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from contextlib import closing
from .workflow import ROOT, make_store
from .workflow_store import ASR_UPLOAD_STAGES, ASR_UPLOAD_TASK_STAGES, WorkflowError
from .video_journal import VideoJournal, is_chat_stage
from tools.api_smoke import reserve
from .asr_storage import PreparedAudio, StorageError, create_storage
from .video_services import ProviderError

DEFAULT_CHAT_TIMEOUT_RETRIES = 1


def _positive(value):
    if isinstance(value, bool): raise ValueError()
    n = Decimal(str(value))
    if not n.is_finite() or n <= 0: raise ValueError()
    return n


def _legacy_text_prompt(strategy):
    if 'legacy_text_prompt' not in strategy:
        return None
    legacy = strategy['legacy_text_prompt']
    if not isinstance(legacy, dict) or not isinstance(legacy.get('value'), str) or not legacy['value'].strip():
        raise ValueError('invalid legacy prompt')
    return legacy['value']


def _bind_strategy(journal, task_id, token, config, keys):
    """Keep the prompt of a previously bound task when the full strategy still matches."""
    strategy = dict(config['strategy'])
    old_prompt = _legacy_text_prompt(strategy)
    strategy.pop('legacy_text_prompt', None)
    config['strategy'] = strategy
    inputs = {key: config[key] for key in keys}
    if 'storage' in inputs:
        # These transport limits do not change the submitted audio or results.
        timeout_options = {'policy_timeout_seconds', 'policy_timeout_seconds说明',
                           'upload_timeout_seconds', 'upload_timeout_seconds说明'}
        inputs['storage'] = {key: value for key, value in inputs['storage'].items() if key not in timeout_options}
    fingerprint = _digest(inputs)
    compatible = []
    if old_prompt is not None:
        compatible.append({**strategy, 'text_system_prompt': old_prompt})
    old_vision_limit = config.get('legacy_vision_max_tokens') if 'storage' in keys else None
    if old_vision_limit is not None:
        compatible.extend({**candidate, 'vision_max_tokens': old_vision_limit}
                          for candidate in [strategy, *compatible])
    alternatives = {_digest({**inputs, 'strategy': candidate}): candidate for candidate in compatible}
    bound = journal.bind(task_id, token, fingerprint, *alternatives)
    config['strategy'] = alternatives.get(bound, strategy)
    return bound


def load_pipeline_config(path=None):
    try:
        with open(path or ROOT / 'config/video-pipeline.json', encoding='utf-8-sig') as f: config = json.load(f)
        for key in ('strategy', 'models', 'storage'):
            name = config.pop(key + '_file')
            if not isinstance(name, str) or not name.strip(): raise ValueError()
            with open(ROOT / name, encoding='utf-8-sig') as f: config[key] = json.load(f)
            if not isinstance(config[key], dict): raise ValueError()
        b = config['budget']
        if not isinstance(b['ledger'], str) or not b['ledger'].strip(): raise ValueError()
        if _positive(b['research_limit']) > 100 or _positive(b['run_limit']) > _positive(b['research_limit']): raise ValueError()
        for key in ('poll_seconds', 'poll_timeout', 'heartbeat_seconds'): _positive(config[key])
        for value in [config['poll_seconds'], config['poll_timeout'], config['heartbeat_seconds'], *config['resources'].values()]:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0: raise ValueError()
        for value in (config['transport']['response_max_bytes'], config['resources']['ffmpeg_threads'], config['resources']['filter_threads'], config['vision_input_token_bound']):
            if type(value) is not int or value <= 0: raise ValueError()
        if config['poll_seconds'] > config['poll_timeout']: raise ValueError()
        if config['default_profile'] not in config['strategy']['profiles']: raise ValueError()
        _legacy_text_prompt(config['strategy'])
        if 'legacy_vision_max_tokens' in config:
            value = config['legacy_vision_max_tokens']
            if type(value) is not int or value <= 0: raise ValueError()
        t = config['transport']
        retries = config.setdefault('chat_timeout_retries', DEFAULT_CHAT_TIMEOUT_RETRIES)
        if type(retries) is not int or retries < 0:
            raise ValueError()
        if not isinstance(t['allowed_api_hosts'], list) or not t['allowed_api_hosts'] or any(not isinstance(h, str) or not h for h in t['allowed_api_hosts']): raise ValueError()
        if not isinstance(t['allowed_oss_suffix'], str) or not t['allowed_oss_suffix']: raise ValueError()
        for k in ('request_timeout_seconds','response_max_bytes'): _positive(t[k])
        for k in ('ffmpeg_threads','filter_threads','min_free_bytes','min_available_bytes','max_host_used_bytes','sample_interval_seconds','terminate_grace_seconds'): _positive(config['resources'][k])
        for k in ('text','vision'):
            if not isinstance(config['prices'][k], list) or len(config['prices'][k]) != 2: raise ValueError()
            for v in config['prices'][k]: _positive(v)
        _positive(config['prices']['asr_per_second'])
        if not isinstance(config['models']['models'], dict) or not isinstance(config['storage']['backend'], str): raise ValueError()
        return config
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation, OverflowError, AttributeError):
        raise WorkflowError('invalid_pipeline_config') from None


def video_status(workflow_config, pipeline_config, task_id):
    store = make_store(workflow_config)
    task = store.get_task(task_id)
    journal = VideoJournal(store)
    return {'task_id': task_id, 'status': task['status'], 'stages': [{k: row[k] for k in ('name','status','result_sha256')} for row in journal.list_stages(task_id)], 'assets': [{k: a[k] for k in ('asset_id','backend','status')} for a in journal.assets(task_id)]}


def paid_stage(journal, task_id, token, name, input_sha256, amount, config, call, *, retry_attempt=None):
    """Execute a non-resumable paid stage once, preserving unknown submissions."""
    try:
        amount = _positive(amount)
        b = config['budget']
        if amount > _positive(b['run_limit']) or _positive(b['research_limit']) > 100: raise ValueError()
        journal.begin(task_id, token, name, input_sha256)
        stage = journal.stage(task_id, name)
        if stage['status'] == 'completed': return stage['result']
        expected = 'in_flight' if retry_attempt is not None else 'prepared'
        if stage['status'] != expected: raise WorkflowError('unknown_submission')
        ledger = ROOT / b['ledger']
        ledger.parent.mkdir(parents=True, exist_ok=True)
        request_id = _stage_request_id(task_id, name, retry_attempt)
        with closing(sqlite3.connect(ledger)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS reservations (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, amount TEXT NOT NULL)')
            existing = db.execute('SELECT run_id,amount FROM reservations WHERE request_id=?', (request_id,)).fetchone()
        if existing:
            if existing[0] != task_id or Decimal(existing[1]) != amount: raise WorkflowError('reservation_conflict')
        else:
            try: reserve(ledger, task_id, request_id, amount, b['run_limit'], b['research_limit'])
            except sqlite3.IntegrityError:
                with closing(sqlite3.connect(ledger)) as db: existing = db.execute('SELECT run_id,amount FROM reservations WHERE request_id=?', (request_id,)).fetchone()
                if not existing or existing[0] != task_id or Decimal(existing[1]) != amount: raise WorkflowError('reservation_conflict')
        if retry_attempt is None:
            journal.mark_started(task_id, token, name)
        else:
            journal.start_chat_retry(task_id, token, name, retry_attempt)
        result = call()
        journal.complete(task_id, token, name, result)
        return result
    except WorkflowError: raise
    except (ValueError, InvalidOperation): raise WorkflowError('budget_invalid_or_exceeded') from None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class _Heartbeat:
    def __init__(self, store, task, token, interval):
        self.store, self.task, self.token = store, task, token
        self.interval = min(float(interval), store.lease_seconds / 3)
        self.stop = threading.Event()
        self.error = None

    def check(self):
        if self.error: raise WorkflowError('invalid_lease')
        self.store.heartbeat(self.task, self.token)

    def __enter__(self):
        def loop():
            while not self.stop.wait(self.interval):
                try: self.check()
                except Exception:
                    self.error = True
                    break
        self.check()
        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=self.interval + self.store.busy_timeout_seconds + 1)


class _Owner:
    def __init__(self, journal, task, token, storage_config):
        self.journal, self.task, self.token = journal, task, token
        self.scope = {k: storage_config['managed_oss'][k] for k in ('bucket', 'endpoint', 'region', 'prefix')}

    def register(self, metadata):
        if metadata['scope'] != self.scope: raise WorkflowError('storage_scope_changed')
        self.journal.register_asset(self.task, self.token, metadata)

    def owns(self, asset):
        return any(a['asset_id'] == asset.asset_id and a['object_key'] == asset.object_key
                   and a['scope'] == self.scope and a['status'] == 'remote_terminal'
                   for a in self.journal.assets(self.task))

    def deleted(self, asset):
        if isinstance(asset, dict):
            self.journal.asset_rolled_back(self.task, self.token, asset['asset_id'])
        else:
            self.journal.mark_cleaned(asset.asset_id, 'deleted')


def _scope_storage(journal, task_id, token, config, secrets):
    owner = _Owner(journal, task_id, token, config) if config['backend'] == 'managed_oss' else None
    return create_storage(config, secrets, ownership=owner)


def _stage_request_id(task_id, name, attempt):
    base = task_id + ':' + name
    return base if attempt is None else base + ':retry:' + str(attempt)


def _chat_recovery(journal, tid, name, amount):
    attempt = journal.chat_attempt(tid, name)
    if attempt and attempt['response'] is not None:
        raw = attempt['response']
        if hashlib.sha256(raw.encode()).hexdigest() != attempt['response_sha256']:
            raise WorkflowError('stage_corrupt')
        return json.loads(raw), None
    if attempt and attempt['amount'] is not None and not attempt['started'] and Decimal(attempt['amount']) == amount:
        return None, attempt['attempt']
    raise WorkflowError('unknown_submission')


def _record_call(journal, tid, token, name, digest, amount, config, call, heartbeat, *, video_amounts=None):
    chat = is_chat_stage(name)
    retry_attempt = None
    attempt = 0
    manually_authorized = False
    if chat:
        journal.begin(tid, token, name, digest)
        stage = journal.stage(tid, name)
        if stage['status'] == 'in_flight':
            saved, retry_attempt = _chat_recovery(journal, tid, name, amount)
            if saved is not None:
                journal.complete(tid, token, name, saved)
                return saved
            attempt = retry_attempt
            manually_authorized = not journal.chat_attempt(tid, name)['automatic']

    def guarded():
        heartbeat.check()
        try:
            value = call()
        except Exception as exc:
            if chat:
                journal.record_chat_outcome(tid, name, attempt,
                    diagnostic=exc.code if isinstance(exc, ProviderError) else 'model_result_not_saved',
                    provider_request_id=exc.request_id if isinstance(exc, ProviderError) else None,
                    metrics=exc.metrics if isinstance(exc, ProviderError) else None)
            raise
        result = dict(value, reserved_upper_cny=str(amount), request_id=_stage_request_id(tid, name, retry_attempt))
        if result.get('estimated_cost_cny') is not None and Decimal(str(result['estimated_cost_cny'])) > amount:
            if chat:
                journal.record_chat_outcome(tid, name, attempt, diagnostic='observed_cost_exceeds_reservation',
                    provider_request_id=result.get('provider_request_id'), metrics=result.get('response_metrics'))
            raise WorkflowError('observed_cost_exceeds_reservation')
        if chat:
            journal.record_chat_outcome(tid, name, attempt, response=result,
                provider_request_id=result.get('provider_request_id'), metrics=result.get('response_metrics'))
        heartbeat.check()
        return result
    maximum = config.get('chat_timeout_retries', DEFAULT_CHAT_TIMEOUT_RETRIES)
    while True:
        try:
            result = paid_stage(journal, tid, token, name, digest, amount, config, guarded, retry_attempt=retry_attempt)
            if result.get('estimated_cost_cny') is not None and Decimal(str(result['estimated_cost_cny'])) > amount:
                raise WorkflowError('observed_cost_exceeds_reservation')
            return result
        except WorkflowError as exc:
            if exc.code != 'chat_response_available':
                raise
            saved, _ = _chat_recovery(journal, tid, name, amount)
            journal.complete(tid, token, name, saved)
            return saved
        except ProviderError as exc:
            if not chat or exc.code != 'provider_timeout' or not maximum or manually_authorized:
                raise
            heartbeat.check()
            if journal.automatic_retry_count(tid, name) >= maximum:
                raise
            _favorites_budget_preflight(journal.store, tid, video_amounts, extra=amount)
            _preflight(journal, tid, config, video_amounts, extra=amount)
            retry_attempt = journal.authorize_timeout_retry(tid, token, name, amount, maximum)
            if retry_attempt is None:
                raise
            attempt = retry_attempt


def _preflight(journal, tid, pc, amounts, retries=None, restored=(), *, extra=Decimal(0)):
    """Check the whole remaining batch, retaining every historical reservation."""
    ledger = ROOT / pc['budget']['ledger']
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS reservations (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, amount TEXT NOT NULL)')
        rows = db.execute('SELECT request_id,run_id,amount FROM reservations').fetchall()
    existing = {r[0]:r for r in rows}
    remaining = sum((value for name,value in amounts.items()
                     if name not in restored and tid + ':' + name not in existing), Decimal(0))
    remaining += sum((amounts[name] for name, attempt in (retries or {}).items()
                      if _stage_request_id(tid, name, attempt) not in existing), Decimal(0))
    total = sum((Decimal(r[2]) for r in rows), Decimal(0))
    run_total = sum((Decimal(r[2]) for r in rows if r[1]==tid), Decimal(0))
    if total + remaining + extra > Decimal(str(pc['budget']['research_limit'])) or run_total + remaining + extra > Decimal(str(pc['budget']['run_limit'])):
        raise WorkflowError('budget_invalid_or_exceeded')


def _favorites_budget_preflight(store, task_id, amounts, *, extra=Decimal(0)):
    """Enforce the durable per-video ceiling reserved by automatic dispatch."""
    with closing(sqlite3.connect(store.db_path)) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='favorites_conversion'").fetchone()
        row = db.execute('SELECT amount FROM favorites_conversion WHERE task_id=?', (task_id,)).fetchone() if exists else None
        if row is None:
            return
        has_attempts = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_chat_attempts'").fetchone()
        retry_amounts = db.execute('SELECT amount FROM video_chat_attempts WHERE task_id=? AND automatic=1',
                                   (task_id,)).fetchall() if has_attempts else []
    try:
        ceiling = Decimal(row[0])
        required = sum((Decimal(row[0]) for row in retry_amounts), sum(amounts.values(), extra))
        if not ceiling.is_finite() or ceiling <= 0 or not required.is_finite() or required > ceiling:
            raise WorkflowError('favorites_budget_exceeded')
    except (InvalidOperation, TypeError, ValueError):
        raise WorkflowError('favorites_budget_exceeded') from None


def run_video(*args, **kwargs):
    from .execution_guard import execution_guard
    with execution_guard(make_store(args[0] if args else kwargs["workflow_config"])):
        return _guarded_run_video(*args, **kwargs)

def _guarded_run_video(workflow_config, pipeline_config, secrets, *, task_id=None, resume=False,
              services=None, media=None, storage=None):
    """Process one explicitly selected imported video; unknown POSTs never repeat."""
    from .video_services import ProviderClient
    from .video_media import prepare_media
    from .workflow import _hash, _root
    pc = dict(pipeline_config)
    # Validate credentials before taking a lease or spending on any capability.
    if services is None:
        for kind in ('asr', 'vision', 'text'):
            spec = pc['models']['models'][kind]
            ref = pc['models']['providers'][spec['provider']]['api_key_env']
            if not isinstance(secrets.get(ref), str) or not secrets[ref].strip():
                raise WorkflowError('missing_model_credentials')
    # Constructor checks are local; invalid storage must not consume a model
    # reservation or strand a task in an apparent unknown submission state.
    if storage is None:
        try:
            create_storage(pc['storage'], secrets)
            if pc['storage']['backend'] == 'managed_oss':
                import importlib.util
                if importlib.util.find_spec('oss2') is None: raise StorageError('missing_sdk')
        except StorageError as exc:
            raise WorkflowError(exc.code) from None
    store = make_store(workflow_config)
    journal = VideoJournal(store)
    if task_id is None: raise WorkflowError('task_id_required')
    task = journal.resume_claim(task_id, 'video-resume') if resume else journal.claim_task(task_id, 'video-worker')
    token = task['lease_token']
    preparing_upload = False
    try:
        vision_limit = pc['strategy']['vision_max_tokens']
        fingerprint = _bind_strategy(journal, task_id, token, pc, ('models', 'strategy', 'storage', 'prices', 'default_profile'))
        legacy_upload = resume and journal.restore_legacy_upload(task_id, token)
        retries = {}
        restored = set()
        recovering_chat = False
        # Resolve all unknown requests before preparing media or uploading.
        for row in journal.list_stages(task_id):
            if row['status'] == 'in_flight' and row['name'] not in ASR_UPLOAD_STAGES and (row['name'] != 'asr_submit' or not row['remote_task_id']):
                name = row['name']
                if is_chat_stage(name):
                    recovering_chat = True
                    saved, attempt = _chat_recovery(journal, task_id, name,
                        Decimal(str(pc['strategy']['reserve_cny']['text' if name == 'text' else 'vision'])))
                    if saved is not None:
                        restored.add(name)
                    if attempt is not None:
                        retries[name] = attempt
                elif name != 'asr_result':
                    raise WorkflowError('unknown_submission')
        source = store.get_source(task['source_id'])
        with store._tx() as db:
            base = db.execute('SELECT base_version_id FROM video_reprocess WHERE task_id=?', (task_id,)).fetchone()
        if base and source['current_version_id'] != base[0] and not task['remote_task_id']:
            raise WorkflowError('version_conflict')
        root = _root(workflow_config).resolve()
        candidate = root / source['blob_relpath']
        blob = candidate.resolve()
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (candidate, *candidate.parents)) or not blob.is_relative_to(root) or not blob.is_file() or _hash(blob) != source['sha256']:
            raise WorkflowError('source_integrity')
        work = root / 'video-work' / task_id
        if any(p.is_symlink() for p in (work, *work.parents)): raise WorkflowError('invalid_work_path')
        if recovering_chat and not (work / 'media-manifest.json').is_file():
            raise WorkflowError('recovery_media_missing')
        work.mkdir(parents=True, exist_ok=True)
        # The manifest is validated against the bound strategy. Only new
        # provider calls use the current output limit.
        provider_config = {**pc, 'strategy': {**pc['strategy'], 'vision_max_tokens': vision_limit}}
        provider = services or ProviderClient(pc['models'], provider_config, secrets)
        with _Heartbeat(store, task_id, token, pc['heartbeat_seconds']) as beat:
            # Preserve the durable upload phase until a resumed upload starts.
            if not legacy_upload and not (resume and task['stage'] in ASR_UPLOAD_TASK_STAGES):
                store.checkpoint(task_id, token, 'preparing_video')
            material = (media or prepare_media)(blob, work, workflow_config, pc, heartbeat=beat.check)
            audio = Path(material['audio_path'])
            if not audio.resolve().is_relative_to(work) or not audio.is_file(): raise WorkflowError('invalid_audio_path')
            audio_hash = _hash(audio)
            audio_seconds = material['audio_seconds']
            if isinstance(audio_seconds, bool) or not isinstance(audio_seconds, (float, int)) or not math.isfinite(audio_seconds) or audio_seconds <= 0:
                raise WorkflowError('invalid_audio_duration')
            frames = material['frames']
            if not isinstance(frames, list) or not frames: raise WorkflowError('empty_frames')
            asr_price = Decimal(str(pc['prices']['asr_per_second']))
            asr_amount = max(Decimal(str(pc['strategy']['reserve_cny']['asr'])), Decimal(str(audio_seconds)) * asr_price)
            amounts = {'asr_submit':asr_amount, 'text':Decimal(str(pc['strategy']['reserve_cny']['text']))}
            amounts.update({'vision-' + str(f['index']):Decimal(str(pc['strategy']['reserve_cny']['vision'])) for f in frames})
            _favorites_budget_preflight(store, task_id, amounts)
            _preflight(journal, task_id, pc, amounts, retries, restored)
            voice_digest = _digest({'audio': audio_hash, 'model': pc['models']['models']['asr']})
            journal.begin(task_id, token, 'asr_submit', voice_digest)
            row = journal.stage(task_id, 'asr_submit')
            if row['status'] == 'in_flight':
                if not row['remote_task_id']: raise WorkflowError('unknown_submission')
                remote_id = row['remote_task_id']
                journal.complete(task_id, token, 'asr_submit', {'remote_task_id':remote_id,
                    'audio_seconds':audio_seconds, 'reserved_upper_cny':str(asr_amount),
                    'request_id':task_id + ':asr_submit'})
            elif row['status'] == 'completed':
                remote_id = row['result']['remote_task_id']
            else:
                from .asr_storage_temporary import TemporaryStorage

                def upload_progress(stage, completed):
                    beat.check()
                    journal.upload_progress(task_id, token, stage, voice_digest, completed)

                preparing_upload = True
                adapter = storage or _scope_storage(journal, task_id, token, pc['storage'], secrets)
                model = pc['models']['models']['asr']['model']
                if isinstance(adapter, TemporaryStorage):
                    asset = adapter.prepare(audio, model, on_stage=upload_progress)
                else:
                    upload_progress('asr_audio_upload', False)
                    asset = adapter.prepare(audio, model)
                    upload_progress('asr_audio_upload', True)
                if asset.backend == 'temporary':
                    journal.register_asset(task_id, token, dict(asset_id=asset.asset_id, backend='temporary',
                        object_key='', source_sha256=audio_hash, size_bytes=asset.size_bytes, model=asset.model,
                        expires_at=asset.expires_at, scope={}))
                beat.check()
                if asset.is_expired():
                    raise WorkflowError('audio_url_expired')
                preparing_upload = False

                def submit():
                    remote = provider.submit_asr(asset)
                    journal.save_remote(task_id, token, 'asr_submit', remote)
                    return {'remote_task_id': remote, 'audio_seconds': audio_seconds}
                submission = _record_call(journal, task_id, token, 'asr_submit', voice_digest, asr_amount, pc, submit, beat)
                remote_id = submission['remote_task_id']
            result_digest = _digest({'remote_id': remote_id, 'audio': audio_hash})
            journal.begin(task_id, token, 'asr_result', result_digest)
            row = journal.stage(task_id, 'asr_result')
            if row['status'] == 'completed':
                asr = row['result']
            else:
                if row['status'] == 'prepared': journal.mark_started(task_id, token, 'asr_result')
                start = time.monotonic()
                while True:
                    beat.check()
                    output = provider.query_asr(remote_id)
                    state = output.get('task_status')
                    if state == 'SUCCEEDED':
                        results = output.get('results', [])
                        if not results or results[0].get('subtask_status') != 'SUCCEEDED':
                            for a in journal.assets(task_id):
                                if a['status'] == 'registered': journal.asset_terminal(task_id, token, a['asset_id'])
                            journal.complete(task_id, token, 'asr_result', {'error':'asr_subtask_failed'})
                            raise WorkflowError('asr_subtask_failed')
                        asr = provider.download_asr(results[0]['transcription_url'], audio_seconds)
                        journal.complete(task_id, token, 'asr_result', asr)
                        break
                    if state not in ('PENDING', 'RUNNING'):
                        for a in journal.assets(task_id):
                            if a['status'] == 'registered': journal.asset_terminal(task_id, token, a['asset_id'])
                        journal.complete(task_id, token, 'asr_result', {'error': 'asr_remote_failed'})
                        raise WorkflowError('asr_remote_failed')
                    if time.monotonic() - start >= pc['poll_timeout']: raise WorkflowError('asr_pending')
                    beat.stop.wait(min(pc['poll_seconds'], max(0, pc['poll_timeout'] - (time.monotonic() - start))))
            if asr.get('error'): raise WorkflowError(asr['error'])
            for a in journal.assets(task_id):
                if a['status'] == 'registered': journal.asset_terminal(task_id, token, a['asset_id'])
            if base and store.get_source(task['source_id'])['current_version_id'] != base[0]:
                raise WorkflowError('version_conflict')
            visual, evidence = [], [dict(type='audio', **s) for s in asr['segments']]
            for frame in frames:
                beat.check()
                path = Path(frame['path'])
                if not path.resolve().is_relative_to(work) or _hash(path) != frame['sha256']: raise WorkflowError('frame_integrity')
                amount = Decimal(str(pc['strategy']['reserve_cny']['vision']))
                # Explicit upper token allowance for the configured image limits.
                upper = (Decimal(pc['vision_input_token_bound']) * Decimal(str(pc['prices']['vision'][0])) + Decimal(vision_limit) * Decimal(str(pc['prices']['vision'][1]))) / 1000000
                if amount < upper: raise WorkflowError('vision_reservation_too_small')
                name = 'vision-' + str(frame['index'])
                val = _record_call(journal, task_id, token, name, _digest({'frame':frame['sha256'], 'seconds':frame['seconds']}), amount, pc,
                                   lambda: provider.vision(path), beat, video_amounts=amounts)
                visual.append(f'## [{frame["seconds"]:.3f}s]\n' + val['content'])
                evidence.append({'type':'visual', 'seconds':frame['seconds'], 'text':val['content'], 'image_sha256':frame['sha256']})
            visual_text = '\n\n'.join(visual)
            body = '## 完整语音转录\n' + asr['text'] + '\n\n## 抽样画面材料\n' + visual_text
            amount = Decimal(str(pc['strategy']['reserve_cny']['text']))
            upper = (Decimal(len((body + source['original_name'] + pc['strategy']['text_system_prompt']).encode('utf8'))) * Decimal(str(pc['prices']['text'][0])) + Decimal(pc['strategy']['text_max_tokens']) * Decimal(str(pc['prices']['text'][1]))) / 1000000
            if upper > amount: raise WorkflowError('text_reservation_too_small')
            notes = _record_call(journal, task_id, token, 'text', _digest({'body':body, 'title':source['original_name']}), amount, pc,
                                 lambda: provider.summarize(body, source['original_name']), beat, video_amounts=amounts)
            result = dict(title=source['original_name'], body=body, transcript=asr['text'], visual=visual_text,
                summary=notes['structured']['summary'], notes=notes['structured']['notes'], evidence=evidence,
                provenance='provider', output_kind='machine_initial', scheme_id='video-pipeline', scheme_version=fingerprint,
                duration_seconds=material['duration_seconds'], frames=[{k:f[k] for k in ('index','seconds','sha256')} for f in frames])
            beat.check()
        version = store.finish(task_id, token, result)
    except Exception as exc:
        code = exc.code if isinstance(exc, (WorkflowError, StorageError, ProviderError)) else 'video_processing_failed'
        try: store.fail(task_id, token, code, needs_attention=preparing_upload)
        except WorkflowError: pass
        if code == 'version_conflict':
            try: cleanup_video(workflow_config, pc, secrets, task_id, storage=storage)
            except Exception: pass
        raise WorkflowError(code) from None
    # Cleanup failure must never erase or roll back a completed knowledge draft.
    try: cleanup_video(workflow_config, pc, secrets, task_id, storage=storage)
    except Exception: pass  # Durable remote_terminal records remain visible for retry.
    return version


def cleanup_video(*args, **kwargs):
    from .execution_guard import execution_guard
    with execution_guard(make_store(args[0] if args else kwargs["workflow_config"])):
        return _guarded_cleanup_video(*args, **kwargs)

def _guarded_cleanup_video(workflow_config, pipeline_config, secrets, task_id, *, storage=None):
    store = make_store(workflow_config)
    journal = VideoJournal(store)
    results = []
    with journal.cleanup_claim(task_id):
        for row in journal.assets(task_id):
            if row['status'] != 'remote_terminal':
                results.append({'asset_id':row['asset_id'], 'status':row['status']})
                continue
            if row['backend'] == 'temporary':
                journal.mark_cleaned(row['asset_id'], 'provider_managed')
                results.append({'asset_id':row['asset_id'], 'status':'provider_managed', 'deleted':False})
            else:
                cfg = pipeline_config['storage']
                if cfg['backend'] != 'managed_oss' or row['scope'] != {k:cfg['managed_oss'][k] for k in ('bucket','endpoint','region','prefix')}:
                    raise WorkflowError('storage_scope_changed')
                adapter = storage or _scope_storage(journal, task_id, None, cfg, secrets)
                asset = PreparedAudio(row['backend'], row['model'], row['asset_id'], row['source_sha256'], row['size_bytes'], row['expires_at'], '', row['object_key'])
                adapter.cleanup(asset)
                # Injected storage fakes need the same durable transition.
                if next(a for a in journal.assets(task_id) if a['asset_id']==row['asset_id'])['status']=='remote_terminal':
                    journal.mark_cleaned(row['asset_id'], 'deleted')
                results.append({'asset_id':row['asset_id'], 'status':'deleted', 'deleted':True})
        # Only the owned temporary WAV; keep frames, manifests, original and evidence.
        task = store._row(journal._cleanup[0], 'tasks', task_id)
        if (task['status'] == 'succeeded' or task['error_code'] == 'version_conflict') and results and all(r['status'] in ('deleted','provider_managed') for r in results):
            root = Path(workflow_config['data_dir']).resolve()
            audio = root / 'video-work' / task_id / 'audio.wav'
            if any(p.is_symlink() for p in (audio, *audio.parents)): raise WorkflowError('invalid_cleanup_path')
            if audio.exists():
                from .workflow import _hash
                if _hash(audio) not in {a['source_sha256'] for a in journal.assets(task_id)}: raise WorkflowError('audio_integrity')
                audio.unlink()
    return {'task_id':task_id, 'assets':results}
