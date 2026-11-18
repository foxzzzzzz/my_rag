import copy
import pytest
from personalkb.video_pipeline import _bind_strategy, _digest, load_pipeline_config
from personalkb.html_pipeline import load_html_config
from personalkb.workflow_store import WorkflowError

class Journal:
    def __init__(self, bound=None): self.bound = bound
    def bind(self, task, token, current, *compatible):
        if self.bound is not None and self.bound not in (current, *compatible): raise WorkflowError('fingerprint_conflict')
        self.bound = self.bound or current
        return self.bound

@pytest.mark.parametrize('loader,keys', [(load_pipeline_config, ('models','strategy','storage','prices','default_profile')), (load_html_config, ('models','strategy','prices','scheme_id','extractor_version'))])
@pytest.mark.parametrize('prompt_key', ['legacy_text_prompt', 'previous_text_prompt'])
def test_prompt_fingerprint_compatibility(loader, keys, prompt_key):
    config = loader()
    original = {'text_system_prompt': config['strategy'][prompt_key]['value']}
    old = copy.deepcopy(config)
    for key in ('legacy_text_prompt','previous_text_prompt','summary_format','summary_format说明'):
        old['strategy'].pop(key, None)
    old['strategy']['text_system_prompt'] = original['text_system_prompt']
    if 'storage' in keys:
        # The saved pre-upgrade fingerprint predates the split upload timeouts.
        for key in ('policy_timeout_seconds', 'policy_timeout_seconds说明',
                    'upload_timeout_seconds', 'upload_timeout_seconds说明'):
            old['storage'].pop(key)
    old_fingerprint = _digest({k: old[k] for k in keys})
    resumed = copy.deepcopy(config)
    assert _bind_strategy(Journal(old_fingerprint), 't', 'token', resumed, keys) == old_fingerprint
    assert resumed['strategy']['text_system_prompt'] == original['text_system_prompt']
    fresh = copy.deepcopy(config)
    assert _bind_strategy(Journal(), 't', 'token', fresh, keys) != old_fingerprint
    assert fresh['strategy']['text_system_prompt'] != original['text_system_prompt']
    altered = copy.deepcopy(config)
    altered['strategy']['max_context_utf8_bytes'] += 1
    with pytest.raises(WorkflowError, match='fingerprint_conflict'):
        _bind_strategy(Journal(old_fingerprint), 't', 'token', altered, keys)


def test_video_note_policy_is_applied_only_to_new_tasks():
    keys = ('models','strategy','storage','prices','default_profile')
    config = load_pipeline_config()
    old = copy.deepcopy(config)
    old['strategy'].pop('legacy_text_prompt')
    old['strategy'].pop('previous_text_prompt')
    for key in ('policy_timeout_seconds', 'policy_timeout_seconds说明',
                'upload_timeout_seconds', 'upload_timeout_seconds说明'):
        old['storage'].pop(key, None)
    fingerprint = _digest({key: old[key] for key in keys})
    resumed = copy.deepcopy(config)
    _bind_strategy(Journal(fingerprint), 'task', 'token', resumed, keys)
    assert resumed['strategy']['text_system_prompt'] == old['strategy']['text_system_prompt']
    fresh = copy.deepcopy(config)
    _bind_strategy(Journal(), 'task', 'token', fresh, keys)
    assert fresh['strategy']['text_system_prompt'].endswith(config['video_notes_prompt_suffix'])
    html = load_html_config()
    _bind_strategy(Journal(), 'task', 'token', html, ('models','strategy','prices','scheme_id','extractor_version'))
    assert config['video_notes_prompt_suffix'] not in html['strategy']['text_system_prompt']
