"""Small local-corpus smoke benchmark; never uploads source text."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.documents import load_documents
from app.search import SearchEngine

cases = [
    ('Какие документы нужны для возвращения с академической мобильности?', 'возвращение', True),
    ('Академиялық ұтқырлықтан оралу үшін қандай құжат керек?', 'возвращение', True),
    ('Что такое академическая честность?', 'честности', True),
    ('Как студенту пройти тестирование в Platonus?', 'обучающегося', True),
    ('Как приготовить борщ?', '', False),
    ('Какая стоимость общежития в 2026 году?', '', False),
]
documents, _ = load_documents()
if not documents:
    sys.exit('Добавьте документы в enu-data/documents перед запуском проверки.')
engine = SearchEngine(documents)
results = []
for question, expected, should_find in cases:
    started = time.perf_counter()
    hits = engine.search(question)
    passed = bool(hits) == should_find and (not hits or expected in hits[0]['title'].lower())
    results.append({'question': question, 'pass': passed, 'first_title': hits[0]['title'] if hits else None, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)})
report = {'kind': 'six-case smoke benchmark, not a representative accuracy measure', 'documents': len(documents), 'ready': sum(d['status']=='ready' for d in documents), 'cases': results}
output = Path(__file__).resolve().parents[1] / 'qa'
output.mkdir(exist_ok=True)
(output / 'retrieval-evaluation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if all(r['pass'] for r in results) else 1)
