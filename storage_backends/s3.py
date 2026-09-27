"""Supabase's S3-compatible API; interchangeable with another S3 provider."""
from contextlib import contextmanager
from tempfile import SpooledTemporaryFile

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.utils.http import content_disposition_header

from .base import ObjectMissing, ObjectTooLarge, StorageError


@contextmanager
def translate_errors():
    try:
        yield
    except ClientError as exc:
        if (exc.response.get('Error', {}).get('Code') in {'404', 'NoSuchKey', 'NotFound'}
                or exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode') == 404):
            raise ObjectMissing from exc
        raise StorageError('Object storage request failed.') from exc
    except BotoCoreError as exc:
        raise StorageError('Object storage is unavailable.') from exc


class S3Storage:
    direct_upload = True

    def __init__(self):
        self.bucket = settings.S3_BUCKET_NAME
        self.client = boto3.client(
            's3', endpoint_url=settings.S3_ENDPOINT_URL, region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(
                signature_version='s3v4', s3={'addressing_style': 'path'},
                connect_timeout=5, read_timeout=30, retries={'max_attempts': 2},
                request_checksum_calculation='when_required',
                response_checksum_validation='when_required',
            ),
        )

    def save(self, key, stream, content_type):
        with translate_errors():
            stream.seek(0)
            self.client.put_object(Bucket=self.bucket, Key=key, Body=stream, ContentType=content_type)
        return key

    def delete(self, key):
        with translate_errors():
            self.client.delete_object(Bucket=self.bucket, Key=key)

    def copy(self, source, destination):
        with translate_errors():
            self.client.copy_object(
                Bucket=self.bucket, Key=destination,
                CopySource={'Bucket': self.bucket, 'Key': source},
            )

    def open(self, key):
        # Bounded temporary spool, never an enduring file on the web server.
        spool = SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
        try:
            with translate_errors():
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                body = response['Body']
                try:
                    if response['ContentLength'] > settings.MAX_UPLOAD_SIZE:
                        raise ObjectTooLarge
                    size = 0
                    for chunk in body.iter_chunks(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > settings.MAX_UPLOAD_SIZE:
                            raise ObjectTooLarge
                        spool.write(chunk)
                finally:
                    body.close()
                spool.seek(0)
            return spool
        except Exception:
            spool.close()
            raise

    def upload_url(self, key, content_type, size):
        with translate_errors():
            return self.client.generate_presigned_url(
                'put_object', Params={
                    'Bucket': self.bucket, 'Key': key,
                    'ContentType': content_type, 'ContentLength': size,
                }, ExpiresIn=settings.DIRECT_UPLOAD_TTL,
            )

    def download_url(self, key, name):
        with translate_errors():
            self.client.head_object(Bucket=self.bucket, Key=key)
            return self.client.generate_presigned_url(
                'get_object', Params={
                    'Bucket': self.bucket, 'Key': key,
                    'ResponseContentDisposition': content_disposition_header(True, name),
                    'ResponseContentType': 'application/octet-stream',
                    'ResponseCacheControl': 'private, no-store',
                }, ExpiresIn=settings.DOWNLOAD_URL_TTL,
            )
