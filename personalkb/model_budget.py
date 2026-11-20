"""Shared budget settings and conservative ledger views."""

import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path


class BudgetRevisionConflict(ValueError):
    pass


def _money(value, *, positive=False, cents=False):
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (positive and number == 0):
            raise ValueError()
        if cents and number != number.quantize(Decimal('0.01')):
            raise ValueError()
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('预算金额无效') from None


def _exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def effective_limit(connection, fallback):
    default = _money(fallback, positive=True)
    if not _exists(connection, 'budget_settings'):
        return default
    row = connection.execute('SELECT limit_cny FROM budget_settings WHERE id=1').fetchone()
    return _money(row[0], positive=True) if row else default


def _snapshot(db, fallback):
    limit = effective_limit(db, fallback)
    amounts = db.execute('SELECT amount FROM reservations').fetchall() if _exists(db, 'reservations') else []
    total = sum((_money(row[0]) for row in amounts), Decimal(0))
    row = db.execute('SELECT revision FROM budget_settings WHERE id=1').fetchone() if _exists(db, 'budget_settings') else None
    changes = []
    if _exists(db, 'budget_changes'):
        changes = [dict(previous_limit_cny=r[0], limit_cny=r[1], changed_at=r[2]) for r in db.execute(
            'SELECT previous_limit_cny,limit_cny,changed_at FROM budget_changes ORDER BY revision DESC LIMIT 50')]
    return dict(limit_cny=str(limit), reserved_cny=str(total), available_cny=str(max(Decimal(0), limit-total)),
                revision=row[0] if row else 0, changes=changes)


def budget_snapshot(db_path, fallback, *, include_entries=False):
    if not Path(db_path).exists():
        limit = _money(fallback, positive=True)
        result = dict(limit_cny=str(limit), reserved_cny='0', available_cny=str(limit), revision=0, changes=[])
        if include_entries:
            result['entries'] = []
        return result
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
        db.execute('BEGIN')
        result = _snapshot(db, fallback)
        if include_entries:
            result['entries'] = _entries(db)
        return result


def update_budget_limit(db_path, fallback, limit_cny, expected_revision, *, include_entries=False):
    amount = _money(limit_cny, positive=True, cents=True)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('预算版本无效')
    with closing(sqlite3.connect(db_path, timeout=30, isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS budget_settings (id INTEGER PRIMARY KEY CHECK(id=1), limit_cny TEXT NOT NULL, revision INTEGER NOT NULL)')
            db.execute("CREATE TABLE IF NOT EXISTS budget_changes (revision INTEGER PRIMARY KEY, previous_limit_cny TEXT NOT NULL, limit_cny TEXT NOT NULL, changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
            before = _snapshot(db, fallback)
            if before['revision'] != expected_revision:
                raise BudgetRevisionConflict('预算已更改，请刷新')
            revision = expected_revision + 1
            db.execute('INSERT INTO budget_settings VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET limit_cny=excluded.limit_cny, revision=excluded.revision', (str(amount), revision))
            db.execute('INSERT INTO budget_changes(revision,previous_limit_cny,limit_cny) VALUES (?,?,?)', (revision, before['limit_cny'], str(amount)))
            result = _snapshot(db, fallback)
            if include_entries:
                result['entries'] = _entries(db)
            db.execute('COMMIT')
            return result
        except BaseException:
            db.execute('ROLLBACK')
            raise


def record_estimate(db_path, request_id, amount):
    value = _money(amount)
    if not isinstance(request_id, str) or not request_id:
        raise ValueError('请求标识无效')
    with closing(sqlite3.connect(db_path, timeout=30)) as db:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS budget_estimates (request_id TEXT PRIMARY KEY, estimated_cost_cny TEXT NOT NULL)')
            db.execute('INSERT INTO budget_estimates VALUES (?,?) ON CONFLICT(request_id) DO UPDATE SET estimated_cost_cny=excluded.estimated_cost_cny', (request_id, str(value)))


def _entries(db):
    if not _exists(db, 'reservations'):
        return []
    estimates = dict(db.execute('SELECT request_id,estimated_cost_cny FROM budget_estimates')) if _exists(db, 'budget_estimates') else {}
    limits = dict(db.execute('SELECT request_id,reserved_limit_cny FROM budget_reservation_limits')) if _exists(db, 'budget_reservation_limits') else {}
    return [dict(request_id=r[0], run_id=r[1], reserved_cny=r[2], reserved_limit_cny=limits.get(r[0]), estimated_cost_cny=estimates.get(r[0]))
            for r in db.execute('SELECT request_id,run_id,amount FROM reservations ORDER BY rowid DESC')]


def budget_entries(db_path):
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
        db.execute('BEGIN')
        return _entries(db)
