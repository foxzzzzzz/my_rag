"""Atomic conservative reservation for the experimental smoke-test budget.

The API smoke runner is not implemented; this module does not make network calls.
"""
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation

def reserve(db_path, run_id, request_id, amount, run_limit, research_limit):
    """Reserve once before a request. Outstanding reservations remain charged."""
    try:
        amount, run_limit, research_limit = (Decimal(str(x)) for x in (amount,run_limit,research_limit))
    except InvalidOperation as exc:
        raise ValueError('预算金额无效') from exc
    if any(not n.is_finite() or n<=0 for n in (amount,run_limit,research_limit)):
        raise ValueError('预算金额无效')
    if not run_id or not request_id:
        raise ValueError('标识不能为空')
    with closing(sqlite3.connect(db_path, timeout=30, isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS reservations (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, amount TEXT NOT NULL)')
            rows=db.execute('SELECT run_id, amount FROM reservations').fetchall()
            total=sum((Decimal(row[1]) for row in rows),Decimal(0))
            run_total=sum((Decimal(value) for run,value in rows if run==run_id),Decimal(0))
            if total+amount>research_limit or run_total+amount>run_limit:
                raise ValueError('预算不足')
            db.execute('INSERT INTO reservations VALUES (?,?,?)',(request_id,run_id,str(amount)))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
