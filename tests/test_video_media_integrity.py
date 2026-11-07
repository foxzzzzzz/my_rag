import hashlib, json, tempfile, unittest, wave
from pathlib import Path
from personalkb.video_pipeline import load_pipeline_config
from personalkb.video_media import _prepare_media

class MediaIntegrityTests(unittest.TestCase):
    def test_cached_audio_duration_tampering_rejected(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d); source=root/'source.mp4'; source.write_bytes(b'video'); work=root/'work'; work.mkdir()
            pc=load_pipeline_config(); strategy=pc['strategy']; source_sha=hashlib.sha256(b'video').hexdigest()
            profile=next((x['profile'] for x in strategy['items'] if x['sha256']==source_sha),pc['default_profile'])
            signature=hashlib.sha256(json.dumps({'source':source_sha,'strategy':strategy,'profile':profile},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            audio=work/'audio.wav'
            with wave.open(str(audio),'wb') as w:
                w.setnchannels(strategy['audio_channels']); w.setsampwidth(2); w.setframerate(strategy['audio_sample_rate'])
                w.writeframes(b'\0' * (120*strategy['audio_sample_rate']*strategy['audio_channels']*2))
            frame=work/'frame.jpg'; frame.write_bytes(b'frame')
            manifest={'signature':signature,'audio':{'file':'audio.wav','sha256':hashlib.sha256(audio.read_bytes()).hexdigest()},'audio_seconds':1,'duration_seconds':1,'frames':[{'index':0,'seconds':0,'file':'frame.jpg','sha256':hashlib.sha256(b'frame').hexdigest()}]}
            (work/'media-manifest.json').write_text(json.dumps(manifest),encoding='utf8')
            with self.assertRaisesRegex(RuntimeError,'media_cache_changed'):
                _prepare_media(source,work,{'ffmpeg':'ffmpeg'},pc,heartbeat=lambda:None)
