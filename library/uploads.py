"""Upload lifecycle and validation; no provider SDK or provider URLs here."""
import logging
from datetime import timedelta
from pathlib import PurePosixPath
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from storage_backends import get_storage
from storage_backends.base import StorageError

from .forms import validate_file_content
from .models import File, UploadIntent
from .services import mime_type_for

logger = logging.getLogger(__name__)


def begin_upload(*, folder, user, name, size):
    storage = get_storage()
    if not storage.direct_upload:
        raise ValidationError('当前环境不支持直传。')
    if UploadIntent.objects.filter(
        uploader=user, completed_at__isnull=True, expires_at__gt=timezone.now(),
    ).count() >= 10:
        raise ValidationError('待完成上传过多，请稍后再试。')
    extension = PurePosixPath(name).suffix.lower()
    intent = UploadIntent(
        folder=folder, uploader=user, name=name, size=size,
        mime_type=mime_type_for(name),
        staging_key=f'pending/{uuid4().hex}{extension}',
        final_key=f'files/{uuid4().hex}{extension}',
        expires_at=timezone.now() + timedelta(seconds=settings.DIRECT_UPLOAD_TTL),
    )
    url = storage.upload_url(intent.staging_key, intent.mime_type, size)
    intent.save()
    return intent, url


def cleanup_staging(storage, key):
    try:
        storage.delete(key)
    except StorageError:
        # Keep the intent: cleanup_uploads retries after its signed URL expires.
        logger.warning('Upload staging cleanup failed; run cleanup_uploads.')


@transaction.atomic
def complete_upload(*, intent_id, user):
    intent = UploadIntent.objects.select_for_update().get(pk=intent_id, uploader=user)
    if intent.completed_at:
        if intent.file_id:
            return intent.file  # Network retries must not create duplicate files.
        raise ValidationError('这个上传已处理，文件已被删除。')
    if intent.expires_at <= timezone.now() or intent.folder_id is None:
        raise ValidationError('上传已过期或目标文件夹已删除，请重新上传。')
    if File.objects.filter(folder_id=intent.folder_id, name=intent.name).exists():
        raise ValidationError('这个文件夹已有同名文件。')

    storage = get_storage()
    try:
        # Browser credentials only cover staging_key. Copy before validating so
        # replaying a still-valid PUT cannot mutate a published, validated file.
        storage.copy(intent.staging_key, intent.final_key)
        with storage.open(intent.final_key) as stream:
            stream.seek(0, 2)
            if stream.tell() != intent.size or stream.tell() > settings.MAX_UPLOAD_SIZE:
                raise ValidationError('上传文件大小不符，请重新上传。')
            stream.seek(0)
            validate_file_content(stream, PurePosixPath(intent.name).suffix.lower())
        document = File.objects.create(
            folder_id=intent.folder_id, name=intent.name, size=intent.size,
            mime_type=intent.mime_type, uploader=user, storage_key=intent.final_key,
        )
        intent.file = document
        intent.completed_at = timezone.now()
        intent.save(update_fields=['file', 'completed_at'])
    except Exception:
        cleanup_staging(storage, intent.final_key)
        raise
    transaction.on_commit(lambda: cleanup_staging(storage, intent.staging_key))
    return document
