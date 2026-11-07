import importlib.util
import unittest
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('probe', 'tools/server_probe.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
class Tests(unittest.TestCase):
 def test_mem(self):
  self.assertEqual(p.parse_mem('MemTotal: 1024 kB\nMemAvailable: 512 kB\nSwapTotal: 0 kB')['MemTotal'], 1048576)
 def test_disk(self):
  self.assertTrue(p.disk_ok(40, 8, 40, 8)); self.assertFalse(p.disk_ok(39, 8, 40, 8))
 def test_cgroup(self):
  self.assertEqual(p.parse_cpu('200000 100000'), 2); self.assertIsNone(p.parse_cpu('max 100000')); self.assertIsNone(p.parse_limit('max'))
 def test_network(self):
  with patch.object(p, 'http_status', return_value=401):
   self.assertEqual(p.network_result('https://pypi.org/simple/sqlite-vec/', 2)['reachable'], True)
 def test_http_error_closed(self):
  import urllib.error
  from unittest.mock import MagicMock
  error = urllib.error.HTTPError('https://pypi.org/', 401, 'unauthorized', {}, None)
  self.addCleanup(error.close)
  error.close = MagicMock()
  with patch.object(p.urllib.request, 'build_opener') as opener:
   opener.return_value.open.side_effect = error
   self.assertEqual(p.http_status('https://pypi.org/', 2), 401)
  error.close.assert_called_once()
 def test_nested_limits_and_affinity(self):
  values = {'/proc/self/cgroup': '0::/a/b', '/sys/fs/cgroup/a/b/cpu.max': '400000 100000', '/sys/fs/cgroup/a/cpu.max': 'max 100000', '/sys/fs/cgroup/a/memory.max': 'max', '/sys/fs/cgroup/cpu.max': '800000 100000', '/sys/fs/cgroup/a/b/memory.max': '4000', '/sys/fs/cgroup/memory.max': '8000'}
  with patch.object(p, 'read', side_effect=lambda path: values.get(path)), patch.object(p.os.path, 'realpath', side_effect=lambda path: path.replace('\\', '/')), patch.object(p.os.path, 'join', side_effect=lambda a, b: a + '/' + b), patch.object(p.os.path, 'dirname', side_effect=lambda path: path.rsplit('/', 1)[0]), patch.object(p.os, 'sep', '/'):
   c = p.cgroups()
  self.assertTrue(c['reliable']); self.assertEqual(c['cpu_quota_cores'], 4); self.assertEqual(c['memory_limit_bytes'], 4000)
  self.assertEqual(p.effective_cpu(8, 2, c), 2)
 def test_unresolved(self):
  with patch.object(p, 'read', return_value=None): c = p.cgroups()
  self.assertFalse(c['reliable']); self.assertIsNone(p.effective_cpu(8, 2, c))
if __name__ == '__main__': unittest.main()
