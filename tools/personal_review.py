"""Offline, local-only personal review of supplied conversion artifacts."""
import argparse
import hashlib
import html
import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'config/personal-review.json'
FIELDS = {'id','source_path','source_sha256','scheme_id','scheme_version','run_id','output_version','output_kind','status','provenance','transcript','visual','body','summary','notes','duration_seconds','cost_cny'}

def load(path):
    def bad(value): raise ValueError('JSON 不能包含非有限数: '+value)
    with open(path, encoding='utf-8-sig') as f: return json.load(f, parse_constant=bad)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')

def bundle_hash(bundle): return hashlib.sha256(canonical(bundle)).hexdigest()

def item_binding(item, digest):
    return {'item_sha256':hashlib.sha256(canonical(item)).hexdigest(), **{k:item[k] for k in ('source_sha256','scheme_id','scheme_version','run_id','output_version','output_kind')}}

def safe_source(root, rel):
    if not isinstance(rel,str) or not rel or Path(rel).is_absolute(): raise ValueError('来源路径无效')
    root=Path(root).resolve(); path=(root/rel).resolve()
    if not path.is_relative_to(root) or not path.is_file(): raise ValueError('来源不存在或路径越界')
    return path

def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def finite(value): return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def validate_bundle(bundle, root):
    if not isinstance(bundle,dict) or set(bundle)!={'items'} or not isinstance(bundle['items'],list) or not bundle['items']: raise ValueError('bundle 必须包含非空 items')
    ids=set(); paths={}
    for item in bundle['items']:
        if not isinstance(item,dict) or set(item)!=FIELDS: raise ValueError('item 字段无效')
        for key in ('id','source_path','source_sha256','scheme_id','scheme_version','run_id','output_version'):
            if not isinstance(item[key],str) or not item[key].strip(): raise ValueError('缺少字段: '+key)
        if item['id'] in ids: raise ValueError('item ID 重复')
        ids.add(item['id'])
        for key in ('transcript','visual','body','summary','notes'):
            if not isinstance(item[key],str): raise ValueError('内容须为文本: '+key)
        if not any(item[k].strip() for k in ('transcript','visual','body')) or not item['summary'].strip() or not item['notes'].strip(): raise ValueError('缺少正文、摘要或笔记')
        if Path(item['source_path']).suffix.lower() in ('.mp4','.mov','.mkv','.webm') and (not item['transcript'].strip() or not item['visual'].strip()): raise ValueError('视频转录与视觉须提供内容或明确缺失原因')
        if item['status']!='completed' or item['provenance']!='provider' or item['output_kind'] not in ('machine_initial','human_edited'): raise ValueError('结果状态或来源不符合要求')
        for key in ('duration_seconds','cost_cny'):
            if item[key] is not None and (not finite(item[key]) or item[key]<0): raise ValueError('耗时或费用无效')
        p=safe_source(root,item['source_path'])
        if file_hash(p)!=item['source_sha256']: raise ValueError('来源哈希不匹配: '+item['id'])
        paths[item['id']]=p
    return paths

def config():
    c=load(CONFIG)
    if not isinstance(c,dict) or not finite(c.get('quality_target')) or not 0<=c['quality_target']<=100 or not isinstance(c.get('default_reviewer'),str) or not c['default_reviewer'].strip(): raise ValueError('评审配置无效')
    return c

def build(bundle, paths, c, output):
    digest=bundle_hash(bundle); esc=lambda s:html.escape(str(s),quote=True); blocks=[]
    for i,item in enumerate(bundle['items']):
        uri=paths[item['id']].as_uri(); parts=[f'<section id="item-{i}"><h2>{esc(Path(item["source_path"]).name)}</h2>',f'<p>方案：{esc(item["scheme_id"])} / {esc(item["scheme_version"])}；运行：{esc(item["run_id"])}；版本：{esc(item["output_version"])} / {esc(item["output_kind"])}</p>',f'<p>耗时（秒）：{esc(item["duration_seconds"] if item["duration_seconds"] is not None else "未知")}；费用（元）：{esc(item["cost_cny"] if item["cost_cny"] is not None else "未知")}</p>',f'<p><a href="{esc(uri)}" download>下载原始文件</a></p>']
        for key,label in [('summary','摘要'),('notes','笔记')]: parts.append(f'<h3>{label}</h3><pre>{esc(item[key])}</pre>')
        parts.append(f'<label>评分 <input id="score{i}" type="number" min="0" max="100" step="any"></label> <label>决定 <select id="decision{i}"><option value="">未评</option><option value="approve">批准</option><option value="rework">返工</option><option value="reject">拒绝</option></select></label> <label>审核人 <input id="reviewer{i}" value="{esc(c["default_reviewer"])}"></label><p>问题标签（逗号分隔） <input id="tags{i}"></p><p>备注 <textarea id="note{i}"></textarea></p>')
        for key,label in [('transcript','转录'),('visual','视觉'),('body','正文')]: parts.append(f'<details><summary>{label}</summary><pre>{esc(item[key])}</pre></details>')
        parts.append('</section>'); blocks.extend(parts)
    navigation='<nav><h2>目录</h2><ol>'+''.join(f'<li><a href="#item-{i}">{esc(Path(item["source_path"]).name)}</a></li>' for i,item in enumerate(bundle['items']))+'</ol></nav>'
    data=[{'item_id':it['id'],'binding':item_binding(it,digest)} for it in bundle['items']]
    safe_json=json.dumps(data,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    page='''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>个人评审</title><style>body{font:16px sans-serif;max-width:1100px;margin:auto;padding:2em}section{border-top:1px solid #aaa;padding:1em 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:1em}input,select,textarea{font:inherit}</style></head><body><h1>personal_review 本人评审</h1><p>仅当前 bundle 列出产物的审核就绪，不代表全部 demo 完成或选型，不自动写入 RAG；费用仅展示，预算预检请另行执行。</p>'''+navigation+''.join(blocks)+'''<button id="export">导出反馈 JSON</button><script>const items='''+safe_json+''';document.getElementById('export').addEventListener('click',()=>{const reviews=[];for(let i=0;i<items.length;i++){const get=id=>document.getElementById(id+i).value;const decision=get('decision'),raw=get('score');if(!decision&&!raw)continue;if(!decision||!raw||!get('reviewer').trim()){alert('请填写完整评分、决定和审核人');return;}let score=Number(raw);if(!Number.isFinite(score)||score<0||score>100){alert('评分须为0至100');return;}reviews.push({...items[i],review_id:crypto.randomUUID(),overall_score:score,decision,reviewer:get('reviewer'),reviewed_at:new Date().toISOString(),tags:get('tags').split(',').map(x=>x.trim()).filter(Boolean),note:get('note')});}const blob=new Blob([JSON.stringify({reviews},null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='feedback.json';a.click();URL.revokeObjectURL(a.href);});</script></body></html>'''
    with open(output,'x',encoding='utf8') as f: f.write(page)

def summarize(bundle, feedback, target):
    if not isinstance(feedback,dict) or set(feedback)!={'reviews'} or not isinstance(feedback['reviews'],list): raise ValueError('反馈格式无效')
    items={x['id']:x for x in bundle['items']}; digest=bundle_hash(bundle); seen=set(); times=set(); latest={}
    fields={'review_id','item_id','binding','overall_score','decision','reviewer','reviewed_at','tags','note'}
    for r in feedback['reviews']:
        if not isinstance(r,dict) or set(r)!=fields: raise ValueError('反馈字段无效')
        rid=r['review_id']; ident=r['item_id']
        if not isinstance(rid,str) or not rid.strip() or rid in seen or not isinstance(ident,str) or ident not in items: raise ValueError('审核 ID 重复或未知项目')
        seen.add(rid)
        if r['binding']!=item_binding(items[ident],digest): raise ValueError('反馈绑定与当前版本不符')
        if not finite(r['overall_score']) or not 0<=r['overall_score']<=100 or r['decision'] not in ('approve','rework','reject') or not isinstance(r['reviewer'],str) or not r['reviewer'].strip() or not isinstance(r['note'],str) or not isinstance(r['tags'],list) or not all(isinstance(t,str) for t in r['tags']): raise ValueError('评分或审核字段无效')
        if not isinstance(r['reviewed_at'],str): raise ValueError('审核时间无效')
        try: t=datetime.fromisoformat(r['reviewed_at'].replace('Z','+00:00'))
        except ValueError: raise ValueError('审核时间无效')
        if t.tzinfo is None or t.utcoffset() is None: raise ValueError('审核时间须带时区')
        if (ident,t) in times: raise ValueError('同一项目审核时间存在歧义')
        times.add((ident,t))
        if ident not in latest or t>latest[ident][0]: latest[ident]=(t,r)
    rows=[]
    for ident in items:
        r=latest.get(ident,(None,None))[1]; ready=bool(r and r['decision']=='approve' and r['overall_score']>=target)
        rows.append({'item_id':ident, **{key:items[ident][key] for key in ('source_path','source_sha256','scheme_id','scheme_version','run_id','output_version','output_kind')},'score':r['overall_score'] if r else None,'decision':r['decision'] if r else None,'review_ready':ready, **{key:r[key] if r else None for key in ('review_id','reviewer','reviewed_at','tags','note')}})
    scores=[x['score'] for x in rows if x['score'] is not None]
    tag_counts={}
    for row in rows:
        for tag in set(row['tags'] or []): tag_counts[tag]=tag_counts.get(tag,0)+1
    return {'mode':'personal_review','scope':'仅当前 bundle 列出的产物','quality_target':target,'items':rows,'unreviewed':[x['item_id'] for x in rows if x['score'] is None],'rework':[x['item_id'] for x in rows if x['decision']=='rework'],'rejected':[x['item_id'] for x in rows if x['decision']=='reject'],'low_score':[x['item_id'] for x in rows if x['score'] is not None and x['score']<target],'problem_tags':tag_counts,'minimum_score':min(scores) if scores else None,'mean_score':sum(scores)/len(scores) if scores else None,'all_review_ready':all(x['review_ready'] for x in rows),'note':'个人审核就绪，不代表客观准确率或授权写入 RAG'}

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    for name in ('build','summarize'):
        q=sub.add_parser(name); q.add_argument('--bundle',required=True); q.add_argument('--source-root',required=True)
        if name=='build': q.add_argument('--output',required=True)
        else: q.add_argument('--feedback',required=True,action='append')
    a=p.parse_args(); c=config(); bundle=load(a.bundle); paths=validate_bundle(bundle,a.source_root)
    if a.command=='build': build(bundle,paths,c,a.output); print('已生成个人评审页，未进行模型调用。')
    else:
        combined=[]
        for path in a.feedback:
            feedback=load(path)
            if not isinstance(feedback,dict) or set(feedback)!={'reviews'} or not isinstance(feedback['reviews'],list): raise ValueError('反馈格式无效')
            combined.extend(feedback['reviews'])
        print(json.dumps(summarize(bundle,{'reviews':combined},c['quality_target']),ensure_ascii=False))
    return 0
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8'); sys.stderr.reconfigure(encoding='utf8')
    try: sys.exit(main())
    except (ValueError,KeyError,TypeError,OSError,OverflowError,AttributeError,RecursionError) as e: print('错误: '+str(e),file=sys.stderr); sys.exit(2)
