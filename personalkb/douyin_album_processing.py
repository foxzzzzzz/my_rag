"""Process ordered images with durable, individually budgeted model steps."""
import hashlib
import json
import os
from decimal import Decimal, ROUND_CEILING

from tools.demo_setup import dotenv

from .douyin_album import stage_amounts
from .summary_structure import summary_fields
from .video_journal import VideoJournal
from .video_pipeline import (
    _Heartbeat, _bind_strategy, _chat_recovery, _digest,
    _favorites_budget_preflight, _preflight, _record_call,
)
from .video_services import ProviderClient, ProviderError
from .workflow import ROOT
from .workflow_store import WorkflowError


ALBUM_TEXT_RETRY_MODE = 'retry-album-text'


def pipeline_config(album):
    pc = {**album.service.pc, **album.config}
    strategy = pc['strategy']
    pc['strategy'] = {
        **strategy, 'vision_prompt': album.config['vision_prompt'],
        'text_system_prompt': strategy['text_system_prompt'] + '\n' + album.config['text_prompt_suffix'],
    }
    return pc


def _text_retry_config(album):
    prompt = album.config.get('text_retry_prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkflowError('album_text_retry_unavailable')
    pc = pipeline_config(album)
    pc['strategy'].update(text_system_prompt=prompt.strip() + '\n' + album.config['text_prompt_suffix'],
                          summary_format='structured')
    return pc


def _album_body(manifest, images):
    caption = manifest['description'].strip()
    return '\n\n'.join([
        f'## 作品信息\n{manifest["title"]}\n作者：{manifest["author"] or "未知"}\n'
        f'https://www.douyin.com/note/{manifest["work_id"]}',
        *([f'## 原文案\n{caption}'] if caption else []),
        *(f'## 图 {image["index"]}\n{image["text"]}' for image in images),
    ])


def _check_album_context(pc, body, title):
    strategy = pc['strategy']
    prompt_bytes = len((strategy['text_system_prompt'] + title + '\n\n' + body).encode('utf-8'))
    if prompt_bytes > pc['album_text_input_token_bound'] or len(body.encode('utf-8')) > strategy['max_context_utf8_bytes']:
        raise WorkflowError('album_context_limit')


def _saved_album_text_inputs(album, db, task, source):
    manifest = album._manifest(source)
    stages = {row['name']: row for row in db.execute(
        'SELECT name,status,input_sha256,result,result_sha256 FROM video_stages WHERE task_id=?', (task['id'],))}
    images = []
    for index, image in enumerate(manifest['images'], 1):
        stage = stages.get(f'vision-{index}')
        if not (image['index'] == index and stage and stage['status'] == 'completed' and stage['result']
                and stage['input_sha256'] == _digest(image)
                and hashlib.sha256(stage['result'].encode()).hexdigest() == stage['result_sha256']):
            raise WorkflowError('album_text_retry_unavailable')
        content = json.loads(stage['result'])['content']
        if not isinstance(content, str) or not content.strip():
            raise WorkflowError('album_text_retry_unavailable')
        images.append(dict(index=index, text=content, sha256=image['sha256']))
    body = _album_body(manifest, images)
    digest = _digest({'body': body, 'title': manifest['title']})
    text = stages.get('text')
    if not text or text['status'] != 'in_flight' or text['input_sha256'] != digest:
        raise WorkflowError('album_text_retry_unavailable')
    return manifest, images, body, digest


def _prepare_album_text_retry(album, db, task, source):
    if (source['kind'] != 'douyin_album' or source['deleted'] or source['current_version_id'] is not None
            or task['status'] not in ('cancelled', 'needs_attention') or task['stage'] != 'text'):
        return None
    attempts = db.execute("""SELECT * FROM video_chat_attempts WHERE task_id=? AND stage='text'
                             ORDER BY attempt DESC""", (task['id'],)).fetchall()
    if not attempts or any(row['response_sha256'] for row in attempts):
        return None
    latest = attempts[0]
    pending = latest['album_text_retry_key'] and not latest['started'] and latest['diagnostic'] is None
    if task['status'] != 'cancelled' and not latest['album_text_retry_key']:
        return None
    if not pending and not (task['error_code'] == 'model_output_truncated' and
                            latest['diagnostic'] == 'model_output_truncated'):
        return None
    original = db.execute('SELECT amount FROM favorites_conversion WHERE task_id=?', (task['id'],)).fetchone()
    if not original or not Decimal(original['amount']).is_finite() or Decimal(original['amount']) <= 0:
        return None
    manifest, images, body, digest = _saved_album_text_inputs(album, db, task, source)
    pc = _text_retry_config(album)
    _check_album_context(pc, body, manifest['title'])
    amount = stage_amounts(pc)['text']
    plan = {'stage': 'text', 'mode': ALBUM_TEXT_RETRY_MODE, 'amount': str(amount),
            'ceiling_cny': str(amount.quantize(Decimal('.01'), rounding=ROUND_CEILING)), 'image_count': len(images)}
    identity = dict(task_id=task['id'], input=digest, config=pc['strategy'], models=pc['models'],
                    prices=pc['prices']['text'], amount=str(amount), original=original['amount'])
    attempt = latest['attempt'] if pending else latest['attempt'] + 1
    quote_key = _digest({**identity, 'attempt': attempt})
    if pending and (quote_key != latest['album_text_retry_key'] or str(amount) != latest['amount']):
        attempt += 1
        quote_key = _digest({**identity, 'attempt': attempt})
    plan.update(attempt=attempt, quote_key=quote_key)
    return plan, (manifest, images, body, digest, pc, original['amount'])


def album_text_retry_plan(album, db, task, source):
    try:
        prepared = _prepare_album_text_retry(album, db, task, source)
    except (WorkflowError, ValueError, KeyError, TypeError, ArithmeticError):
        return None
    return prepared[0] if prepared else None


def _confirmed_work_budget(album, task, work_id, reserved):
    limit = album.manual_work_budget(work_id)
    if limit is None:
        return None, None
    with album.store._tx() as db:
        row = db.execute("""SELECT m.video_budget_cny,e.image_count,r.amount FROM favorites_queue q
                           JOIN favorites_manual_consent m ON m.queue_seq=q.seq
                           LEFT JOIN favorites_manual_album_extensions e ON e.queue_seq=m.queue_seq
                           JOIN favorites_conversion r ON r.task_id=q.task_id AND r.account_id=q.account_id
                           JOIN douyin_jobs j ON j.id=q.job_id AND j.source_id=?
                           WHERE q.task_id=? AND q.work_id=? AND q.automatic=0""",
                         (task['source_id'], task['id'], work_id)).fetchone()
    if row and Decimal(row['video_budget_cny']) == Decimal(row['amount']) == reserved:
        return min(limit, reserved), row['image_count']
    return None, None


def _cost_summary(store, task_id, pc):
    with store._tx() as db:
        rows = db.execute("""SELECT stage,response_metrics,attempt,automatic,amount,started FROM video_chat_attempts
                             WHERE task_id=? ORDER BY stage,attempt""", (task_id,)).fetchall()
    cost = Decimal(0)
    additional = Decimal(0)
    unknown = 0
    for row in rows:
        if row['attempt'] and row['started'] and not row['automatic']:
            additional += Decimal(row['amount'])
        if row['attempt'] and not row['started']:
            continue
        metrics = json.loads(row['response_metrics']) if row['response_metrics'] else {}
        usage = metrics.get('usage', {})
        if {'prompt_tokens', 'completion_tokens'} <= usage.keys():
            kind = 'text' if row['stage'] == 'text' else 'vision'
            in_rate, out_rate = pc['prices'][kind]
            cost += (Decimal(usage['prompt_tokens']) * Decimal(str(in_rate)) +
                     Decimal(usage['completion_tokens']) * Decimal(str(out_rate))) / 1000000
        else:
            unknown += 1
    return str(cost), unknown, str(additional)


def _album_result(store, task_id, pc, manifest, images, body, notes, reserved, fingerprint):
    try:
        summary = summary_fields(notes.get('structured'), pc['strategy'])
    except ValueError:
        raise WorkflowError('invalid_summary_json') from None
    caption = manifest['description'].strip()
    evidence = [{'type': 'caption', 'locator': '作品文案', 'text': caption}] if caption else []
    evidence.extend({'type': 'image', 'locator': f'图 {image["index"]}', 'page': image['index'], 'text': image['text'],
                     'image_sha256': image['sha256']} for image in images)
    cost, unknown, additional = _cost_summary(store, task_id, pc)
    return dict(title=manifest['title'], body=body, **summary, evidence=evidence, images=images,
                provenance='provider', output_kind='machine_initial', scheme_id='douyin-album',
                scheme_version=fingerprint, processing={
                    'mode': 'model', 'model': notes.get('model'), 'reserved_cny': str(reserved),
                    'estimated_cost_cny': cost, 'stats': {
                        'unknown_attempts': unknown, 'additional_reserved_cny': additional,
                    },
                })


def _album_services(album, pc, kinds):
    keys = dotenv(ROOT / album.service.webcfg['env_file'])
    keys.update(os.environ)
    for kind in kinds:
        spec = pc['models']['models'][kind]
        ref = pc['models']['providers'][spec['provider']]['api_key_env']
        if not keys.get(ref, '').strip():
            raise WorkflowError('missing_model_credentials')
    return ProviderClient(pc['models'], pc, keys)


def run_album_text_retry(album, task_id, *, services=None):
    store = album.store
    journal = VideoJournal(store)
    with store._tx() as db:
        task = store._row(db, 'tasks', task_id)
        source = store._row(db, 'sources', task['source_id'])
        prepared = _prepare_album_text_retry(album, db, task, source)
        if not prepared or task['status'] != 'needs_attention':
            raise WorkflowError('album_text_retry_unavailable')
        quote, (manifest, images, body, digest, pc, reserved) = prepared
        authorized = db.execute("""SELECT amount,started,album_text_retry_key FROM video_chat_attempts
                                  WHERE task_id=? AND stage='text' AND attempt=?""",
                                (task_id, quote['attempt'])).fetchone()
        if not authorized or authorized['started'] or (authorized['amount'], authorized['album_text_retry_key']) != (
            quote['amount'], quote['quote_key'],
        ):
            raise WorkflowError('model_recovery_conflict')
        additional = sum((Decimal(row[0]) for row in db.execute(
            'SELECT amount FROM video_chat_attempts WHERE task_id=? AND attempt>0 AND automatic=0 AND amount IS NOT NULL',
            (task_id,))), Decimal(0))
    pc['budget'] = {**pc['budget'], 'run_limit': str(Decimal(reserved) + additional)}
    pc['chat_timeout_retries'] = 0
    if services is None:
        services = _album_services(album, pc, ('text',))
    task = journal.resume_claim(task_id, 'douyin-album')
    token = task['lease_token']
    amount = Decimal(quote['amount'])
    try:
        _preflight(journal, task_id, pc, {'text': amount}, {'text': quote['attempt']})
        with _Heartbeat(store, task_id, token, pc['heartbeat_seconds']) as beat:
            notes = _record_call(journal, task_id, token, 'text', digest, amount, pc,
                                 lambda: services.summarize(body, manifest['title']), beat)
            result = _album_result(store, task_id, pc, manifest, images, body, notes, reserved, quote['quote_key'])
            beat.check()
        return store.finish(task_id, token, result, expected_version_id=None)
    except Exception as exc:
        code = exc.code if isinstance(exc, (WorkflowError, ProviderError)) else 'album_processing_failed'
        try:
            store.fail(task_id, token, code)
        except WorkflowError:
            pass
        raise WorkflowError(code) from None


def run_album(album, task_id, reserved, *, resume=False, services=None):
    """Run under the dispatcher's execution guard."""
    pc = pipeline_config(album)
    store = album.store
    task = store.get_task(task_id)
    manifest = album.manifest(task['source_id'])
    work_id = manifest['work_id']
    reserved = Decimal(reserved)
    work_budget, extended_image_count = _confirmed_work_budget(album, task, work_id, reserved)
    amount = album.quote(len(manifest['images']), work_id=work_id, manual=work_budget is not None,
                         extended_image_count=extended_image_count)
    if amount > reserved:
        raise WorkflowError('album_quote_changed')
    if work_budget is not None:
        # Only this confirmed manual task receives a different ledger ceiling.
        pc['budget'] = {**pc['budget'], 'run_limit': str(work_budget)}
    if services is None:
        services = _album_services(album, pc, ('vision', 'text'))
    rates = stage_amounts(pc)
    materials = [(image, *album.original_image(task['source_id'], image['index'])) for image in manifest['images']]
    amounts = {f'vision-{image["index"]}': rates['vision'] for image, _, _ in materials}
    amounts['text'] = rates['text']
    journal = VideoJournal(store)
    task = (journal.resume_claim if resume else journal.claim_task)(task_id, 'douyin-album')
    token = task['lease_token']
    try:
        fingerprint = _bind_strategy(journal, task_id, token, pc, ('models', 'strategy', 'prices', 'album_text_input_token_bound'))
        retries, restored = {}, set()
        for stage in journal.list_stages(task_id):
            if stage['status'] == 'in_flight':
                name = stage['name']
                saved, attempt = _chat_recovery(journal, task_id, name, amounts[name])
                if saved is not None:
                    restored.add(name)
                if attempt is not None:
                    retries[name] = attempt
        _favorites_budget_preflight(store, task_id, amounts)
        _preflight(journal, task_id, pc, amounts, retries, restored)
        images = []
        title = manifest['title']
        with _Heartbeat(store, task_id, token, pc['heartbeat_seconds']) as beat:
            for image, path, mime in materials:
                page = image['index']
                name = f'vision-{page}'
                extracted = _record_call(journal, task_id, token, name, _digest(image),
                                         amounts[name], pc, lambda: services.vision(path, mime=mime),
                                         beat, video_amounts=amounts)
                images.append({'index': page, 'text': extracted['content'], 'sha256': image['sha256']})
            body = _album_body(manifest, images)
            _check_album_context(pc, body, title)
            notes = _record_call(journal, task_id, token, 'text', _digest({'body': body, 'title': title}),
                                 amounts['text'], pc, lambda: services.summarize(body, title),
                                 beat, video_amounts=amounts)
            result = _album_result(store, task_id, pc, manifest, images, body, notes, reserved, fingerprint)
            beat.check()
        return store.finish(task_id, token, result)
    except Exception as exc:
        code = exc.code if isinstance(exc, (WorkflowError, ProviderError)) else 'album_processing_failed'
        try:
            store.fail(task_id, token, code)
        except WorkflowError:
            pass
        raise WorkflowError(code) from None
