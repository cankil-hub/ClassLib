from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage

from .base import ObjectMissing


class LocalStorage:
    direct_upload = False

    def __init__(self):
        self.storage = FileSystemStorage(location=settings.PRIVATE_FILE_ROOT)

    def save(self, key, stream, content_type):
        stream.seek(0)
        return self.storage.save(key, File(stream))

    def delete(self, key):
        self.storage.delete(key)

    def open(self, key):
        try:
            return self.storage.open(key, 'rb')
        except FileNotFoundError as exc:
            raise ObjectMissing from exc

    def download_url(self, key, name):
        return None
