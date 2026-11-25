"""Describe a failed audio upload using its local media cache and the active limit."""

import json

from .video_recovery import media_workspace
from .workflow import _root


def audio_limit_details(workflow_config, task, limit):
    if task['error_code'] != 'file_too_large' or limit is None:
        return None

    root = _root(workflow_config).resolve()
    work = media_workspace(root, task['id'])
    manifest, audio = work / 'media-manifest.json', work / 'audio.wav'
    actual = None
    try:
        if (work.parent == root / 'video-work' and work.resolve() == work
                and not manifest.is_symlink() and not audio.is_symlink()
                and manifest.is_file() and audio.is_file()):
            entry = json.loads(manifest.read_text(encoding='utf8')).get('audio')
            if isinstance(entry, dict) and entry.get('file') == audio.name:
                actual = audio.stat().st_size
    except (OSError, ValueError, AttributeError, RuntimeError):
        pass
    return {'key': 'asr_upload_bytes', 'actual': actual, 'limit': limit}
