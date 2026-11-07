import hashlib
import html
import json
import re
from pathlib import Path

from tools.answer_layout import split_paragraphs


def build(report, output):
    """Write a self-contained offline review page without replacing an existing file."""
    questions = report['questions']
    entries = []
    display = json.loads((Path(__file__).resolve().parent.parent / 'config/citation-display.json').read_text(encoding='utf-8'))
    presentation = report.get('presentation', {})
    cited_only = presentation.get('cited_only', False)
    show_comparisons = presentation.get('show_comparisons', True)
    for i, q in enumerate(questions):
        canonical = json.dumps(q, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        esc = lambda value: html.escape(str(value), quote=True)
        citations = q.get('citations', [])
        if cited_only:
            ids = q.get('citation_ids', [])
            known = {c.get('id') for c in citations}
            inline = set(re.findall(r'(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])', q.get('answer', '')))
            if not set(ids) <= known or inline != set(ids):
                raise ValueError('Citation IDs do not match evidence or answer')
            if q.get('insufficient_evidence', False) and ids:
                raise ValueError('Insufficient evidence cannot have citations')
            if not q.get('insufficient_evidence', False) and not ids:
                raise ValueError('Answer must have citations')
            citations = [c for c in citations if c.get('id') in ids]
        known = {c.get('id'): c for c in citations}
        order = []
        def marker(n):
            return display['markers'][n - 1] if n <= len(display['markers']) else display['overflow_template'].replace('{n}', str(n))
        def replace_ref(match):
            ident = match.group(1)
            if ident not in known:
                return esc(match.group(0))
            if ident not in order:
                order.append(ident)
            n = order.index(ident) + 1
            return f'<sup><a href="#q{i}-source-{n}" aria-label="来源 {n}">{esc(marker(n))}</a></sup>'
        answer = q.get('answer', '')
        paragraphs = []
        for paragraph in split_paragraphs(answer):
            parts = []
            pos = 0
            for match in re.finditer(r'\[([0-9a-fA-F]{64})\]', paragraph):
                parts.append(esc(paragraph[pos:match.start()]))
                parts.append(replace_ref(match))
                pos = match.end()
            parts.append(esc(paragraph[pos:]))
            paragraphs.append('<p class="answer-paragraph">' + ''.join(parts) + '</p>')
        rendered_answer = ''.join(paragraphs)
        if cited_only and not order:
            order.extend(ident for ident in q.get('citation_ids', []) if ident in known)
        cards = []
        summaries = []
        for n, ident in enumerate(order, 1):
            c = known[ident]
            heading = str(c.get('heading', ''))
            title, sep, raw = heading.partition('{')
            raw = '{' + raw if sep else ''
            try:
                loc = json.loads(raw) if raw else {}
            except (ValueError, TypeError):
                loc = {}
            title = title.strip() or display['unknown_source_label']
            location = []
            human = loc.get('origin') == 'human_edit' or str(loc.get('type', '')).startswith('human_')
            if human:
                location.append('人工修订，' + display['no_video_time_label'])
            elif 'start_seconds' in loc:
                location.append(str(loc['start_seconds']) + ('–' + str(loc['end_seconds']) if 'end_seconds' in loc else '') + ' 秒')
            elif 'seconds' in loc:
                location.append(str(loc['seconds']) + ' 秒')
            elif loc.get('type') in ('audio', 'video') and 'start' in loc:
                location.append(str(loc['start']) + ('–' + str(loc['end']) if 'end' in loc else '') + ' 秒')
            if 'offset' in loc:
                location.append('字符 ' + str(loc['offset']) + ('–' + str(loc['end_offset']) if 'end_offset' in loc else ''))
            loc_text = '，'.join(location) or display['no_video_time_label']
            label = esc(marker(n) + ' ' + title + ' · ' + loc_text)
            summaries.append(f'<li><a href="#q{i}-source-{n}">{label}</a></li>')
            cards.append(f'<details id="q{i}-source-{n}" class="source-card"><summary>{label}</summary><strong>{esc(display["evidence_label"])}</strong><blockquote>{esc(c.get("text", ""))}</blockquote><details><summary>{esc(display["technical_label"])}</summary><pre>{esc(ident)}\n{esc(c.get("source_path", ""))}\n{esc(raw)}</pre></details></details>')
        evidence = ''.join(cards)
        comparisons = ''.join('<h3>{}</h3><ol>{}</ol>'.format(esc(method), ''.join('<li>{} | {} | {}</li>'.format(esc(c.get('item_id', '')), esc(c.get('heading', '')), esc(c.get('score', ''))) for c in chunks[:3])) for method, chunks in q.get('retrievals', {}).items())
        evidence_section = ('<h3>' + esc(display['source_label']) + '</h3><ol>' + ''.join(summaries) + '</ol>' + evidence) if order else ''
        if cited_only and q.get('insufficient_evidence', False):
            evidence_section = '<p>未找到可支持回答的证据</p>'
        comparison_section = '<details><summary>检索对比</summary>' + comparisons + '</details>' if show_comparisons and not (cited_only and q.get('insufficient_evidence', False)) else ''
        revision = ''.join('<p>{}：{}</p>'.format(label, esc(q[key])) for key, label in [('output_version', '输出版本'), ('revision_note', '修改说明')] if q.get(key))
        entries.append(f'''<section id="q{i}"><h2>{esc(q['id'])} {esc(q['question'])}</h2>
<div class="answer-text">{rendered_answer}</div>{revision}{evidence_section}
{comparison_section}
<label>评分（0–100）<input type="number" min="0" max="100" step="1" data-field="score"></label>
<label>决定<select data-field="decision"><option value=""></option><option value="approve">通过</option><option value="rework">返工</option><option value="reject">拒绝</option></select></label>
<label>备注<textarea data-field="note"></textarea></label><label>评审人<input data-field="reviewer" value="本人"></label></section>''')
    bindings = [{'question_id': q['id'], 'output_sha256': hashlib.sha256(json.dumps(q, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()} for q in questions]
    payload = json.dumps({'run_id': report['run_id'], 'bindings': bindings, 'feedback_filename': presentation.get('feedback_filename', 'reviews.json')}, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    nav = ' '.join(f'<a href="#q{i}">{html.escape(str(q["id"]))}</a>' for i, q in enumerate(questions))
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>检索问答预研评审</title><style>body{font:16px sans-serif;max-width:900px;margin:auto;padding:2em;line-height:1.6}section{border-top:1px solid #bbb;padding:1em 0}label{display:block;margin:.5em 0}input,select,textarea{margin-left:1em}textarea{vertical-align:top}</style></head><body><h1>检索问答预研评审</h1><p>''' + html.escape(str(report.get('review_notice', '开发者拟题 / 待本人评分 / 非统计准确率'))) + '''</p><nav>''' + nav + '</nav>' + ''.join(entries) + '''<button id="export">导出 JSON</button><script type="application/json" id="data">''' + payload + '''</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
document.getElementById('export').addEventListener('click',()=>{
 const reviews=[];
 for (const [i,section] of [...document.querySelectorAll('section')].entries()) {
  const get=name=>section.querySelector('[data-field="'+name+'"]').value.trim();
  const score=get('score'), decision=get('decision'), note=get('note'), reviewer=get('reviewer');
  if(!score && !decision && !note) continue;
  if(score==='' || !Number.isInteger(Number(score)) || Number(score)<0 || Number(score)>100 || !decision || !reviewer) {
   alert('请填写 0–100 的整数评分、决定和评审人'); return;
  }
  reviews.push({...data.bindings[i],score:Number(score),decision,note,reviewer,reviewed_at:new Date().toISOString()});
 }
 const blob=new Blob([JSON.stringify({run_id:data.run_id,reviews},null,2)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=data.feedback_filename;a.click();URL.revokeObjectURL(a.href);
});</script></body></html>'''
    config = json.loads((Path(__file__).resolve().parent.parent / 'config/review-export.json').read_text(encoding='utf-8'))
    if type(config['revoke_delay_ms']) is not int or not 1000 <= config['revoke_delay_ms'] <= 3600000 or type(config['draft_enabled']) is not bool:
        raise ValueError('Invalid review export configuration')
    if type(presentation.get('external_assets', False)) is not bool:
        raise ValueError('external_assets must be boolean')
    filename = presentation.get('feedback_filename', 'reviews.json')
    if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9_-]+(?:[.][A-Za-z0-9_-]+)*[.]json', filename, re.ASCII):
        raise ValueError('feedback_filename must be a safe JSON basename')
    payload_data = json.loads(payload)
    payload_data.update(revoke_delay_ms=config['revoke_delay_ms'], draft_enabled=config['draft_enabled'])
    payload = json.dumps(payload_data, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    script = (Path(__file__).parent / 'review_export.js').read_text(encoding='utf-8')
    css = (Path(__file__).parent / 'review_export.css').read_text(encoding='utf-8')
    start = page.index('<style>')
    end = page.index('</style>', start) + len('</style>')
    external = presentation.get('external_assets', False)
    if external:
        basename = presentation.get('asset_basename', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', basename):
            raise ValueError('asset_basename must be a safe basename')
        style = f'<link rel="stylesheet" href="{basename}.css">'
        script_tag = f'<script src="{basename}.js" defer></script>'
        page = page.replace("style-src 'unsafe-inline'; script-src 'unsafe-inline'", "style-src 'self'; script-src 'self'")
    else:
        style = '<style>' + css + '</style>'
        script_tag = '<script>' + script + '</script>'
    start = page.index('<style>')
    end = page.index('</style>', start) + len('</style>')
    page = page[:start] + style + page[end:]
    page = page[:page.index('<button id="export">')] + '<button id="export">导出 JSON</button><p id="status" role="status"></p><label>JSON 复制备用<textarea id="fallback" readonly rows="12" cols="80"></textarea></label><script type="application/json" id="data">' + payload + '</script>' + script_tag + '</body></html>'
    output = Path(output)
    assets = [(output.parent / (basename + '.js'), script.encode('utf-8')),
              (output.parent / (basename + '.css'), css.encode('utf-8'))] if external else []
    if output.exists():
        raise FileExistsError(output)
    for path, content in assets:
        if path.exists() and path.read_bytes() != content:
            raise FileExistsError(f'Conflicting review asset: {path}')
    for path, content in assets:
        if not path.exists():
            with path.open('xb') as f:
                f.write(content)
    with output.open('x', encoding='utf-8') as f:
        f.write(page)
