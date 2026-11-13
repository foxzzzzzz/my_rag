import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .execution_guard import execution_guard
from .workflow_store import WorkflowError

logger = logging.getLogger(__name__)


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        for key in ('enabled', 'schedule_enabled', 'auto_download', 'conversion_enabled'):
            if type(config[key]) is not bool:
                raise ValueError()
        for key in ('baseline_limit', 'scan_limit', 'download_limit', 'conversion_limit', 'max_pages'):
            if type(config[key]) is not int or config[key] < 1:
                raise ValueError()
        if config['scan_limit'] < config['baseline_limit']:
            raise ValueError()
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', config['daily_at']):
            raise ValueError()
        ZoneInfo(config['timezone'])
        for key in ('daily_budget_cny', 'video_budget_cny'):
            amount = Decimal(str(config[key]))
            if not amount.is_finite() or amount < 0:
                raise ValueError()
        manual_budget = Decimal(str(config.get('manual_video_budget_cny', config['video_budget_cny'])))
        if not manual_budget.is_finite() or manual_budget < 0 or manual_budget != manual_budget.quantize(Decimal('.01')):
            raise ValueError()
        config['manual_video_budget_cny'] = format(manual_budget, '.2f') if manual_budget else None
        if config['conversion_enabled'] and not (
            config['auto_download'] and 0 < Decimal(str(config['video_budget_cny'])) <= Decimal(str(config['daily_budget_cny']))
        ):
            raise ValueError()
        if not isinstance(config['browser_settings'], str) or not config['browser_settings'].strip():
            raise ValueError()
        return config
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation, ZoneInfoNotFoundError):
        raise WorkflowError('invalid_favorites_config') from None


class FavoritesSync:
    def __init__(self, store, config):
        self.store = store
        self.config = config
        with store._tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS favorites_state (
                id INTEGER PRIMARY KEY CHECK(id=1), active TEXT, pending TEXT,
                pending_label TEXT, credential TEXT, state TEXT NOT NULL DEFAULT 'idle',
                error_code TEXT, scan_requested INTEGER NOT NULL DEFAULT 0, last_day TEXT);
            INSERT OR IGNORE INTO favorites_state(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS favorites_accounts (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, snapshot TEXT);
            CREATE TABLE IF NOT EXISTS favorites_items (
                account_id TEXT NOT NULL, work_id TEXT NOT NULL, title TEXT NOT NULL,
                position INTEGER NOT NULL, baseline INTEGER NOT NULL,
                PRIMARY KEY(account_id,work_id));
            CREATE TABLE IF NOT EXISTS favorites_queue (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
                work_id TEXT NOT NULL UNIQUE, automatic INTEGER NOT NULL,
                job_id TEXT UNIQUE, download_day TEXT, task_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued');
            CREATE TABLE IF NOT EXISTS favorites_conversion (
                task_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, day TEXT NOT NULL, amount TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS favorites_manual_consent (
                queue_seq INTEGER PRIMARY KEY, video_budget_cny TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS favorites_conversion_slots (
                task_id TEXT NOT NULL, day TEXT NOT NULL, amount TEXT NOT NULL, PRIMARY KEY(task_id,day));
            CREATE TABLE IF NOT EXISTS favorites_download_slots (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, day TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS favorites_scan_runs (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, recorded REAL NOT NULL,
                account_id TEXT, state TEXT NOT NULL, error_code TEXT, read_count INTEGER NOT NULL,
                queued_count INTEGER NOT NULL);
            """)

    @staticmethod
    def _state(db):
        return db.execute('SELECT * FROM favorites_state WHERE id=1').fetchone()

    @staticmethod
    def _credential(cookie):
        return hashlib.sha256(cookie.encode()).hexdigest() if cookie else None

    @staticmethod
    def _existing(db, work):
        # A successful import remains seen even if its source was later purged.
        return db.execute("""SELECT 1 FROM douyin_cache WHERE work_id=?
            UNION ALL SELECT 1 FROM douyin_jobs WHERE work_id=? AND status='succeeded'
            UNION ALL SELECT 1 FROM sources WHERE original_name=? LIMIT 1""", (work, work, f'douyin-{work}.mp4')).fetchone()

    def can_claim_conversion(self, db, reservation, cookie):
        s = self._state(db)
        if (not cookie or s['state'] != 'ready' or s['scan_requested'] or
                s['active'] != reservation['account_id'] or self._credential(cookie) != s['credential']):
            return False
        manual = db.execute("""SELECT 1 FROM favorites_manual_consent m
                            JOIN favorites_queue q ON q.seq=m.queue_seq WHERE q.task_id=?""",
                            (reservation['task_id'],)).fetchone()
        if manual:
            return True
        now = datetime.now(ZoneInfo(self.config['timezone']))
        day = now.date().isoformat()
        needs_scan = self.config['schedule_enabled'] and s['last_day'] != day
        if not self.config['conversion_enabled'] or needs_scan:
            return False
        amount = Decimal(reservation['amount'])
        if amount > Decimal(str(self.config['video_budget_cny'])):
            return False
        used = [Decimal(row[0]) for row in db.execute(
            'SELECT amount FROM favorites_conversion_slots WHERE day=? AND task_id<>?', (day, reservation['task_id'])
        )]
        if len(used) >= self.config['conversion_limit'] or sum(used, amount) > Decimal(str(self.config['daily_budget_cny'])):
            return False
        if reservation['day'] == day:
            return True
        db.execute('INSERT OR IGNORE INTO favorites_conversion_slots VALUES (?,?,?)',
                   (reservation['task_id'], day, str(amount)))
        db.execute('UPDATE favorites_conversion SET day=? WHERE task_id=?', (day, reservation['task_id']))
        return True

    def status(self, cookie, *, manual_conversion_available=False):
        with self.store._tx() as db:
            s = self._state(db)
            account = db.execute('SELECT * FROM favorites_accounts WHERE id=?', (s['active'],)).fetchone()
            ready = s['state'] == 'ready' and not s['scan_requested'] and self._credential(cookie) == s['credential']
            state = s['state']
            if s['scan_requested']:
                state = 'scan_queued'
            elif state == 'ready' and not ready:
                state = 'paused'
            items = []
            for row in db.execute("""SELECT i.work_id,i.title,q.status,
                  (m.queue_seq IS NOT NULL AND q.account_id=i.account_id) AS paid
                  FROM favorites_items i LEFT JOIN favorites_queue q USING(work_id)
                  LEFT JOIN favorites_manual_consent m ON m.queue_seq=q.seq
                  WHERE i.account_id=? AND i.baseline=1 ORDER BY i.position""", (s['active'],)):
                status = row['status']
                if self._existing(db, row['work_id']):
                    removed = db.execute("""SELECT 1 FROM sources WHERE deleted=1 AND (
                        original_name=? OR id=(SELECT source_id FROM douyin_cache WHERE work_id=?))""",
                        (f"douyin-{row['work_id']}.mp4", row['work_id'])).fetchone()
                    if removed:
                        status = 'deleted'
                    elif not row['paid'] or status not in ('downloaded', 'conversion_queued', 'converted', 'conversion_failed'):
                        status = 'imported'
                items.append(dict(work_id=row['work_id'], title=row['title'], status=status,
                                  selectable=bool(ready and not status)))
            counts = dict(db.execute('SELECT status, COUNT(*) FROM favorites_queue WHERE account_id=? GROUP BY status',
                                     (s['active'],)).fetchall())
            scan = db.execute("""SELECT day, state, error_code, read_count, queued_count
                                 FROM favorites_scan_runs ORDER BY seq DESC LIMIT 1""").fetchone()
            return dict(enabled=self.config['enabled'], state=state, error_code=s['error_code'],
                        active_account=dict(id=account['id'], label=account['label']) if account else None,
                        pending_account=dict(id=s['pending'], label=s['pending_label']) if s['pending'] else None,
                        items=items, download_limit=self.config['download_limit'], baseline_limit=self.config['baseline_limit'],
                        queue_counts=counts,
                        last_scan=dict(scan) if scan else None,
                        manual_conversion_available=manual_conversion_available and self.config['manual_video_budget_cny'] is not None,
                        manual_video_budget_cny=self.config['manual_video_budget_cny'],
                        conversion_enabled=self.config['conversion_enabled'])

    def _enabled(self):
        if not self.config['enabled']:
            raise WorkflowError('favorites_disabled')

    def request_scan(self):
        self._enabled()
        with self.store._tx() as db:
            db.execute('UPDATE favorites_state SET scan_requested=1 WHERE id=1')
        return {'queued': True}

    def confirm(self, account_id, cookie):
        self._enabled()
        with self.store._tx() as db:
            s = self._state(db)
            if not isinstance(account_id, str) or s['pending'] != account_id or not cookie or self._credential(cookie) != s['credential'] or s['state'] != 'confirm_account':
                raise WorkflowError('favorites_account_conflict')
            db.execute('INSERT OR IGNORE INTO favorites_accounts(id,label) VALUES (?,?)', (account_id, s['pending_label']))
            db.execute("""UPDATE favorites_state SET active=?,pending=NULL,pending_label=NULL,
                       state='baseline_pending',scan_requested=1 WHERE id=1""", (account_id,))
        return {'confirmed': True}

    def select(self, account_id, work_ids, cookie, *, rights_confirmed, allow_paid=False, video_budget_cny=None):
        self._enabled()
        if rights_confirmed is not True:
            raise WorkflowError('rights_required')
        if allow_paid is not True:
            raise WorkflowError('paid_consent_required')
        amount = self.config['manual_video_budget_cny']
        if amount is None:
            raise WorkflowError('favorites_manual_disabled')
        if video_budget_cny != amount:
            raise WorkflowError('favorites_price_changed')
        if not isinstance(work_ids, list) or not work_ids or len(work_ids) > self.config['baseline_limit'] or any(
            not isinstance(item, str) or not re.fullmatch(r'[0-9]+', item) for item in work_ids
        ):
            raise WorkflowError('invalid_request')
        with self.store._tx() as db:
            s = self._state(db)
            if not cookie or account_id != s['active'] or s['state'] != 'ready' or s['scan_requested'] or self._credential(cookie) != s['credential']:
                raise WorkflowError('favorites_account_conflict')
            wanted = set(work_ids)
            available = [row[0] for row in db.execute('SELECT work_id FROM favorites_items WHERE account_id=? AND baseline=1 ORDER BY position', (account_id,))]
            if not wanted.issubset(available):
                raise WorkflowError('invalid_request')
            count = 0
            for work in available:
                if work in wanted and not self._existing(db, work):
                    row = db.execute('INSERT OR IGNORE INTO favorites_queue(account_id,work_id,automatic) VALUES (?,?,0)',
                                     (account_id, work))
                    if row.rowcount:
                        db.execute('INSERT INTO favorites_manual_consent VALUES (?,?)', (row.lastrowid, amount))
                        count += 1
        return {'queued': count}

    def _pause(self, db, code):
        db.execute("""UPDATE favorites_state SET state='paused', error_code=?,pending=NULL,
                   pending_label=NULL WHERE id=1""", (code,))

    def _accept_scan(self, db, payload, credential):
        s = self._state(db)
        account_id = payload.get('account_id')
        status = payload.get('status')
        if status not in ('ok', 'pagination_incomplete') or not isinstance(account_id, str) or not account_id:
            self._pause(db, status if status and status != 'ok' else 'account_unverified')
            return
        if account_id != s['active']:
            label = payload.get('account_label') or account_id
            db.execute("""UPDATE favorites_state SET pending=?,pending_label=?,credential=?,
                       state='confirm_account',error_code=NULL WHERE id=1""", (account_id, label, credential))
            return
        if status != 'ok':
            self._pause(db, status)
            return
        videos = payload.get('videos')
        if not isinstance(videos, list) or any(
            not isinstance(item, dict) or not isinstance(item.get('id'), str) or
            not re.fullmatch(r'[0-9]+', item['id']) or not isinstance(item.get('title'), str) for item in videos
        ):
            self._pause(db, 'collection_invalid')
            return
        items = {item['id']: item['title'] for item in videos}
        account = db.execute('SELECT * FROM favorites_accounts WHERE id=?', (account_id,)).fetchone()
        snapshot = json.loads(account['snapshot']) if account['snapshot'] is not None else None
        known = set(snapshot or ())
        first_known = next((pos for pos, work in enumerate(items) if work in known), None)
        exhausted = payload.get('exhausted') is True
        limit = self.config['baseline_limit']
        if snapshot is None and len(items) < limit and not exhausted:
            self._pause(db, 'baseline_incomplete')
            return
        if snapshot is not None and first_known is None and not exhausted:
            self._pause(db, 'snapshot_gap')
            return
        # A complete but disjoint snapshot becomes the new baseline.
        rebase = bool(snapshot and first_known is None)
        for pos, (work, title) in enumerate(items.items()):
            row = db.execute("""INSERT OR IGNORE INTO favorites_items VALUES (?,?,?,?,?)""",
                             (account_id, work, title or work, pos, int((snapshot is None or rebase) and pos < limit)))
            if row.rowcount and snapshot is not None and not rebase and (first_known is None or pos < first_known) and not self._existing(db, work):
                db.execute('INSERT OR IGNORE INTO favorites_queue(account_id,work_id,automatic) VALUES (?,?,1)', (account_id, work))
        if rebase:
            db.execute('UPDATE favorites_items SET baseline=0 WHERE account_id=?', (account_id,))
            db.executemany('UPDATE favorites_items SET baseline=1,position=? WHERE account_id=? AND work_id=?',
                           ((pos, account_id, work) for pos, work in enumerate(list(items)[:limit])))
        boundary = list(items)
        if first_known is not None and not exhausted:
            boundary.extend(work for work in snapshot if work not in items)
        db.execute('UPDATE favorites_accounts SET snapshot=? WHERE id=?',
                   (json.dumps(boundary[:self.config['scan_limit']]), account_id))
        db.execute("UPDATE favorites_state SET state='ready',credential=?,error_code=? WHERE id=1",
                   (credential, 'snapshot_rebased' if rebase else None))

    def tick(self, cookie, reader, downloader, dispatcher, *, now=None, stop_requested=lambda: False):
        if not self.config['enabled']:
            return None
        if stop_requested():
            return None
        now = now or datetime.now(ZoneInfo(self.config['timezone']))
        day = now.date().isoformat()
        credential = self._credential(cookie)
        with execution_guard(self.store):
            with self.store._tx() as db:
                s = self._state(db)
                due = (self.config['schedule_enabled'] and s['last_day'] != day and
                       now.strftime('%H:%M') >= self.config['daily_at'])
                scan = bool(s['scan_requested'] or due or s['state'] == 'scanning')
                account = db.execute('SELECT snapshot FROM favorites_accounts WHERE id=?', (s['active'],)).fetchone()
                snapshot = account['snapshot'] if account else None
                limit = self.config['scan_limit'] if snapshot is not None else self.config['baseline_limit']
                if scan:
                    db.execute("""UPDATE favorites_state SET state='scanning',scan_requested=0,last_day=? WHERE id=1""", (day,))
            if scan:
                try:
                    anchors = json.loads(snapshot) if snapshot is not None else []
                    payload = reader(cookie, limit, anchors, s['active']) if cookie else {'status': 'missing_douyin_cookie'}
                except (OSError, WorkflowError, ValueError, RuntimeError, KeyError, TypeError):
                    payload = {'status': 'collection_failed'}
                with self.store._tx() as db:
                    before = db.execute('SELECT COUNT(*) FROM favorites_queue').fetchone()[0]
                    self._accept_scan(db, payload, credential)
                    state = self._state(db)
                    read_count = len(payload.get('videos', [])) if isinstance(payload.get('videos'), list) else 0
                    queued = db.execute('SELECT COUNT(*) FROM favorites_queue').fetchone()[0] - before
                    db.execute("""INSERT INTO favorites_scan_runs
                        (day,recorded,account_id,state,error_code,read_count,queued_count)
                        VALUES (?,?,?,?,?,?,?)""",
                        (day, time.time(), state['active'], state['state'], state['error_code'], read_count, queued))
                logger.info('Favorites scan %s state=%s read=%s queued=%s error=%s',
                            day, state['state'], read_count, queued, state['error_code'])
                return {'favorites': 'scanned'}
            if stop_requested():
                return None
            with self.store._tx() as db:
                s = self._state(db)
                if not cookie or credential != s['credential'] or s['state'] != 'ready' or s['scan_requested']:
                    return None
                account = s['active']
            return self._dispatch(account, day, credential, downloader, dispatcher)

    def _dispatch(self, account, day, credential, downloader, dispatcher):
        with self.store._tx() as db:
            s = self._state(db)
            if s['state'] != 'ready' or s['scan_requested'] or s['active'] != account or s['credential'] != credential:
                return None
            db.execute("""UPDATE favorites_queue SET status='downloading', download_day=NULL
                       WHERE account_id=? AND status='download_failed' AND job_id IN
                       (SELECT id FROM douyin_jobs WHERE status='queued')""", (account,))
            db.execute("""UPDATE favorites_queue SET status='downloaded'
                       WHERE account_id=? AND status='downloading' AND job_id IN
                       (SELECT id FROM douyin_jobs WHERE status='succeeded')""", (account,))
            db.execute("""UPDATE favorites_queue SET status='download_failed'
                       WHERE account_id=? AND status='downloading' AND job_id IN
                       (SELECT id FROM douyin_jobs WHERE status IN ('failed','needs_attention'))""", (account,))
            db.execute("""UPDATE favorites_queue SET status='converted' WHERE account_id=?
                       AND status IN ('conversion_queued','conversion_failed')
                       AND task_id IN (SELECT id FROM tasks WHERE status='succeeded')""", (account,))
            db.execute("""UPDATE favorites_queue SET status='conversion_failed' WHERE account_id=?
                       AND status='conversion_queued' AND task_id IN
                       (SELECT task_id FROM web_dispatch WHERE state IN ('error','cancelled'))""", (account,))
            scheduled_ready = not self.config['schedule_enabled'] or s['last_day'] == day
            if self._enqueue_conversion(db, account, day, dispatcher, scheduled_ready):
                return {'favorites': 'conversion_queued'}
            if not all(downloader.status().values()):
                return None
            count = db.execute('SELECT COUNT(*) FROM favorites_download_slots WHERE day=?', (day,)).fetchone()[0]
            has_slot = count < self.config['download_limit']
            pending = db.execute("""SELECT q.job_id,q.work_id,q.download_day,m.queue_seq AS paid
                    FROM favorites_queue q JOIN douyin_jobs j ON j.id=q.job_id
                    LEFT JOIN favorites_manual_consent m ON m.queue_seq=q.seq
                    WHERE q.account_id=? AND q.status='downloading' AND j.status='queued'
                    AND (m.queue_seq IS NOT NULL OR (? AND (q.automatic=0 OR ?) AND (q.download_day=? OR ?)))
                    ORDER BY q.seq LIMIT 1""", (account, scheduled_ready, self.config['auto_download'], day, has_slot)).fetchone()
            if pending:
                job_id = pending[0]
                if self._existing(db, pending['work_id']):
                    db.execute("UPDATE favorites_queue SET status='skipped' WHERE job_id=?", (job_id,))
                    db.execute("UPDATE douyin_jobs SET status='succeeded', source_id=(SELECT source_id FROM douyin_cache WHERE work_id=?) WHERE id=?",
                               (pending['work_id'], job_id))
                    return {'favorites': 'skipped'}
                # The original reservation follows a queued job across restarts. Moving to a new day consumes today's slot.
                if pending['paid'] is None and pending['download_day'] != day:
                    db.execute('UPDATE favorites_queue SET download_day=? WHERE job_id=?', (day, job_id))
                    db.execute('INSERT INTO favorites_download_slots(job_id,day) VALUES (?,?)', (job_id, day))
            else:
                row = db.execute("""SELECT q.*,m.queue_seq AS paid FROM favorites_queue q
                            LEFT JOIN favorites_manual_consent m ON m.queue_seq=q.seq
                            WHERE q.account_id=? AND q.status='queued'
                            AND (m.queue_seq IS NOT NULL OR (? AND (q.automatic=0 OR ?)))
                            ORDER BY q.seq LIMIT 1""", (account, scheduled_ready and has_slot, self.config['auto_download'])).fetchone()
                if row is None:
                    return None
                work = row['work_id']
                if self._existing(db, work):
                    db.execute("UPDATE favorites_queue SET status='skipped' WHERE seq=?", (row['seq'],))
                    return {'favorites': 'skipped'}
                job_id = uuid.uuid4().hex
                now = time.time()
                db.execute("""INSERT INTO douyin_jobs(id,canonical_url,work_id,status,created_at,updated_at)
                             VALUES (?,?,?,'queued',?,?)""", (job_id, f'https://www.douyin.com/video/{work}', work, now, now))
                db.execute("UPDATE favorites_queue SET job_id=?,download_day=?,status='downloading' WHERE seq=?",
                           (job_id, day, row['seq']))
                if row['paid'] is None:
                    db.execute('INSERT INTO favorites_download_slots(job_id,day) VALUES (?,?)', (job_id, day))
        job = downloader.process_next(job_id=job_id)
        if job and job['error_code'] in ('douyin_resolver_failed', 'douyin_http_failed'):
            with self.store._tx() as db:
                self._pause(db, job['error_code'])
        return job

    def _enqueue_conversion(self, db, account, day, dispatcher, scheduled_ready):
        if not dispatcher.config['live_video_enabled']:
            return False
        used = [Decimal(row[0]) for row in db.execute('SELECT amount FROM favorites_conversion_slots WHERE day=?', (day,))]
        amount = Decimal(str(self.config['video_budget_cny']))
        can_schedule = (scheduled_ready and self.config['conversion_enabled'] and len(used) < self.config['conversion_limit']
                        and sum(used, amount) <= Decimal(str(self.config['daily_budget_cny'])))
        row = db.execute("""SELECT q.seq,t.id,m.video_budget_cny FROM favorites_queue q
                JOIN douyin_jobs j ON j.id=q.job_id JOIN sources s ON s.id=j.source_id
                JOIN tasks t ON t.source_id=s.id LEFT JOIN web_dispatch d ON d.task_id=t.id
                LEFT JOIN web_task_archive a ON a.task_id=t.id
                LEFT JOIN favorites_manual_consent m ON m.queue_seq=q.seq
                WHERE q.account_id=? AND q.status='downloaded'
                AND (m.queue_seq IS NOT NULL OR (? AND q.automatic=1))
                AND s.deleted=0 AND s.current_version_id IS NULL AND t.status='queued'
                AND d.task_id IS NULL AND a.task_id IS NULL ORDER BY q.seq,t.rowid LIMIT 1""", (account, can_schedule)).fetchone()
        if row is None:
            return False
        manual_amount = row['video_budget_cny']
        db.execute('INSERT INTO favorites_conversion VALUES (?,?,?,?)', (row['id'], account, day, manual_amount or str(amount)))
        if manual_amount is None:
            db.execute('INSERT INTO favorites_conversion_slots VALUES (?,?,?)', (row['id'], day, str(amount)))
        db.execute("INSERT INTO web_dispatch(task_id,mode,state,requested) VALUES (?,'run','pending',?)", (row['id'], time.time()))
        db.execute("UPDATE favorites_queue SET task_id=?,status='conversion_queued' WHERE seq=?", (row['id'], row['seq']))
        return True
