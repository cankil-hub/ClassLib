import mimetypes
from pathlib import PurePosixPath
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction

from .models import File, Folder


def using_supabase_storage():
    return settings.STORAGE_BACKEND == 'supabase'


def private_storage():
    return FileSystemStorage(location=settings.PRIVATE_FILE_ROOT)


def supabase_storage():
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError('Supabase storage environment variables are not configured.')
    from supabase import create_client
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return client.storage.from_(settings.SUPABASE_STORAGE_BUCKET)


def save_upload(uploaded_file, extension):
    key = f'{uuid4().hex}{extension}'
    uploaded_file.seek(0)

    if using_supabase_storage():
        payload = uploaded_file.read()
        supabase_storage().upload(
            key,
            payload,
            {
                'content-type': mimetypes.guess_type(uploaded_file.name)[0] or 'application/octet-stream',
                'upsert': 'false',
            },
        )
        return key

    return private_storage().save(key, uploaded_file)


def delete_object(storage_key):
    if using_supabase_storage():
        supabase_storage().remove([storage_key])
        return
    private_storage().delete(storage_key)


def open_download(storage_key):
    if using_supabase_storage():
        raise RuntimeError('Use signed_download_url() for Supabase-backed files.')
    return private_storage().open(storage_key, 'rb')


def signed_download_url(storage_key, expires_in=60):
    if using_supabase_storage():
        response = supabase_storage().create_signed_url(
            storage_key,
            expires_in,
            {'download': True},
        )
        if isinstance(response, dict):
            return response.get('signedURL') or response.get('signedUrl')
        return getattr(response, 'signed_url', None) or getattr(response, 'signedURL', None)

    return None


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
        transaction.on_commit(lambda: delete_object(key))


def delete_folder(folder):
    with transaction.atomic():
        folder_ids = descendant_folder_ids(folder)
        keys = list(File.objects.filter(folder_id__in=folder_ids).values_list('storage_key', flat=True))
        folder.delete()

        def cleanup_deleted_files():
            for key in keys:
                delete_object(key)

        transaction.on_commit(cleanup_deleted_files)
