import math
import unittest
from tools.retrieval_trial import chunks, lexical, dense, rrf

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.text = '前言\n# 标题\n中文检索系统 alpha 数据\n' + '测试内容' * 30
        self.bundle = {'items':[{'id':'one','notes':self.text,'source_path':'one.md','source_sha256':'hash','output_version':'1'}]}
    def test_coverage(self):
        for strategy in ('heading','fixed'):
            rows = chunks(self.bundle,strategy,25,5)
            covered = set()
            for row in rows:
                self.assertEqual(row['text'],self.text[row['offset']:row['end']])
                self.assertEqual(row['source_sha256'],'hash')
                covered.update(range(row['offset'],row['end']))
            self.assertEqual(covered,set(range(len(self.text))))
    def test_lexical(self):
        rows = chunks(self.bundle,'heading',1000,5)
        self.assertTrue(lexical(rows,'中文检索',10))
        self.assertTrue(lexical(rows,'ALPHA',10))
    def test_dense(self):
        rows = [{'id':'a'},{'id':'b'}]
        self.assertEqual(dense(rows,[[0,1],[1,0]],[1,0],1)[0]['id'],'b')
    def test_bad_vectors(self):
        for v in ([[math.nan,1]], [[1]], [[0,0]]):
            with self.assertRaises(ValueError): dense([{'id':'a'}],v,[1,0],1)
    def test_rrf(self):
        a,b = {'id':'a'}, {'id':'b'}
        self.assertEqual([r['id'] for r in rrf([a,b],[b,a],2)],['a','b'])
    def test_identity_and_count(self):
        with self.assertRaises(ValueError): dense([{'id':'a'}],[],[1],1)
        with self.assertRaises(ValueError): dense([{'id':'a'},{'id':'a'}],[[1],[1]],[1],2)

if __name__ == '__main__': unittest.main()
