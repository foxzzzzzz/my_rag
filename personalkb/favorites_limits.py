"""Shared settings for scheduled favorites processing and album image counts."""

import re
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .workflow_store import WorkflowError


def saved_limits(db):
    return db.execute('SELECT s.max_images, s.download_limit, s.revision, b.video_budget_cny, b.daily_budget_cny FROM favorites_limit_settings s LEFT JOIN favorites_budget_settings b ON b.id=s.id WHERE s.id=1').fetchone()


def image_limit(store, default):
    # Quoting can run inside the favorites write transaction.
    uri = Path(store.db_path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=store.busy_timeout_seconds)) as db:
        settings = saved_limits(db)
    return settings[0] if settings else default


def downloads_used(db, day):
    return db.execute('SELECT COUNT(*) FROM favorites_download_slots WHERE day=?', (day,)).fetchone()[0]


def snapshot(db, defaults, day):
    settings = saved_limits(db)
    limits = dict(settings) if settings else {**defaults, 'revision': 0}
    for key in ('video_budget_cny', 'daily_budget_cny'):
        effective = defaults[key] if limits[key] is None else limits[key]
        limits[key] = format(Decimal(str(effective)), '.2f')
    amounts = [Decimal(row[0]) for row in db.execute('SELECT amount FROM favorites_conversion_slots WHERE day=?', (day,))]
    reserved = sum(amounts, Decimal(0))
    remaining = max(Decimal(0), Decimal(limits['daily_budget_cny']) - reserved)
    limits.update(conversions_used=len(amounts), conversion_reserved_cny=format(reserved, '.2f'),
                  conversion_remaining_cny=format(remaining, '.2f'))
    changes = [dict(row) for row in db.execute("""
        SELECT previous_max_images,max_images,previous_download_limit,download_limit,previous_video_budget_cny,video_budget_cny,previous_daily_budget_cny,daily_budget_cny,changed_at
        FROM favorites_limit_changes ORDER BY revision DESC LIMIT 50
    """)]
    return {**limits, 'day': day, 'downloads_used': downloads_used(db, day), 'changes': changes}


def change_limits(db, defaults, day, payload):
    images = payload.get('max_images')
    downloads = payload.get('download_limit')
    expected_revision = payload.get('expected_revision')
    if (type(images) is not int or not 1 <= images < 2**53 or
        type(downloads) is not int or not 0 <= downloads < 2**53 or
        type(expected_revision) is not int or expected_revision < 0):
        raise WorkflowError('invalid_favorites_limits')
    before = snapshot(db, defaults, day)
    if before['revision'] != expected_revision:
        raise WorkflowError('favorites_limits_conflict')
    saved_row = saved_limits(db)
    saved = dict(saved_row) if saved_row else {}
    overrides = {}
    for key in ('video_budget_cny', 'daily_budget_cny'):
        if key not in payload:
            overrides[key] = saved.get(key)
            continue
        raw = payload[key]
        try:
            if not isinstance(raw, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', raw):
                raise ValueError()
            value = Decimal(raw).quantize(Decimal('.01'))
            if key == 'video_budget_cny' and value == 0:
                raise ValueError()
            overrides[key] = format(value, '.2f')
        except (InvalidOperation, ValueError):
            raise WorkflowError('invalid_favorites_limits') from None
    if ((images, downloads) == (before['max_images'], before['download_limit'])
            and all(saved.get(key) == value for key, value in overrides.items())):
        return before
    video_override = overrides['video_budget_cny']
    daily_override = overrides['daily_budget_cny']
    revision = expected_revision + 1
    db.execute("""INSERT INTO favorites_limit_settings VALUES (1,?,?,?)
        ON CONFLICT(id) DO UPDATE SET max_images=excluded.max_images,
            download_limit=excluded.download_limit,revision=excluded.revision
    """, (images, downloads, revision))
    db.execute("""INSERT INTO favorites_budget_settings VALUES (1,?,?)
        ON CONFLICT(id) DO UPDATE SET video_budget_cny=excluded.video_budget_cny,
            daily_budget_cny=excluded.daily_budget_cny
    """, (video_override, daily_override))
    db.execute("""INSERT INTO favorites_limit_changes
        (revision,previous_max_images,max_images,previous_download_limit,download_limit,previous_video_budget_cny,video_budget_cny,previous_daily_budget_cny,daily_budget_cny) VALUES (?,?,?,?,?,?,?,?,?)
    """, (revision, before['max_images'], images, before['download_limit'], downloads,
          before['video_budget_cny'], video_override or before['video_budget_cny'],
          before['daily_budget_cny'], daily_override or before['daily_budget_cny']))
    return snapshot(db, defaults, day)
