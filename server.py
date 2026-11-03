#!/usr/bin/env python3
"""Loopback-only MVP server. Local Ollama chat; original files are served by allowlisted IDs."""
import argparse
import json
from contextlib import nullcontext
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
from app.hosting import CURRENT, visitor, BusyError
from app.providers import settings, public_settings, save_settings, list_models, ProviderError
from app.chat import social, retrieval_query, generate, model_available, MODEL, converse

LOCK = threading.RLock()
DOCUMENTS = []
FILES = {}
ENGINE = None
WEB = ROOT / 'web'

def hosted():
    return os.environ.get('ENU_HOSTED') == '1'

def active_documents():
    return CURRENT.get()['documents'] if CURRENT.get() is not None else DOCUMENTS

def active_files():
    return CURRENT.get()['files'] if CURRENT.get() is not None else FILES

def active_engine():
    return CURRENT.get()['engine'] if CURRENT.get() is not None else ENGINE

def active_data():
    return CURRENT.get()['data'] if CURRENT.get() is not None else DATA



def rebuild():
    global DOCUMENTS, FILES, ENGINE
    space = CURRENT.get()
    documents, files = load_documents(space['data'], include_root=False) if space is not None else load_documents()
    if space is not None and sum(d['characters'] for d in documents) > 300000:
        raise ValueError('Hosted workspace text limit exceeded')
    engine = SearchEngine([d for d in documents if d['status'] == 'ready'])
    with LOCK:
        if space is not None:
            space.update(documents=documents, files=files, engine=engine)
        else:
            DOCUMENTS, FILES, ENGINE = documents, files, engine
    return len(documents)


def public_docs():
    return [{k: v for k, v in d.items() if k != 'pages'} for d in active_documents()]


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
        hits = active_engine().search(effective, role=role, topic=topic, document_ids=document_ids)
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
        if self.new_cookie:
            self.send_header('Set-Cookie', 'enu_session=' + self.new_cookie + '; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=1800')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def json(self, obj, status=200):
        self.send_bytes(json.dumps(obj, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)

    def valid_host(self):
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        public = os.environ.get('RENDER_EXTERNAL_HOSTNAME') or os.environ.get('ENU_PUBLIC_HOST')
        if hosted() and public and re.fullmatch(r'[a-zA-Z0-9.-]+', public):
            hosts.update({public, public + ':443'})
        return self.headers.get('Host') in hosts

    def setup(self):
        super().setup()
        self.connection.settimeout(30)
        self.new_cookie = None

    def route(self, action):
        if not hosted():
            return action()
        if not self.valid_host():
            return self.json({'error': 'Invalid host'}, 403)
        if urlsplit(self.path).path == '/healthz' and self.command == 'GET':
            return self.json({'status': 'ok'})
        try:
            with visitor(self.headers.get('Cookie')) as (space, token):
                self.new_cookie = token
                return action()
        except BusyError:
            return self.json({'error': 'Demo busy; please try again later'}, 503)

    def do_GET(self):
        return self.route(self.get)

    def do_POST(self):
        return self.route(self.post)

    def get(self):
        if not self.valid_host():
            return self.json({'error': 'Invalid host'}, 403)
        path = urlsplit(self.path).path
        if path == '/healthz':
            return self.json({'status': 'ok'})
        if path == '/api/health':
            return self.json({'status': 'ok', 'documents': len(active_documents()), 'chunks': len(active_engine().chunks), 'model': 'TF-IDF + LSA (TruncatedSVD)', 'local': not hosted(), 'hosted': hosted(), 'chat_model': MODEL, 'chat_available': model_available(), 'settings': public_settings()})
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
            file = active_files().get(parts[3])
            doc = next((d for d in active_documents() if d['id'] == parts[3]), None)
            page_number = int(parts[5])
            if not file or file.suffix.lower() != '.pdf' or not doc or not 1 <= page_number <= doc['page_count']:
                return self.json({'error': 'Page not found'}, 404)
            if not shutil.which('pdftoppm'):
                return self.json({'error': 'PDF preview requires Poppler'}, 503)
            folder = active_data() / 'previews'
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
            file = active_files().get(doc_id)
            if not file:
                return self.json({'error': 'Document not found'}, 404)
            return self.send_bytes(file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream', extra={'Content-Disposition': f"inline; filename*=UTF-8''{quote(file.name)}"})
        allowed = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/workspace.css': 'workspace.css', '/favicon.svg': 'favicon.svg'}
        if path not in allowed:
            return self.json({'error': 'Not found'}, 404)
        file = WEB / allowed[path]
        self.send_bytes(file.read_bytes(), (mimetypes.guess_type(file.name)[0] or 'text/plain') + '; charset=utf-8')

    def post(self):
        if not self.valid_host():
            return self.json({'error': 'Invalid host'}, 403)
        origin = self.headers.get('Origin')
        origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        public = os.environ.get('RENDER_EXTERNAL_HOSTNAME') or os.environ.get('ENU_PUBLIC_HOST')
        if hosted() and public:
            origins.add('https://' + public)
        if (origin and origin not in origins) or (hosted() and not origin):
            return self.json({'error': 'Cross-origin request rejected'}, 403)
        path = urlsplit(self.path).path
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.json({'error': 'Invalid content length'}, 400)
        if size < 1 or size > ((5_000_000 if hosted() else 20_000_000) if path == '/api/upload' else 12000):
            return self.json({'error': 'Размер запроса превышает допустимый / Сұрау тым үлкен'}, 413)
        if hosted():
            space = CURRENT.get()
            now = time.monotonic()
            space['requests'] = [t for t in space['requests'] if now - t < 600]
            if len(space['requests']) >= 40:
                return self.json({'error': 'Demo request limit reached. Try again later.'}, 429)
            space['requests'].append(now)
            if path == '/api/upload' and len(space['files']) >= 3:
                return self.json({'error': 'Hosted demo allows up to 3 documents per session'}, 413)
        raw = self.rfile.read(size)
        try:
            if path == '/api/upload':
                name = unquote(self.headers.get('X-Filename', ''))
                if not name or Path(name).name != name or '\\' in name or any(ord(c) < 32 for c in name) or len(name) > 220:
                    return self.json({'error': 'Недопустимое имя файла'}, 400)
                suffix = Path(name).suffix.lower()
                if suffix not in {'.pdf', '.docx'} or (suffix == '.pdf' and not raw.startswith(b'%PDF-')) or (suffix == '.docx' and not raw.startswith(b'PK')):
                    return self.json({'error': 'Допустимы только PDF и DOCX'}, 400)
                target = active_data() / 'documents' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    return self.json({'error': 'Файл с таким именем уже существует'}, 409)
                with target.open('xb') as stream:
                    stream.write(raw)
                try:
                    count = rebuild()
                except ValueError:
                    target.unlink(missing_ok=True)
                    return self.json({'error': 'Document exceeds hosted demo limits'}, 413)
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


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True
    slots = threading.BoundedSemaphore(12)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0' if hosted() else '127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8777')))
    args = parser.parse_args()
    # Start only the installed local runtime; never download a model implicitly.
    if not hosted() and shutil.which('ollama'):
        try:
            from urllib.request import urlopen
            with urlopen('http://127.0.0.1:11434/api/tags', timeout=1):
                pass
        except OSError:
            subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Индексация документов…', flush=True)
    if hosted():
        ENGINE = SearchEngine([])
    else:
        rebuild()
    print(f'ENU Көмек: http://127.0.0.1:{args.port} — {len(active_documents())} документов, {len(active_engine().chunks)} фрагментов', flush=True)
    DemoServer((args.host, args.port), Handler).serve_forever()
