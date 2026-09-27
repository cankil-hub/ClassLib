import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


PRODUCTION_ENV = {
    'DJANGO_SECRET_KEY': 'test-only-production-setting-' * 3,
    'DJANGO_ALLOWED_HOSTS': 'classlib.example.test',
    'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://classlib.example.test',
    'DATABASE_URL': 'postgresql://test:test@localhost:6543/test',
    'S3_ENDPOINT_URL': 'https://example.storage.supabase.co/storage/v1/s3',
    'S3_REGION': 'ap-southeast-1', 'S3_ACCESS_KEY_ID': 'fake-key',
    'S3_SECRET_ACCESS_KEY': 'fake-secret', 'S3_BUCKET_NAME': 'private-files',
}


class EnvironmentTests(SimpleTestCase):
    def production(self, changes=None):
        with patch.dict(os.environ, PRODUCTION_ENV | (changes or {}), clear=True):
            return runpy.run_module('config.production')

    def test_production_requires_database_storage_and_secret(self):
        for name in PRODUCTION_ENV:
            with self.subTest(setting=name), self.assertRaises(ImproperlyConfigured):
                self.production({name: ''})

    def test_production_rejects_sqlite_insecure_hosts_and_http_storage(self):
        for setting in [
            {'DATABASE_URL': 'sqlite:///db.sqlite3'},
            {'DJANGO_ALLOWED_HOSTS': '*'},
            {'DJANGO_SECRET_KEY': 'django-insecure-' * 5},
            {'S3_ENDPOINT_URL': 'http://example.test'},
            {'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://example.test'},
        ]:
            with self.subTest(setting=setting), self.assertRaises(ImproperlyConfigured):
                self.production(setting)

    def test_production_pooler_and_https_settings(self):
        values = self.production()
        db = values['DATABASES']['default']
        self.assertEqual(db['CONN_MAX_AGE'], 0)
        self.assertTrue(db['DISABLE_SERVER_SIDE_CURSORS'])
        self.assertIsNone(db['OPTIONS']['prepare_threshold'])
        self.assertEqual(db['OPTIONS']['sslmode'], 'require')
        self.assertFalse(values['DEBUG'])
        self.assertTrue(values['SESSION_COOKIE_SECURE'])
        self.assertEqual(values['STORAGE_BACKEND'], 'storage_backends.s3.S3Storage')

    def test_local_does_not_use_cloud_database_or_storage(self):
        with patch.dict(os.environ, PRODUCTION_ENV):
            values = runpy.run_path(str(Path(__file__).with_name('local.py')), run_name='config.local')
        self.assertEqual(values['DATABASES']['default']['ENGINE'], 'django.db.backends.sqlite3')
        self.assertEqual(values['STORAGE_BACKEND'], 'storage_backends.local.LocalStorage')

    def test_vercel_cannot_accidentally_use_local_persistence(self):
        from .bootstrap import configure
        with patch.dict(os.environ, {'VERCEL': '1', 'DJANGO_SETTINGS_MODULE': 'config.local'}), \
                patch('config.bootstrap.load_dotenv'), self.assertRaises(ImproperlyConfigured):
            configure()

    def test_vercel_collectstatic_can_use_the_platform_cdn_shim(self):
        from .bootstrap import configure
        with patch.dict(os.environ, {
            'VERCEL': '1', 'DJANGO_SETTINGS_MODULE': '_vercel_collectstatic_settings',
        }), patch('config.bootstrap.load_dotenv'), \
                patch('sys.argv', ['manage.py', 'collectstatic', '--noinput']):
            configure()
            self.assertEqual(os.environ['DJANGO_SETTINGS_MODULE'], '_vercel_collectstatic_settings')

    def test_vercel_web_runtime_rejects_the_build_only_shim(self):
        from .bootstrap import configure
        with patch.dict(os.environ, {
            'VERCEL': '1', 'DJANGO_SETTINGS_MODULE': '_vercel_collectstatic_settings',
        }), patch('config.bootstrap.load_dotenv'), patch('sys.argv', ['wsgi.py']), \
                self.assertRaises(ImproperlyConfigured):
            configure()
