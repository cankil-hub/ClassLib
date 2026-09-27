from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from library.models import File, Folder, ObjectDeletion, UploadIntent
from library.services import delete_file
from storage_backends.base import ObjectMissing, StorageError


class MemoryStorage:
    """Contract fake for business tests; separate adapter tests cover S3 calls."""
    direct_upload = True

    def __init__(self):
        self.objects = {}

    def upload_url(self, key, content_type, size):
        return f'https://storage.example.test/{key}?signature=test'

    def copy(self, source, destination):
        if source not in self.objects:
            raise ObjectMissing
        self.objects[destination] = self.objects[source]

    def open(self, key):
        if key not in self.objects:
            raise ObjectMissing
        return BytesIO(self.objects[key])

    def delete(self, key):
        self.objects.pop(key, None)

    def download_url(self, key, name):
        if key not in self.objects:
            raise ObjectMissing
        return f'https://storage.example.test/{key}?download=signed'


class DirectUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username='cloud-teacher', role=User.Role.TEACHER)
        cls.other = User.objects.create_user(username='other-teacher', role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username='cloud-student')
        cls.folder = Folder.objects.create(name='Cloud')

    def setUp(self):
        self.storage = MemoryStorage()
        for module in ('library.views', 'library.uploads', 'library.services',
                       'library.management.commands.cleanup_uploads'):
            patcher = patch(f'{module}.get_storage', return_value=self.storage)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.force_login(self.teacher)
        self.begin_url = reverse('library:upload_begin', args=[self.folder.pk])

    def begin(self, name='lesson.txt', content=b'hello'):
        response = self.client.post(self.begin_url, {'name': name, 'size': len(content)})
        self.assertEqual(response.status_code, 200, response.content)
        intent = UploadIntent.objects.latest('expires_at')
        self.storage.objects[intent.staging_key] = content
        return intent, response.json()['complete_url']

    def finish(self, url):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url)

    def test_large_direct_upload_is_validated_and_download_redirects(self):
        content = b'a' * (5 * 1024 * 1024)
        intent, url = self.begin(content=content)
        self.assertEqual(self.finish(url).status_code, 200)
        document = File.objects.get()
        self.assertEqual(document.size, len(content))
        self.assertEqual(self.storage.objects[document.storage_key], content)
        self.assertNotIn(intent.staging_key, self.storage.objects)
        self.client.force_login(self.student)
        response = self.client.get(reverse('library:file_download', args=[document.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertTrue(response.url.startswith('https://storage.example.test/files/'))

    def test_page_uses_direct_upload_and_rejects_multipart_proxy(self):
        url = reverse('library:file_upload', args=[self.folder.pk])
        self.assertContains(self.client.get(url), 'direct-upload.js')
        self.assertEqual(self.client.post(url).status_code, 400)

    def test_begin_validates_name_extension_size_and_duplicates(self):
        cases = [('evil.exe', 5), ('../notes.txt', 5), ('x.txt', 0), ('x.txt', 52428801)]
        for name, size in cases:
            with self.subTest(name=name, size=size):
                self.assertEqual(self.client.post(self.begin_url, {'name': name, 'size': size}).status_code, 400)
        self.assertFalse(UploadIntent.objects.exists())
        _, url = self.begin()
        self.finish(url)
        self.assertEqual(self.client.post(self.begin_url, {'name': 'lesson.txt', 'size': 5}).status_code, 400)

    def test_authorization_and_ownership(self):
        intent, url = self.begin()
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(self.begin_url, {'name': 'n.txt', 'size': 5}).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(File.objects.exists())

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher)
        self.assertEqual(client.post(self.begin_url, {'name': 'n.txt', 'size': 5}).status_code, 403)

    def test_missing_object_and_expiration_do_not_publish(self):
        intent, url = self.begin()
        self.storage.objects.clear()
        self.assertEqual(self.finish(url).status_code, 409)
        intent.expires_at = timezone.now() - timedelta(seconds=1)
        intent.save()
        self.assertEqual(self.finish(url).status_code, 400)
        self.assertFalse(File.objects.exists())

    def test_signature_and_actual_size_are_checked(self):
        for name, content, replacement in [('fake.pdf', b'notpdf', None), ('notes.txt', b'hello', b'x')]:
            with self.subTest(name=name):
                intent, url = self.begin(name=name, content=content)
                if replacement:
                    self.storage.objects[intent.staging_key] = replacement
                self.assertEqual(self.finish(url).status_code, 400)
                self.assertNotIn(intent.final_key, self.storage.objects)
        self.assertFalse(File.objects.exists())

    def test_completion_is_idempotent_and_replayed_put_cannot_change_file(self):
        intent, url = self.begin()
        first = self.finish(url)
        self.storage.objects[intent.staging_key] = b'changed after publication'
        self.assertEqual(self.finish(url).json(), first.json())
        self.assertEqual(File.objects.count(), 1)
        self.assertEqual(self.storage.objects[File.objects.get().storage_key], b'hello')

    def test_deleted_completed_file_cannot_be_resurrected(self):
        intent, url = self.begin()
        self.finish(url)
        with self.captureOnCommitCallbacks(execute=True):
            delete_file(File.objects.get())
        self.assertEqual(self.finish(url).status_code, 400)
        self.assertFalse(File.objects.exists())

    def test_deleted_folder_does_not_publish_and_cleanup_retains_record(self):
        intent, url = self.begin()
        self.folder.delete()
        self.assertEqual(self.finish(url).status_code, 400)
        self.assertTrue(UploadIntent.objects.filter(pk=intent.pk).exists())

    def test_collision_between_begin_and_complete_does_not_publish(self):
        intent, first = self.begin()
        second_intent, second = self.begin()
        self.assertEqual(self.finish(first).status_code, 200)
        self.assertEqual(self.finish(second).status_code, 400)
        self.assertEqual(File.objects.count(), 1)

    def test_storage_outage_has_safe_retryable_error(self):
        intent, url = self.begin()
        with patch.object(self.storage, 'copy', side_effect=StorageError('private provider details')):
            response = self.finish(url)
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'private provider details', status_code=503)
        self.assertEqual(self.finish(url).status_code, 200)

    def test_cleanup_dry_run_then_removes_expired_only_and_preserves_final_file(self):
        completed, complete_url = self.begin()
        self.finish(complete_url)
        stale, _ = self.begin(name='abandoned.txt')
        self.storage.objects[stale.final_key] = b'interrupted copy'
        self.storage.objects[completed.staging_key] = b'replayed PUT'
        fresh, _ = self.begin(name='fresh.txt')
        UploadIntent.objects.filter(pk__in=[completed.pk, stale.pk]).update(
            expires_at=timezone.now() - timedelta(days=2))
        call_command('cleanup_uploads', stdout=StringIO())
        self.assertEqual(UploadIntent.objects.count(), 3)
        call_command('cleanup_uploads', apply=True, stdout=StringIO())
        self.assertEqual(list(UploadIntent.objects.values_list('pk', flat=True)), [fresh.pk])
        self.assertEqual(self.storage.objects[completed.final_key], b'hello')
        self.assertNotIn(stale.staging_key, self.storage.objects)
        self.assertNotIn(stale.final_key, self.storage.objects)
        self.assertNotIn(completed.staging_key, self.storage.objects)

    def test_failed_deletion_is_durable_and_retryable(self):
        intent, url = self.begin()
        self.finish(url)
        with patch.object(self.storage, 'delete', side_effect=StorageError), self.captureOnCommitCallbacks(execute=True):
            delete_file(File.objects.get())
        self.assertFalse(File.objects.exists())
        self.assertTrue(ObjectDeletion.objects.filter(pk=intent.final_key).exists())
        call_command('cleanup_objects', apply=True, stdout=StringIO())
        self.assertFalse(ObjectDeletion.objects.exists())
        self.assertNotIn(intent.final_key, self.storage.objects)

    def test_rollback_does_not_delete_file_or_queue(self):
        intent, url = self.begin()
        self.finish(url)
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    delete_file(File.objects.get())
                    raise ValueError('rollback')
            except ValueError:
                pass
        self.assertTrue(File.objects.exists())
        self.assertFalse(ObjectDeletion.objects.exists())
        self.assertIn(intent.final_key, self.storage.objects)


@override_settings(STORAGE_BACKEND='storage_backends.local.LocalStorage')
class LocalEndpointTests(TestCase):
    def test_direct_upload_endpoint_is_unavailable_locally(self):
        teacher = User.objects.create_user(username='teacher', role=User.Role.TEACHER)
        folder = Folder.objects.create(name='Local')
        self.client.force_login(teacher)
        self.assertEqual(self.client.post(reverse('library:upload_begin', args=[folder.pk])).status_code, 404)
