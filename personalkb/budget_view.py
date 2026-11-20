"""Join the budget ledger with available, attributable workflow estimates."""

import json
import re
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .model_budget import BudgetRevisionConflict, budget_snapshot, update_budget_limit
from .workflow import ROOT
from .workflow_store import WorkflowError


def _estimate(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount >= 0 else None
    except InvalidOperation:
        return None


def _workflow_details(store):
    path = Path(store.db_path).resolve().as_uri()
    with closing(sqlite3.connect(path + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        titles = dict(db.execute("""SELECT t.id,COALESCE(NULLIF(o.title,''),NULLIF(json_extract(v.result,'$.title'),''),
                     NULLIF(d.title,''),s.original_name)
              FROM tasks t JOIN sources s ON s.id=t.source_id
              LEFT JOIN source_title_overrides o ON s.id=o.source_id
              LEFT JOIN source_display_titles d ON s.id=d.source_id
              LEFT JOIN versions v ON s.current_version_id=v.id"""))
        requests, estimates = {}, {}
        for table, label in (('rag_requests', '知识库检索与问答'), ('classification_suggestions', '分类建议')):
            if table not in tables:
                continue
            for request_id, cost in db.execute(f"SELECT id,json_extract(result,'$.estimated_cost_cny') FROM {table}"):
                requests[request_id] = label
                estimates[request_id] = _estimate(cost)
        if 'video_stages' in tables:
            for task_id, stage, request_id, cost in db.execute("""SELECT task_id,name,json_extract(result,'$.request_id'),
                       json_extract(result,'$.estimated_cost_cny') FROM video_stages WHERE status='completed'"""):
                amount = _estimate(cost)
                if amount is None:
                    continue
                if stage == 'asr_result':
                    request_id = f'{task_id}:asr_submit'
                elif not request_id and stage == 'html-text':
                    request_id = f'{task_id}:html-text'
                if request_id:
                    estimates[request_id] = amount
    return titles, requests, estimates


def _entry_stage(entry):
    suffix = entry['request_id'].removeprefix(entry['run_id'] + ':')
    stage, _, retry = suffix.partition(':retry:')
    label = {'text':'生成文本', 'html-text':'整理网页', 'asr_submit':'语音转录', 'answer':'生成回答'}.get(stage)
    if not label and re.fullmatch(r'vision-\d+', stage):
        label = f'画面识别 · {stage.removeprefix("vision-")}'
    if not label and ('embedding:' in suffix or suffix.endswith(':embedding')):
        label = '生成向量'
    return f'{label} · 重试 {retry}' if label and retry.isdigit() else label


def _limits(web_config, video_budget):
    limits = {'video': str(video_budget['run_limit'])}
    for kind, key, fallback in (
        ('html', 'html_pipeline_config', 'config/html-pipeline.json'),
        ('rag', 'rag_config', 'config/rag.json'),
        ('classification', 'suggestions_config', 'config/classification-suggestions.json'),
    ):
        cfg = json.loads((ROOT / web_config.get(key, fallback)).read_text(encoding='utf-8-sig'))
        limits[kind] = str(cfg['budget']['run_limit'])
    return limits


def _with_details(result, limits, details):
    entries = result['entries']
    titles, requests, historical = details
    total = Decimal(0)
    known = 0
    for entry in entries:
        request_id = entry['request_id']
        estimate = _estimate(entry['estimated_cost_cny'])
        if estimate is None:
            estimate = historical.get(request_id)
        if estimate is not None:
            total += estimate
            known += 1
        entry.update(label=titles.get(entry['run_id']) or requests.get(request_id) or '历史请求',
                     stage=_entry_stage(entry), estimated_cost_cny=format(estimate, 'f') if estimate is not None else None)
        for key in ('reserved_cny', 'reserved_limit_cny'):
            if entry[key] is not None:
                entry[key] = format(Decimal(entry[key]), 'f')
    for key in ('limit_cny', 'reserved_cny', 'available_cny'):
        result[key] = format(Decimal(result[key]), 'f')
    result.update(estimated_cost_cny=format(total, 'f') if known else None, unknown_count=len(entries) - known,
                  run_limits=limits)
    return result


def overview(store, video_budget, web_config):
    result = budget_snapshot(ROOT / video_budget['ledger'], video_budget['research_limit'], include_entries=True)
    return _with_details(result, _limits(web_config, video_budget), _workflow_details(store))


def change_limit(store, video_budget, web_config, payload):
    value = payload.get('limit_cny')
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', value):
        raise WorkflowError('invalid_budget_limit')
    ledger = ROOT / video_budget['ledger']
    ledger.parent.mkdir(parents=True, exist_ok=True)
    limits = _limits(web_config, video_budget)
    details = _workflow_details(store)
    try:
        result = update_budget_limit(ledger, video_budget['research_limit'], value, payload.get('expected_revision'), include_entries=True)
    except BudgetRevisionConflict:
        raise WorkflowError('budget_revision_conflict') from None
    except ValueError:
        raise WorkflowError('invalid_budget_limit') from None
    return _with_details(result, limits, details)
