import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class WorkflowCLITest(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.root = Path(self.tmp.name)
        config = json.loads((ROOT / 'config/workflow.json').read_text(encoding='utf-8'))
        config.update(data_dir=str(self.root / 'data'), min_free_bytes=0)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps(config), encoding='utf-8')
        self.html = self.root / 'sample.html'
        self.html.write_text('<html><body><h1>Title</h1><p>Real text here.</p></body></html>', encoding='utf-8')
    def tearDown(self): self.tmp.cleanup()
    def cli(self, *args, ok=True):
        p = subprocess.run([sys.executable, '-m', 'tools.workflow_cli', '--config', str(self.config), *map(str,args)], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0 if ok else 2, p.stderr)
        return json.loads(p.stdout if ok else p.stderr)
    def imported(self): return self.cli('import', self.html, '--rights-confirmed')
    def processed(self):
        source = self.imported()['source']['id']
        self.cli('work-once')
        return source, self.cli('show', source)['current']
    def review(self, source, version, score, decision, ok=True):
        return self.cli('review', source, '--version', version['id'], '--sha256', version['content_sha256'], '--score', score, '--decision', decision, '--reviewer', 'test', ok=ok)
    def test_init_and_lists(self):
        self.cli('init'); self.assertEqual(self.cli('sources'), []); self.assertEqual(self.cli('tasks'), [])
    def test_rights_and_duplicate(self):
        self.cli('import', self.html, ok=False)
        a = self.imported(); b = self.imported()
        self.assertTrue(b['duplicate']); self.assertEqual(a['source']['id'], b['source']['id'])
    def test_work_and_pending(self):
        source, v = self.processed(); self.assertIsNotNone(v); self.assertEqual(self.cli('eligible'), [])
    def test_review_and_revoke(self):
        source, v = self.processed(); self.review(source, v, 97, 'approve', ok=False)
        self.review(source, v, 99, 'approve'); self.assertEqual(len(self.cli('eligible')), 1)
        self.review(source, v, 99, 'reject'); self.assertEqual(self.cli('eligible'), [])
    def test_revise_old_review(self):
        source, v = self.processed(); path = self.root / 'result.json'; result = v['result']; result['output_kind'] = 'human_edited'; result['provenance'] = 'human_edited'; path.write_text(json.dumps(result), encoding='utf-8')
        self.cli('revise', source, '--expected-version', v['id'], '--result', path)
        self.review(source, v, 99, 'approve', ok=False)
    def test_export(self):
        source, v = self.processed(); self.cli('export', '--version', v['id'], '--output-dir', self.root / 'data' / 'exports')
    def test_cancel_retry_delete(self):
        item = self.imported(); self.cli('cancel', item['task']['id']); self.cli('retry', item['task']['id']); self.cli('delete', item['source']['id'])
    def test_worker_failure_is_error(self):
        item = self.imported()
        (self.root / 'data' / item['source']['blob_relpath']).write_text('tampered', encoding='utf-8')
        error = self.cli('work-once', ok=False)
        self.assertEqual(error, {'task_id': item['task']['id'], 'error': 'source_integrity'})
    def test_database_error_is_safe(self):
        self.cli('init')
        (self.root / 'data' / 'workflow.sqlite3').write_bytes(b'not a database')
        self.assertEqual(self.cli('tasks', ok=False), {'error': 'database_error'})
    def test_safe_errors(self):
        self.assertEqual(self.cli('show', 'missing', ok=False)['error'], 'source_not_found')
        self.cli('unknown', ok=False)
        self.cli('revise', 'x', '--expected-version', 'x', '--result', self.root / 'missing', ok=False)

if __name__ == '__main__': unittest.main()



