import pytest

from personalkb.summary_structure import summary_fields


def test_structured_summary_keeps_fields_and_markdown():
    summary = {'overview': '简述', 'key_points': ['甲', '乙'], 'limitations': '仅限样本。'}
    fields = summary_fields({'summary': summary, 'notes': '笔记'}, {'summary_format': 'structured'})
    assert fields == {
        'summary': '简述\n\n- 甲\n- 乙\n\n仅限样本。',
        'summary_structure': summary,
        'notes': '笔记',
    }
    summary = {'overview': '简述', 'key_points': [], 'limitations': ''}
    assert summary_fields({'summary': summary, 'notes': '笔记'}, {'summary_format': 'structured'})['summary'] == '简述'


@pytest.mark.parametrize('summary', [
    '旧版字符串',
    {'overview': '简述', 'key_points': ['甲']},
    {'overview': '', 'key_points': [], 'limitations': ''},
    {'overview': '简述', 'key_points': '甲', 'limitations': ''},
    {'overview': '简述', 'key_points': [' '], 'limitations': ''},
    {'overview': '简述', 'key_points': ['甲\n乙'], 'limitations': ''},
    {'overview': '简述', 'key_points': [], 'limitations': None},
])
def test_invalid_structured_summary_does_not_become_a_version(summary):
    with pytest.raises(ValueError):
        summary_fields({'summary': summary, 'notes': '笔记'}, {'summary_format': 'structured'})


def test_legacy_summary_remains_a_string_without_sidecar():
    result = {'summary': '概述。要点：①甲；②乙。', 'notes': '笔记'}
    assert summary_fields(result, {}) == result
