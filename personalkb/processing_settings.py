"""Persist user-selected processing limits in the shared workflow database."""
import json
import re
from functools import cache
from pathlib import Path

from .workflow_store import WorkflowError


BYTE_KEYS = (
    'asr_upload_bytes', 'video_upload_bytes', 'html_upload_bytes',
    'douyin_video_download_bytes', 'douyin_image_bytes', 'douyin_album_bytes',
)
BOOL_KEYS = ('schedule_enabled', 'auto_download', 'conversion_enabled')
SCHEDULE_KEYS = (*BOOL_KEYS, 'daily_at')


@cache
def _default_bounds():
    return json.loads((Path(__file__).parent / 'processing_settings_bounds.json').read_text(encoding='utf8'))


def bounds_for(web_config):
    configured = web_config.get('processing_settings_bounds', {})
    if not isinstance(configured, dict) or configured.keys() - set(BYTE_KEYS):
        raise WorkflowError('invalid_config')
    for bound in configured.values():
        if (not isinstance(bound, dict) or type(bound.get('min')) is not int
                or type(bound.get('max')) is not int or not 0 < bound['min'] <= bound['max']):
            raise WorkflowError('invalid_config')
    return {**_default_bounds(), **configured}


def effective_size(settings, key, default, bounds):
    return min(settings.get(key, default), bounds[key]['max'])


def upload_sizes(store, workflow_config, web_config):
    _, values = overrides(store)
    bounds = bounds_for(web_config)
    video = effective_size(values, 'video_upload_bytes', workflow_config['max_upload_bytes'], bounds)
    html_default = min(workflow_config['max_html_bytes'], workflow_config['max_upload_bytes'])
    html = effective_size(values, 'html_upload_bytes', html_default, bounds)
    return video, html


def effective_asr_limit(store, web_config, pipeline_config, connection=None):
    default = pipeline_config.get('storage', {}).get('max_upload_bytes')
    if default is None:
        return None
    _, values = _stored_settings(connection) if connection is not None else overrides(store)
    return effective_size(values, 'asr_upload_bytes', default, bounds_for(web_config))


def _stored_settings(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='processing_settings'").fetchone():
        return 0, {}
    row = db.execute('SELECT revision, values_json FROM processing_settings WHERE id=1').fetchone()
    return (row['revision'], json.loads(row['values_json'])) if row else (0, {})


def overrides(store):
    with store._tx() as db:
        return _stored_settings(db)


class ProcessingSettings:
    def __init__(self, store, defaults, bounds, timezone, favorites_enabled=True, conversion_available=True):
        self.store = store
        self.defaults = defaults
        self.bounds = bounds
        self.timezone = timezone
        self.readonly = {'max_attempts'}
        if not favorites_enabled:
            self.readonly.update(SCHEDULE_KEYS)
        if not conversion_available:
            self.readonly.add('conversion_enabled')

    def _result(self, revision, overrides):
        settings = {}
        for key, default in self.defaults.items():
            entry = {'value': overrides.get(key, default), 'editable': key not in self.readonly}
            if key == 'conversion_enabled' and not entry['editable']:
                entry['value'] = False
            if key in self.bounds:
                entry['value'] = effective_size(overrides, key, default, self.bounds)
                entry.update(min=self.bounds[key]['min'], max=self.bounds[key]['max'])
            settings[key] = entry
        return {'revision': revision, 'settings': settings, 'timezone': self.timezone}

    def read(self):
        return self._result(*overrides(self.store))

    def change(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'expected_revision', 'values'}:
            raise WorkflowError('invalid_request')
        revision, values = payload['expected_revision'], payload['values']
        if type(revision) is not int or revision < 0 or not isinstance(values, dict) or not values:
            raise WorkflowError('invalid_request')
        for key, value in values.items():
            if key in self.readonly or key not in self.defaults:
                raise WorkflowError('invalid_request')
            if key in BYTE_KEYS:
                bound = self.bounds[key]
                if type(value) is not int or not bound['min'] <= value <= bound['max']:
                    raise WorkflowError('invalid_request')
            elif key in BOOL_KEYS:
                if type(value) is not bool:
                    raise WorkflowError('invalid_request')
            elif key == 'daily_at':
                if not isinstance(value, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
                    raise WorkflowError('invalid_request')
            else:
                raise WorkflowError('invalid_request')
        with self.store._tx() as connection:
            saved_revision, saved = _stored_settings(connection)
            if saved_revision != revision:
                raise WorkflowError('revision_conflict')
            saved.update(values)
            merged = {**self.defaults, **saved}
            if ('conversion_enabled' not in self.readonly and values.keys() & {'conversion_enabled', 'auto_download'}
                    and merged.get('conversion_enabled') and not merged.get('auto_download')):
                raise WorkflowError('invalid_request')
            connection.execute('''CREATE TABLE IF NOT EXISTS processing_settings
                (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, values_json TEXT NOT NULL)''')
            connection.execute('''INSERT INTO processing_settings(id, revision, values_json) VALUES(1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, values_json=excluded.values_json''',
                (revision + 1, json.dumps(saved, ensure_ascii=False)))
            return self._result(revision + 1, saved)
