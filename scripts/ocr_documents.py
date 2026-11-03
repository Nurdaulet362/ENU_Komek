"""Explicit local OCR. Originals are never modified; OCR pages require manual review."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.documents import load_documents, CACHE, DATA

if not shutil.which('tesseract') or not shutil.which('pdftoppm'):
    sys.exit('Install Tesseract and Poppler first.')
languages = DATA / 'ocr-languages'
if not all((languages / (lang + '.traineddata')).exists() for lang in ('kaz', 'rus')):
    sys.exit('Add kaz.traineddata and rus.traineddata to enu-data/ocr-languages.')
documents, files = load_documents()
for doc in documents:
    if doc['status'] != 'needs_ocr' or doc['format'] != 'PDF':
        continue
    pages = []
    with tempfile.TemporaryDirectory(prefix='enu-ocr-') as folder:
        for number in range(1, doc['page_count'] + 1):
            prefix = str(Path(folder) / 'page')
            subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number), '-singlefile', '-r', '180', '-png', str(files[doc['id']]), prefix], check=True, capture_output=True, timeout=90)
            result = subprocess.run(['tesseract', prefix + '.png', 'stdout', '--tessdata-dir', str(languages), '-l', 'kaz+rus', '--psm', '3'], check=True, capture_output=True, timeout=90)
            pages.append({'page': number, 'text': result.stdout.decode('utf-8').strip(), 'location': 'page', 'ocr': True})
            print(f'{doc["id"]}: {number}/{doc["page_count"]}', flush=True)
    # Write only after all pages succeed. Partial jobs never replace the extraction cache.
    target = CACHE / (doc['sha256'] + '.json')
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
    temp.replace(target)
    print('OCR complete; verify text against originals before relying on it.', flush=True)
