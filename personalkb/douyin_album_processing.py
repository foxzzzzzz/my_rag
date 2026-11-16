"""Process ordered images with durable, individually budgeted model steps."""
import json
import os
from decimal import Decimal

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


def pipeline_config(album):
    pc = {**album.service.pc, **album.config}
    strategy = pc['strategy']
    pc['strategy'] = {
        **strategy, 'vision_prompt': album.config['vision_prompt'],
        'text_system_prompt': strategy['text_system_prompt'] + '\n' + album.config['text_prompt_suffix'],
    }
    return pc


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


def run_album(album, task_id, reserved, *, resume=False, services=None):
    """Run under the dispatcher's execution guard."""
    pc = pipeline_config(album)
    store = album.store
    task = store.get_task(task_id)
    manifest = album.manifest(task['source_id'])
    if album.quote(len(manifest['images'])) > Decimal(reserved):
        raise WorkflowError('album_quote_changed')
    if services is None:
        keys = dotenv(ROOT / album.service.webcfg['env_file'])
        keys.update(os.environ)
        for kind in ('vision', 'text'):
            spec = pc['models']['models'][kind]
            ref = pc['models']['providers'][spec['provider']]['api_key_env']
            if not keys.get(ref, '').strip():
                raise WorkflowError('missing_model_credentials')
        services = ProviderClient(pc['models'], pc, keys)
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
        images, evidence = [], []
        title = manifest['title']
        caption = manifest['description'].strip()
        if caption:
            evidence.append({'type': 'caption', 'locator': '作品文案', 'text': caption})
        with _Heartbeat(store, task_id, token, pc['heartbeat_seconds']) as beat:
            for image, path, mime in materials:
                page = image['index']
                name = f'vision-{page}'
                extracted = _record_call(journal, task_id, token, name, _digest(image),
                                         amounts[name], pc, lambda: services.vision(path, mime=mime),
                                         beat, video_amounts=amounts)
                images.append({'index': page, 'text': extracted['content'], 'sha256': image['sha256']})
                evidence.append({'type': 'image', 'locator': f'图 {page}', 'page': page, 'text': extracted['content'],
                                 'image_sha256': image['sha256']})
            body = '\n\n'.join([
                f'## 作品信息\n{title}\n作者：{manifest["author"] or "未知"}\n'
                f'https://www.douyin.com/note/{manifest["work_id"]}',
                *([f'## 原文案\n{caption}'] if caption else []),
                *(f'## 图 {image["index"]}\n{image["text"]}' for image in images),
            ])
            strategy = pc['strategy']
            prompt_bytes = len((strategy['text_system_prompt'] + title + '\n\n' + body).encode('utf-8'))
            if prompt_bytes > pc['album_text_input_token_bound'] or len(body.encode('utf-8')) > strategy['max_context_utf8_bytes']:
                raise WorkflowError('album_context_limit')
            notes = _record_call(journal, task_id, token, 'text', _digest({'body': body, 'title': title}),
                                 amounts['text'], pc, lambda: services.summarize(body, title),
                                 beat, video_amounts=amounts)
            try:
                summary = summary_fields(notes.get('structured'), strategy)
            except ValueError:
                raise WorkflowError('invalid_summary_json') from None
            cost, unknown, additional = _cost_summary(store, task_id, pc)
            result = dict(title=title, body=body, **summary, evidence=evidence, images=images,
                          provenance='provider', output_kind='machine_initial', scheme_id='douyin-album',
                          scheme_version=fingerprint, processing={
                              'mode': 'model', 'model': notes.get('model'), 'reserved_cny': str(reserved),
                              'estimated_cost_cny': cost, 'stats': {
                                  'unknown_attempts': unknown, 'additional_reserved_cny': additional,
                              },
                          })
            beat.check()
        return store.finish(task_id, token, result)
    except Exception as exc:
        code = exc.code if isinstance(exc, (WorkflowError, ProviderError)) else 'album_processing_failed'
        try:
            store.fail(task_id, token, code)
        except WorkflowError:
            pass
        raise WorkflowError(code) from None
