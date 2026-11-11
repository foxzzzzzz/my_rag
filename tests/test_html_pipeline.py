import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from personalkb.workflow import load_config, import_file, make_store
from personalkb.workflow_store import WorkflowError
from personalkb.html_pipeline import load_html_config, run_html


class FakeProvider:
    def __init__(self): self.calls = 0; self.action = None
    def summarize(self, body, title):
        self.calls += 1
        if self.action: self.action()
        return {'structured': {'summary': '摘要', 'notes': '笔记'}, 'model': 'fake',
                'usage': {'input_tokens': 12, 'output_tokens': 3}, 'estimated_cost_cny': '0.001'}


class HtmlPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='tmp'); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.wc = load_config(); self.wc['data_dir'] = str(self.root / 'data'); self.wc['min_free_bytes'] = 0
        self.config = load_html_config(); self.config['budget']['ledger'] = str(self.root / 'ledger.sqlite')
        source = self.root / 'sample.html'
        source.write_text('<html><title>题目</title><body><h1>正文</h1><table><tr><td>证据</td></tr></table></body></html>', encoding='utf8')
        obj = import_file(self.wc, source, True); self.task = obj['task']['id']; self.sid = obj['source']['id']
        self.provider = FakeProvider()
    def run_html(self, resume=False):
        return run_html(self.wc, self.config, {}, task_id=self.task, resume=resume, services=self.provider)
    def store(self): return make_store(self.wc)
    def status(self): return self.store().get_task(self.task)['status']
    def test_success_contains_evidence_and_usage(self):
        version = self.run_html()
        self.assertEqual(self.status(), 'succeeded')
        content = json.dumps(version, ensure_ascii=False)
        for expected in ('正文', '证据', '摘要', 'input_tokens'): self.assertIn(expected, content)
        self.assertEqual(self.provider.calls, 1)
    def test_missing_key_before_claim(self):
        with self.assertRaises(WorkflowError): run_html(self.wc, self.config, {}, task_id=self.task)
        self.assertEqual(self.status(), 'queued'); self.assertFalse(Path(self.config['budget']['ledger']).exists())
    def test_invalid_config_before_post(self):
        self.config['models']['models']['text']['model'] = ''
        with self.assertRaises(WorkflowError): self.run_html()
        self.assertEqual(self.provider.calls, 0); self.assertEqual(self.status(), 'queued')
    def test_budget_before_post(self):
        db = sqlite3.connect(self.config['budget']['ledger'])
        db.execute('CREATE TABLE reservations (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, amount TEXT NOT NULL)')
        db.execute('INSERT INTO reservations VALUES (?,?,?)', ('other', 'other', self.config['budget']['research_limit']))
        db.commit(); db.close()
        with self.assertRaises(WorkflowError): self.run_html()
        self.assertEqual(self.provider.calls, 0)
    def test_context_before_post(self):
        self.config['strategy']['max_context_utf8_bytes'] = 1
        with self.assertRaises(WorkflowError): self.run_html()
        self.assertEqual(self.provider.calls, 0)
    def test_long_title_context_before_post(self):
        source = self.root / 'long.html'
        source.write_text('<html><title>' + 'T' * 3000 + '</title><body>x</body></html>', encoding='utf8')
        self.task = import_file(self.wc, source, True)['task']['id']
        self.config['strategy']['max_context_utf8_bytes'] = 2000
        with self.assertRaises(WorkflowError): self.run_html()
        self.assertEqual(self.provider.calls, 0)
    def test_unknown_post_never_repeats(self):
        def timeout(): raise TimeoutError()
        self.provider.action = timeout
        with self.assertRaises(WorkflowError): self.run_html()
        self.assertEqual(self.status(), 'needs_attention')
        with self.assertRaises(WorkflowError): self.run_html(True)
        self.assertEqual(self.provider.calls, 1)
    def test_cancel_during_post_never_publishes(self):
        self.provider.action = lambda: self.store().cancel(self.task)
        with self.assertRaises(WorkflowError): self.run_html()
        self.assertEqual(self.status(), 'cancelled')
        self.assertEqual(self.store().list_versions(self.sid), [])
    def test_cached_response_reused_after_finish_failure(self):
        from personalkb.workflow_store import WorkflowStore
        strategy = self.config['strategy']
        legacy = strategy['legacy_text_prompt']['value']
        self.config['strategy'] = {key: value for key, value in strategy.items() if key != 'legacy_text_prompt'}
        self.config['strategy']['text_system_prompt'] = legacy
        with patch.object(WorkflowStore, 'finish', side_effect=WorkflowError('injected_failure')):
            with self.assertRaises(WorkflowError): self.run_html()
        self.config['strategy'] = strategy
        self.assertEqual(self.status(), 'needs_attention')
        self.run_html(True)
        self.assertEqual(self.provider.calls, 1)
