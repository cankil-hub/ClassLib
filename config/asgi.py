"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

from .bootstrap import configure

from django.core.asgi import get_asgi_application

configure()

application = get_asgi_application()
