"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

from .bootstrap import configure

from django.core.wsgi import get_wsgi_application

configure()

application = get_wsgi_application()
