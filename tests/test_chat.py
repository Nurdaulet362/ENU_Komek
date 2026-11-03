import io
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.chat import generate, retrieval_query, social
import server
from app.search import SearchEngine


class ChatTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch('app.providers.CONFIG', Path(folder.name) / '.env')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_short_followup_keeps_topic(self):
        self.assertIn('мобильности', retrieval_query('А дальше?', ['Как вернуться с мобильности?']))
        self.assertEqual(retrieval_query('Что такое академическая честность?', ['Как вернуться?']), 'Что такое академическая честность?')

    def test_new_explicit_question_does_not_inherit_previous_topic(self):
        question = 'Какие документы нужны для возвращения с академической мобильности?'
        self.assertEqual(retrieval_query(question, ['Какая стоимость общежития в 2026 году?']), question)

    def test_greetings_in_both_languages(self):
        self.assertEqual(social('Привет!'), 'greeting')
        self.assertEqual(social('Сәлем!'), 'greeting')
        self.assertIsNone(social('Привет, какие документы нужны?'))

    def model_reply(self, value):
        return io.BytesIO(json.dumps({'message': {'content': json.dumps(value)}}).encode())

    def test_rag_requires_valid_citations(self):
        source = {'title': 'Guide', 'page': 1, 'text': 'Evidence'}
        for refs in [[], [2], [True]]:
            with self.subTest(refs=refs), patch('app.chat.urllib.request.urlopen', return_value=self.model_reply({'supported': True, 'answer': 'Answer', 'answer_sources': refs, 'steps': []})):
                with self.assertRaises(ValueError):
                    generate('question', [], [source], 'ru')
        with patch('app.chat.urllib.request.urlopen', return_value=self.model_reply({'supported': True, 'answer': 'Answer', 'answer_sources': [1], 'steps': [{'text': 'Action', 'sources': [1]}]})):
            self.assertEqual(generate('question', [], [source], 'ru')['steps'], ['Action [1]'])

    def test_unavailable_general_chat_is_explicit(self):
        with patch('server.converse', side_effect=OSError):
            result = server.answer('Расскажи о себе', 'ru', conversation_mode='general')
        self.assertEqual(result['status'], 'model_unavailable')
        self.assertEqual(result['sources'], [])

    def test_generation_failure_keeps_evidence(self):
        engine = SearchEngine([{'id': 'a', 'title': 'Академическая мобильность', 'role': 'student', 'pages': [{'page': 1, 'text': 'Академическая мобильность: после возвращения загрузите скан-копию транскрипта стороннего вуза.'}]}])
        with patch.object(server, 'ENGINE', engine), patch('server.model_available', return_value=True), patch('server.generate', side_effect=ValueError):
            result = server.answer('Как вернуться с академической мобильности?', 'ru')
        self.assertTrue(result['sources'])
        self.assertTrue(result['model_error'])
        self.assertEqual(result['mode'], 'local-extractive')

    def test_direct_requirement_is_exact_quote_without_model(self):
        source_text = '14. Құжаттар бөліміне өтіңіз. 15. Транскрипттің скан-көшірмесін жүктейсіз.'
        engine = SearchEngine([{'id': 'a', 'title': 'Академиялық ұтқырлық мобильность', 'role': 'student', 'pages': [{'page': 4, 'text': source_text}]}])
        with patch.object(server, 'ENGINE', engine), patch('server.generate') as model:
            result = server.answer('Академиялық ұтқырлық үшін қандай құжат керек?', 'kk')
        self.assertEqual(result['mode'], 'local-extractive-summary')
        self.assertIn('Транскрипттің скан-көшірмесін жүктейсіз.', result['message'])
        model.assert_not_called()
