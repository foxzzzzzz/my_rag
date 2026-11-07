import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from personalkb.workflow import load_config, import_file
from personalkb.workflow_store import WorkflowError
from personalkb.web_service import WebService


class HtmlDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='tmp'); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.wc = load_config(); self.wc['data_dir'] = str(root/'data'); self.wc['min_free_bytes'] = 0
        self.cfg = {'live_video_enabled': False, 'live_html_enabled': False, 'dispatch_recovery_seconds': 0,
                    'dispatch_poll_seconds': 1, 'shutdown_timeout_seconds': 1,
                    'env_file': 'unused', 'html_pipeline_config': 'unused'}
        self.s = WebService(self.wc, {}, self.cfg)
        source = root/'source.html'; source.write_text('<html><body>Evidence</body></html>', encoding='utf8')
        imported = import_file(self.wc, source, True)
        self.tid = imported['task']['id']; self.sid = imported['source']['id']
    def enqueue_model(self, consent=True):
        return self.s.dispatcher.enqueue(self.tid, allow_paid=consent, processing_mode='model')
    def test_disabled_and_missing_consent(self):
        with self.assertRaises(WorkflowError): self.enqueue_model()
        self.cfg['live_html_enabled'] = True
        with self.assertRaises(WorkflowError): self.enqueue_model(False)
        with self.s.store._tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM web_dispatch').fetchone()[0], 0)
    def test_preview_default_does_not_call_model(self):
        self.s.dispatcher.enqueue(self.tid)
        with patch('personalkb.html_pipeline.run_html') as call:
            self.assertEqual(self.s.process_next()['dispatch_state'], 'done')
            call.assert_not_called()
    def test_model_survives_restart(self):
        self.cfg['live_html_enabled'] = True; self.enqueue_model()
        restarted = WebService(self.wc, {}, self.cfg)
        with patch('personalkb.html_pipeline.run_html') as call, patch('personalkb.html_pipeline.load_html_config', return_value={}), patch('tools.demo_setup.dotenv', return_value={}):
            self.assertEqual(restarted.process_next()['dispatch_state'], 'done')
            call.assert_called_once(); self.assertEqual(call.call_args.kwargs['task_id'], self.tid)
    def test_pending_cannot_switch_mode(self):
        self.cfg['live_html_enabled'] = True; self.enqueue_model()
        with self.assertRaises(WorkflowError): self.s.dispatcher.enqueue(self.tid)
    def test_disabled_at_worker_no_post(self):
        self.cfg['live_html_enabled'] = True; self.enqueue_model(); self.cfg['live_html_enabled'] = False
        with patch('personalkb.html_pipeline.run_html') as call:
            result = self.s.process_next(); call.assert_not_called()
        self.assertEqual(result['error'], 'html_model_disabled')
    def test_retry_without_consent_is_atomic(self):
        self.cfg['live_html_enabled'] = True; self.enqueue_model()
        self.s.dispatcher.cancel(self.tid)
        with self.assertRaises(WorkflowError): self.s.dispatcher.retry(self.tid, allow_paid=False)
        self.assertEqual(self.s.store.get_task(self.tid)['status'], 'cancelled')
        with self.s.store._tx() as db:
            row = db.execute('SELECT state, processing_mode FROM web_dispatch WHERE task_id=?', (self.tid,)).fetchone()
            self.assertEqual(tuple(row), ('cancelled', 'model'))

    def test_reprocess_checks_and_preserves_review(self):
        self.s.dispatcher.enqueue(self.tid); self.s.process_next()
        current = self.s.detail(self.sid)['current']
        self.s.store.review(self.sid, current['id'], current['content_sha256'], 99, 'approve', 'tester')
        def count():
            with self.s.store._tx() as db:
                return db.execute('SELECT count(*) FROM tasks').fetchone()[0]
        before = count()
        with self.assertRaises(WorkflowError): self.s.dispatcher.reprocess_html(self.sid, current['id'], True)
        self.cfg['live_html_enabled'] = True
        with self.assertRaises(WorkflowError): self.s.dispatcher.reprocess_html(self.sid, current['id'], False)
        with self.assertRaises(WorkflowError): self.s.dispatcher.reprocess_html(self.sid, 'wrong', True)
        self.assertEqual(count(), before)
        result = self.s.dispatcher.reprocess_html(self.sid, current['id'], True)
        self.assertNotEqual(result['task_id'], self.tid)
        self.assertEqual(self.s.detail(self.sid)['current']['id'], current['id'])
        self.assertEqual(self.s.detail(self.sid)['review']['decision'], 'approve')
        with self.s.store._tx() as db:
            self.assertEqual(db.execute('SELECT processing_mode FROM web_dispatch WHERE task_id=?', (result['task_id'],)).fetchone()[0], 'model')
            self.assertEqual(db.execute('SELECT base_version_id FROM html_runs WHERE task_id=?', (result['task_id'],)).fetchone()[0], current['id'])
        with self.assertRaises(WorkflowError): self.s.dispatcher.reprocess_html(self.sid, current['id'], True)
        self.assertEqual(count(), before + 1)
