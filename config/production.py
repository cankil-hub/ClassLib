"""Production settings fail closed if persistence or credentials are missing."""
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ImproperlyConfigured(f'Missing required production setting: {name}')
    return value


DEBUG = False
SECRET_KEY = required('DJANGO_SECRET_KEY')
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY must be a new random secret of at least 50 characters.')
ALLOWED_HOSTS = [host.strip() for host in required('DJANGO_ALLOWED_HOSTS').split(',') if host.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in required('DJANGO_CSRF_TRUSTED_ORIGINS').split(',') if origin.strip()
]
if '*' in ALLOWED_HOSTS or any(not origin.startswith('https://') for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured('Use explicit production hosts and HTTPS CSRF origins.')

DATABASES = {'default': dj_database_url.parse(required('DATABASE_URL'), conn_max_age=0, ssl_require=True)}
if DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise ImproperlyConfigured('Production requires PostgreSQL.')
# Supabase transaction pooling cannot retain session state or server-side cursors.
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
DATABASES['default']['OPTIONS'].update({'prepare_threshold': None, 'connect_timeout': 10})

STORAGE_BACKEND = 'storage_backends.s3.S3Storage'
S3_ENDPOINT_URL = required('S3_ENDPOINT_URL')
if not S3_ENDPOINT_URL.startswith('https://'):
    raise ImproperlyConfigured('S3_ENDPOINT_URL must use HTTPS.')
S3_REGION = required('S3_REGION')
S3_ACCESS_KEY_ID = required('S3_ACCESS_KEY_ID')
S3_SECRET_ACCESS_KEY = required('S3_SECRET_ACCESS_KEY')
S3_BUCKET_NAME = required('S3_BUCKET_NAME')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = 'same-origin'
# A Vercel function must not attempt Django's disk-backed multipart uploads.
FILE_UPLOAD_HANDLERS = ['library.upload_handlers.RejectProxyUploadHandler']
