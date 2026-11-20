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
        self.assertEqual(select_times(.04,self.strategy['profiles']['dense_screen'],[],self.strategy), [0])
    def test_cache_tampering(self):
        with TemporaryDirectory(dir='tmp') as d:
            folder=Path(d); source=folder/'source'; source.write_bytes(b'x')
            (folder/'media-manifest.json').write_text('{"signature":"wrong"}')
            with self.assertRaisesRegex(RuntimeError,'media_cache_changed'): prepare_media(source,folder,{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
    def test_no_audio(self):
        with TemporaryDirectory(dir='tmp') as d:
            source=Path(d)/'source'; source.write_bytes(b'x')
            def run(command, *args, **kwargs):
                if command[0] == 'ffprobe':
                    return json.dumps({'format':{'duration':'10.0'}, 'streams':[{'codec_type':'video','start_time':'0','duration':'9.8'}]})
                if str(command[-1]).endswith('.jpg'):
                    Path(command[-1]).write_bytes(b'\xff\xd8\xffframe')
                return 'Duration: 00:00:10.0\nStream #0:0: Video: h264'
            with patch('personalkb.video_media._run',side_effect=run), patch('personalkb.video_media._check'):
                first=prepare_media(source,Path(d)/'work',{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
                second=prepare_media(source,Path(d)/'work',{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
            self.assertIsNone(first['audio_path']); self.assertEqual(first['audio_seconds'],0)
            self.assertEqual(first,second)
            self.assertTrue(all(f['seconds'] < 9.8 for f in first['frames']))
    def test_video_track_shorter_than_audio(self):
        import wave
        with TemporaryDirectory(dir='tmp') as d:
            source=Path(d)/'source'; source.write_bytes(b'x')
            def run(command, *args, **kwargs):
                if command[0] == 'ffprobe':
                    return json.dumps({'format':{'duration':'270.71'}, 'streams':[
                        {'codec_type':'video', 'duration':'270.466667'}, {'codec_type':'audio', 'duration':'270.71'}]})
                target=Path(command[-1])
                if target.suffix == '.wav':
                    with wave.open(str(target), 'wb') as w:
                        w.setnchannels(self.strategy['audio_channels']); w.setsampwidth(2); w.setframerate(self.strategy['audio_sample_rate'])
                        w.writeframes(b'\0' * (round(270.71*self.strategy['audio_sample_rate'])*self.strategy['audio_channels']*2))
                elif target.suffix == '.jpg':
                    target.write_bytes(b'\xff\xd8\xffframe')
                return 'Duration: 00:04:30.71\nStream #0:0: Video: h264\nStream #0:1: Audio: aac'
            with patch('personalkb.video_media._run',side_effect=run), patch('personalkb.video_media._check'):
                material=prepare_media(source,Path(d)/'work',{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
                cached=prepare_media(source,Path(d)/'work',{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
            self.assertEqual(material,cached)
            self.assertAlmostEqual(material['audio_seconds'],270.71,places=2)
            self.assertTrue(all(f['seconds'] < 270.466667 for f in material['frames']))
    def test_short_audio_track_and_failed_preparation_do_not_poison_workspace(self):
        import wave
        with TemporaryDirectory(dir='tmp') as d:
            source=Path(d)/'source'; source.write_bytes(b'x')
            work=Path(d)/'work'
            fail = True
            def run(command, *args, **kwargs):
                if command[0] == 'ffprobe':
                    return json.dumps({'format':{'duration':'8'}, 'streams':[
                        {'codec_type':'video','duration':'8'}, {'codec_type':'audio','duration':'1'}]})
                target=Path(command[-1])
                if target.suffix == '.wav':
                    with wave.open(str(target), 'wb') as audio:
                        audio.setnchannels(self.strategy['audio_channels']); audio.setsampwidth(2)
                        audio.setframerate(self.strategy['audio_sample_rate'])
                        audio.writeframes(b'\0' * (self.strategy['audio_sample_rate'] * self.strategy['audio_channels'] * 2))
                if target.suffix == '.jpg' and not fail:
                    target.write_bytes(b'\xff\xd8\xffframe')
                return ''
            with patch('personalkb.video_media._run',side_effect=run), patch('personalkb.video_media._check'):
                with self.assertRaisesRegex(RuntimeError, 'invalid_frame'):
                    prepare_media(source,work,{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
                self.assertEqual(list(work.iterdir()), [])
                fail = False
                material=prepare_media(source,work,{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
                self.assertEqual(material,prepare_media(source,work,{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None))
            self.assertEqual(material['audio_seconds'],1)
    def test_partial_cache_is_refused(self):
        with TemporaryDirectory(dir='tmp') as d:
            root=Path(d); source=root/'source'; source.write_bytes(b'x')
            work=root/'work'; work.mkdir(); (work/'audio.wav').write_bytes(b'partial')
            with self.assertRaisesRegex(RuntimeError, 'media_workdir_unverified'):
                prepare_media(source,work,{'ffmpeg':'ffmpeg'},self.cfg,heartbeat=lambda:None)
            self.assertEqual((work/'audio.wav').read_bytes(), b'partial')
    def test_cancel_stops_process(self):
        process=MagicMock(); process.poll.return_value=None
        with TemporaryDirectory(dir='tmp') as d, patch('personalkb.video_media.subprocess.Popen',return_value=process), patch('personalkb.video_media._check',side_effect=[None,RuntimeError('cancel')]):
            with self.assertRaisesRegex(RuntimeError,'cancel'): _run(['ffmpeg'],d,self.limits,5,lambda:None)
            process.terminate.assert_called_once()
