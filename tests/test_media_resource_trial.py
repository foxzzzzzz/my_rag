import hashlib
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tmp/benchmark-deps'))
import media_resource_trial as trial


class TrialTests(unittest.TestCase):
    def test_cleanup_boundary_and_unregistered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); work = root / 'work'; work.mkdir()
            registered = work / 'registered'; registered.write_text('x')
            other = work / 'other'; other.write_text('x')
            outside = root / 'outside'; outside.write_text('x')
            self.assertEqual(trial.cleanup_generated(work, [registered, outside]), 1)
            self.assertTrue(other.exists() and outside.exists())

    def test_source_hash_changed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(trial, 'ROOT', Path(directory)):
            (trial.ROOT / 'source').write_bytes(b'changed')
            source = {'id': 'a', 'path': 'source', 'sha256': hashlib.sha256(b'original').hexdigest(), 'duration_seconds': 1, 'frame_seconds': [0]}
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                trial.validate_sources([source])

    def test_missing_ffmpeg_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(trial, 'ROOT', Path(directory)):
            root = Path(directory); (root / 'source').write_bytes(b'x')
            config = {'sources': [{'id': 'a', 'path': 'source', 'sha256': hashlib.sha256(b'x').hexdigest(), 'duration_seconds': 1, 'frame_seconds': [0]}], 'output_base': 'reports', 'cleanup': True}
            path = root / 'config.json'; path.write_text(json.dumps(config))
            output = root / 'run'
            self.assertEqual(trial.main(['--config', str(path), '--output', str(output), '--ffmpeg', 'definitely-missing-ffmpeg']), 1)
            self.assertIn('missing ffmpeg', json.loads((output / 'report.json').read_text())['summary']['error'])

    def test_audio_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b'\0\0' * 8000)
            self.assertEqual(trial.audio_duration(path), 0.5)

    def test_progress_and_missing_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); progress = root / 'progress'
            progress.write_text('frame=5\nout_time_us=10000000\nprogress=end\n')
            self.assertTrue(trial.parse_decode_progress(progress, 10, 1)['valid'])
            progress.write_text('frame=5\nout_time_us=10000000\nprogress=continue\n')
            self.assertFalse(trial.parse_decode_progress(progress, 10, 1)['valid'])
            stage = {'status': 'completed'}
            trial.record_frame(stage, root / 'missing')
            self.assertEqual(stage['stop_reason'], 'missing_or_empty_frame')

    def test_symlink_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); work = root / 'work'; work.mkdir()
            outside = root / 'outside'; outside.write_text('keep')
            link = work / 'link'
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest('symlink creation unavailable')
            self.assertEqual(trial.cleanup_generated(work, [link]), 0)
            self.assertEqual(outside.read_text(), 'keep')

    def test_user_interrupt_stage_retained(self):
        import media_resource_monitor as monitor
        with tempfile.TemporaryDirectory() as directory, patch.object(trial, 'ROOT', Path(directory)):
            root = Path(directory); (root / 'source').write_bytes(b'x')
            config = {'sources': [{'id': 'a', 'path': 'source', 'sha256': hashlib.sha256(b'x').hexdigest(), 'duration_seconds': 1, 'frame_seconds': [0]}], 'output_base': 'reports', 'cleanup': True, 'ffmpeg': {'threads': 2, 'filter_threads': 1, 'filter_complex_threads': 1}, 'limits': {}}
            path = root / 'config.json'; path.write_text(json.dumps(config))
            sample = {'host_total': 1, 'host_available': 1, 'host_used_proxy': 0, 'swap_used': 0, 'disk_free': 1, 'tree_rss': 1}
            with patch.object(monitor, 'sample_resources', return_value=sample), patch.object(monitor, 'run_command', return_value={'status': 'interrupted_by_user', 'samples': [], 'stop_reason': 'keyboard_interrupt'}), patch.object(trial.shutil, 'which', return_value='ffmpeg'):
                self.assertEqual(trial.main(['--config', str(path), '--output', str(root / 'run')]), 1)
            report = json.loads((root / 'run/report.json').read_text())
            self.assertEqual(report['stages'][0]['status'], 'interrupted_by_user')


if __name__ == '__main__':
    unittest.main()
