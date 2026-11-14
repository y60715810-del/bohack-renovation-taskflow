"""The optional motion scene must not relax the application's frame policy."""
import os
import tempfile
from unittest.mock import patch
import unittest
from server import create_app


class SceneHeadersTest(unittest.TestCase):
    def test_only_local_scene_can_be_framed(self):
        with tempfile.TemporaryDirectory() as directory:
            client = create_app(directory).test_client()
            app = client.get('/')
            scene = client.get('/static/collaboration-scene.html')
            self.assertEqual(scene.status_code, 200)
            self.assertEqual(app.headers['X-Frame-Options'], 'DENY')
            self.assertIn("frame-ancestors 'none'", app.headers['Content-Security-Policy'])
            self.assertNotIn("'unsafe-inline'", app.headers['Content-Security-Policy'])
            self.assertEqual(scene.headers['X-Frame-Options'], 'SAMEORIGIN')
            self.assertIn("frame-ancestors 'self'", scene.headers['Content-Security-Policy'])
            self.assertIn("connect-src 'none'", scene.headers['Content-Security-Policy'])
            self.assertIn("script-src 'self';", scene.headers['Content-Security-Policy'])
            self.assertIn("form-action 'none'", scene.headers['Content-Security-Policy'])


class PreviewProxyTest(unittest.TestCase):
    def test_https_origin_requires_explicit_proxy_trust(self):
        for trust, expected in [('0', 403), ('1', 200)]:
            with self.subTest(trust=trust), tempfile.TemporaryDirectory() as directory:
                with patch.dict(os.environ, {'TASKFLOW_TRUST_PROXY': trust,
                                             'TASKFLOW_PUBLIC_DEMO_HOST': ''}):
                    client = create_app(directory).test_client()
                    response = client.post('/api/register', base_url='http://preview.test',
                        headers={'Origin': 'https://preview.test', 'X-Forwarded-Proto': 'https'},
                        json={'username': 'preview_test', 'name': 'Preview test',
                              'role': 'coordinator', 'password': 'test-only-password'})
                    self.assertEqual(response.status_code, expected)
                    if trust == '1':
                        self.assertIn('Secure', response.headers['Set-Cookie'])


class DirectPublicPreviewTest(unittest.TestCase):
    def test_render_preview_uses_browser_isolated_demo_without_account_routes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'TASKFLOW_PUBLIC_PREVIEW': '1',
            'RENDER_EXTERNAL_HOSTNAME': 'preview.example',
            'TASKFLOW_PUBLIC_DEMO_HOST': '',
            'TASKFLOW_TRUST_PROXY': '1',
        }):
            client = create_app(directory, demo_access=True).test_client()
            base = 'https://preview.example'
            status = client.get('/api/demo-access', base_url=base)
            self.assertTrue(status.get_json()['available'])
            login = client.post('/api/demo-login', base_url=base, json={'role': 'coordinator'})
            self.assertEqual(login.status_code, 200)
            project = client.post('/api/projects/demo', base_url=base, json={},
                                  headers={'X-CSRF-Token': login.get_json()['csrf']})
            self.assertEqual(project.status_code, 201)
            self.assertEqual(len(project.get_json()['members']), 4)
            self.assertEqual(client.get('/api/demo-access', base_url='https://wrong.example').status_code, 403)
            self.assertEqual(client.get('/api/demo-access', base_url='http://preview.example').status_code, 403)
            self.assertEqual(client.post('/api/register', base_url=base, json={}).status_code, 403)
            self.assertEqual(client.post('/api/login', base_url=base, json={}).status_code, 403)
            outsider = create_app(directory, demo_access=True).test_client()
            self.assertFalse(outsider.get('/api/demo-access', base_url=base).get_json()['ready'])
