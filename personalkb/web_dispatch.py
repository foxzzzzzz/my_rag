"""Persisted, explicit browser processing requests; no implicit paid scans."""
import os
import json
import re
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from .douyin_album_processing import ALBUM_TEXT_RETRY_MODE, album_text_retry_plan
from .video_services import SUMMARY_FORMAT_ERRORS
from .workflow_store import ASR_UPLOAD_STAGES, WorkflowError
from .video_journal import initialize_chat_attempts, is_chat_stage, legacy_upload_interruption
from .video_recovery import (PARTIAL_MEDIA_ERRORS, TERMINAL_ASR_ERRORS, can_rebuild_media, can_use_visual_only,
                             media_workspace, terminal_asr_stage)
from .workflow import ROOT, _root

VIDEO_RECOVERY_MODES = ('visual-only', 'rebuild-media')
MODEL_RECOVERY_DISPATCH_MODES = ('recover-model', 'recover-album-text')
FAVORITES_REAUTHORIZE_MODE = 'reauthorize-favorites'
HARD_VIDEO_FAILURES = frozenset({'invalid_frame', 'empty_frames', 'media_cache_changed', 'media_workdir_unverified',
                                'media_missing_duration', 'media_missing_video', 'media_video_timeline_invalid',
                                'invalid_media_duration', 'audio_not_full_length', 'source_integrity'})


def task_stages(connection, task_id):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_stages'").fetchone():
        return []
    return connection.execute('SELECT name,status,remote_task_id FROM video_stages WHERE task_id=?', (task_id,)).fetchall()


def has_unknown_submission(task, stages, *, legacy_upload=False):
    if legacy_upload:
        return False
    return task['error_code'] == 'unknown_submission' or any(
        stage['status'] == 'in_flight' and stage['name'] not in (*ASR_UPLOAD_STAGES, 'asr_result')
        and not (stage['name'] == 'asr_submit' and stage['remote_task_id'])
        for stage in stages
    )


def task_can_archive(status, dispatch_state):
    return status in ('succeeded', 'failed', 'cancelled', 'needs_attention') and dispatch_state not in ('pending', 'working')


def task_is_archived(connection, task_id):
    return connection.execute('SELECT 1 FROM web_task_archive WHERE task_id=?', (task_id,)).fetchone() is not None


class WebDispatcher:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.config = service.webcfg
        self.stop_event = threading.Event()
        self.thread = None
        self.active = None
        with self.store._tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS web_dispatch (task_id TEXT PRIMARY KEY, mode TEXT NOT NULL, state TEXT NOT NULL, requested REAL NOT NULL, claimed REAL, owner TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS web_task_archive (task_id TEXT PRIMARY KEY)')
            c.execute("""CREATE TABLE IF NOT EXISTS favorites_video_reauthorizations (
                request_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, previous_cny TEXT NOT NULL,
                required_cny TEXT NOT NULL, amount_cny TEXT NOT NULL, created REAL NOT NULL)""")
            if 'error_code' not in {r[1] for r in c.execute('PRAGMA table_info(web_dispatch)')}:
                c.execute('ALTER TABLE web_dispatch ADD COLUMN error_code TEXT')
            if 'processing_mode' not in {r[1] for r in c.execute('PRAGMA table_info(web_dispatch)')}:
                c.execute("ALTER TABLE web_dispatch ADD COLUMN processing_mode TEXT NOT NULL DEFAULT 'preview'")
            initialize_chat_attempts(c)

    def favorites_reauthorization(self, c, task):
        if (task['status'] != 'failed' or task['error_code'] != 'favorites_budget_exceeded'
                or task_is_archived(c, task['id'])):
            return None
        source = self.store._row(c, 'sources', task['source_id'])
        if source['deleted'] or source['kind'] not in ('video', 'mp4'):
            return None
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='favorites_conversion' AND type='table'").fetchone():
            return None
        row = c.execute('SELECT amount FROM favorites_conversion WHERE task_id=?', (task['id'],)).fetchone()
        if not row:
            return None
        quote = {'authorized_cny': row['amount'], 'required_cny': None}
        if (not self.config['live_video_enabled'] or task['stage'] != 'preparing_video'
                or task['attempts'] >= self.store.max_attempts or task['external_started']
                or task_stages(c, task['id'])
                or c.execute('SELECT 1 FROM video_chat_attempts WHERE task_id=?', (task['id'],)).fetchone()
                or c.execute("SELECT 1 FROM web_dispatch WHERE task_id=? AND state IN ('pending','working')",
                             (task['id'],)).fetchone()
                or c.execute("""SELECT 1 FROM tasks WHERE source_id=? AND id<>? AND
                    status IN ('queued','running','needs_attention')""", (task['source_id'], task['id'])).fetchone()):
            return {**quote, 'blocked_reason': 'favorites_reauthorization_unavailable'}
        manifest = media_workspace(_root(self.service.wc), task['id']) / 'media-manifest.json'
        media = self.store.data_root / source['blob_relpath']
        from .video_pipeline import video_reservation_amounts, video_strategy_for_fingerprint
        has_runs = c.execute("SELECT 1 FROM sqlite_master WHERE name='video_runs' AND type='table'").fetchone()
        bound = c.execute('SELECT fingerprint FROM video_runs WHERE task_id=?', (task['id'],)).fetchone() if has_runs else None
        strategy = video_strategy_for_fingerprint(self.service.pc, bound['fingerprint']) if bound else None
        if strategy is None:
            return {**quote, 'blocked_reason': 'favorites_reauthorization_strategy_changed'}
        video_config = {**self.service.pc, 'strategy': strategy}
        try:
            if any(path.is_symlink() for path in (manifest, *manifest.parents)) or not media.is_file():
                raise ValueError()
            data = json.loads(manifest.read_text(encoding='utf-8'))
            frames = [frame['index'] for frame in data['frames']]
            seconds = Decimal(str(data['audio_seconds']))
            has_audio = data['audio'] is not None
            assets = [*data['frames'], data['audio']] if has_audio else data['frames']
            if (not frames or any(type(index) is not int for index in frames)
                    or frames != list(range(len(frames))) or not seconds.is_finite()
                    or (seconds <= 0 if has_audio else seconds != 0)):
                raise ValueError()
            for asset in assets:
                name = asset['file']
                path = manifest.parent / name
                if path.parent != manifest.parent or path.is_symlink() or not path.is_file():
                    raise ValueError()
            required = sum(video_reservation_amounts(video_config, frames, seconds, has_audio=has_audio).values())
            required = required.quantize(Decimal('.01'), rounding=ROUND_CEILING)
        except (OSError, KeyError, TypeError, ValueError, InvalidOperation):
            return {**quote, 'blocked_reason': 'favorites_reauthorization_media_unavailable'}
        quote['required_cny'] = format(required, '.2f')
        available = self._favorites_available_budget()
        quote['available_cny'] = format(available, 'f')
        if required > available:
            quote['blocked_reason'] = 'budget_invalid_or_exceeded'
        return quote

    def _favorites_available_budget(self):
        from .model_budget import budget_snapshot
        budget = self.service.pc['budget']
        overview = budget_snapshot(ROOT / budget['ledger'], budget['research_limit'])
        return min(Decimal(str(budget['run_limit'])), Decimal(overview['available_cny']))

    def reauthorize_favorites(self, task_id, payload):
        if payload.get('allow_paid') is not True:
            raise WorkflowError('paid_consent_required')
        value = payload.get('amount_cny')
        request_id = payload.get('request_id')
        if (not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', value)
                or not isinstance(request_id, str)):
            raise WorkflowError('invalid_request')
        try:
            request_id = uuid.UUID(request_id).hex
            amount = Decimal(value).quantize(Decimal('.01'))
        except (ValueError, InvalidOperation):
            raise WorkflowError('invalid_request') from None
        previous_amount = payload.get('expected_ceiling_cny')
        required_amount = payload.get('expected_required_cny')
        with self.store._tx() as c:
            task = self.store._row(c, 'tasks', task_id)
            prior = c.execute('SELECT * FROM favorites_video_reauthorizations WHERE request_id=?',
                              (request_id,)).fetchone()
            if prior:
                if (prior['task_id'], prior['previous_cny'], prior['required_cny'], Decimal(prior['amount_cny'])) != (
                        task_id, previous_amount, required_amount, amount):
                    raise WorkflowError('favorites_reauthorization_conflict')
                dispatch = c.execute('SELECT state FROM web_dispatch WHERE task_id=?', (task_id,)).fetchone()
                return {'task_id': task_id, 'dispatch_state': dispatch['state'] if dispatch else None, 'duplicate': True}
            quote = self.favorites_reauthorization(c, task)
            if not quote or quote['authorized_cny'] != previous_amount:
                raise WorkflowError('favorites_reauthorization_conflict')
            if quote.get('blocked_reason'):
                raise WorkflowError(quote['blocked_reason'])
            if quote['required_cny'] != required_amount:
                raise WorkflowError('favorites_reauthorization_conflict')
            if amount < Decimal(required_amount):
                raise WorkflowError('favorites_budget_exceeded')
            if amount > self._favorites_available_budget():
                raise WorkflowError('budget_invalid_or_exceeded')
            now = time.time()
            c.execute('INSERT INTO favorites_video_reauthorizations VALUES (?,?,?,?,?,?)',
                      (request_id, task_id, previous_amount, required_amount, str(amount), now))
            c.execute('UPDATE favorites_conversion SET amount=? WHERE task_id=?', (str(amount), task_id))
            c.execute("UPDATE favorites_queue SET status='conversion_queued' WHERE task_id=?", (task_id,))
            c.execute("UPDATE tasks SET status='queued',error_code=NULL WHERE id=?", (task_id,))
            c.execute("""INSERT INTO web_dispatch(task_id,mode,state,requested,processing_mode)
                VALUES (?,?,'pending',?,'preview') ON CONFLICT(task_id) DO UPDATE SET
                    mode=excluded.mode,state=excluded.state,requested=excluded.requested,
                    claimed=NULL,owner=NULL,error_code=NULL""", (task_id, FAVORITES_REAUTHORIZE_MODE, now))
            return {'task_id': task_id, 'dispatch_state': 'pending', 'duplicate': False}

    def video_failure(self, c, task, stages):
        reason = task['error_code']
        if task['status'] == 'needs_attention':
            terminal = terminal_asr_stage(c, task['id'], stages)
            if terminal:
                failure = {'failure_stage': 'asr_result', 'resume_blocked_reason': terminal['error']}
                if terminal['provider_code']:
                    failure['asr_provider_code'] = terminal['provider_code']
                if can_use_visual_only(task, stages, terminal['error']):
                    attempt = {'mode': 'visual-only'}
                    work = media_workspace(_root(self.service.wc), task['id'])
                    try:
                        manifest = work / 'media-manifest.json'
                        if not any(p.is_symlink() for p in (manifest, *manifest.parents)):
                            count = len(json.loads(manifest.read_text(encoding='utf8'))['frames'])
                            price = self.service.pc['strategy']['reserve_cny']
                            if count:
                                attempt['amount_cny'] = format(Decimal(str(price['text'])) + count * Decimal(str(price['vision'])), 'f')
                    except (OSError, ValueError, KeyError, TypeError, InvalidOperation):
                        pass
                    failure['video_recovery'] = attempt
                return failure
            return ({'failure_stage': 'asr_result', 'resume_blocked_reason': reason}
                    if reason in TERMINAL_ASR_ERRORS else {})

        if task['status'] not in ('failed', 'cancelled'):
            return {}
        failure = {}
        if reason in PARTIAL_MEDIA_ERRORS and task['stage'] in ('preparing_video', 'rebuilding_media'):
            work = media_workspace(_root(self.service.wc), task['id'])
            if can_rebuild_media(task, stages, work):
                failure.update(failure_stage=task['stage'], failure_code='media_workdir_unverified', retry_blocked_reason='media_workdir_unverified',
                               video_recovery={'mode': 'rebuild-media'})
        if reason in HARD_VIDEO_FAILURES:
            failure.setdefault('retry_blocked_reason', reason)
            failure.setdefault('failure_stage', task['stage'])
        return failure

    def recover_video(self, task_id, mode, *, allow_paid=False):
        if mode not in VIDEO_RECOVERY_MODES:
            raise WorkflowError('invalid_request')
        if allow_paid is not True:
            raise WorkflowError('paid_consent_required')
        if not self.config['live_video_enabled']:
            raise WorkflowError('video_disabled')
        with self.store._tx() as c:
            task = self.store._row(c, 'tasks', task_id)
            source = self.store._row(c, 'sources', task['source_id'])
            if source['deleted']:
                raise WorkflowError('source_deleted')
            if task_is_archived(c, task_id):
                raise WorkflowError('task_archived')
            if source['kind'] not in ('video', 'mp4'):
                raise WorkflowError('video_recovery_conflict')
            old = c.execute('SELECT mode,state FROM web_dispatch WHERE task_id=?', (task_id,)).fetchone()
            if old and old['state'] in ('pending', 'working'):
                if old['mode'] != mode:
                    raise WorkflowError('dispatch_conflict')
                return {'task_id': task_id, 'dispatch_state': old['state'], 'duplicate': True}
            recovery = self.video_failure(c, task, task_stages(c, task_id)).get('video_recovery')
            if not recovery or recovery['mode'] != mode:
                raise WorkflowError('video_recovery_conflict')
            if c.execute("""SELECT 1 FROM tasks WHERE source_id=? AND id<>? AND
                (status IN ('queued','running') OR (status='needs_attention' AND error_code IS NOT 'version_conflict'))""",
                         (task['source_id'], task_id)).fetchone():
                raise WorkflowError('video_recovery_conflict')
            if mode == 'rebuild-media':
                c.execute("UPDATE tasks SET status='queued' WHERE id=?", (task_id,))
            c.execute("""INSERT INTO web_dispatch(task_id,mode,state,requested,processing_mode)
                VALUES(?,?,'pending',?,'preview') ON CONFLICT(task_id) DO UPDATE SET mode=excluded.mode,
                state='pending',requested=excluded.requested,claimed=NULL,owner=NULL,error_code=NULL,processing_mode='preview'""",
                      (task_id, mode, time.time()))
            return {'task_id': task_id, 'dispatch_state': 'pending', 'duplicate': False}

    def model_recovery(self, c, task, stages):
        if self.config['live_video_enabled'] and task['status'] in ('cancelled', 'needs_attention') and task['stage'] == 'text':
            source = self.store._row(c, 'sources', task['source_id'])
            if source['kind'] == 'douyin_album':
                try:
                    plan = album_text_retry_plan(self.service.douyin_album, c, task, source)
                except WorkflowError as exc:
                    if exc.code != 'invalid_album_config':
                        raise
                    plan = None
                if plan or task['status'] == 'cancelled':
                    return plan
                latest = c.execute("""SELECT album_text_retry_key,response_sha256,diagnostic FROM video_chat_attempts
                    WHERE task_id=? AND stage='text' ORDER BY (response_sha256 IS NOT NULL) DESC,attempt DESC LIMIT 1""",
                                   (task['id'],)).fetchone()
                if latest and not latest['response_sha256'] and (
                    latest['album_text_retry_key'] or latest['diagnostic'] in SUMMARY_FORMAT_ERRORS
                ):
                    return None
        blocked = [r['name'] for r in stages
                   if r['status'] == 'in_flight' and r['name'] not in (*ASR_UPLOAD_STAGES, 'asr_result')
                   and not (r['name'] == 'asr_submit' and r['remote_task_id'])]
        if (not self.config['live_video_enabled'] or task['status'] != 'needs_attention'
                or task['error_code'] == 'version_conflict' or len(blocked) != 1 or not is_chat_stage(blocked[0])):
            return None
        stage = blocked[0]
        prior = c.execute("""SELECT attempt,response_sha256,diagnostic,amount,started FROM video_chat_attempts
                    WHERE task_id=? AND stage=? ORDER BY (response_sha256 IS NOT NULL) DESC, attempt DESC LIMIT 1""",
                          (task['id'], stage)).fetchone()
        if prior and prior['response_sha256']:
            return dict(stage=stage, mode='restore', attempt=prior['attempt'], amount=None, reason=prior['diagnostic'])
        kind = 'text' if stage == 'text' else 'vision'
        try:
            source = self.store._row(c, 'sources', task['source_id'])
            if source['kind'] == 'douyin_album':
                from .douyin_album import stage_amounts

                album = self.service.douyin_album
                amount = stage_amounts({**self.service.pc, **album.config})[kind]
            else:
                amount = Decimal(str(self.service.pc['strategy']['reserve_cny'][kind]))
            if not amount.is_finite() or amount <= 0:
                return None
        except (AttributeError, KeyError, TypeError, InvalidOperation, WorkflowError):
            return None
        if prior and prior['amount'] == str(amount) and not prior['started']:
            return dict(stage=stage, mode='restore', attempt=prior['attempt'], amount=None, reason=prior['diagnostic'],
                        authorized_amount=prior['amount'])
        return dict(stage=stage, mode='retry', attempt=(prior['attempt'] if prior else 0) + 1,
                    amount=str(amount), reason=prior['diagnostic'] if prior else None)

    def recover_model(self, task_id, payload):
        with self.store._tx() as c:
            task = self.store._row(c, 'tasks', task_id)
            source = self.store._row(c, 'sources', task['source_id'])
            if source['deleted']:
                raise WorkflowError('source_deleted')
            if task_is_archived(c, task_id):
                raise WorkflowError('task_archived')
            if source['kind'] not in ('video', 'mp4', 'douyin_album'):
                raise WorkflowError('invalid_state')
            dispatch = c.execute('SELECT state FROM web_dispatch WHERE task_id=?', (task_id,)).fetchone()
            if dispatch and dispatch['state'] in ('pending', 'working'):
                raise WorkflowError('dispatch_conflict')
            recovery = self.model_recovery(c, task, task_stages(c, task_id))
            if (not recovery or type(payload.get('attempt')) is not int
                    or any(payload.get(key) != recovery[key] for key in ('stage', 'attempt', 'mode', 'amount'))):
                raise WorkflowError('model_recovery_conflict')
            mode = 'recover-model'
            if recovery['mode'] == ALBUM_TEXT_RETRY_MODE:
                if payload.get('quote_key') != recovery['quote_key']:
                    raise WorkflowError('model_recovery_conflict')
                if payload.get('allow_paid') is not True:
                    raise WorkflowError('paid_consent_required')
                c.execute("""INSERT OR IGNORE INTO video_chat_attempts(task_id,stage,attempt,amount,album_text_retry_key)
                             VALUES(?,'text',?,?,?)""",
                          (task_id, recovery['attempt'], recovery['amount'], recovery['quote_key']))
                c.execute("UPDATE tasks SET status='needs_attention' WHERE id=? AND status='cancelled'", (task_id,))
                mode = 'recover-album-text'
            elif recovery['mode'] == 'retry':
                if payload.get('allow_paid') is not True:
                    raise WorkflowError('paid_consent_required')
                c.execute('INSERT INTO video_chat_attempts(task_id,stage,attempt,amount) VALUES(?,?,?,?)',
                          (task_id, recovery['stage'], recovery['attempt'], recovery['amount']))
            c.execute("""INSERT INTO web_dispatch(task_id,mode,state,requested,processing_mode) VALUES(?,?,'pending',?,'model')
                ON CONFLICT(task_id) DO UPDATE SET mode=excluded.mode,state='pending',requested=excluded.requested,
                claimed=NULL,owner=NULL,error_code=NULL""", (task_id, mode, time.time()))
            return {'task_id': task_id, 'dispatch_state': 'pending'}

    def enqueue(self, task_id, mode='run', allow_paid=False, processing_mode='preview'):
        if mode not in ('run', 'resume') or type(allow_paid) is not bool or processing_mode not in ('preview','model'):
            raise WorkflowError('invalid_request')
        with self.store._tx() as c:
            task = self.store._row(c, 'tasks', task_id)
            source = self.store._row(c, 'sources', task['source_id'])
            if source['deleted']: raise WorkflowError('source_deleted')
            if task_is_archived(c, task_id): raise WorkflowError('task_archived')
            if task['error_code'] == 'favorites_budget_exceeded':
                raise WorkflowError('favorites_budget_exceeded')
            if source['kind'] in ('video', 'mp4'):
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
            elif source['kind'] == 'douyin_album':
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                if not c.execute('SELECT 1 FROM favorites_conversion WHERE task_id=?', (task_id,)).fetchone():
                    raise WorkflowError('invalid_state')
            elif source['kind']=='html' and processing_mode=='model':
                if not self.config.get('live_html_enabled',False): raise WorkflowError('html_model_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
            elif mode == 'resume': raise WorkflowError('invalid_state')
            old = c.execute('SELECT * FROM web_dispatch WHERE task_id=?', (task_id,)).fetchone()
            if old and old['state'] in ('pending', 'working'):
                if old['mode'] == mode:
                    if old['processing_mode'] != processing_mode: raise WorkflowError('dispatch_conflict')
                    return {'task_id': task_id, 'dispatch_state': old['state'], 'duplicate': True}
                if old['mode'] in VIDEO_RECOVERY_MODES:
                    raise WorkflowError('dispatch_conflict')
            expected = 'needs_attention' if mode == 'resume' else 'queued'
            if task['status'] != expected: raise WorkflowError('invalid_state')
            if mode == 'resume':
                if source['kind'] in ('video', 'mp4') and task['error_code'] == 'version_conflict':
                    raise WorkflowError('version_conflict')
                stages = task_stages(c, task_id)
                if source['kind'] in ('video', 'mp4') and self.video_failure(c, task, stages).get('resume_blocked_reason'):
                    raise WorkflowError('video_recovery_conflict')
                if has_unknown_submission(task, stages, legacy_upload=legacy_upload_interruption(c, task, stages)):
                    raise WorkflowError('unknown_submission')
            c.execute("INSERT INTO web_dispatch(task_id,mode,state,requested,claimed,owner,error_code) VALUES(?,?,'pending',?,NULL,NULL,NULL) ON CONFLICT(task_id) DO UPDATE SET mode=excluded.mode,state='pending',requested=excluded.requested,claimed=NULL,owner=NULL,error_code=NULL", (task_id, mode, time.time()))
            c.execute('UPDATE web_dispatch SET processing_mode=? WHERE task_id=?',(processing_mode,task_id))
            return {'task_id': task_id, 'dispatch_state': 'pending', 'duplicate': False}

    def set_archived(self, task_id, archived):
        with self.store._tx() as c:
            task = self.store._row(c, 'tasks', task_id)
            if archived:
                dispatch = c.execute('SELECT state FROM web_dispatch WHERE task_id=?', (task_id,)).fetchone()
                if not task_can_archive(task['status'], dispatch['state'] if dispatch else None):
                    raise WorkflowError('invalid_state')
                c.execute('INSERT OR IGNORE INTO web_task_archive VALUES(?)', (task_id,))
            else:
                c.execute('DELETE FROM web_task_archive WHERE task_id=?', (task_id,))
            return {'task_id': task_id, 'archived': archived}

    def _claim(self):
        sync = cookie = None
        try:
            sync = self.service.favorites_sync
            cookie = self.service.favorites_cookie() if sync else None
        except (AttributeError, WorkflowError):
            pass
        with self.store._tx() as c:
            now = time.time()
            self.store._recover(c, now)
            # Only a stale dispatch whose domain task never began can requeue.
            c.execute("UPDATE web_dispatch SET state='pending',owner=NULL WHERE state='working' AND claimed<=? AND task_id IN (SELECT id FROM tasks WHERE status='queued')", (now-self.config['dispatch_recovery_seconds'],))
            c.execute("UPDATE web_dispatch SET state='done' WHERE state='working' AND task_id IN (SELECT id FROM tasks WHERE status='succeeded')")
            # With the execution lock held, a working dispatch whose task is
            # still interrupted can expose recovery again without resending.
            c.execute("""UPDATE web_dispatch SET state='error' WHERE state='working' AND task_id IN
                (SELECT id FROM tasks WHERE status IN ('failed','needs_attention','cancelled'))""")
            if c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone() or c.execute('SELECT 1 FROM video_maintenance').fetchone():
                return None
            has_favorites = c.execute("SELECT 1 FROM sqlite_master WHERE name='favorites_conversion' AND type='table'").fetchone()
            row = None
            for pending in c.execute("SELECT * FROM web_dispatch WHERE state='pending' ORDER BY requested").fetchall():
                reservation = c.execute('SELECT * FROM favorites_conversion WHERE task_id=?', (pending['task_id'],)).fetchone() if has_favorites else None
                if pending['mode'] in (*MODEL_RECOVERY_DISPATCH_MODES, *VIDEO_RECOVERY_MODES, FAVORITES_REAUTHORIZE_MODE) or not reservation or sync and sync.can_claim_conversion(c, reservation, cookie):
                    row = pending
                    break
            if not row: return None
            job = dict(row)
            token = uuid.uuid4().hex
            c.execute("UPDATE web_dispatch SET state='working',owner=?,claimed=? WHERE task_id=? AND state='pending'", (token,now,job['task_id']))
            job['owner'] = token
            return job

    def reprocess_html(self, source_id, expected_version_id, allow_paid=False):
        return self.reprocess(source_id, expected_version_id, allow_paid, html_only=True)

    def reprocess(self, source_id, expected_version_id, allow_paid=False, *, html_only=False, request_id=None):
        """New explicit task and consent in one transaction; never revive a POST."""
        if type(allow_paid) is not bool: raise WorkflowError('invalid_request')
        if not allow_paid: raise WorkflowError('paid_consent_required')
        with self.store._tx() as c:
            s=self.store._row(c,'sources',source_id)
            if s['deleted']: raise WorkflowError('source_deleted')
            video = not html_only and s['kind'] in ('video', 'mp4')
            if video:
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                if request_id is not None:
                    try:
                        task_id = uuid.UUID(request_id).hex if isinstance(request_id, str) else None
                    except ValueError:
                        raise WorkflowError('invalid_request') from None
                    if not task_id: raise WorkflowError('invalid_request')
                    previous = c.execute("""SELECT t.source_id, v.base_version_id, d.state
                        FROM tasks t LEFT JOIN video_reprocess v ON v.task_id=t.id
                        LEFT JOIN web_dispatch d ON d.task_id=t.id WHERE t.id=?""", (task_id,)).fetchone()
                    if previous:
                        if previous['source_id'] != source_id or previous['base_version_id'] != expected_version_id or not previous['state']:
                            raise WorkflowError('dispatch_conflict')
                        return {'task_id':task_id,'source_id':source_id,'dispatch_state':previous['state'],'processing_mode':'model'}
            elif s['kind'] == 'html':
                if not self.config.get('live_html_enabled', False): raise WorkflowError('html_model_disabled')
            else:
                raise WorkflowError('invalid_source')
            if not expected_version_id or s['current_version_id']!=expected_version_id: raise WorkflowError('version_conflict')
            if c.execute("""SELECT 1 FROM tasks WHERE source_id=? AND
                         (status IN ('queued','running') OR
                          (status='needs_attention' AND (?=0 OR error_code IS NOT 'version_conflict')))""",
                         (source_id, video)).fetchone(): raise WorkflowError('invalid_state')
            if video:
                from .maintenance import media_status
                blob = self.store.data_root / s['blob_relpath']
                if not media_status(self.store, source_id)['available'] or not blob.is_file():
                    raise WorkflowError('media_expired')
            tid=task_id if video and request_id is not None else uuid.uuid4().hex
            c.execute("INSERT INTO tasks(id,source_id,status) VALUES(?,?,'queued')",(tid,source_id))
            c.execute("INSERT INTO web_dispatch(task_id,mode,state,requested,processing_mode) VALUES(?,'run','pending',?,'model')",(tid,time.time()))
            if video:
                c.execute('INSERT INTO video_reprocess(task_id,base_version_id) VALUES(?,?)',(tid,expected_version_id))
            else:
                c.execute('CREATE TABLE IF NOT EXISTS html_runs (task_id TEXT PRIMARY KEY, base_version_id TEXT)')
                c.execute('INSERT INTO html_runs(task_id,base_version_id) VALUES(?,?)',(tid,expected_version_id))
            return {'task_id':tid,'source_id':source_id,'dispatch_state':'pending','processing_mode':'model'}

    def cancel(self, task_id):
        # Revoke both the lease and the explicit web request atomically.
        with self.store._tx() as c:
            task = self.store._cancel(c, task_id)
            c.execute("UPDATE web_dispatch SET state='cancelled',owner=NULL WHERE task_id=?", (task_id,))
            return {'id':task_id,'source_id':task['source_id'],'status':'cancelled'}

    def retry(self, task_id, allow_paid=False, processing_mode=None):
        if type(allow_paid) is not bool or processing_mode not in (None,'preview','model'): raise WorkflowError('invalid_request')
        with self.store._tx() as c:
            task = self.store._row(c,'tasks',task_id)
            source = self.store._row(c,'sources',task['source_id'])
            if source['deleted']: raise WorkflowError('source_deleted')
            if task_is_archived(c, task_id): raise WorkflowError('task_archived')
            if source['kind'] in ('video', 'mp4'):
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
                if task['error_code'] == 'favorites_budget_exceeded':
                    raise WorkflowError('favorites_budget_exceeded')
            elif source['kind'] == 'douyin_album' and not c.execute(
                'SELECT 1 FROM favorites_conversion WHERE task_id=?', (task_id,)
            ).fetchone():
                raise WorkflowError('invalid_state')
            if task['status'] not in ('failed','cancelled') or task['external_started'] or task['attempts']>=self.store.max_attempts:
                raise WorkflowError('invalid_state')
            if source['kind'] in ('video', 'mp4') and self.video_failure(c, task, task_stages(c, task_id)).get('retry_blocked_reason'):
                raise WorkflowError('video_recovery_conflict')
            if source['kind'] in ('video', 'mp4') and c.execute(
                """SELECT 1 FROM tasks WHERE source_id=? AND id<>? AND
                   (status IN ('queued','running') OR (status='needs_attention' AND error_code IS NOT 'version_conflict'))""",
                (task['source_id'], task_id),
            ).fetchone():
                raise WorkflowError('invalid_state')
            old=c.execute('SELECT processing_mode FROM web_dispatch WHERE task_id=?',(task_id,)).fetchone()
            chosen=processing_mode if processing_mode is not None else (old['processing_mode'] if old else 'preview')
            if source['kind']=='html' and chosen=='model':
                if not self.config.get('live_html_enabled',False): raise WorkflowError('html_model_disabled')
                if not allow_paid: raise WorkflowError('paid_consent_required')
            c.execute("UPDATE tasks SET status='queued',error_code=NULL WHERE id=?", (task_id,))
            c.execute("INSERT INTO web_dispatch(task_id,mode,state,requested,claimed,owner,error_code) VALUES(?,'run','pending',?,NULL,NULL,NULL) ON CONFLICT(task_id) DO UPDATE SET mode='run',state='pending',requested=excluded.requested,claimed=NULL,owner=NULL,error_code=NULL", (task_id,time.time()))
            c.execute('UPDATE web_dispatch SET processing_mode=? WHERE task_id=?',(chosen,task_id))
            return {'task_id':task_id,'dispatch_state':'pending','duplicate':False}

    def process_next(self, *args, **kwargs):
        from .execution_guard import execution_guard
        try:
            with execution_guard(self.store):
                return self._guarded_process_next(*args, **kwargs)
        except WorkflowError as exc:
            if exc.code == 'worker_busy': return None
            raise
    def _guarded_process_next(self):
        # Recover only locks proven to belong to expired download jobs, even
        # after the administrator disables downloads or removes credentials.
        from .douyin_import import recover_download_locks
        recover_download_locks(self.store)
        job = self._claim()
        if not job:
            try:
                downloader=self.service.douyin
                status=downloader.status()
                if all(status.values()): return downloader.process_next()
            except WorkflowError:
                pass  # Optional downloads do not block HTML/video work.
            return None
        tid, token = job['task_id'], job['owner']
        self.active = (tid, token)
        error = None
        try:
            task = self.store.get_task(tid)
            source = self.store.get_source(task['source_id'])
            if source['deleted']: raise WorkflowError('source_deleted')
            resume = job['mode'] in ('resume', *MODEL_RECOVERY_DISPATCH_MODES, 'visual-only')
            expected = 'needs_attention' if resume else 'queued'
            if task['status'] != expected: raise WorkflowError('invalid_state')
            if source['kind'] == 'html':
                if job['processing_mode']=='model':
                    if not self.config.get('live_html_enabled',False): raise WorkflowError('html_model_disabled')
                    from .html_pipeline import run_html, load_html_config
                    from .workflow import ROOT
                    from tools.demo_setup import dotenv
                    keys=dotenv(ROOT/self.config['env_file']);keys.update(os.environ)
                    run_html(self.service.wc,load_html_config(ROOT/self.config['html_pipeline_config']),keys,task_id=tid,resume=job['mode']=='resume')
                else:
                    from .workflow import run_once
                    result = run_once(self.service.wc, worker_id='web-html', task_id=tid)
                    if not result or 'error' in result: raise WorkflowError(result.get('error','invalid_state') if result else 'invalid_state')
            elif source['kind'] == 'douyin_album':
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                from .douyin_album_processing import run_album, run_album_text_retry

                with self.store._tx() as c:
                    reservation = c.execute('SELECT amount FROM favorites_conversion WHERE task_id=?', (tid,)).fetchone()
                if not reservation:
                    raise WorkflowError('invalid_state')
                if job['mode'] == 'recover-album-text':
                    run_album_text_retry(self.service.douyin_album, tid)
                else:
                    run_album(self.service.douyin_album, tid, reservation['amount'], resume=resume)
            elif source['kind'] in ('video', 'mp4'):
                if not self.config['live_video_enabled']: raise WorkflowError('video_disabled')
                runner = self.service.video_runner
                if runner is None:
                    from .video_pipeline import run_video
                    runner = run_video
                    from .workflow import ROOT
                    from tools.demo_setup import dotenv
                    keys = dotenv(ROOT/self.config['env_file'])
                    keys.update(os.environ)
                else:
                    keys = {}  # Injected offline tests do not read secrets.
                options = {}
                if job['mode'] == 'visual-only':
                    options['visual_only'] = True
                if job['mode'] == 'rebuild-media':
                    options['rebuild_media'] = True
                runner(self.service.wc, self.service.pc, keys, task_id=tid, resume=resume, **options)
            else:
                raise WorkflowError('unsupported_format')
        except Exception as exc:
            error = exc.code if isinstance(exc, WorkflowError) else 'dispatch_failed'
        finally:
            self.active = None
            with self.store._tx() as c:
                c.execute('UPDATE web_dispatch SET state=?,error_code=? WHERE task_id=? AND owner=?', ('error' if error else 'done', error, tid, token))
        return {'task_id':tid, 'dispatch_state':'error' if error else 'done', 'error':error}

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try: self.service.process_next()
                except Exception: pass  # Persisted requests survive transient DB errors.
                self.stop_event.wait(self.config['dispatch_poll_seconds'])
        self.thread = threading.Thread(target=loop, name='personalkb-web-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=self.config['shutdown_timeout_seconds'])
        # An active external call is not pretended to have stopped. On process
        # exit its domain lease recovers using the Phase 2B unknown-call rules.
        return not (self.thread and self.thread.is_alive())
