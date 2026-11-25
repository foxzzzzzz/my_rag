import pytest

from personalkb.processing_settings import ProcessingSettings, effective_asr_limit
from personalkb.workflow_store import WorkflowError, WorkflowStore


def test_shared_settings_revision_validation_and_audio_limit(tmp_path):
    store = WorkflowStore(tmp_path / 'workflow.sqlite3')
    settings = ProcessingSettings(store, {'asr_upload_bytes': 64, 'max_attempts': 3},
                                  {'asr_upload_bytes': {'min': 1, 'max': 100}}, 'Asia/Shanghai')
    pipeline = {'storage': {'max_upload_bytes': 64}}
    assert settings.read()['revision'] == 0
    assert effective_asr_limit(store, {}, pipeline) == 64
    result = settings.change({'expected_revision': 0, 'values': {'asr_upload_bytes': 80}})
    assert result['revision'] == 1
    assert effective_asr_limit(store, {}, pipeline) == 80
    with store._tx() as db:
        assert effective_asr_limit(store, {}, pipeline, db) == 80
    for payload in (
        {'expected_revision': 0, 'values': {'asr_upload_bytes': 90}},
        {'expected_revision': 1, 'values': {'asr_upload_bytes': 101}},
        {'expected_revision': 1, 'values': {'asr_upload_bytes': True}},
        {'expected_revision': 1, 'values': {'max_attempts': 7}},
    ):
        with pytest.raises(WorkflowError):
            settings.change(payload)
    assert settings.read()['settings']['asr_upload_bytes']['value'] == 80


def test_disabled_favorites_and_lowered_deployment_ceiling(tmp_path):
    store = WorkflowStore(tmp_path / 'workflow.sqlite3')
    defaults = {'asr_upload_bytes': 64, 'schedule_enabled': False, 'auto_download': False,
                'conversion_enabled': False, 'daily_at': '05:30'}
    original = ProcessingSettings(store, defaults, {'asr_upload_bytes': {'min': 1, 'max': 100}},
                                  'Asia/Shanghai', favorites_enabled=False)
    assert original.read()['settings']['schedule_enabled']['editable'] is False
    with pytest.raises(WorkflowError):
        original.change({'expected_revision': 0, 'values': {'schedule_enabled': True}})
    original.change({'expected_revision': 0, 'values': {'asr_upload_bytes': 80}})
    lowered = ProcessingSettings(store, defaults, {'asr_upload_bytes': {'min': 1, 'max': 70}},
                                 'Asia/Shanghai', favorites_enabled=False)
    assert lowered.read()['settings']['asr_upload_bytes']['value'] == 70
    assert effective_asr_limit(store, {'processing_settings_bounds': {'asr_upload_bytes': {'min': 1, 'max': 70}}},
                               {'storage': {'max_upload_bytes': 64}}) == 70
