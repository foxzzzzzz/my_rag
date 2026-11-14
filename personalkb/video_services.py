import base64
import json
import math
import re
import socket
import ipaddress
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.error import URLError


class ProviderError(RuntimeError):
    def __init__(self, code, request_id=None, *, metrics=None):
        self.code = code
        self.request_id = request_id if isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', request_id) else None
        self.metrics = metrics
        super().__init__(code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('redirect_forbidden')


class _Transport:
    def __init__(self, cfg):
        self.cfg = cfg

    def request(self, url, key=None, payload=None, headers=None):
        try:
            addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise ValueError()
        except Exception:
            raise ProviderError('provider_dns_failed') from None
        hdr = dict(headers or {})
        if key:
            hdr['Authorization'] = 'Bearer ' + key
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            hdr['Content-Type'] = 'application/json'
        try:
            with build_opener(_NoRedirect()).open(Request(url, data=data, headers=hdr), timeout=self.cfg['request_timeout_seconds']) as response:
                raw = response.read(self.cfg['response_max_bytes'] + 1)
                if len(raw) > self.cfg['response_max_bytes']:
                    raise ProviderError('response_too_large', response.headers.get('x-request-id'))
                try:
                    return response.status, json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ProviderError('provider_response_invalid', response.headers.get('x-request-id')
                                        or response.headers.get('x-dashscope-request-id')) from None
        except HTTPError as exc:
            request_id = (exc.headers.get('x-request-id') or exc.headers.get('x-dashscope-request-id')) if exc.headers else None
            exc.close()
            raise ProviderError(f'provider_http_{exc.code}', request_id) from None
        except URLError as exc:
            raise ProviderError('provider_timeout' if isinstance(exc.reason, TimeoutError) else 'provider_network_error') from None
        except TimeoutError:
            raise ProviderError('provider_timeout') from None
        except OSError:
            raise ProviderError('provider_network_error') from None


class ProviderClient:
    def __init__(self, model_config, pipeline_config, secrets, transport=None):
        self.models = model_config
        self.config = pipeline_config
        self._secrets = secrets
        self.transport = transport or _Transport(pipeline_config['transport'])

    def _request(self, url, key=None, payload=None, headers=None, download=False):
        u = urlsplit(url)
        host = (u.hostname or '').lower()
        cfg = self.config['transport']
        suffix = cfg['allowed_oss_suffix'].lower().lstrip('.')
        allowed = host in cfg['allowed_api_hosts'] if not download else host.endswith('.' + suffix)
        if u.scheme != 'https' or not allowed or u.username or u.password or u.port not in (None, 443):
            raise RuntimeError('provider_url_forbidden')
        try:
            status, data = self.transport.request(url, key=key, payload=payload, headers=headers)
        except ProviderError:
            raise
        except Exception:
            raise RuntimeError('provider_request_failed') from None
        if not 200 <= status < 300 or not isinstance(data, dict):
            raise RuntimeError('provider_response_invalid')
        return data

    def _provider(self, kind):
        model = self.models['models'][kind]
        provider = self.models['providers'][model['provider']]
        return model, provider, self._secrets[provider['api_key_env']]

    def submit_asr(self, asset):
        model, provider, key = self._provider('asr')
        payload = {'model': model['model'], 'input': {'file_urls': [asset.file_url]}, 'parameters': {'channel_id': [0], 'language_hints': ['zh', 'en'], 'timestamp_alignment_enabled': True}}
        data = self._request(provider['api_base_url'].rstrip('/') + '/services/audio/asr/transcription', key, payload, asset.asr_headers())
        task = data.get('output', {}).get('task_id')
        if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9-]+', task):
            raise RuntimeError('missing_task_id')
        return task

    def query_asr(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9-]+', task_id):
            raise RuntimeError('invalid_task_id')
        _, provider, key = self._provider('asr')
        return self._request(provider['api_base_url'].rstrip('/') + '/tasks/' + task_id, key).get('output', {})

    def download_asr(self, url, audio_seconds):
        data = self._request(url, download=True)
        segments = []
        for transcript in data.get('transcripts', []):
            for s in transcript.get('sentences', []):
                if not isinstance(s.get('text'), str) or not s['text'].strip():
                    continue
                a, b = s.get('begin_time'), s.get('end_time')
                if any(type(x) not in (int, float) or not math.isfinite(x) for x in (a, b)) or not 0 <= a < b <= (audio_seconds + self.config['strategy']['audio_duration_tolerance_seconds']) * 1000:
                    raise RuntimeError('invalid_native_timestamps')
                segments.append({'start_seconds': a / 1000, 'end_seconds': b / 1000, 'text': s['text']})
        if not segments:
            raise RuntimeError('asr_empty')
        def tc(value):
            ms = round(value * 1000)
            return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'
        return {'text': '\n'.join(f'[{tc(s["start_seconds"])}–{tc(s["end_seconds"])}] {s["text"]}' for s in segments), 'segments': segments, 'processed_audio_seconds': audio_seconds, 'estimated_cost_cny': str(Decimal(str(audio_seconds)) * Decimal(str(self.config['prices']['asr_per_second'])))}

    def _chat(self, kind, messages):
        model, provider, key = self._provider(kind)
        strategy = self.config['strategy']
        payload = {'model': model['model'], 'messages': messages, 'max_tokens': strategy[kind + '_max_tokens']}
        payload.update({'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}} if kind == 'text' else {'enable_thinking': False})
        data = self._request(provider['compatible_base_url'].rstrip('/') + '/chat/completions', key, payload)
        choices = data.get('choices')
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        finish_reason = choice.get('finish_reason')
        if not isinstance(finish_reason, str) or not re.fullmatch(r'[a-z][a-z_0-9]{0,63}', finish_reason):
            finish_reason = None
        raw_usage = data.get('usage')
        usage = {key: raw_usage[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                 if isinstance(raw_usage, dict) and type(raw_usage.get(key)) is int and raw_usage[key] >= 0}
        metrics = dict(finish_reason=finish_reason, output_chars=len(content) if isinstance(content, str) else None, usage=usage)
        request_id = data.get('id') or data.get('request_id')
        if finish_reason == 'length':
            raise ProviderError('model_output_truncated', request_id, metrics=metrics)
        if not isinstance(message, dict) or 'content' not in message or (content is not None and not isinstance(content, str)):
            raise ProviderError('model_output_invalid', request_id, metrics=metrics)
        if content is None or not content.strip():
            raise ProviderError('model_output_empty', request_id, metrics=metrics)
        prices = self.config['prices'][kind]
        cost = None
        if 'prompt_tokens' in usage and 'completion_tokens' in usage:
            cost = str((Decimal(usage['prompt_tokens']) * Decimal(str(prices[0])) + Decimal(usage['completion_tokens']) * Decimal(str(prices[1]))) / Decimal(1000000))
        return {'content': content, 'model': data.get('model', model['model']), 'usage': usage,
                'estimated_cost_cny': cost, 'provider_request_id': request_id, 'response_metrics': metrics}

    def vision(self, image_path):
        data = base64.b64encode(Path(image_path).read_bytes()).decode('ascii')
        return self._chat('vision', [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + data}}, {'type': 'text', 'text': self.config['strategy']['vision_prompt']}]}])

    def summarize(self, body, title):
        strategy = self.config['strategy']
        if len(body.encode('utf-8')) > strategy['max_context_utf8_bytes']:
            raise RuntimeError('context_too_large')
        result = self._chat('text', [{'role': 'system', 'content': strategy['text_system_prompt']}, {'role': 'user', 'content': title + '\n\n' + body}])
        try:
            structured = json.loads(result['content'])
            if not isinstance(structured, dict) or not all(isinstance(structured.get(k), str) and structured[k].strip() for k in ('summary', 'notes')):
                raise ValueError()
        except (ValueError, TypeError):
            raise ProviderError('invalid_summary_json', result.get('provider_request_id'), metrics=result['response_metrics']) from None
        result['structured'] = structured
        return result
