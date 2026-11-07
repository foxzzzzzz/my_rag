import unittest
from personalkb.html_extract import extract_html


class HtmlExtractTests(unittest.TestCase):
    def test_static_evidence_and_unsafe_content(self):
        result = extract_html('''<html><head><title>标题</title></head><body>
        <h1>正文</h1><table><tr><th>名称</th><th>值</th></tr><tr><td>A</td><td>1</td></tr></table>
        <pre>print(1)</pre><a href="https://example.com">链接</a>
        <svg onload="evil()"><text>节点 → 节点</text><script>evil()</script><path d="M0 0"/></svg>
        <math><mi>x</mi><mo>+</mo><mn>1</mn></math><canvas></canvas><img src="https://example.com/a.png">
        <script>fetch('https://example.com')</script></body></html>''')
        self.assertEqual(result['title'], '标题')
        for text in ('# 正文', '| 名称 | 值 |', 'print(1)', 'https://example.com', 'x+1'):
            self.assertIn(text, result['body'])
        self.assertIn('节点 → 节点', result['svg_context'])
        self.assertNotIn('evil', result['svg_context'])
        self.assertNotIn('fetch', result['body'])
        self.assertGreaterEqual(len(result['warnings']), 2)
        self.assertEqual(result['stats'], {'table': 1, 'code': 1, 'svg': 1, 'formula': 1})

    def test_requires_text(self):
        with self.assertRaises(TypeError): extract_html(b'<html>')

    def test_incomplete_svg_and_lossy_formula_warn(self):
        result = extract_html('<body><math><mi>x</mi></math><svg><text>partial')
        self.assertIn('partial', result['svg_context'])
        self.assertTrue(any('SVG' in warning for warning in result['warnings']))
        self.assertTrue(any('公式' in warning for warning in result['warnings']))

    def test_nested_table_preserves_text_and_warns(self):
        result = extract_html('<table><tr><td>outerA<table><tr><td>innerB</td></tr></table>tail</td></tr></table>')
        for word in ('outerA', 'innerB', 'tail'): self.assertIn(word, result['body'])
        self.assertTrue(any('嵌套' in warning for warning in result['warnings']))

    def test_nested_script_is_excluded(self):
        result = extract_html('<body>before<script><style>bad</style>still bad</script>after</body>')
        self.assertIn('before', result['body'])
        self.assertIn('after', result['body'])
        self.assertNotIn('bad', result['body'])
