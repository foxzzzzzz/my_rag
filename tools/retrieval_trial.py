"""Small offline retrieval prototype; in-memory cosine is not a production scale solution."""
from contextlib import closing
import hashlib
import math
import re
import sqlite3


def chunks(bundle, strategy, max_chars=1000, overlap=120):
    if strategy not in ('heading', 'fixed') or not 0 <= overlap < max_chars:
        raise ValueError('invalid chunk strategy or limits')
    result = []
    for item in bundle['items']:
        text = item['notes']
        bounds = [(0, len(text), '')]
        if strategy == 'heading':
            heads = list(re.finditer(r'(?m)^\s{0,3}#{1,6}\s+([^\n]+)', text))
            if heads:
                bounds = []
                if heads[0].start():
                    bounds.append((0, heads[0].start(), ''))
                bounds.extend((h.start(), heads[i+1].start() if i+1 < len(heads) else len(text), h.group(1).strip()) for i, h in enumerate(heads))
        for start, end, heading in bounds:
            pos = start
            while pos < end:
                stop = min(end, pos + max_chars)
                identity = f"{item['id']}\0{strategy}\0{pos}\0{stop}\0{item['source_sha256']}\0{item['output_version']}"
                result.append({'id': hashlib.sha256(identity.encode()).hexdigest(), 'item_id': item['id'], 'heading': heading, 'text': text[pos:stop], 'source_path': item['source_path'], 'source_sha256': item['source_sha256'], 'output_version': item['output_version'], 'offset': pos, 'end': stop})
                if stop == end:
                    break
                pos = stop - overlap
    return result


def tokens(text):
    parts = re.findall(r'[\u4e00-\u9fff]+|[A-Za-z0-9]+', text.lower())
    out = []
    for p in parts:
        if '\u4e00' <= p[0] <= '\u9fff' and len(p) > 1:
            out.extend(p[i:i+2] for i in range(len(p)-1))
        else:
            out.append(p)
    return out


def lexical(items, query, k):
    terms = tokens(query)
    if not terms or k <= 0:
        return []
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('CREATE VIRTUAL TABLE docs USING fts5(content)')
        db.executemany('INSERT INTO docs(rowid,content) VALUES (?,?)', ((i+1, ' '.join(tokens(c['text']))) for i,c in enumerate(items)))
        expression = ' OR '.join('"' + t + '"' for t in dict.fromkeys(terms))
        rows = db.execute('SELECT rowid,bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs),rowid LIMIT ?', (expression,k)).fetchall()
    return [{**items[i-1], 'score': -score} for i,score in rows]


def dense(items, vectors, queryvector, k):
    if len(vectors) != len(items) or len({c['id'] for c in items}) != len(items):
        raise ValueError('vector count or chunk IDs invalid')
    def norm(v):
        if not isinstance(v, (list, tuple)) or not v or any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(x) for x in v):
            raise ValueError('invalid vector')
        length = math.sqrt(sum(x*x for x in v))
        if not math.isfinite(length) or not length:
            raise ValueError('invalid vector norm')
        return length
    qnorm = norm(queryvector)
    ranked = []
    for c,v in zip(items,vectors):
        vn = norm(v)
        if len(v) != len(queryvector):
            raise ValueError('dimension mismatch')
        ranked.append({**c, 'score': sum(a*b for a,b in zip(v,queryvector))/(vn*qnorm)})
    return sorted(ranked, key=lambda c: (-c['score'], c['id']))[:max(0,k)]


def rrf(first, second, k, constant=60):
    if constant <= 0:
        raise ValueError('invalid RRF constant')
    found = {}
    for ranking in (first, second):
        seen = set()
        for rank, item in enumerate(ranking, 1):
            ident = item['id']
            if ident in seen:
                raise ValueError('duplicate ranking ID')
            seen.add(ident)
            if ident not in found:
                found[ident] = {**item, 'score': 0.0}
            found[ident]['score'] += 1 / (constant + rank)
    return sorted(found.values(), key=lambda c: (-c['score'], c['id']))[:max(0,k)]
