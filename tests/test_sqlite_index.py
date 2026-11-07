import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tmp' / 'benchmark-deps'))
from tools.sqlite_index import SQLiteIndex


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.idx = SQLiteIndex(':memory:', 3)
        self.idx.upsert(1, 'a', 'apple alpha', [1, 0, 0])
        self.idx.upsert(2, 'b', 'banana beta', [0, 1, 0])

    def tearDown(self):
        self.idx.close()

    def test_cosine(self):
        hits = self.idx.search_vector([1, 0, 0], 2)
        self.assertEqual([h['id'] for h in hits], [1, 2])
        self.assertAlmostEqual(hits[0]['distance'], 0, places=6)
        self.assertAlmostEqual(hits[1]['distance'], 1, places=6)

    def test_upsert(self):
        self.idx.upsert(1, 'c', 'cherry', [0, 0, 1])
        self.assertFalse(self.idx.search_lexical('apple', 2))
        self.assertEqual(self.idx.search_lexical('cherry', 2)[0]['source'], 'c')
        self.assertEqual(self.idx.search_vector([0, 0, 1], 1)[0]['id'], 1)
        self.assertEqual(self.idx.search_hybrid('cherry', [0, 0, 1], 2, 60)[0]['id'], 1)

    def test_delete(self):
        self.idx.delete(1)
        self.assertFalse(self.idx.search_lexical('apple', 2))
        self.assertEqual([x['id'] for x in self.idx.search_vector([1, 0, 0], 2)], [2])
        self.assertEqual(self.idx.db.execute('SELECT count(*) FROM docs').fetchone()[0], 1)

    def test_invalid_unchanged(self):
        for vector in ([0, 0, 0], [1, 2], [float('nan'), 0, 1]):
            with self.assertRaises(ValueError):
                self.idx.upsert(1, 'bad', 'bad', vector)
        self.assertEqual(self.idx.search_lexical('apple', 1)[0]['id'], 1)
        self.assertEqual(self.idx.search_vector([1, 0, 0], 1)[0]['id'], 1)

    def test_outer_transaction_rollback(self):
        self.idx.db.execute('BEGIN')
        self.idx.upsert(3, 'c', 'cherry', [0, 0, 1])
        self.idx.delete(1)
        self.idx.db.rollback()
        self.assertEqual(self.idx.search_lexical('apple', 1)[0]['id'], 1)
        self.assertFalse(self.idx.search_lexical('cherry', 1))
        self.assertEqual(self.idx.search_vector([1, 0, 0], 1)[0]['id'], 1)
        self.assertEqual(self.idx.db.execute('SELECT id FROM docs ORDER BY id').fetchall(), [(1,), (2,)])
        self.assertEqual(self.idx.db.execute('SELECT id FROM embeddings ORDER BY id').fetchall(), [(1,), (2,)])

    def test_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.idx.db:
                self.idx.db.execute('DELETE FROM docs WHERE id=1')
                self.idx.db.execute('DELETE FROM docs_fts WHERE rowid=1')
                self.idx.db.execute('DELETE FROM embeddings WHERE id=1')
                raise RuntimeError('rollback')
        self.assertEqual(self.idx.search_lexical('apple', 1)[0]['id'], 1)
        self.assertEqual(self.idx.search_vector([1, 0, 0], 1)[0]['id'], 1)


if __name__ == '__main__':
    unittest.main()
