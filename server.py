#!/usr/bin/env python3
"""Loopback-only MVP server. Local Ollama chat; original files are served by allowlisted IDs."""
import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from app.documents import ROOT, DATA, load_documents
from app.search import SearchEngine
from app.providers import settings, public_settings, save_settings, list_models, ProviderError
from app.chat import social, retrieval_query, generate, model_available, MODEL, converse

LOCK = threading.RLock()
DOCUMENTS = []
FILES = {}
ENGINE = None
WEB = ROOT / 'web'


def rebuild():
    global DOCUMENTS, FILES, ENGINE
    documents, files = load_documents()
    engine = SearchEngine([d for d in documents if d['status'] == 'ready'])
    with LOCK:
        DOCUMENTS, FILES, ENGINE = documents, files, engine
    return len(documents)


def public_docs():
    return [{k: v for k, v in d.items() if k != 'pages'} for d in DOCUMENTS]


def answer(query, language, role='student', topic='all', document_ids=None, history=None, conversation_mode="documents"):
    start = time.perf_counter()
    history = history or []
    kk = language == 'kk'
    if conversation_mode == 'general':
        result = {'status': 'chat', 'sources': [], 'steps': [], 'mode': 'general-chat', 'message': ''}
        try:
            result['message'] = converse(query, history, language)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.update(status='model_unavailable', mode='conversation', provider_error=getattr(exc, 'code', 'connection_failed'))
        result['elapsed_ms'] = round((time.perf_counter() - start) * 1000)
        return result
    kind = social(query)
    if kind:
        return {'status': kind, 'message': '', 'sources': [], 'mode': 'conversation', 'steps': [], 'elapsed_ms': 0}
    effective = retrieval_query(query, history)
    with LOCK:
        hits = ENGINE.search(effective, role=role, topic=topic, document_ids=document_ids)
    matching_language = [s for s in hits if (len(re.findall('[әғқңөұүһі]', s['text'].lower())) >= 8) == kk]
    if matching_language:
        hits = matching_language
    result = {
        'status': 'found' if hits else 'not_found',
        'message': ('Құжаттардан сұрағыңызға қатысты үзінділер табылды. Қадамдарды түпнұсқамен тексеріңіз.' if kk else 'В документах найдены фрагменты по вашему вопросу. Проверьте действия по оригиналу.') if hits else ('Жүктелген құжаттарда жеткілікті ақпарат табылмады. Сұрақты нақтылаңыз немесе басқа құжатты қосыңыз.' if kk else 'В загруженных документах недостаточно информации для ответа. Уточните вопрос или добавьте подходящий документ.'),
        'sources': hits,
        'mode': 'local-extractive',
        'elapsed_ms': round((time.perf_counter() - start) * 1000),
        'notice': 'Үзінділер түпнұсқа тілінде берілген.' if kk else 'Выдержки приведены на языке оригинала.',
    }

    result['steps'] = []
    result['resolved_question'] = effective
    # Direct document requirements can be quoted more reliably than paraphrased,
    # especially for the small model's weaker Kazakh generation.
    if re.search(r'құжат|документ', query.lower()):
        for index, source in enumerate(hits):
            for sentence in re.split(r'(?<=[.!?])\s+|(?<=\d)\.\s+', source['text']):
                if 'транскрипт' in sentence.lower() and re.search(r'скан|жүкт|загруз', sentence.lower()) and len(sentence) < 550:
                    result.update(message=f'«{sentence.strip()}» [{index + 1}]', mode='local-extractive-summary')
                    result['elapsed_ms'] = round((time.perf_counter() - start) * 1000)
                    return result
    if hits and settings()['provider']!='local' and not settings()['allow_documents']:
        result['cloud_documents_blocked'] = True
        return result
    if hits and model_available():
        try:
            generated = generate(query, history, hits, language)
            if generated:
                result.update(message=generated['answer'], steps=generated['steps'], mode='local-rag')
            else:
                result.update(status='not_found', sources=[], message=('Жеткілікті дәлел жоқ.' if kk else 'Недостаточно подтверждений для ответа.'))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result['provider_error'] = getattr(exc, 'code', 'invalid_response')
            result['model_error'] = True
    elif hits:
        result['model_error'] = True
    result['elapsed_ms'] = round((time.perf_counter() - start) * 1000)
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = 'ENU-Komek/0.1'

    def log_message(self, fmt, *args):
        # Questions and document names are not written to access logs.
        pass

    def send_bytes(self, data, content_type, status=200, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def json(self, obj, status=200):
        self.send_bytes(json.dumps(obj, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)

    def valid_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def do_GET(self):
        if not self.valid_host():
            return self.json({'error': 'Invalid host'}, 403)
        path = urlsplit(self.path).path
        if path == '/api/health':
            return self.json({'status': 'ok', 'documents': len(DOCUMENTS), 'chunks': len(ENGINE.chunks), 'model': 'TF-IDF + LSA (TruncatedSVD)', 'local': True, 'chat_model': MODEL, 'chat_available': model_available(), 'settings': public_settings()})
        if path == '/api/settings':
            return self.json(public_settings())
        if path == '/api/documents':
            return self.json({'documents': public_docs()})
        if path == '/api/export':
            return self.send_bytes(json.dumps({'documents': public_docs()}, ensure_ascii=False, indent=2).encode(), 'application/json', extra={'Content-Disposition': 'attachment; filename="enu-sources.json"'})
        if path.startswith('/api/documents/') and '/preview/' in path:
            parts = path.split('/')
            if len(parts) != 6 or not parts[5].isdigit():
                return self.json({'error': 'Invalid page'}, 400)
            file = FILES.get(parts[3])
            doc = next((d for d in DOCUMENTS if d['id'] == parts[3]), None)
            page_number = int(parts[5])
            if not file or file.suffix.lower() != '.pdf' or not doc or not 1 <= page_number <= doc['page_count']:
                return self.json({'error': 'Page not found'}, 404)
            if not shutil.which('pdftoppm'):
                return self.json({'error': 'PDF preview requires Poppler'}, 503)
            folder = DATA / 'previews'
            folder.mkdir(exist_ok=True)
            prefix = folder / f'{parts[3]}-{page_number}'
            image = prefix.with_suffix('.png')
            try:
                with LOCK:
                    if not image.exists():
                        subprocess.run(['pdftoppm', '-f', str(page_number), '-l', str(page_number), '-singlefile', '-scale-to', '1400', '-png', str(file), str(prefix)], check=True, capture_output=True, timeout=40)
                return self.send_bytes(image.read_bytes(), 'image/png')
            except (OSError, subprocess.SubprocessError):
                return self.json({'error': 'Preview unavailable'}, 503)
        if path.startswith('/api/documents/') and path.endswith('/file'):
            doc_id = path.split('/')[3]
            file = FILES.get(doc_id)
            if not file:
                return self.json({'error': 'Document not found'}, 404)
            return self.send_bytes(file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream', extra={'Content-Disposition': f"inline; filename*=UTF-8''{quote(file.name)}"})
        allowed = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/workspace.css': 'workspace.css', '/favicon.svg': 'favicon.svg'}
        if path not in allowed:
            return self.json({'error': 'Not found'}, 404)
        file = WEB / allowed[path]
        self.send_bytes(file.read_bytes(), (mimetypes.guess_type(file.name)[0] or 'text/plain') + '; charset=utf-8')

    def do_POST(self):
        if not self.valid_host():
            return self.json({'error': 'Invalid host'}, 403)
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}:
            return self.json({'error': 'Cross-origin request rejected'}, 403)
        path = urlsplit(self.path).path
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.json({'error': 'Invalid content length'}, 400)
        if size < 1 or size > (20_000_000 if path == '/api/upload' else 12000):
            return self.json({'error': 'Размер запроса превышает допустимый / Сұрау тым үлкен'}, 413)
        raw = self.rfile.read(size)
        try:
            if path == '/api/upload':
                name = unquote(self.headers.get('X-Filename', ''))
                if not name or Path(name).name != name or '\\' in name or any(ord(c) < 32 for c in name) or len(name) > 220:
                    return self.json({'error': 'Недопустимое имя файла'}, 400)
                suffix = Path(name).suffix.lower()
                if suffix not in {'.pdf', '.docx'} or (suffix == '.pdf' and not raw.startswith(b'%PDF-')) or (suffix == '.docx' and not raw.startswith(b'PK')):
                    return self.json({'error': 'Допустимы только PDF и DOCX'}, 400)
                target = DATA / 'documents' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    return self.json({'error': 'Файл с таким именем уже существует'}, 409)
                with target.open('xb') as stream:
                    stream.write(raw)
                count = rebuild()
                return self.json({'status': 'ok', 'documents': count})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.json({'error': 'Expected application/json'}, 415)
            body = json.loads(raw)
            if not isinstance(body, dict):
                return self.json({'error': 'Expected JSON object'}, 400)
            if path == '/api/settings':
                return self.json(save_settings(body))
            if path == '/api/models':
                try:
                    return self.json({'models': list_models(body.get('provider'))})
                except ProviderError as exc:
                    return self.json({'error': exc.code, 'code': exc.code}, 502)
            if path == '/api/ask':
                query = body.get('question', '')
                if not isinstance(query, str) or not 3 <= len(query.strip()) <= 1500:
                    return self.json({'error': 'Вопрос: от 3 до 1500 символов / 3–1500 таңба'}, 400)
                role = body.get('role', 'student')
                language = body.get('language', 'kk')
                topic = body.get('topic', 'all')
                ids = body.get('document_ids')
                if role not in {'student','all'} or language not in {'kk','ru'} or not isinstance(topic, str) or (ids is not None and (not isinstance(ids, list) or any(not isinstance(i, str) for i in ids))):
                    return self.json({'error': 'Invalid parameters'}, 400)
                conversation_mode = body.get('conversation_mode', 'documents')
                if conversation_mode not in {'documents', 'general'}:
                    return self.json({'error': 'Invalid conversation mode'}, 400)
                history = body.get('history', [])
                if not isinstance(history, list) or len(history) > 6 or any(not isinstance(q, str) or len(q) > 1000 for q in history):
                    return self.json({'error': 'Invalid conversation history'}, 400)
                return self.json(answer(query.strip(), language, role, topic, set(ids) if ids is not None else None, history, conversation_mode))
            if path == '/api/reindex':
                return self.json({'documents': rebuild(), 'status': 'ok'})
            return self.json({'error': 'Not found'}, 404)
        except (ValueError, UnicodeError, OSError) as exc:
            return self.json({'error': f'Не удалось обработать запрос: {type(exc).__name__}'}, 400)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8777')))
    args = parser.parse_args()
    # Start only the installed local runtime; never download a model implicitly.
    if shutil.which('ollama'):
        try:
            from urllib.request import urlopen
            with urlopen('http://127.0.0.1:11434/api/tags', timeout=1):
                pass
        except OSError:
            subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Индексация документов…', flush=True)
    rebuild()
    print(f'ENU Көмек: http://127.0.0.1:{args.port} — {len(DOCUMENTS)} документов, {len(ENGINE.chunks)} фрагментов', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
