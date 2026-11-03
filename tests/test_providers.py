import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import providers

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = patch.object(providers, 'CONFIG', Path(self.folder.name) / '.env')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_secret_is_not_returned_and_file_is_private(self):
        result = providers.save_settings({'api_key': 'test-secret', 'provider': 'gemini', 'model': 'gemini-example'})
        self.assertTrue(result['key_saved'])
        self.assertNotIn('test-secret', json.dumps(result))
        self.assertEqual(os.stat(providers.CONFIG).st_mode & 0o777, 0o600)
        providers.save_settings({'model': 'gemini-other'})
        self.assertEqual(providers.settings()['key'], 'test-secret')
        providers.save_settings({'clear_key': True})
        self.assertFalse(providers.public_settings()['key_saved'])

    def test_model_path_and_header_injection_are_rejected(self):
        for value in ['gemini-x?key=leak', '../x\nHeader: y', '<script>']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                providers.save_settings({'model': value})
        with self.assertRaises(ValueError):
            providers.save_settings({'api_key': 'key\nHeader: y'})

    def test_models_are_filtered_and_pagination_is_followed(self):
        pages = [{'models': [{'name': 'models/gemini-a', 'supportedGenerationMethods': ['generateContent']}, {'name': 'models/embedding', 'supportedGenerationMethods': ['embedContent']}], 'nextPageToken': 'next'}, {'models': [{'name': 'models/gemini-b', 'supportedGenerationMethods': ['generateContent']}]}]
        with patch.object(providers, 'google_request', side_effect=pages) as request:
            self.assertEqual([m['id'] for m in providers.list_models('gemini')], ['gemini-a', 'gemini-b'])
            self.assertIn('pageToken=next', request.call_args.args[0])

    def test_google_key_only_goes_to_official_fixed_host(self):
        providers.save_settings({'provider': 'gemini', 'api_key': 'test-secret'})
        opener = unittest.mock.MagicMock()
        opener.open.return_value.__enter__.return_value = io.BytesIO(b'{"models":[]}')
        with patch.object(providers.urllib.request, 'build_opener', return_value=opener):
            providers.google_request('models')
        req = opener.open.call_args.args[0]
        self.assertTrue(req.full_url.startswith('https://generativelanguage.googleapis.com/'))
        self.assertNotIn('test-secret', req.full_url)
        self.assertEqual(req.get_header('X-goog-api-key'), 'test-secret')

    def test_documents_are_not_sent_without_opt_in(self):
        import server
        from app.search import SearchEngine
        engine = SearchEngine([{'id': 'a', 'title': 'Академическая мобильность', 'role': 'student', 'pages': [{'page': 1, 'text': 'Академическая мобильность позволяет обучаться в другом университете по согласованной программе.'}]}])
        providers.save_settings({'provider': 'gemini', 'model': 'gemini-example', 'api_key': 'test-secret'})
        with patch.object(server, 'ENGINE', engine), patch('server.generate') as generate:
            result = server.answer('Что такое академическая мобильность?', 'ru')
        generate.assert_not_called()
        self.assertTrue(result['cloud_documents_blocked'])

    def test_keys_models_and_permissions_are_isolated(self):
        providers.save_settings({'provider': 'gemini', 'model': 'gemini-demo', 'api_key': 'google-secret', 'allow_documents': True})
        # Saving another provider's key does not activate it or grant its document permission.
        providers.save_settings({'key_provider': 'openai', 'api_key': 'openai-secret'})
        self.assertEqual(providers.settings()['provider'], 'gemini')
        self.assertEqual(providers.settings('gemini')['key'], 'google-secret')
        self.assertEqual(providers.settings('openai')['key'], 'openai-secret')
        self.assertFalse(providers.settings('openai')['allow_documents'])
        providers.save_settings({'provider': 'openai', 'model': 'gpt-example'})
        providers.save_settings({'provider': 'anthropic', 'model': 'claude-example', 'api_key': 'claude-secret'})
        self.assertEqual(providers.settings('openai')['model'], 'gpt-example')
        public = json.dumps(providers.public_settings())
        for secret in ('google-secret', 'openai-secret', 'claude-secret'):
            self.assertNotIn(secret, public)
        providers.save_settings({'clear_key': True, 'key_provider': 'openai'})
        self.assertEqual(providers.settings('anthropic')['key'], 'claude-secret')
        self.assertEqual(providers.settings('openai')['key'], '')

    def test_each_request_uses_only_its_own_key_and_host(self):
        for provider, key in [('gemini', 'google-secret'), ('openai', 'openai-secret'), ('anthropic', 'claude-secret')]:
            providers.save_settings({'key_provider': provider, 'api_key': key})
        for provider, host, header, key in [('gemini', 'generativelanguage.googleapis.com', 'X-goog-api-key', 'google-secret'), ('openai', 'api.openai.com', 'Authorization', 'Bearer openai-secret'), ('anthropic', 'api.anthropic.com', 'Authorization', 'Bearer claude-secret')]:
            with self.subTest(provider=provider):
                opener = unittest.mock.MagicMock()
                opener.open.return_value.__enter__.return_value = io.BytesIO(b'{}')
                with patch.object(providers.urllib.request, 'build_opener', return_value=opener):
                    providers.provider_request(provider, 'models')
                req = opener.open.call_args.args[0]
                self.assertEqual(providers.urllib.parse.urlsplit(req.full_url).hostname, host)
                self.assertEqual(req.get_header(header), key)
                self.assertNotIn('secret', req.full_url)

    def test_native_generation_payloads_and_parsing(self):
        for provider, model, reply in [('openai', 'gpt-example', {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"answer":"Hello"}'}]}]}), ('anthropic', 'claude-example', {'content': [{'type': 'text', 'text': '{"answer":"Hello"}'}]})]:
            with self.subTest(provider=provider):
                providers.save_settings({'provider': provider, 'model': model})
                with patch.object(providers, 'provider_request', return_value=reply) as request:
                    self.assertEqual(providers.cloud_generate('system', 'question'), {'answer': 'Hello'})
                self.assertEqual(request.call_args.args[0], provider)
                payload = request.call_args.args[2]
                self.assertEqual(payload['model'], model)
                if provider == 'openai':
                    self.assertEqual(request.call_args.args[1], 'responses')
                    self.assertFalse(payload['store'])
                    self.assertEqual(payload['text']['format']['type'], 'json_schema')
                else:
                    self.assertEqual(request.call_args.args[1], 'messages')
                    self.assertEqual(payload['output_config']['format']['type'], 'json_schema')

    def test_anthropic_models_paginate(self):
        with patch.object(providers, 'provider_request', side_effect=[{'data': [{'id': 'claude-a', 'display_name': 'Claude A'}], 'has_more': True, 'last_id': 'claude-a'}, {'data': [{'id': 'claude-b'}], 'has_more': False}]) as request:
            self.assertEqual([m['id'] for m in providers.list_models('anthropic')], ['claude-a', 'claude-b'])
            self.assertIn('after_id=claude-a', request.call_args.args[1])

    def test_openai_non_text_models_are_disabled(self):
        with patch.object(providers, 'provider_request', return_value={'data': [{'id': 'gpt-example'}, {'id': 'text-embedding-demo'}, {'id': 'gpt-realtime-demo'}]}):
            models = {m['id']: m['chat_supported'] for m in providers.list_models('openai')}
        self.assertTrue(models['gpt-example'])
        self.assertFalse(models['text-embedding-demo'])
        self.assertFalse(models['gpt-realtime-demo'])

    def test_missing_provider_key_never_borrows_gemini_key(self):
        providers.save_settings({'provider': 'gemini', 'api_key': 'google-secret'})
        with patch.object(providers.urllib.request, 'build_opener') as opener:
            for provider in ('openai', 'anthropic'):
                with self.subTest(provider=provider), self.assertRaises(providers.ProviderError) as caught:
                    providers.provider_request(provider, 'models')
                self.assertEqual(caught.exception.code, 'key_required')
            opener.assert_not_called()
