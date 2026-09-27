import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

from .environment import DEFAULT_SETTINGS_MODULE


def configure():
    # Hosting environment variables always take precedence over the local file.
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=False)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', DEFAULT_SETTINGS_MODULE)
    # Vercel wraps the discovered production settings to send collected static
    # files to its CDN output directory. This shim is only valid during that
    # build command; web entrypoints must still use the production module.
    vercel_static_build = (
        os.environ['DJANGO_SETTINGS_MODULE'] == '_vercel_collectstatic_settings'
        and len(sys.argv) > 1
        and sys.argv[1] == 'collectstatic'
    )
    if (os.environ.get('VERCEL')
            and os.environ['DJANGO_SETTINGS_MODULE'] != 'config.production'
            and not vercel_static_build):
        raise ImproperlyConfigured('Vercel deployments must use config.production.')
