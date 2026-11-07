import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.retrieval_review import build


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'review.html'
        self.q = {'id': 'x', 'question': '</script><img src=x onerror=alert(1)>', 'answer': '<b>bad</b>', 'citations': [], 'retrievals': {}, 'usage': {}}
        self.report = {'run_id': '</script>', 'questions': [self.q]}

    def test_escape(self):
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        self.assertIn('&lt;img', page)
        self.assertIn('\\u003c/script\\u003e', page)
        self.assertNotIn('<img src=x', page)

    def test_blank_and_binding(self):
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        digest = hashlib.sha256(json.dumps(self.q, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertIn(digest, page)
        self.assertIn('if(!score && !decision && !note) continue', page)
        self.assertIn('data-field="reviewer" value="本人"', page)
        self.assertNotIn('value="0"', page)

    def test_comparison(self):
        self.q['retrievals'] = {'<method>': [{'item_id': '<id>', 'heading': '<heading>', 'score': 0.5}]}
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        self.assertIn('&lt;method&gt;', page)
        self.assertIn('&lt;id&gt; | &lt;heading&gt; | 0.5', page)

    def test_cited_only_and_revision(self):
        ids = ['a' * 64, 'b' * 64, 'c' * 64]
        self.q.update(answer=ids[0] + ' ' + ids[1], citation_ids=ids[:2],
                      citations=[{'id': x, 'text': 'evidence' + str(i)} for i, x in enumerate(ids)],
                      retrievals={'secret-method': [{'item_id': 'secret-candidate'}]},
                      revision_note='<修改>', output_version='v2')
        self.report.update(presentation={'cited_only': True, 'show_comparisons': False, 'feedback_filename': 'reviews-revision-2.json'}, review_notice='独立四题复核')
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        self.assertIn('evidence0', page)
        self.assertIn('evidence1', page)
        self.assertNotIn('evidence2', page)
        self.assertNotIn('secret-method', page)
        self.assertIn('&lt;修改&gt;', page)
        self.assertIn('独立四题复核', page)
        self.assertIn('reviews-revision-2.json', page)
        self.assertIn("if(!score && !decision && !note) continue", page)

    def test_refusal_hides_candidates(self):
        self.q.update(answer='无法回答', citation_ids=[], insufficient_evidence=True,
                      citations=[{'id': 'a' * 64, 'text': 'irrelevant'}],
                      retrievals={'method': [{'item_id': 'candidate'}]})
        self.report['presentation'] = {'cited_only': True, 'show_comparisons': False}
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        self.assertIn('未找到可支持回答的证据', page)
        self.assertNotIn('irrelevant', page)
        self.assertNotIn('candidate', page)
        self.assertNotIn('检索对比', page)

    def test_invalid_citations(self):
        self.report['presentation'] = {'cited_only': True}
        identifier = 'a' * 64
        for answer, ids, citations, insufficient in [
            (identifier, [identifier], [], False),
            ('no id', [identifier], [{'id': identifier}], False),
            (identifier, [identifier], [{'id': identifier}], True),
            ('answer', [], [], False),
        ]:
            self.q.update(answer=answer, citation_ids=ids, citations=citations, insufficient_evidence=insufficient)
            with self.assertRaises(ValueError):
                build(self.report, self.path)

    def test_external_assets_and_binding(self):
        self.report['presentation'] = {'external_assets': True, 'asset_basename': 'review-test'}
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        digest = hashlib.sha256(json.dumps(self.q, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertIn(digest, page)
        self.assertIn('<link rel="stylesheet" href="review-test.css">', page)
        self.assertIn('<script src="review-test.js" defer></script>', page)
        self.assertNotIn('<style>', page)
        self.assertTrue((self.path.parent / 'review-test.js').is_file())
        build(self.report, self.path.parent / 'second.html')

    def test_unsafe_names_and_conflicts(self):
        for filename in ['../bad.json', 'a\\b.json', 'bad\x00.json', 'bad.txt']:
            self.report['presentation'] = {'feedback_filename': filename}
            with self.assertRaises(ValueError):
                build(self.report, self.path)
        self.report['presentation'] = {'external_assets': True, 'asset_basename': '../bad'}
        with self.assertRaises(ValueError):
            build(self.report, self.path)
        self.report['presentation']['asset_basename'] = 'safe'
        conflict = self.path.parent / 'safe.css'
        conflict.write_text('existing')
        with self.assertRaises(FileExistsError):
            build(self.report, self.path)
        self.assertFalse(self.path.exists())
        self.assertFalse((self.path.parent / 'safe.js').exists())
        self.assertEqual(conflict.read_text(), 'existing')

    def test_no_overwrite(self):
        self.path.write_text('existing')
        with self.assertRaises(FileExistsError):
            build(self.report, self.path)
        self.assertEqual(self.path.read_text(), 'existing')

    def test_citation_readability(self):
        a, b = 'a' * 64, 'b' * 64
        self.q.update(answer=f'[{b}] [{a}] [{b}] [sandbox] items[0]', citations=[{'id': a, 'heading': '视频 {"seconds": 3, "offset": 0, "end_offset": 5}', 'text': '<原文>', 'source_path': 'source_id: x'}, {'id': b, 'heading': '视频 {"seconds": 2}', 'text': '正文', 'source_path': 'source_id: y'}])
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        self.assertIn('href="#q0-source-1"', page)
        self.assertIn('①', page)
        self.assertIn('[sandbox] items[0]', page)
        self.assertIn('&lt;原文&gt;', page)
        self.assertIn('定位详情', page)


    def test_numbering_overflow_unknown_and_human_locator(self):
        ids = [f"{n:064x}" for n in range(1, 22)]
        unknown = 'f' * 64
        self.q['answer'] = ''.join(f'[{x}]' for x in ids) + f'[{ids[0]}] [{unknown}] [sandbox] items[0] <script>'
        self.q['citations'] = [{'id': x, 'heading': '视频 {"origin":"human_edit","seconds":99}', 'text': '<script>', 'source_path': 'source_id: example'} for x in ids]
        build(self.report, self.path)
        page = self.path.read_text(encoding='utf-8')
        self.assertEqual(page.count('href="#q0-source-1"'), 3)
        self.assertIn('[21]', page)
        self.assertIn(f'[{unknown}] [sandbox] items[0] &lt;script&gt;', page)
        self.assertNotIn('99 秒', page)
        self.assertIn('人工修订', page)
        self.assertIn('无可验证视频时间', page)
        self.assertIn('class="answer-text"', page)

    def test_real_report_binding_unchanged(self):
        report = json.loads(Path('reports/phase3-live-review-20261106/review-report.json').read_text(encoding='utf-8'))
        original = json.dumps(report['questions'], ensure_ascii=False, sort_keys=True)
        build(report, self.path)
        page = self.path.read_text(encoding='utf-8')
        self.assertEqual(original, json.dumps(report['questions'], ensure_ascii=False, sort_keys=True))
        for q in report['questions']:
            digest = hashlib.sha256(json.dumps(q, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            self.assertIn(digest, page)
