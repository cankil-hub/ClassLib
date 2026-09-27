"""Infrastructure boundary. No library models, forms or permissions belong here."""
from django.conf import settings
from django.utils.module_loading import import_string


def get_storage():
    return import_string(settings.STORAGE_BACKEND)()
