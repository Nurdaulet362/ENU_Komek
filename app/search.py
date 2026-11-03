"""Local hybrid retrieval: character TF-IDF, latent semantic analysis and evidence gates."""
import re
import unicodedata

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize


CONCEPTS = [
    ('мобильност', 'ұтқыр', 'mobility', 'академическая мобильность академиялық ұтқырлық'),
    ('возвращ', 'вернул', 'оралу', 'қайтып', 'возвращение оралу қайтып келу'),
    ('внешн', 'сыртқы', 'внешняя сыртқы'),
    ('внутрен', 'ішкі', 'внутренняя ішкі'),
    ('стажиров', 'тағылым', 'стажировка тағылымдама'),
    ('тест', 'емтихан', 'экзамен', 'тестирование тестілеу емтихан экзамен'),
    ('договор', 'шарт', 'договор шарт келісім'),
    ('диплом', 'выпускн', 'бітіру', 'диплом выпускная работа бітіру жұмысы'),
    ('честност', 'адалдық', 'плагиат', 'академическая честность академиялық адалдық плагиат'),
    ('общежит', 'жатақхана', 'общежитие жатақхана'),
    ('транскрипт', 'транскрипт'),
    ('заявлен', 'заявк', 'өтін', 'заявление өтініш өтінім'),
    ('стипенд', 'шәкіртақы', 'стипендия шәкіртақы'),
]
STOP = {'как','какие','какой','какая','когда','где','для','мне','нужно','нужны','что','это','или','при','его','она','чтобы','можно','хочу','надо','подать','получить','через','после','каким','чем','мен','үшін','қалай','қандай','керек','болады','туралы','бар','бойынша','және','неге','кто','сколько','почему','ли','нужен','нужна','чего'}


def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip()


def expand(text: str) -> str:
    text = clean(text).lower().replace('ё', 'е')
    return text + ' ' + ' '.join(group[-1] for group in CONCEPTS if any(term in text for term in group[:-1]))


def meaningful(text: str) -> list[str]:
    return [token for token in re.findall(r'[^\W\d_]+', text.lower()) if len(token) > 3 and token not in STOP]


class SearchEngine:
    def __init__(self, documents: list[dict]):
        self.chunks = []
        for document in documents:
            for page in document['pages']:
                text = clean(page['text'])
                if len(text) < 35:
                    continue
                # Overlapping source windows preserve locality and exact page citations.
                for start in range(0, len(text), 1000):
                    segment = text[start:start + 1400]
                    if len(segment) < 35:
                        continue
                    self.chunks.append({'document_id': document['id'], 'title': document['title'], 'role': document['role'], 'page': page['page'], 'text': segment, 'location': page.get('location', 'page')})
        self.vectorizer = None
        self.svd = None
        if not self.chunks:
            return
        self.vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=1, max_features=60000, sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform([expand(c['title']) + ' ' + expand(c['text']) for c in self.chunks])
        if min(self.matrix.shape) > 3:
            self.svd = TruncatedSVD(n_components=min(64, self.matrix.shape[0] - 1, self.matrix.shape[1] - 1), random_state=42)
            self.latent = normalize(self.svd.fit_transform(self.matrix))

    def search(self, query: str, role: str = 'student', topic: str = 'all', limit: int = 4, document_ids: set | None = None) -> list[dict]:
        if not self.vectorizer or not clean(query):
            return []
        expanded = expand(query)
        lower_query = clean(query).lower()
        intents = [group[:-1] for group in CONCEPTS[:11] if any(term in lower_query for term in group[:-1])]
        years = re.findall(r'\b20\d{2}\b', lower_query)
        wants_cost = any(term in lower_query for term in ('стоит', 'стоимост', 'цен', 'баға', 'тұрады'))
        wants_documents = any(term in lower_query for term in ('документ', 'құжат'))
        kazakh = bool(re.search('[әғқңөұүһі]', lower_query))
        raw_terms = meaningful(query)
        concept_terms = meaningful(expanded[len(clean(query)):])
        query_vector = self.vectorizer.transform([expanded])
        lexical = (self.matrix @ query_vector.T).toarray().ravel()
        scores = lexical.copy()
        if self.svd:
            latent_score = self.latent @ normalize(self.svd.transform(query_vector))[0]
            scores = 0.78 * lexical + 0.22 * np.maximum(latent_score, 0)
        for i, chunk in enumerate(self.chunks):
            content = chunk['text'].lower()
            if len(content) < 160:
                scores[i] *= 0.55
            if kazakh and len(re.findall('[әғқңөұүһі]', content)) >= 8:
                scores[i] += 0.09
            if wants_documents and any(term in content for term in ('скан-коп', 'скан-көш', 'загруз', 'жүкт', 'предостав')):
                scores[i] += 0.22
                if any(term in content for term in ('транскрипт', 'справк', 'анықтама')):
                    scores[i] += 0.15
        found = []
        seen = set()
        for index in np.argsort(-scores):
            chunk = self.chunks[int(index)]
            if role == 'student' and chunk['role'] == 'staff':
                continue
            if document_ids is not None and chunk['document_id'] not in document_ids:
                continue
            if topic != 'all' and topic not in expand(chunk['title']):
                continue
            text = expand(chunk['title'] + ' ' + chunk['text'])
            original = clean(chunk['title'] + ' ' + chunk['text']).lower()
            if any(not any(stem in original for stem in intent) for intent in intents):
                continue
            if years and any(year not in chunk['text'] for year in years):
                continue
            if wants_cost and not any(term in chunk['text'].lower() for term in ('стоимост', 'тариф', 'тенге', 'теңге', '₸', 'баға')):
                continue
            # Gate on meaningful overlap; latent similarity alone must never invent support.
            overlap = sum(term[:5] in text for term in raw_terms)
            concept_overlap = sum(term[:5] in text for term in concept_terms)
            if not raw_terms or (overlap == 0 and concept_overlap == 0) or lexical[index] < 0.065 or scores[index] < 0.10:
                continue
            key = (chunk['document_id'], chunk['page'])
            if key in seen:
                continue
            seen.add(key)
            found.append({**chunk, 'score': round(float(scores[index]), 4)})
            if len(found) >= limit:
                break
        return found
