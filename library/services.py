import logging
import mimetypes
from pathlib import PurePosixPath
from uuid import uuid4

from django.db import transaction

from storage_backends import get_storage
from storage_backends.base import StorageError

from .models import File, Folder, ObjectDeletion

logger = logging.getLogger(__name__)


def save_upload(uploaded_file, extension):
    key = f'{uuid4().hex}{extension}'
    uploaded_file.seek(0)
    return get_storage().save(key, uploaded_file, mime_type_for(key))


def delete_object(storage_key):
    get_storage().delete(storage_key)


def open_download(storage_key):
    return get_storage().open(storage_key)


def mime_type_for(name):
    return mimetypes.guess_type(name)[0] or 'application/octet-stream'


def create_file(*, folder, uploaded_file, name, uploader):
    extension = PurePosixPath(name).suffix.lower()
    key = save_upload(uploaded_file, extension)
    try:
        return File.objects.create(
            name=name,
            folder=folder,
            storage_key=key,
            size=uploaded_file.size,
            mime_type=mime_type_for(name),
            uploader=uploader,
        )
    except Exception:
        delete_object(key)
        raise


def descendant_folder_ids(folder):
    return folder_tree_ids([folder.pk])


def folder_tree_ids(root_ids):
    result = set()
    pending = set(root_ids)
    while pending:
        fresh = pending - result
        if not fresh:
            break
        result.update(fresh)
        pending = set(Folder.objects.filter(parent_id__in=fresh).values_list('pk', flat=True))
    return result


def delete_file(file):
    key = file.storage_key
    with transaction.atomic():
        file.delete()
        schedule_object_deletion(key)


def delete_folder(folder):
    with transaction.atomic():
        folder_ids = descendant_folder_ids(folder)
        keys = list(File.objects.filter(folder_id__in=folder_ids).values_list('storage_key', flat=True))
        folder.delete()

        for key in keys:
            schedule_object_deletion(key)


def schedule_object_deletion(key):
    ObjectDeletion.objects.get_or_create(storage_key=key)
    transaction.on_commit(lambda: retry_object_deletion(key))


def retry_object_deletion(key):
    try:
        delete_object(key)
    except (StorageError, OSError):
        logger.warning('Object deletion deferred; run cleanup_objects.')
        return False
    ObjectDeletion.objects.filter(storage_key=key).delete()
    return True
