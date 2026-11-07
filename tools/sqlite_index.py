import math
from contextlib import contextmanager
import sqlite3
import struct

import sqlite_vec
from tools.retrieval_trial import tokens


class SQLiteIndex:
    def __init__(self, path, dimension):
        if not isinstance(dimension, int) or dimension <= 0:
            raise ValueError('dimension must be a positive integer')
        self.dimension = dimension
        self.db = sqlite3.connect(path)
        self.db.enable_load_extension(True)
        try:
            sqlite_vec.load(self.db)
        finally:
            self.db.enable_load_extension(False)
        self.db.execute('CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, source TEXT, text TEXT)')
        self.db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(text)')
        self.db.execute(f'CREATE VIRTUAL TABLE IF NOT EXISTS embeddings USING vec0(id INTEGER PRIMARY KEY, vector float[{dimension}] distance_metric=cosine)')
        self.db.commit()

    def _vector(self, vector):
        values = list(vector)
        if len(values) != self.dimension or not all(math.isfinite(x) for x in values) or not any(values):
            raise ValueError('vector must have the configured dimension, finite values and nonzero magnitude')
        try:
            packed = struct.pack(f'{self.dimension}f', *values)
        except (OverflowError, struct.error) as exc:
            raise ValueError('vector cannot be represented as float32') from exc
        converted = struct.unpack(f'{self.dimension}f', packed)
        if not all(math.isfinite(x) for x in converted) or not any(converted):
            raise ValueError('vector cannot be represented as nonzero finite float32')
        return packed

    @contextmanager
    def _atomic(self):
        self.db.execute('SAVEPOINT sqlite_index_operation')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK TO sqlite_index_operation')
            self.db.execute('RELEASE sqlite_index_operation')
            raise
        else:
            self.db.execute('RELEASE sqlite_index_operation')

    def upsert(self, id, source, text, vector):
        blob = self._vector(vector)
        with self._atomic():
            self.db.execute('DELETE FROM docs_fts WHERE rowid=?', (id,))
            self.db.execute('DELETE FROM embeddings WHERE id=?', (id,))
            self.db.execute('DELETE FROM docs WHERE id=?', (id,))
            self.db.execute('INSERT INTO docs VALUES (?,?,?)', (id, source, text))
            self.db.execute('INSERT INTO docs_fts(rowid,text) VALUES (?,?)', (id, ' '.join(tokens(text))))
            self.db.execute('INSERT INTO embeddings(id,vector) VALUES (?,?)', (id, blob))

    def delete(self, id):
        with self._atomic():
            self.db.execute('DELETE FROM docs_fts WHERE rowid=?', (id,))
            self.db.execute('DELETE FROM embeddings WHERE id=?', (id,))
            self.db.execute('DELETE FROM docs WHERE id=?', (id,))

    def search_vector(self, vector, k):
        blob = self._vector(vector)
        if k <= 0:
            return []
        hits = self.db.execute('SELECT id,distance FROM embeddings WHERE vector MATCH ? AND k = ? ORDER BY distance', (blob, k)).fetchall()
        result = []
        for id, distance in hits:
            row = self.db.execute('SELECT source,text FROM docs WHERE id=?', (id,)).fetchone()
            if row:
                result.append(dict(id=id, source=row[0], text=row[1], distance=distance))
        return result

    def search_lexical(self, query, k):
        terms = tokens(query)
        if not terms or k <= 0:
            return []
        expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
        rows = self.db.execute('SELECT d.id,d.source,d.text,-bm25(docs_fts) FROM docs_fts JOIN docs d ON d.id=docs_fts.rowid WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts) LIMIT ?', (expression, k)).fetchall()
        return [dict(id=i, source=s, text=t, score=score) for i, s, t, score in rows]

    def search_hybrid(self, query, vector, k, rrfconstant):
        if rrfconstant < 0:
            raise ValueError('rrfconstant must be nonnegative')
        merged = {}
        for hits in (self.search_lexical(query, k), self.search_vector(vector, k)):
            for rank, hit in enumerate(hits, 1):
                entry = merged.setdefault(hit['id'], dict(id=hit['id'], source=hit['source'], text=hit['text'], score=0.0))
                entry['score'] += 1 / (rrfconstant + rank)
        return sorted(merged.values(), key=lambda x: (-x['score'], x['id']))[:max(k, 0)]

    def close(self):
        self.db.close()
