import json
import re
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / 'config/answer-layout.json').read_text(encoding='utf-8'))
REF = re.compile(r'\[[a-fA-F0-9]{64}\]')

def split_paragraphs(answer):
    s = answer or ''
    out = []
    start = visible = i = 0
    quotes = []
    code = ''
    def refs(end):
        while m := re.match(r'\s*\[[a-fA-F0-9]{64}\]', s[end:]):
            end += len(m.group())
        return end
    while i < len(s):
        ref = REF.match(s, i)
        if ref:
            i = ref.end(); continue
        c = s[i]
        if not quotes and c in '`~':
            run = re.match(re.escape(c) + '+', s[i:]).group()
            if c == '`' or len(run) >= 3:
                if not code: code = run
                elif code == run: code = ''
                i += len(run); visible += len(run); continue
        word_apostrophe = c in "'’" and i > 0 and i + 1 < len(s) and re.fullmatch('[A-Za-z0-9]', s[i-1]) and re.fullmatch('[A-Za-z0-9]', s[i+1])
        if not code and not word_apostrophe:
            top = quotes[-1] if quotes else None
            if c in '“‘': quotes.append(c)
            elif (c == '”' and top == '“') or (c == '’' and top == '‘'): quotes.pop()
            elif c in '\"\'' and (i == 0 or s[i-1] != '\\'):
                if top == c: quotes.pop()
                elif c == '"' or not (i > 0 and i+1 < len(s) and re.fullmatch('[A-Za-z0-9]', s[i-1]) and re.fullmatch('[A-Za-z0-9]', s[i+1])): quotes.append(c)
        i += 1; visible += 1
        if code or quotes: continue
        if c == '\n' and (m := re.match(r'\r?\n', s[i:])):
            i += len(m.group()); i = refs(i)
            if i < len(s): out.append(s[start:i]); start = i; visible = 0
            continue
        if c not in RULES['sentence_endings'] and c not in RULES['semicolon_endings']: continue
        end = i
        while end < len(s) and s[end] in RULES['sentence_endings']: end += 1
        end = refs(end)
        following = s[end:].lstrip()
        if c in RULES['sentence_endings']:
            boundary = visible >= RULES['min_paragraph_chars'] or (visible >= RULES['transition_min_chars'] and any(following.startswith(x) for x in RULES['transition_starts']))
        else: boundary = visible >= RULES['semicolon_break_chars']
        if boundary and following:
            out.append(s[start:end]); start = end; visible = 0; i = end
    if start < len(s) or not out: out.append(s[start:])
    return out
