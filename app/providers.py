"""Server-only provider credentials and model selection. Never return secret values."""
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from .hosting import CURRENT

CONFIG = Path(__file__).resolve().parents[1] / '.env'
LOCK = threading.RLock()
GOOGLE = 'https://generativelanguage.googleapis.com/v1beta/'
LOCAL_MODEL = 'qwen2.5:3b'

class ProviderError(OSError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


PROVIDERS = ('local', 'gemini', 'openai', 'anthropic')
CLOUD = ('gemini', 'openai', 'anthropic')
KEY_NAMES = {'gemini': 'ENU_GEMINI_KEY', 'openai': 'ENU_OPENAI_KEY', 'anthropic': 'ENU_ANTHROPIC_KEY'}
ENV_KEYS = {'gemini': 'GEMINI_API_KEY', 'openai': 'OPENAI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY'}


def read_values():
    space = CURRENT.get()
    if space is not None:
        return dict(space['values'])
    values = {}
    if CONFIG.exists():
        for line in CONFIG.read_text().splitlines():
            name, sep, value = line.partition('=')
            if sep and name.startswith('ENU_'):
                try:
                    values[name] = json.loads(value)
                except ValueError:
                    values[name] = value
    return values


def settings(provider=None):
    values = read_values()
    active = values.get('ENU_PROVIDER', 'local')
    provider = provider or active
    if provider not in PROVIDERS:
        raise ValueError('Invalid provider')
    model = values.get('ENU_' + provider.upper() + '_MODEL', values.get('ENU_MODEL', '') if provider == active else '')
    if provider == 'local':
        model = LOCAL_MODEL
    return {'provider': provider, 'model': model,
            'key': values.get(KEY_NAMES.get(provider, ''), (os.environ.get(ENV_KEYS.get(provider, ''), '') if CURRENT.get() is None else '')),
            'allow_documents': values.get('ENU_' + provider.upper() + '_DOCUMENTS', values.get('ENU_ALLOW_CLOUD_DOCUMENTS', False) if provider == 'gemini' else False) is True}


def public_settings():
    c = settings()
    per_provider = {provider: {'key_saved': bool(settings(provider)['key']), 'model': settings(provider)['model'], 'allow_documents': settings(provider)['allow_documents']} for provider in PROVIDERS}
    return {'provider': c['provider'], 'model': c['model'], 'key_saved': bool(c['key']), 'allow_documents': c['allow_documents'], 'providers': per_provider, 'hosted': CURRENT.get() is not None}


def save_settings(body):
    with LOCK:
        c = settings()
        provider = body.get('provider', c['provider'])
        target = body.get('key_provider', provider)
        if provider not in PROVIDERS or target not in PROVIDERS:
            raise ValueError('Invalid provider')
        if CURRENT.get() is not None and provider == 'local':
            raise ValueError('Local Ollama is not available on this hosted demo')
        model = body.get('model', settings(provider)['model'])
        if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9._:/-]{0,140}', model):
            raise ValueError('Invalid model')
        key = body.get('api_key', '')
        if not isinstance(key, str) or len(key) > 2048 or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
            raise ValueError('Invalid key')
        values = read_values()
        if target in CLOUD:
            if key or body.get('clear_key') is True:
                values[KEY_NAMES[target]] = '' if body.get('clear_key') is True else key
            if 'allow_documents' in body:
                if type(body['allow_documents']) is not bool:
                    raise ValueError('Invalid document setting')
                values['ENU_' + target.upper() + '_DOCUMENTS'] = body['allow_documents']
        values.update(ENU_PROVIDER=provider, ENU_MODEL=model)
        values['ENU_' + provider.upper() + '_MODEL'] = model
        if CURRENT.get() is not None:
            CURRENT.get()['values'].clear()
            CURRENT.get()['values'].update(values)
            return public_settings()
        existing = [line for line in CONFIG.read_text().splitlines() if line.partition('=')[0] not in values] if CONFIG.exists() else []
        temp = CONFIG.with_name('.env.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(temp, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('\n'.join(existing + [f'{k}={json.dumps(v)}' for k, v in values.items()]) + '\n')
        temp.replace(CONFIG)
        return public_settings()


def provider_request(provider, path, payload=None):
    bases = {'gemini': GOOGLE, 'openai': 'https://api.openai.com/v1/', 'anthropic': 'https://api.anthropic.com/v1/'}
    if provider not in bases or not re.fullmatch(r'[a-zA-Z0-9._:/?=&%+-]+', path) or path.startswith('/') or '..' in path:
        raise ValueError('Invalid provider path')
    key = settings(provider)['key']
    if not key:
        raise ProviderError('key_required')
    headers = {'Content-Type': 'application/json'}
    if provider == 'gemini':
        headers['x-goog-api-key'] = key
    else:
        headers['Authorization'] = 'Bearer ' + key
    if provider == 'anthropic':
        headers['anthropic-version'] = '2026-10-21'
    request = urllib.request.Request(bases[provider] + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        code = {401: 'invalid_key', 403: 'access_denied', 404: 'model_unavailable', 429: 'quota_exceeded'}.get(error.code, 'provider_error')
        try:
            details = json.loads(error.read(65536)).get('error', {}).get('details', [])
            if any(d.get('reason') == 'API_KEY_INVALID' for d in details if isinstance(d, dict)):
                code = 'invalid_key'
        except (ValueError, AttributeError):
            pass
        error.close()
        raise ProviderError(code) from None
    except (OSError, ValueError):
        raise ProviderError('connection_failed') from None


def google_request(path, payload=None):
    return provider_request('gemini', path, payload)


def list_models(provider=None):
    provider = provider or settings()['provider']
    if provider == 'local':
        return [{'id': LOCAL_MODEL, 'name': 'Qwen 2.5 3B', 'chat_supported': True}]
    if provider in ('openai', 'anthropic'):
        models, cursor = [], ''
        for _ in range(10):
            path = 'models'
            if provider == 'anthropic':
                path += '?limit=100' + ('&after_id=' + urllib.parse.quote(cursor, safe='') if cursor else '')
            data = provider_request(provider, path)
            for item in data.get('data', []):
                name = item.get('id', '')
                if not re.fullmatch(r'[a-zA-Z0-9._:-]+', name):
                    continue
                text_model = name.startswith(('gpt-', 'chatgpt-', 'o1', 'o3', 'o4')) if provider == 'openai' else name.startswith('claude-')
                excluded = ('audio', 'realtime', 'transcribe', 'tts', 'image', 'search', 'instruct', 'computer-use')
                models.append({'id': name, 'name': item.get('display_name', name), 'chat_supported': text_model and not any(term in name for term in excluded)})
            if provider == 'openai' or not data.get('has_more') or not data.get('last_id'):
                break
            cursor = data['last_id']
        return sorted(models, key=lambda m: (not m['chat_supported'], m['id']))
    if provider != 'gemini':
        raise ValueError('Invalid provider')
    models, token = [], ''
    for _ in range(10):
        data = google_request('models?pageSize=100' + ('&pageToken=' + urllib.parse.quote(token, safe='') if token else ''))
        for m in data.get('models', []):
            name = m.get('name', '').removeprefix('models/')
            if 'generateContent' in m.get('supportedGenerationMethods', []) and name.startswith('gemini-') and re.fullmatch(r'[a-zA-Z0-9._-]+', name):
                models.append({'id': name, 'name': m.get('displayName', name), 'chat_supported': not any(part in name for part in ('image', 'tts', 'transcribe', 'robotics', 'computer-use', 'nano-banana'))})
        token = data.get('nextPageToken', '')
        if not token:
            break
    return sorted(models, key=lambda m: m['id'])


def gemini_generate(system, user, schema=None):
    c = settings('gemini')
    model = c['model'].removeprefix('models/')
    if not re.fullmatch(r'gemini-[a-zA-Z0-9._-]+', model):
        raise ProviderError('select_model')
    generation = {'responseMimeType': 'application/json', 'maxOutputTokens': 2048}
    if schema:
        generation['responseJsonSchema'] = schema
    data = google_request('models/' + model + ':generateContent', {
        'systemInstruction': {'parts': [{'text': system}]},
        'contents': [{'role': 'user', 'parts': [{'text': user}]}], 'generationConfig': generation})
    try:
        text = ''.join(p.get('text', '') for p in data['candidates'][0]['content']['parts'] if not p.get('thought'))
        return json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProviderError('invalid_response') from None


def cloud_generate(system, user, schema=None):
    c = settings()
    provider, model = c['provider'], c['model']
    if provider == 'gemini':
        return gemini_generate(system, user, schema)
    if not model or not re.fullmatch(r'[a-zA-Z0-9._:-]+', model):
        raise ProviderError('select_model')
    answer_schema = schema or {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer'], 'additionalProperties': False}
    if provider == 'openai':
        data = provider_request('openai', 'responses', {
            'model': model, 'instructions': system, 'input': user, 'store': False,
            'max_output_tokens': 2048,
            'text': {'format': {'type': 'json_schema', 'name': 'enu_answer', 'schema': answer_schema, 'strict': True}}})
        try:
            text = ''.join(part.get('text', '') for item in data['output'] if item.get('type') == 'message' for part in item.get('content', []) if part.get('type') == 'output_text')
            return json.loads(text)
        except (KeyError, TypeError, ValueError):
            raise ProviderError('invalid_response') from None
    if provider == 'anthropic':
        data = provider_request('anthropic', 'messages', {
            'model': model, 'max_tokens': 2048, 'system': system,
            'messages': [{'role': 'user', 'content': user}],
            'output_config': {'format': {'type': 'json_schema', 'schema': answer_schema}}})
        try:
            return json.loads(''.join(part.get('text', '') for part in data['content'] if part.get('type') == 'text'))
        except (KeyError, TypeError, ValueError):
            raise ProviderError('invalid_response') from None
    raise ProviderError('select_model')
