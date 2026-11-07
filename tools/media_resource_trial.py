import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def validate_sources(sources):
    result, seen = [], set()
    for source in sources:
        ident = source['id']
        path = (ROOT / source['path']).resolve()
        if not isinstance(ident, str) or not ident or ident in seen or not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('invalid, duplicate, missing or outside source: ' + str(ident))
        seen.add(ident)
        actual = digest(path)
        if actual.lower() != source['sha256'].lower():
            raise ValueError('source hash mismatch: ' + ident)
        if source['duration_seconds'] <= 0 or any(t < 0 or t >= source['duration_seconds'] for t in source['frame_seconds']):
            raise ValueError('invalid source timing: ' + ident)
        result.append({'id': ident, 'path': str(path), 'sha256': actual})
    if not result:
        raise ValueError('no sources configured')
    return result


def cleanup_generated(work, paths):
    work = work.resolve()
    removed = 0
    for item in paths:
        path = Path(item)
        resolved = path.resolve()
        if resolved != work and resolved.is_relative_to(work) and path.is_file() and not path.is_symlink():
            path.unlink()
            removed += 1
    return removed


def audio_duration(path):
    with wave.open(str(path), 'rb') as wav:
        return wav.getnframes() / wav.getframerate()



def parse_decode_progress(path, duration, tolerance):
    values = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                values[key] = value
    try:
        frames = int(values.get('frame', '0'))
        elapsed_us = int(values.get('out_time_us', '0'))
    except ValueError:
        frames, elapsed_us = 0, 0
    return {'decoded_frames': frames, 'out_time_us': elapsed_us,
            'progress': values.get('progress'),
            'valid': values.get('progress') == 'end' and frames > 0 and elapsed_us / 1_000_000 >= duration - tolerance}


def record_frame(stage, path):
    if not path.is_file() or path.stat().st_size == 0:
        stage.update(status='failed', stop_reason='missing_or_empty_frame')
        return
    stage.update(bytes=path.stat().st_size, sha256=digest(path))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(ROOT / 'config/media-resource.json'))
    parser.add_argument('--output')
    parser.add_argument('--ffmpeg')
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    dep = config.get('dependencies')
    if dep:
        sys.path.insert(0, str(ROOT / dep))
    try:
        from media_resource_monitor import run_command, sample_resources
    except ModuleNotFoundError as exc:
        if exc.name == 'psutil':
            raise SystemExit('Missing psutil; install with: python -m pip install --target tmp/media-deps psutil') from exc
        raise
    runid = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    run = Path(args.output) if args.output else ROOT / config['output_base'] / runid
    run.mkdir(parents=True, exist_ok=False)
    work, logs = run / 'work', run / 'logs'
    work.mkdir(); logs.mkdir()
    generated, stages = [], []
    report = {'scope': 'offline_media_resource_trial_not_full_production_acceptance', 'environment': {}, 'runid': runid, 'configuration': config, 'sourcevalidation': [], 'stages': stages, 'summary': {}, 'remaining_scope': ['No real ASR or vision-language network calls', 'Business health and response not tested', 'Production queue and admission control not tested']}
    before = after = None
    interrupted = False
    error = None
    try:
        report['sourcevalidation'] = validate_sources(config['sources'])
        ffmpeg = args.ffmpeg or shutil.which('ffmpeg')
        if not ffmpeg or not (shutil.which(ffmpeg) or Path(ffmpeg).is_file()):
            raise ValueError('missing ffmpeg')
        report['environment']['ffmpeg'] = str(ffmpeg)
        before = sample_resources(run)
        import psutil
        report['environment'].update(platform=platform.platform(), python=platform.python_version(), psutil=psutil.__version__, logical_cpus=os.cpu_count(), total_ram_bytes=before['host_total'])
        options = config['ffmpeg']
        base = [str(ffmpeg), '-nostdin', '-hide_banner', '-v', 'error', '-threads', str(options['threads']), '-filter_threads', str(options['filter_threads']), '-filter_complex_threads', str(options['filter_complex_threads']), '-n']
        def execute(name, cmd, cancel=None):
            result = run_command(base + cmd, logs / (name + '.log'), run, config['limits'], cancel_after_seconds=cancel)
            result['name'] = name
            stages.append(result)
            return result
        for index, source in enumerate(config['sources']):
            src = report['sourcevalidation'][index]['path']
            prefix = f'source-{index}'
            progress_path = logs / (prefix + '-decode-progress.txt')
            stage = execute(prefix + '-decode', ['-xerror', '-progress', str(progress_path), '-i', src, '-map', '0:v:0', '-an', '-threads', str(options['threads']), '-f', 'null', '-'])
            if stage['status'] != 'completed': break
            progress = parse_decode_progress(progress_path, source['duration_seconds'], config['decode_duration_tolerance_seconds'])
            stage.update(progress)
            if not progress['valid']:
                stage.update(status='failed', stop_reason='incomplete_decode'); break
            wav = work / (prefix + '.wav'); generated.append(wav)
            stage = execute(prefix + '-audio', ['-i', src, '-vn', '-ac', str(options['audio_channels']), '-ar', str(options['audio_sample_rate']), '-c:a', 'pcm_s16le', '-threads', str(options['threads']), str(wav)])
            if stage['status'] != 'completed': break
            stage['duration_seconds'] = audio_duration(wav)
            if abs(stage['duration_seconds'] - source['duration_seconds']) > config['audio_duration_tolerance_seconds']:
                stage.update(status='failed', stop_reason='audio_duration_mismatch'); break
            for n, t in enumerate(source['frame_seconds']):
                frame = work / f'{prefix}-frame-{n}.jpg'; generated.append(frame)
                stage = execute(f'{prefix}-frame-{n}', ['-ss', str(t), '-i', src, '-frames:v', '1', '-vf', f"scale=min({options['frame_width']}\\,iw):-2", '-q:v', str(options['jpeg_quality']), '-pix_fmt', str(options['pixel_format']), '-color_range', str(options['color_range']), '-strict', str(options['compliance']), '-threads', str(options['threads']), str(frame)])
                if stage['status'] != 'completed': break
                record_frame(stage, frame)
                if stage['status'] != 'completed': break
            if stage['status'] != 'completed': break
        else:
            stage = execute('interruption', ['-re', '-stream_loop', '-1', '-i', report['sourcevalidation'][0]['path'], '-map', '0:v:0', '-an', '-f', 'null', '-'], config['interruption_seconds'])
            termination = stage.get('termination', {})
            interrupted = (stage['status'] == 'interrupted' and termination.get('verified') is True
                           and termination.get('owned_descendants_stopped') is True)
        after = sample_resources(run)
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or type(exc).__name__
    finally:
        removed = cleanup_generated(work, generated) if config.get('cleanup', True) else 0
        remaining = [str(p.relative_to(work)) for p in work.rglob('*') if p.is_file()]
        samples = [s for stage in stages for s in stage.get('samples', [])]
        if before: samples.insert(0, before)
        if after: samples.append(after)
        source_count = len(config['sources'])
        expected_frames = sum(len(source['frame_seconds']) for source in config['sources'])
        decoded = sum(s['status'] == 'completed' and s['name'].endswith('-decode') for s in stages)
        audio = sum(s['status'] == 'completed' and s['name'].endswith('-audio') and 'duration_seconds' in s for s in stages)
        frames = sum(s['status'] == 'completed' and '-frame-' in s['name'] and s.get('bytes', 0) > 0 for s in stages)
        cleanup_checked = config.get('cleanup', True) and not remaining
        completed = (source_count > 0 and len(report['sourcevalidation']) == source_count and decoded == source_count
                     and audio == source_count and frames == expected_frames and interrupted and cleanup_checked
                     and error is None and all(s['status'] == 'completed' for s in stages if s['name'] != 'interruption'))
        report['summary'] = {'source_count': source_count, 'decode_expected': source_count, 'decode_completed': decoded, 'audio_expected': source_count, 'audio_completed': audio, 'frames_expected': expected_frames, 'frames_completed': frames, 'host_cpu_sample_peak_percent': max((s['host_cpu_percent'] for s in samples if 'host_cpu_percent' in s), default=None), 'all_completed': completed, 'guard_stops': [s['stop_reason'] for s in stages if s['status'] in ('resource_stop', 'timeout')], 'interruption_checked': interrupted, 'cleanup_checked': cleanup_checked, 'removed_files': removed, 'remaining_files': remaining, 'host_used_proxy_peak_bytes': max((s['host_used_proxy'] for s in samples), default=None), 'process_tree_sample_peak_rss_bytes': max((s['tree_rss'] for s in samples), default=None), 'min_available_bytes': min((s['host_available'] for s in samples), default=None), 'min_disk_free_bytes': min((s['disk_free'] for s in samples), default=None), 'swap_used_before_after': [before['swap_used'] if before else None, after['swap_used'] if after else None], 'resource_stage_pass': completed and cleanup_checked, 'business_response_tested': False, 'error': error}
        (run / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if report['summary']['resource_stage_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
