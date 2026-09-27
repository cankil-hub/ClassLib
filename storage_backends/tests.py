from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from botocore.response import StreamingBody
from botocore.stub import Stubber
from django.test import SimpleTestCase, override_settings

from .base import ObjectMissing, ObjectTooLarge, StorageError
from .s3 import S3Storage


@override_settings(
    S3_ENDPOINT_URL='https://example.storage.supabase.co/storage/v1/s3',
    S3_REGION='ap-southeast-1', S3_ACCESS_KEY_ID='test-key',
    S3_SECRET_ACCESS_KEY='test-secret', S3_BUCKET_NAME='private-files',
)
class S3AdapterTests(SimpleTestCase):
    def test_upload_url_signs_length_and_type_and_never_contains_secret(self):
        storage = S3Storage()
        url = storage.upload_url('pending/test.txt', 'text/plain', 123)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, '/storage/v1/s3/private-files/pending/test.txt')
        self.assertEqual(query['X-Amz-Expires'], ['900'])
        self.assertIn('content-length', query['X-Amz-SignedHeaders'][0])
        self.assertIn('content-type', query['X-Amz-SignedHeaders'][0])
        self.assertNotIn('test-secret', url)

    def test_download_is_short_lived_attachment_and_checks_existence(self):
        storage = S3Storage()
        with Stubber(storage.client) as stub:
            stub.add_response('head_object', {}, {'Bucket': 'private-files', 'Key': 'files/test.txt'})
            url = storage.download_url('files/test.txt', '中文资料.txt')
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query['X-Amz-Expires'], ['60'])
        self.assertTrue(query['response-content-disposition'][0].startswith('attachment;'))
        self.assertEqual(query['response-cache-control'], ['private, no-store'])

    def test_read_enforces_declared_and_streamed_limits_and_closes_body(self):
        for length, content in [(6, b'abcdef'), (4, b'abcdef')]:
            storage = S3Storage()
            body = StreamingBody(BytesIO(content), length)
            with self.subTest(length=length), override_settings(MAX_UPLOAD_SIZE=5), Stubber(storage.client) as stub:
                stub.add_response('get_object', {'ContentLength': length, 'Body': body},
                                  {'Bucket': 'private-files', 'Key': 'file.txt'})
                with patch.object(body, 'close', wraps=body.close) as close, self.assertRaises(ObjectTooLarge):
                    storage.open('file.txt')
                close.assert_called_once()

    def test_read_returns_seekable_validatable_content(self):
        storage = S3Storage()
        body = StreamingBody(BytesIO(b'hello'), 5)
        with Stubber(storage.client) as stub:
            stub.add_response('get_object', {'ContentLength': 5, 'Body': body},
                              {'Bucket': 'private-files', 'Key': 'file.txt'})
            with storage.open('file.txt') as stream:
                self.assertEqual(stream.read(), b'hello')
                stream.seek(0)
                self.assertEqual(stream.read(2), b'he')

    def test_missing_object_is_translated(self):
        for code in ('NoSuchKey', ''):
            storage = S3Storage()
            with self.subTest(code=code), Stubber(storage.client) as stub:
                stub.add_client_error('get_object', service_error_code=code, http_status_code=404)
                with self.assertRaises(ObjectMissing):
                    storage.open('missing.txt')

    def test_empty_provider_error_does_not_hide_a_service_failure(self):
        storage = S3Storage()
        with Stubber(storage.client) as stub:
            stub.add_client_error('get_object', service_error_code='', http_status_code=503)
            with self.assertRaises(StorageError) as error:
                storage.open('file.txt')
            self.assertNotIsInstance(error.exception, ObjectMissing)

    def test_copy_and_delete_use_the_selected_bucket(self):
        storage = S3Storage()
        with Stubber(storage.client) as stub:
            stub.add_response('copy_object', {}, {
                'Bucket': 'private-files', 'Key': 'files/a.txt',
                'CopySource': {'Bucket': 'private-files', 'Key': 'pending/a.txt'},
            })
            stub.add_response('delete_object', {}, {'Bucket': 'private-files', 'Key': 'pending/a.txt'})
            storage.copy('pending/a.txt', 'files/a.txt')
            storage.delete('pending/a.txt')
            stub.assert_no_pending_responses()
