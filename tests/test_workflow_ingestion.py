import tempfile
import unittest
from pathlib import Path
from personalkb.workflow import load_config, import_file, run_once, export_version, make_store
from personalkb.workflow_store import WorkflowError

ROOT = Path(__file__).resolve().parent.parent

class IngestionTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = load_config()
        self.config.update(data_dir=str(self.path / 'data'), min_free_bytes=0)
        self.html = self.path / 'sample.html'
        self.html.write_text('<html><title>T</title><body><p>body</p><table><tr><td>A</td><td>B</td></tr></table><script>evil()</script><img src="https://example.com/x"></body></html>', encoding='utf8')

    def test_import_worker_export(self):
        source = import_file(self.config, self.html, True)
        self.assertTrue(import_file(self.config, self.html, True)['duplicate'])
        v = run_once(self.config)
        self.assertIn('body', v['result']['body'])
        self.assertIn('A', v['result']['body'])
        self.assertIn('B', v['result']['body'])
        self.assertNotIn('evil()', v['result']['body'])
        self.assertTrue(any('JavaScript' in x for x in v['result']['warnings']))
        self.assertFalse(make_store(self.config).eligible_sources())
        result = export_version(self.config, v['id'], Path(self.config['data_dir']) / 'exports')
        self.assertTrue(Path(result['path']).is_file())
        with self.assertRaises(FileExistsError): export_version(self.config, v['id'], Path(self.config['data_dir']) / 'exports')
        self.assertTrue(source['source']['sha256'])

    def test_rights_invalid(self):
        with self.assertRaises(WorkflowError): import_file(self.config, self.html)
        empty = self.path / 'empty.html'; empty.write_bytes(b'')
        with self.assertRaises(WorkflowError): import_file(self.config, empty, True)
        bad = self.path / 'bad.html'; bad.write_text('not html')
        with self.assertRaises(WorkflowError): import_file(self.config, bad, True)
        self.assertEqual(make_store(self.config).list_sources(), [])

    def test_disk_and_size(self):
        self.config['min_free_bytes'] = 10**30
        with self.assertRaises(WorkflowError): import_file(self.config, self.html, True)
        self.config.update(min_free_bytes=0, max_upload_bytes=1)
        with self.assertRaises(WorkflowError): import_file(self.config, self.html, True)

    def test_export_boundary(self):
        import_file(self.config, self.html, True); v = run_once(self.config)
        with self.assertRaises(WorkflowError): export_version(self.config, v['id'], self.path / 'outside')

    def test_deleted_no_restore(self):
        s = import_file(self.config, self.html, True)['source']
        make_store(self.config).delete_source(s['id'])
        with self.assertRaises(WorkflowError): import_file(self.config, self.html, True)

    def test_corrupt_blob(self):
        source = import_file(self.config, self.html, True)['source']
        (Path(self.config['data_dir']) / source['blob_relpath']).write_bytes(b'corrupt')
        with self.assertRaises(WorkflowError): import_file(self.config, self.html, True)
        self.assertEqual(run_once(self.config)['error'], 'source_integrity')

    def test_missing_bundle_can_retry_with_provider_result(self):
        import hashlib
        import json
        from tools.personal_review import FIELDS
        store = make_store(self.config)
        blob = b'video fixture'
        sha = hashlib.sha256(blob).hexdigest()
        originals = Path(self.config['data_dir']) / 'originals'
        originals.mkdir()
        (originals / sha).write_bytes(blob)
        imported = store.import_source('video', sha, 'sample.mp4', 'originals/' + sha)
        tid = imported['task']['id']
        self.assertEqual(run_once(self.config)['error'], 'video_bundle_required')
        self.assertEqual(store.get_task(tid)['status'], 'failed')
        self.assertEqual(store.get_task(tid)['stage'], 'loading_provider_result')
        store.retry(tid)
        item = {k: 'value' for k in FIELDS}
        item.update(source_sha256=sha, status='completed', provenance='provider', output_kind='machine_initial', duration_seconds=1, cost_cny=0)
        bundle = self.path / 'bundle.json'
        bundle.write_text(json.dumps({'items': [item]}), encoding='utf8')
        version = run_once(self.config, bundle_path=bundle)
        self.assertEqual(version['result']['provenance'], 'provider')
        self.assertEqual(store.get_task(tid)['status'], 'succeeded')

    def test_invalid_bundle_metadata(self):
        import json
        source = import_file(self.config, self.html, True)['source']
        store = make_store(self.config)
        with store._tx() as conn: conn.execute("UPDATE sources SET kind='video' WHERE id=?", (source['id'],))
        from tools.personal_review import FIELDS
        item = {k: 'value' for k in FIELDS}
        item.update(source_sha256=source['sha256'], status='completed', provenance='provider', output_kind='machine_initial', duration_seconds=True, cost_cny=0)
        bundle = self.path / 'bundle.json'; bundle.write_text(json.dumps({'items':[item]}))
        self.assertEqual(run_once(self.config, bundle_path=bundle)['error'], 'invalid_bundle')

    def test_invalid_encoding_and_huge_number(self):
        import json
        config = load_config()
        p = self.path / 'bad-config.json'
        config['html_encoding'] = 'base64_codec'
        p.write_text(json.dumps(config))
        with self.assertRaises(WorkflowError): load_config(p)
        config['html_encoding'] = 'utf-8'
        config['min_free_bytes'] = 10 ** 400
        p.write_text(json.dumps(config))
        with self.assertRaises(WorkflowError): load_config(p)

    def test_copy_replace_failure_cleans_staging(self):
        from unittest.mock import patch
        original = self.html.read_bytes()
        with patch('personalkb.workflow.os.replace', side_effect=OSError('failure')):
            with self.assertRaises(OSError): import_file(self.config, self.html, True)
        self.assertEqual(self.html.read_bytes(), original)
        self.assertEqual(make_store(self.config).list_sources(), [])
        self.assertEqual(list((Path(self.config['data_dir']) / 'originals').iterdir()), [])

    def test_db_failure_leaves_only_orphan_then_retry(self):
        import sqlite3
        from unittest.mock import patch
        with patch('personalkb.workflow.make_store', side_effect=sqlite3.OperationalError('failure')):
            with self.assertRaises(sqlite3.OperationalError): import_file(self.config, self.html, True)
        originals = list((Path(self.config['data_dir']) / 'originals').iterdir())
        self.assertEqual(originals, [])
        self.assertEqual(make_store(self.config).list_sources(), [])
        self.assertFalse(import_file(self.config, self.html, True)['duplicate'])

    def test_expired_video_reimport_preserves_missing_original(self):
        import sqlite3
        from contextlib import closing
        from unittest.mock import patch, Mock
        video = self.path / 'video.mp4'; video.write_bytes(b'0000ftypvideo')
        with patch('personalkb.workflow.shutil.which', return_value='ffmpeg'), patch('personalkb.workflow.subprocess.run', return_value=Mock(stderr=b'Stream Video:')):
            first = import_file(self.config, video, True)
            store = make_store(self.config)
            original = Path(self.config['data_dir']) / first['source']['blob_relpath']
            original.unlink()
            with closing(sqlite3.connect(store.db_path)) as db, db:
                db.execute('CREATE TABLE media_retention(source_id TEXT PRIMARY KEY, sha256 TEXT, blob_relpath TEXT, status TEXT, removed_at TEXT)')
                db.execute('INSERT INTO media_retention VALUES(?,?,?,?,NULL)', (first['source']['id'], first['source']['sha256'], first['source']['blob_relpath'], 'planned'))
            for status in ('planned', 'removed'):
                with closing(sqlite3.connect(store.db_path)) as db, db: db.execute('UPDATE media_retention SET status=?', (status,))
                again = import_file(self.config, video, True)
                self.assertTrue(again['duplicate'])
                self.assertEqual(first['source'], again['source'])
                self.assertEqual(first['task'], again['task'])
                self.assertFalse(original.exists())
            # Earlier databases also stored video sources as mp4 with a different path.
            legacy_path = 'originals/legacy-video.mp4'
            with closing(sqlite3.connect(store.db_path)) as db, db:
                db.execute("UPDATE sources SET kind='mp4', blob_relpath=? WHERE id=?", (legacy_path, first['source']['id']))
                db.execute('UPDATE media_retention SET blob_relpath=?', (legacy_path,))
            again = import_file(self.config, video, True)
            self.assertTrue(again['duplicate'])
            self.assertEqual(again['source'], store.get_source(first['source']['id']))
            self.assertEqual(again['task'], first['task'])
            self.assertEqual(len(store.list_sources()), 1)
            self.assertEqual(len(store.list_tasks()), 1)
            self.assertFalse(original.exists())
            self.assertFalse((Path(self.config['data_dir']) / legacy_path).exists())

    def test_reject_fake_mp4_directory_and_symlink(self):
        from unittest.mock import patch
        fake = self.path / 'fake.mp4'; fake.write_bytes(b'not an mp4')
        with patch('personalkb.workflow.shutil.which') as which:
            with self.assertRaises(WorkflowError): import_file(self.config, fake, True)
            which.assert_not_called()
        with self.assertRaises(WorkflowError): import_file(self.config, self.path, True)
        link = self.path / 'link.html'
        try: link.symlink_to(self.html)
        except OSError: return
        with self.assertRaises(WorkflowError): import_file(self.config, link, True)

    def test_invalid_config(self):
        p = self.path / 'config.json'; p.write_text('{}')
        with self.assertRaises(WorkflowError): load_config(p)

if __name__ == '__main__': unittest.main()
