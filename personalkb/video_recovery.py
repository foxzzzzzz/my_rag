"""Recovery eligibility for finalized transcription failures and old media caches."""

import hashlib
import json
import re

from .video_journal import is_chat_stage

TERMINAL_ASR_ERRORS = frozenset({'asr_remote_failed', 'asr_subtask_failed'})
NO_SPEECH_CODES = frozenset({'SUCCESS_WITH_NO_VALID_FRAGMENT', 'ASR_RESPONSE_HAVE_NO_WORDS'})
PARTIAL_MEDIA_ERRORS = frozenset({'video_processing_failed', 'invalid_frame', 'media_workdir_unverified',
                                  'media_command_failed', 'media_timeout', 'resource_limit', 'media_workdir_busy',
                                  'media_rebuild_interrupted'})


def terminal_asr_stage(connection, task_id, stages):
    if not any(row['name'] == 'asr_result' and row['status'] == 'completed' for row in stages):
        return None
    if any(row['name'] == 'asr_visual_only' and row['status'] == 'completed' for row in stages):
        return None
    row = connection.execute("SELECT result,result_sha256 FROM video_stages WHERE task_id=? AND name='asr_result'",
                             (task_id,)).fetchone()
    if not row or not row['result'] or hashlib.sha256(row['result'].encode()).hexdigest() != row['result_sha256']:
        return None
    try:
        result = json.loads(row['result'])
        error = result.get('error')
    except (ValueError, AttributeError):
        return None
    if not isinstance(error, str) or error not in TERMINAL_ASR_ERRORS:
        return None
    code = result.get('provider_code')
    return {'error': error, 'provider_code': code if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', code) else None}


def can_use_visual_only(task, stages, terminal_error):
    return bool(terminal_error and task['remote_task_id'] and task['error_code'] != 'version_conflict'
                and any(row['name'] == 'asr_submit' and row['status'] == 'completed' for row in stages)
                and not any(is_chat_stage(row['name']) for row in stages))


def media_workspace(root, task_id):
    return root / 'video-work' / task_id


def incomplete_backup(work):
    return work.with_name('.' + work.name + '-incomplete')


def incomplete_media_workspace(work):
    return (work.is_dir() and not any(path.is_symlink() for path in (work, *work.parents))
            and not (work / 'media-manifest.json').exists() and not (work / 'media-manifest.json').is_symlink()
            and ((work / 'audio.wav').is_file() or (work / '.media.lock').is_file()
                 or any(work.glob('frame-*.jpg')) or any(work.glob('.media-preparing-*'))))


def can_rebuild_media(task, stages, work):
    backup = incomplete_backup(work)
    if (task['stage'] not in ('preparing_video', 'rebuilding_media') or task['error_code'] not in PARTIAL_MEDIA_ERRORS
            or task['external_started'] or task['remote_task_id']
            or any(row['name'] != 'media_rebuilt' or row['status'] != 'completed' for row in stages)
            or any(path.is_symlink() for path in (work, backup, *work.parents))):
        return False
    if backup.exists():
        return bool(stages and task['stage'] == 'rebuilding_media' and incomplete_media_workspace(backup))
    return incomplete_media_workspace(work)
