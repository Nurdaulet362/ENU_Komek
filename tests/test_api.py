import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server
from app.search import SearchEngine


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.ENGINE = SearchEngine([])
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.base = f'http://127.0.0.1:{cls.http.server_port}'
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers={'Content-Type':'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_unknown_document_is_not_a_filesystem_path(self):
        self.assertEqual(self.request('/api/documents/../../etc/passwd/file')[0], 404)

    def test_invalid_question_is_rejected(self):
        self.assertEqual(self.request('/api/ask', {'question':''})[0], 400)

    def test_foreign_origin_is_rejected(self):
        self.assertEqual(self.request('/api/ask', {'question':'test'}, {'Origin':'https://attacker.example'})[0], 403)

    def test_foreign_host_is_rejected(self):
        self.assertEqual(self.request('/api/health', headers={'Host':'attacker.example'})[0], 403)

    def test_absent_evidence_is_explicit(self):
        status, _, body = self.request('/api/ask', {'question':'Как приготовить борщ?', 'language':'ru'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'not_found')

    def test_ui_has_no_external_network_dependencies(self):
        status, headers, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        self.assertIn(b'app.js', body)

    def test_upload_path_traversal_is_rejected(self):
        req = urllib.request.Request(self.base+'/api/upload', data=b'%PDF-test', headers={'X-Filename':'..%2Foutside.pdf'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 400)
