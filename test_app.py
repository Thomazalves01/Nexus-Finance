import hashlib
import hmac
import json
import re
import tempfile
import unittest
from pathlib import Path

import app as nexus

class NexusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        nexus.DB_PATH = Path(self.temp.name) / 'test.db'
        nexus.APP_PASSWORD = 'test-password-12345'
        nexus.META_APP_SECRET = 'test-meta-secret'
        nexus.VERIFY_TOKEN = 'test-verify-token'
        nexus.ALLOWED_PHONE = '5551234567'
        nexus.ACCESS_TOKEN = ''
        nexus.PHONE_NUMBER_ID = ''
        nexus.app.config.update(TESTING=True, SECRET_KEY='test-secret-key-for-tests')
        self.client = nexus.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def login(self):
        page = self.client.get('/login')
        token = re.search(rb"name=['\"]csrf_token['\"] value=['\"]([^'\"]+)['\"]", page.data).group(1).decode()
        return self.client.post('/login', data={'csrf_token': token, 'password': nexus.APP_PASSWORD}, follow_redirects=True)

    def signed_webhook(self, payload, signature=True):
        raw = json.dumps(payload, separators=(',', ':')).encode()
        headers = {'Content-Type': 'application/json'}
        if signature:
            digest = hmac.new(nexus.META_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
            headers['X-Hub-Signature-256'] = 'sha256=' + digest
        return self.client.post('/webhook', data=raw, headers=headers)

    def test_new_database_is_empty(self):
        self.assertEqual(nexus.get_data(), {'tx': [], 'invest': [], 'subs': []})

    def test_login_required_for_data_api(self):
        self.assertEqual(self.client.get('/api/data').status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/data').status_code, 200)

    def test_unsigned_webhook_is_rejected(self):
        response = self.signed_webhook({'entry': []}, signature=False)
        self.assertEqual(response.status_code, 403)

    def test_signed_allowed_message_is_recorded_once(self):
        self.login()
        payload = {'entry': [{'changes': [{'value': {'messages': [{'id': 'wamid.test1', 'from': '5551234567', 'type': 'text', 'text': {'body': 'Gastei R$ 25,90 no almoço'}}]}}]}]}
        self.assertEqual(self.signed_webhook(payload).status_code, 200)
        self.assertEqual(self.signed_webhook(payload).status_code, 200)
        data = nexus.get_data()
        self.assertEqual(len(data['tx']), 1)
        self.assertEqual(data['tx'][0]['type'], 'expense')
        self.assertEqual(data['tx'][0]['amount'], 25.9)

    def test_disallowed_number_is_not_recorded(self):
        payload = {'entry': [{'changes': [{'value': {'messages': [{'id': 'wamid.test2', 'from': '5559999999', 'type': 'text', 'text': {'body': 'Recebi R$ 320 de salário'}}]}}]}]}
        self.signed_webhook(payload)
        self.assertEqual(nexus.get_data()['tx'], [])

if __name__ == '__main__':
    unittest.main()
