import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tmp' / 'benchmark-deps'))
from tools.media_resource_monitor import run_command

LIMITS = dict(interval_seconds=0.01, timeout_seconds=0.2, min_available_memory_bytes=1,
              min_free_disk_bytes=1, max_host_used_bytes=100, terminate_grace_seconds=1)
SAMPLE = dict(host_available=10, disk_free=10, host_used_proxy=10)

class MonitorTests(unittest.TestCase):
    def run_case(self, code, **kwargs):
        with tempfile.TemporaryDirectory() as directory, patch('tools.media_resource_monitor.sample_resources', return_value=SAMPLE):
            return run_command([sys.executable, '-c', code], Path(directory)/'stderr.log', Path(directory), LIMITS, **kwargs)

    def test_success(self):
        self.assertEqual(self.run_case('pass')['status'], 'completed')

    def test_timeout(self):
        self.assertEqual(self.run_case('import time; time.sleep(5)')['status'], 'timeout')

    def test_cancel(self):
        self.assertEqual(self.run_case('import time; time.sleep(5)', cancel_after_seconds=0.03)['status'], 'interrupted')

    def test_baseline_stops_before_spawn(self):
        with tempfile.TemporaryDirectory() as directory, patch('tools.media_resource_monitor.sample_resources', return_value={**SAMPLE, 'disk_free': 0}), patch('tools.media_resource_monitor.subprocess.Popen') as popen:
            result = run_command(['unused'], Path(directory)/'stderr.log', Path(directory), LIMITS)
            self.assertEqual(result['status'], 'resource_stop')
            popen.assert_not_called()

if __name__ == '__main__':
    unittest.main()

class AdditionalMonitorTests(unittest.TestCase):
    def test_resource_crossing(self):
        with tempfile.TemporaryDirectory() as directory, patch('tools.media_resource_monitor.sample_resources', side_effect=[SAMPLE, {**SAMPLE, 'disk_free': 0}, SAMPLE]):
            result = run_command([sys.executable, '-c', 'import time; time.sleep(5)'], Path(directory)/'log', Path(directory), LIMITS)
            self.assertEqual(result['status'], 'resource_stop')
            self.assertTrue(result['termination']['verified'])

    def test_unrelated_process_survives(self):
        import subprocess
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
        try:
            with tempfile.TemporaryDirectory() as directory, patch('tools.media_resource_monitor.sample_resources', return_value=SAMPLE):
                result = run_command([sys.executable, '-c', 'import time; time.sleep(5)'], Path(directory)/'log', Path(directory), LIMITS)
                self.assertEqual(result['status'], 'timeout')
                self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate()
            sentinel.wait()

    @unittest.skipIf(sys.platform == 'win32', 'POSIX process group test')
    def test_stubborn_descendant(self):
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)']); time.sleep(10)"
        with tempfile.TemporaryDirectory() as directory, patch('tools.media_resource_monitor.sample_resources', return_value=SAMPLE):
            result = run_command([sys.executable, '-c', code], Path(directory)/'log', Path(directory), LIMITS)
            self.assertIn(result['status'], ('timeout', 'failed'))
            if result['status'] == 'failed':
                self.assertFalse(result['termination']['verified'])
