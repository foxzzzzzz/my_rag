import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock
from personalkb.video_media import select_times, prepare_media, _run

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.strategy=json.loads(Path('config/demo-run.json').read_text(encoding='utf8'))
        self.limits={'ffmpeg_threads':2,'filter_threads':1,'min_free_bytes':0,'min_available_bytes':0,'max_host_used_bytes':10**20,'sample_interval_seconds':0.001,'terminate_grace_seconds':1}
        self.cfg={'strategy':self.strategy,'resources':self.limits,'default_profile':'screen_tutorial'}
    def test_coverage(self):
        times=select_times(20,self.strategy['profiles']['dense_screen'],[],self.strategy)
        self.assertEqual(len(times),20); self.assertLess(times[0],1); self.assertGreater(times[-1],19)
    def test_cache_tampering(self):
        with TemporaryDirectory(dir='tmp') as d:
            folder=Path(d); source=folder/'source'; source.write_bytes(b'x')
            (folder/'media-manifest.json').write_text('{"signature":"wrong"}')
            with self.assertRaisesRegex(RuntimeError,'media_cache_changed'): prepare_media(source,folder,{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
    def test_no_audio(self):
        with TemporaryDirectory(dir='tmp') as d:
            source=Path(d)/'source'; source.write_bytes(b'x')
            with patch('personalkb.video_media._run',return_value='Duration: 00:00:10.0'):
                with self.assertRaisesRegex(RuntimeError,'media_missing_audio'): prepare_media(source,Path(d)/'work',{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
    def test_cancel_stops_process(self):
        process=MagicMock(); process.poll.return_value=None
        with TemporaryDirectory(dir='tmp') as d, patch('personalkb.video_media.subprocess.Popen',return_value=process), patch('personalkb.video_media._check',side_effect=[None,RuntimeError('cancel')]):
            with self.assertRaisesRegex(RuntimeError,'cancel'): _run(['ffmpeg'],d,self.limits,5,lambda:None)
            process.terminate.assert_called_once()
