from tools.answer_layout import split_paragraphs

REF = '[' + 'a'*64 + ']'

def test_boundaries():
    cases = [
        ('', ['']), ('无法回答。', ['无法回答。']),
        ('甲\n\n乙', ['甲\n\n', '乙']),
        ('甲\n\n  '+REF+'乙', ['甲\n\n  '+REF, '乙']),
        ('😀'*47+'。 \n'+REF+'乙', ['😀'*47+'。 \n'+REF, '乙']),
        ('甲'*47+'？！乙', ['甲'*47+'？！', '乙']),
        ('“'+ '甲'*50+'“嵌套。”仍在引号。”后续', ['“'+ '甲'*50+'“嵌套。”仍在引号。”后续']),
        ('`'+ '甲'*50+'。`后续', ['`'+ '甲'*50+'。`后续']),
        ('路径 C:/a.b 版本 1.23', ['路径 C:/a.b 版本 1.23']),
        ('甲'*159+'；乙', ['甲'*159+'；', '乙']),
    ]
    for text, expected in cases:
        assert split_paragraphs(text) == expected
        assert ''.join(expected) == text


def test_apostrophes_inside_quotes():
    for text in ["'don't" + '甲'*50 + "。结束'后续", '‘don’t' + '甲'*50 + '。结束’后续']:
        assert split_paragraphs(text) == [text]
