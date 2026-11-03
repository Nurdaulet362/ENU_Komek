"""Read local PDF/DOCX sources without executing document contents."""
import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from pypdf import PdfReader

from .search import clean

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'enu-data'
CACHE = DATA / 'extracted'
SUPPORTED = {'.pdf', '.docx'}


def title_for(path: Path) -> str:
    title = unicodedata.normalize('NFC', path.stem).replace('_', ' ')
    title = re.sub(r'\s*\(\d+\)$', '', title)
    return clean(title)


def role_for(title: str) -> str:
    if 'политика' in title.lower():
        return 'student'
    return 'staff' if any(term in title.lower() for term in ('сотрудник', 'преподаватель', 'админ', 'нормоконтроль', 'bi-аналитика', 'инфраструктура', 'регистрация дипломов')) else 'student'


def extract(path: Path) -> list[dict]:
    if path.suffix.lower() == '.pdf':
        if shutil.which('pdftotext'):
            result = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, check=True, timeout=90)
            texts = result.stdout.decode('utf-8', errors='replace').split('\f')
            if texts and not texts[-1].strip():
                texts.pop()
        else:
            texts = [p.extract_text() or '' for p in PdfReader(path).pages]
        return [{'page': i + 1, 'text': text.strip(), 'location': 'page'} for i, text in enumerate(texts)]
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo('word/document.xml')
        if info.file_size > 20_000_000:
            raise ValueError('Слишком большой XML документа')
        root = ET.fromstring(archive.read(info))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paragraphs = [''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns)]
    paragraphs = [clean(p) for p in paragraphs if clean(p)]
    # DOCX pagination depends on the renderer. Cite extract sections, never invented pages.
    sections = []
    current = []
    size = 0
    for paragraph in paragraphs:
        current.append(paragraph)
        size += len(paragraph)
        if size >= 1800:
            sections.append('\n'.join(current))
            current, size = [], 0
    if current:
        sections.append('\n'.join(current))
    return [{'page': i + 1, 'text': text, 'location': 'section'} for i, text in enumerate(sections)]


def load_documents(data=None, include_root=True) -> tuple[list[dict], dict[str, Path]]:
    data = data or DATA
    cache = data / 'extracted' if data != DATA else CACHE
    cache.mkdir(parents=True, exist_ok=True)
    candidates = (list(ROOT.glob('*')) if include_root else []) + list((data / 'documents').glob('*'))
    documents, files, seen = [], {}, set()
    for path in sorted(candidates):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        doc_id = digest[:16]
        title = title_for(path)
        cache_path = cache / f'{digest}.json'
        error = None
        try:
            if cache_path.exists():
                pages = json.loads(cache_path.read_text())
            else:
                pages = extract(path)
                cache_path.write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, subprocess.SubprocessError) as exc:
            pages, error = [], type(exc).__name__
        chars = sum(len(clean(p['text'])) for p in pages)
        documents.append({'id': doc_id, 'title': title, 'filename': path.name, 'format': path.suffix[1:].upper(), 'role': role_for(title), 'page_count': len(pages), 'characters': chars, 'status': 'ready' if chars > 50 else 'needs_ocr', 'error': error, 'pages': pages, 'source_url': 'https://edu.enu.kz/v7/#/employee/library/books', 'ocr': any(page.get('ocr', False) for page in pages), 'verified_current': False, 'sha256': digest})
        files[doc_id] = path
    return documents, files
