import hashlib
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from personalkb.workflow_store import WorkflowError, WorkflowStore
from personalkb.video_pipeline import _favorites_budget_preflight


class FavoritesBudgetTests(unittest.TestCase):
    def test_per_video_reservation_checks_before_provider_calls(self):
        with tempfile.TemporaryDirectory(dir='tmp') as folder:
            store = WorkflowStore(Path(folder) / 'workflow.sqlite3')
            task = store.import_source('video', hashlib.sha256(b'x').hexdigest(), 'x.mp4', 'x.mp4')['task']['id']
            amounts = {'asr_submit':Decimal('1.00'), 'vision-0':Decimal('0.10'), 'text':Decimal('0.75')}
            _favorites_budget_preflight(store, task, amounts)
            with store._tx() as db:
                db.execute('CREATE TABLE favorites_conversion(task_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,day TEXT NOT NULL,amount TEXT NOT NULL)')
                db.execute('INSERT INTO favorites_conversion VALUES(?,?,?,?)', (task, 'acct', '2026-11-13', '1.85'))
            _favorites_budget_preflight(store, task, amounts)
            _favorites_budget_preflight(store, task, amounts)  # resume uses the same reservation
            with store._tx() as db:
                db.execute('UPDATE favorites_conversion SET amount=? WHERE task_id=?', ('1.84', task))
            with self.assertRaisesRegex(WorkflowError, 'favorites_budget_exceeded'):
                _favorites_budget_preflight(store, task, amounts)
