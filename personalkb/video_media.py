import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''): h.update(chunk)
    return h.hexdigest()


def select_times(duration, cfg, scenes, strategy):
    if not math.isfinite(duration) or duration <= 0: raise RuntimeError('invalid_media_duration')
    last = max(0, duration - cfg['tail_margin_seconds'])
    if cfg['interval_seconds']:
        times = [min(last, .25 + i * cfg['interval_seconds']) for i in range(math.ceil(duration / cfg['interval_seconds']))]
    else:
        count = cfg['uniform_count']
        times = [min(last, max(.1, duration * i / (count - 1))) for i in range(count)]
    for _, value in sorted(scenes, reverse=True):
        value = min(last, max(.1, value + strategy['scene_settle_seconds']))
        if all(abs(value-old) >= strategy['frame_merge_gap_seconds'] for old in times): times.append(value)
        if len(times) >= cfg['uniform_count'] + cfg['scene_count']: break
    return sorted(set(round(t, 3) for t in times))[:cfg['max_frames']]


def _check(path, limits, heartbeat):
    import psutil
    heartbeat()
    mem = psutil.virtual_memory()
    if psutil.disk_usage(str(path)).free < limits['min_free_bytes'] or mem.available < limits['min_available_bytes'] or mem.total - mem.available > limits['max_host_used_bytes']:
        raise RuntimeError('resource_limit')


def _run(command, folder, limits, timeout, heartbeat, allow_failure=False, capture_stdout=False):
    _check(folder, limits, heartbeat)
    with tempfile.TemporaryFile(dir=folder) as log:
        process = subprocess.Popen(command, stdout=log if capture_stdout else subprocess.DEVNULL, stderr=log, shell=False)
        started = time.monotonic()
        try:
            while process.poll() is None:
                _check(folder, limits, heartbeat)
                if time.monotonic() - started > timeout: raise RuntimeError('media_timeout')
                time.sleep(limits['sample_interval_seconds'])
        except BaseException:
            process.terminate()
            try: process.wait(timeout=limits['terminate_grace_seconds'])
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            raise
        log.seek(0, os.SEEK_END)
        log.seek(max(0, log.tell() - 4 * 1024 * 1024))
        output = log.read(4 * 1024 * 1024).decode('utf8', 'replace')
        if process.returncode and not allow_failure: raise RuntimeError('media_command_failed')
        return output


def _seconds(value, default=None):
    if value in (None, 'N/A'):
        return default
    seconds = float(value)
    if not math.isfinite(seconds):
        raise ValueError()
    return seconds


def _stream_duration(stream):
    duration = _seconds(stream.get('duration'))
    if duration is not None:
        return duration
    ticks = _seconds(stream.get('duration_ts'))
    if ticks is not None and stream.get('time_base'):
        numerator, denominator = map(int, stream['time_base'].split('/'))
        return ticks * numerator / denominator
    return None


def _media_timelines(base, source, folder, limits, timeout, heartbeat):
    def run(command, **options):
        return _run(command, folder, limits, timeout, heartbeat, **options)

    ffmpeg_path = Path(base[0])
    probe = str(ffmpeg_path.with_name('ffprobe.exe' if ffmpeg_path.suffix.lower() == '.exe' else 'ffprobe'))
    try:
        text = run([probe, '-v', 'error', '-show_entries',
                    'stream=codec_type,start_time,duration,duration_ts,time_base:format=start_time,duration',
                    '-of', 'json', str(source)], capture_stdout=True)
    except FileNotFoundError:
        # Older local installations may only provide FFmpeg.
        info = run(base + ['-i', str(source), '-t', '0', '-f', 'null', '-'])
        elapsed = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', info)
        if not elapsed:
            raise RuntimeError('media_missing_duration') from None
        duration = int(elapsed[1])*3600 + int(elapsed[2])*60 + float(elapsed[3])
        if not re.search(r'Stream #.*Video:', info):
            raise RuntimeError('media_missing_video') from None
        has_audio = bool(re.search(r'Stream #.*Audio:', info))
        video_start, video_duration, audio_duration = 0, None, None
    else:
        try:
            metadata = json.loads(text)
            container = metadata.get('format', {})
            duration = _seconds(container.get('duration'))
            if duration is None or duration <= 0:
                raise RuntimeError('media_missing_duration')
            streams = metadata['streams']
            video = next((stream for stream in streams if stream['codec_type'] == 'video'), None)
            if video is None:
                raise RuntimeError('media_missing_video')
            audio = [stream for stream in streams if stream['codec_type'] == 'audio']
            has_audio = bool(audio)
            audio_duration = _stream_duration(audio[0]) if len(audio) == 1 else None
            start = _seconds(container.get('start_time'), 0)
            video_start = max(0, _seconds(video.get('start_time'), start) - start)
            video_duration = _stream_duration(video)
        except (ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
            raise RuntimeError('media_video_timeline_invalid') from None
    if video_duration is None:
        log = run(base + ['-i', str(source), '-map', '0:v:0', '-an', '-vf', 'showinfo', '-f', 'null', '-'])
        stamps = [float(x) for x in re.findall(r'pts_time:([-+0-9.eE]+)', log)]
        if not stamps:
            raise RuntimeError('media_video_timeline_invalid')
        # The final decoded frame time is a conservative bound when duration is absent.
        video_duration = max(stamps) - video_start
        if video_duration == 0:
            video_duration = duration - video_start
    video_duration = min(video_duration, duration - video_start)
    if not math.isfinite(video_duration) or video_duration <= 0:
        raise RuntimeError('media_video_timeline_invalid')
    return duration, has_audio, audio_duration, video_start, video_duration


def _prepare_media(source_path, work_dir, workflow_config, pipeline_config, *, heartbeat):
    source = Path(source_path).resolve(strict=True)
    folder = Path(work_dir).resolve(); folder.mkdir(parents=True, exist_ok=True)
    strategy, limits = pipeline_config['strategy'], pipeline_config['resources']
    ffmpeg = workflow_config['ffmpeg']; timeout = strategy['media_timeout_seconds']
    source_sha = _sha(source)
    profile = next((item['profile'] for item in strategy['items'] if item['sha256'] == source_sha), pipeline_config['default_profile'])
    cfg = strategy['profiles'][profile]
    signature = hashlib.sha256(json.dumps({'source':source_sha, 'strategy':strategy, 'profile':profile}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    manifest = folder / 'media-manifest.json'
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding='utf8'))
        if data.get('signature') != signature: raise RuntimeError('media_cache_changed')
        for entry in ([data['audio']] if data.get('audio') else []) + data['frames']:
            path = (folder / entry['file']).resolve()
            if path.parent != folder or not path.is_file() or _sha(path) != entry['sha256']: raise RuntimeError('media_cache_changed')
        audio_entry = data.get('audio')
        if audio_entry:
            with wave.open(str(folder / audio_entry['file']), 'rb') as cached_audio:
                actual_seconds = cached_audio.getnframes() / cached_audio.getframerate()
                if cached_audio.getframerate() != strategy['audio_sample_rate'] or cached_audio.getnchannels() != strategy['audio_channels'] or cached_audio.getsampwidth() != 2:
                    raise RuntimeError('media_cache_changed')
            audio_duration = data.get('audio_track_seconds', data['duration_seconds'])
            if (not math.isfinite(data['audio_seconds']) or abs(actual_seconds - data['audio_seconds']) > 1 / strategy['audio_sample_rate']
                    or (audio_duration is not None and abs(actual_seconds - audio_duration) > strategy['audio_duration_tolerance_seconds'])):
                raise RuntimeError('media_cache_changed')
        elif 'video_duration_seconds' not in data or data['audio_seconds'] != 0:
            raise RuntimeError('media_cache_changed')
        frames = data['frames']
        times = [entry['seconds'] for entry in frames]
        video_duration = data.get('video_duration_seconds', data['duration_seconds'])
        video_start = data.get('video_start_seconds', 0)
        expected = [round(video_start + t, 3) for t in select_times(video_duration, cfg, [], strategy)]
        if not frames or len(frames) > cfg['max_frames'] or times != sorted(set(times)) or any(type(t) not in (int, float) or not math.isfinite(t) or not video_start <= t < video_start + video_duration for t in times) or any(not any(abs(t-u) < .002 for t in times) for u in expected): raise RuntimeError('media_cache_changed')
        if [entry['index'] for entry in frames] != list(range(len(frames))): raise RuntimeError('media_cache_changed')
        _check(folder, limits, heartbeat)
        return {'audio_path':str(folder / audio_entry['file']) if audio_entry else None, 'audio_seconds':data['audio_seconds'], 'duration_seconds':data['duration_seconds'], 'frames':[{'index':x['index'],'seconds':x['seconds'],'path':str(folder / x['file']),'sha256':x['sha256']} for x in data['frames']]}
    base = [ffmpeg, '-hide_banner', '-threads', str(limits['ffmpeg_threads']), '-filter_threads', str(limits['filter_threads'])]
    duration, has_audio, audio_duration, video_start, video_duration = _media_timelines(base, source, folder, limits, timeout, heartbeat)
    audio = folder / 'audio.wav'
    audio_seconds = 0
    if has_audio:
        _run(base + ['-v','error','-i',str(source),'-vn','-ac',str(strategy['audio_channels']),'-ar',str(strategy['audio_sample_rate']),'-y',str(audio)], folder, limits, timeout, heartbeat)
        with wave.open(str(audio), 'rb') as w: audio_seconds = w.getnframes()/w.getframerate()
        if audio_seconds <= 0 or (audio_duration is not None and abs(audio_seconds-audio_duration) > strategy['audio_duration_tolerance_seconds']):
            raise RuntimeError('audio_not_full_length')
    scenes = []
    if cfg['scene_count']:
        log = _run(base + ['-i',str(source),'-map','0:v:0','-an','-vf',f'scale={strategy["scene_analysis_width"]}:-2,select=gt(scene\\,{strategy["scene_threshold"]}),metadata=print','-f','null','-'], folder, limits, timeout, heartbeat)
        pending = None
        for line in log.splitlines():
            m = re.search(r'pts_time:([0-9.]+)', line)
            if m: pending = float(m[1])
            m = re.search(r'lavfi.scene_score=([0-9.]+)', line)
            if m and pending is not None: scenes.append((float(m[1]),pending))
    frames=[]
    for index, seconds in enumerate([round(video_start + t, 3) for t in select_times(video_duration,cfg,[(score, t - video_start) for score, t in scenes],strategy)]):
        target=folder / f'frame-{index:03}.jpg'
        _run(base + ['-v','error','-ss',str(seconds),'-i',str(source),'-map','0:v:0','-frames:v','1','-vf',f'scale=min({strategy["frame_max_width"]}\\,iw):-2','-pix_fmt',strategy['jpeg_pixel_format'],'-color_range',strategy['jpeg_color_range'],'-strict',str(strategy['jpeg_compliance']),'-q:v',str(strategy['jpeg_quality']),'-y',str(target)], folder, limits, timeout, heartbeat)
        if not target.is_file() or not target.read_bytes().startswith(b'\xff\xd8\xff'): raise RuntimeError('invalid_frame')
        frames.append({'index':index,'seconds':seconds,'file':target.name,'sha256':_sha(target)})
    if not frames: raise RuntimeError('empty_frames')
    data={'signature':signature,'audio':{'file':audio.name,'sha256':_sha(audio)} if has_audio else None,'audio_track_seconds':audio_duration,'video_start_seconds':video_start,'video_duration_seconds':video_duration,'audio_seconds':audio_seconds,'duration_seconds':duration,'frames':frames}
    manifest.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    return {'audio_path':str(audio) if has_audio else None,'audio_seconds':audio_seconds,'duration_seconds':duration,'frames':[{'index':x['index'],'seconds':x['seconds'],'path':str(folder / x['file']),'sha256':x['sha256']} for x in frames]}


def prepare_media(source_path, work_dir, workflow_config, pipeline_config, *, heartbeat):
    folder = Path(work_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / '.media.lock'
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError('media_workdir_busy') from None
    try:
        os.close(fd)
        if not (folder / 'media-manifest.json').exists() and ((folder / 'audio.wav').exists() or any(folder.glob('frame-*.jpg'))):
            raise RuntimeError('media_workdir_unverified')
        if (folder / 'media-manifest.json').is_file():
            return _prepare_media(source_path, folder, workflow_config, pipeline_config, heartbeat=heartbeat)
        with tempfile.TemporaryDirectory(dir=folder, prefix='.media-preparing-') as staging:
            stage = Path(staging)
            material = _prepare_media(source_path, stage, workflow_config, pipeline_config, heartbeat=heartbeat)
            for asset in stage.iterdir():
                if asset.name != 'media-manifest.json':
                    asset.replace(folder / asset.name)
            (stage / 'media-manifest.json').replace(folder / 'media-manifest.json')
            if material['audio_path'] is not None:
                material['audio_path'] = str(folder / Path(material['audio_path']).name)
            for frame in material['frames']:
                frame['path'] = str(folder / Path(frame['path']).name)
            return material
    finally:
        lock.unlink(missing_ok=True)
