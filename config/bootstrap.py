import os
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

from .environment import DEFAULT_SETTINGS_MODULE


def configure():
    # Hosting environment variables always take precedence over the local file.
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=False)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', DEFAULT_SETTINGS_MODULE)
    if os.environ.get('VERCEL') and os.environ['DJANGO_SETTINGS_MODULE'] != 'config.production':
        raise ImproperlyConfigured('Vercel deployments must use config.production.')
