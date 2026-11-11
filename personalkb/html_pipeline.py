"""Explicit, budgeted HTML processing; never runs page scripts or downloads assets."""
import json
import math
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .workflow import ROOT, _root, _hash, make_store
from .workflow_store import WorkflowError
from .video_journal import VideoJournal
from .video_pipeline import _digest, _bind_strategy, _legacy_text_prompt, _Heartbeat, _preflight, paid_stage
from .video_services import ProviderClient


def load_html_config(path=None):
    try:
        c = json.loads(Path(path or ROOT/'config/html-pipeline.json').read_text(encoding='utf-8-sig'))
        for key in ('models', 'strategy'):
            name = c.pop(key + '_file')
            c[key] = json.loads((ROOT/name).read_text(encoding='utf-8-sig'))
        c['strategy']['text_max_tokens'] = c['text_max_tokens']
        validate_config(c)
        return c
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation, AttributeError):
        raise WorkflowError('invalid_html_config') from None


def validate_config(c):
    try:
        positive = (c['text_max_tokens'], c['strategy']['max_context_utf8_bytes'], c['heartbeat_seconds'],
                    c['transport']['request_timeout_seconds'], c['transport']['response_max_bytes'])
        if any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in positive): raise ValueError()
        if type(c['text_max_tokens']) is not int or type(c['strategy']['max_context_utf8_bytes']) is not int: raise ValueError()
        amounts = [Decimal(str(x)) for x in (*c['prices']['text'], c['reserve_cny'], c['budget']['run_limit'], c['budget']['research_limit'])]
        if len(c['prices']['text']) != 2 or any(not x.is_finite() or x <= 0 for x in amounts): raise ValueError()
        if not Decimal(str(c['reserve_cny'])) <= Decimal(str(c['budget']['run_limit'])) <= Decimal(str(c['budget']['research_limit'])) <= 100: raise ValueError()
        if any(not isinstance(c[k], str) or not c[k].strip() for k in ('scheme_id', 'extractor_version')): raise ValueError()
        if not isinstance(c['strategy']['text_system_prompt'], str) or not c['strategy']['text_system_prompt'].strip(): raise ValueError()
        _legacy_text_prompt(c['strategy'])
        if not isinstance(c['budget']['ledger'], str) or not c['budget']['ledger'].strip(): raise ValueError()
        m = c['models']['models']['text']; p = c['models']['providers'][m['provider']]
        if any(not isinstance(x, str) or not x.strip() for x in (m['model'], p['api_key_env'], p['compatible_base_url'])): raise ValueError()
        from urllib.parse import urlsplit
        u = urlsplit(p['compatible_base_url'])
        if u.scheme != 'https' or u.username or u.password or u.port not in (None,443) or u.hostname not in c['transport']['allowed_api_hosts']: raise ValueError()
        return c
    except (KeyError, ValueError, TypeError, InvalidOperation, AttributeError):
        raise WorkflowError('invalid_html_config') from None


def _claim(store, task_id, resume):
    if not resume:
        task = store.claim_specific(task_id, 'html-model')
        if task is None: raise WorkflowError('invalid_state')
        return task
    # Only explicit recovery; paid_stage rejects any in-flight sync POST.
    import secrets
    with store._tx() as db:
        store._recover(db, time.time())
        t = store._row(db, 'tasks', task_id)
        s = store._row(db, 'sources', t['source_id'])
        if t['status'] != 'needs_attention' or s['deleted'] or s['kind'] != 'html' or db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone() or db.execute('SELECT 1 FROM video_maintenance').fetchone():
            raise WorkflowError('invalid_state')
        db.execute("UPDATE tasks SET status='running',worker_id='html-resume',lease_token=?,lease_until=?,attempts=attempts+1 WHERE id=?", (secrets.token_urlsafe(32), time.time()+store.lease_seconds, task_id))
        return store._row(db, 'tasks', task_id)


def run_html(*args, **kwargs):
    from .execution_guard import execution_guard
    with execution_guard(make_store(args[0] if args else kwargs["workflow_config"])):
        return _guarded_run_html(*args, **kwargs)

def _guarded_run_html(workflow_config, html_config, keys, *, task_id, resume=False, services=None):
    c = deepcopy(validate_config(html_config))
    store = make_store(workflow_config)
    initial = store.get_task(task_id)
    source = store.get_source(initial['source_id'])
    if source['kind'] != 'html' or source['deleted']: raise WorkflowError('invalid_source')
    if services is None:
        model = c['models']['models']['text']
        ref = c['models']['providers'][model['provider']]['api_key_env']
        if not isinstance(keys.get(ref), str) or not keys[ref].strip(): raise WorkflowError('missing_model_credentials')
    task = _claim(store, task_id, resume)
    token = task['lease_token']; journal = VideoJournal(store)
    try:
        fingerprint = _bind_strategy(journal, task_id, token, c, ('models','strategy','prices','scheme_id','extractor_version'))
        with store._tx() as db:
            store._lease(db,task_id,token,time.time())
            db.execute('CREATE TABLE IF NOT EXISTS html_runs (task_id TEXT PRIMARY KEY, base_version_id TEXT)')
            db.execute('INSERT OR IGNORE INTO html_runs(task_id,base_version_id) VALUES(?,?)',(task_id,source['current_version_id']))
            base_version=db.execute('SELECT base_version_id FROM html_runs WHERE task_id=?',(task_id,)).fetchone()[0]
            if base_version != source['current_version_id']: raise WorkflowError('version_conflict')
        if any(r['status']=='in_flight' for r in journal.list_stages(task_id)): raise WorkflowError('unknown_submission')
        root = _root(workflow_config).resolve(); candidate = root/source['blob_relpath']; blob = candidate.resolve()
        if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in (candidate,*candidate.parents)) or not blob.is_relative_to(root) or _hash(blob) != source['sha256']: raise WorkflowError('source_integrity')
        if blob.stat().st_size > workflow_config['max_html_bytes']: raise WorkflowError('invalid_size')
        with _Heartbeat(store,task_id,token,c['heartbeat_seconds']) as beat:
            store.checkpoint(task_id,token,'extracting_html')
            from .html_extract import extract_html
            extracted = extract_html(blob.read_text(encoding=workflow_config['html_encoding']))
            body = extracted['body']
            if extracted['svg_context']: body += '\n\n## SVG 原始结构（文本证据）\n' + extracted['svg_context']
            if not body.strip(): raise WorkflowError('empty_output')
            title = extracted['title'] or source['original_name']
            prompt = title + '\n\n' + body + c['strategy']['text_system_prompt']
            if len(prompt.encode('utf8')) > c['strategy']['max_context_utf8_bytes']: raise WorkflowError('context_too_large')
            # One UTF-8 byte per input token is a conservative allowance for this
            # validated provider; output bound includes the full configured cap.
            upper = (Decimal(len(prompt.encode('utf8')))*Decimal(str(c['prices']['text'][0])) + Decimal(c['text_max_tokens'])*Decimal(str(c['prices']['text'][1])))/1000000
            amount = Decimal(str(c['reserve_cny']))
            if upper > amount: raise WorkflowError('text_reservation_too_small')
            _preflight(journal,task_id,c,{'html-text':amount})
            beat.check()
            provider = services or ProviderClient(c['models'],c,keys)
            result = paid_stage(journal,task_id,token,'html-text',_digest({'body':body,'title':title}),amount,c,lambda:provider.summarize(body,title))
            if result.get('estimated_cost_cny') is not None and Decimal(str(result['estimated_cost_cny'])) > amount:
                raise WorkflowError('observed_cost_exceeds_reservation')
            beat.check()
            structured = result.get('structured',{})
            if not all(isinstance(structured.get(k),str) and structured[k].strip() for k in ('summary','notes')): raise WorkflowError('invalid_summary_json')
            output = dict(title=title,body=body,summary=structured['summary'],notes=structured['notes'],
                          evidence=[{'type':'html','locator':'static-extraction','text':body}],warnings=extracted['warnings'],
                          provenance='provider',output_kind='machine_initial',scheme_id=c['scheme_id'],scheme_version=fingerprint,
                          processing={'mode':'model','model':result.get('model',c['models']['models']['text']['model']),
                                      'usage':result.get('usage',{}),'estimated_cost_cny':result.get('estimated_cost_cny'),
                                      'reserved_cny':str(amount),'extractor_version':c['extractor_version'],'stats':extracted['stats']})
            # A human edit while processing must not be silently superseded.
            version = store.finish(task_id,token,output,expected_version_id=base_version)
        return version
    except Exception as exc:
        code = exc.code if isinstance(exc,WorkflowError) else 'html_processing_failed'
        try: store.fail(task_id,token,code)
        except WorkflowError: pass
        raise WorkflowError(code) from None


def html_status(workflow_config, task_id):
    store=make_store(workflow_config); t=store.get_task(task_id)
    return {'task_id':task_id,'status':t['status'],'error_code':t['error_code'],
            'stages':VideoJournal(store).list_stages(task_id)}
