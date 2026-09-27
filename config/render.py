"""Render web service: shared production persistence, locally served static assets."""
import os
import re

from django.core.exceptions import ImproperlyConfigured

hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.onrender\.com', hostname):
    raise ImproperlyConfigured('A valid Render service hostname is required.')
os.environ.setdefault('DJANGO_ALLOWED_HOSTS', hostname)
os.environ.setdefault('DJANGO_CSRF_TRUSTED_ORIGINS', f'https://{hostname}')

from .production import *  # noqa: E402,F403

ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, hostname]))  # noqa: F405
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([
    *CSRF_TRUSTED_ORIGINS, f'https://{hostname}',  # noqa: F405
]))
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
