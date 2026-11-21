"""Shared limits for scheduled downloads and album image counts."""

import sqlite3
from contextlib import closing
from pathlib import Path

from .workflow_store import WorkflowError


def saved_limits(db):
    return db.execute('SELECT max_images, download_limit, revision FROM favorites_limit_settings WHERE id=1').fetchone()


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
    changes = [dict(row) for row in db.execute("""
        SELECT previous_max_images,max_images,previous_download_limit,download_limit,changed_at
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
    if (images, downloads) == (before['max_images'], before['download_limit']):
        return before
    revision = expected_revision + 1
    db.execute("""INSERT INTO favorites_limit_settings VALUES (1,?,?,?)
        ON CONFLICT(id) DO UPDATE SET max_images=excluded.max_images,
            download_limit=excluded.download_limit,revision=excluded.revision
    """, (images, downloads, revision))
    db.execute("""INSERT INTO favorites_limit_changes
        (revision,previous_max_images,max_images,previous_download_limit,download_limit) VALUES (?,?,?,?,?)
    """, (revision, before['max_images'], images, before['download_limit'], downloads))
    return snapshot(db, defaults, day)
