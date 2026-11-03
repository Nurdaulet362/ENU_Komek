import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import server
from app import hosting, providers

class HostedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patcher in [patch.dict('os.environ', {'ENU_HOSTED':'1','RENDER_EXTERNAL_HOSTNAME':'enu-test.onrender.com','GEMINI_API_KEY':'must-not-inherit-owner-secret'}), patch.object(hosting,'ROOT',Path(self.temp.name)), patch.object(hosting,'POOL',{})]:
            patcher.start();self.addCleanup(patcher.stop)
        self.http = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()

    def request(self,path,body=None,cookie=None,headers=None):
        raw = json.dumps(body).encode() if isinstance(body,dict) else body
        h={'Content-Type':'application/json','Origin':'https://enu-test.onrender.com',**(headers or {})}
        if cookie:h['Cookie']=cookie
        req=urllib.request.Request(self.base+path,data=raw,headers=h)
        try:
            with urllib.request.urlopen(req) as r:return r.status,r.headers,r.read()
        except urllib.error.HTTPError as e:
            result=(e.code,e.headers,e.read());e.close();return result

    def session(self):
        status,headers,raw=self.request('/api/settings')
        self.assertEqual(status,200)
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('Secure',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0],json.loads(raw)

    def test_keys_and_permission_are_private_to_visitor(self):
        a,info=self.session();b,other=self.session()
        self.assertTrue(info['hosted']);self.assertFalse(info['key_saved'])
        self.request('/api/settings',{'key_provider':'gemini','api_key':'visitor-a-secret','allow_documents':True},a)
        data=json.loads(self.request('/api/settings',cookie=b)[2])
        self.assertFalse(data['key_saved']);self.assertFalse(data['allow_documents'])
        own=json.loads(self.request('/api/settings',cookie=a)[2]);self.assertTrue(own['key_saved'])
        self.assertNotIn('visitor-a-secret',json.dumps(own))
        self.assertNotIn('must-not-inherit-owner-secret',json.dumps(own))

    def test_uploaded_documents_and_downloads_are_isolated(self):
        a,_=self.session();b,_=self.session()
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Синтетический документ: пример для проверки изоляции файлов разных посетителей приложения.</w:t></w:r></w:p></w:body></w:document>')
        status,_,_=self.request('/api/upload',data.getvalue(),a,{'Content-Type':'application/octet-stream','X-Filename':'demo.docx'})
        self.assertEqual(status,200)
        docs=json.loads(self.request('/api/documents',cookie=a)[2])['documents'];self.assertEqual(len(docs),1)
        self.assertEqual(json.loads(self.request('/api/documents',cookie=b)[2])['documents'],[])
        self.assertEqual(self.request('/api/documents/'+docs[0]['id']+'/file',cookie=b)[0],404)

    def test_host_origin_and_ollama_restrictions(self):
        a,_=self.session()
        self.assertEqual(self.request('/api/settings',{'provider':'local'},a)[0],400)
        self.assertEqual(self.request('/api/ask',{'question':'Привет'},a,{'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/settings',cookie=a,headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/settings',cookie=a,headers={'Host':'enu-test.onrender.com'})[0],200)

    def test_health_check_does_not_allocate_visitors(self):
        self.assertEqual(self.request('/healthz')[0],200)
        self.assertEqual(len(hosting.POOL),0)

    def test_rate_limit(self):
        a,_=self.session()
        token=a.split('=',1)[1]
        import time
        hosting.POOL[token]['requests']=[time.monotonic()]*40
        self.assertEqual(self.request('/api/settings',{},a)[0],429)
