from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from library.models import UploadIntent
from storage_backends import get_storage
from storage_backends.base import StorageError


class Command(BaseCommand):
    help = 'Remove expired upload staging objects (dry run unless --apply is supplied).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        storage = get_storage()
        if not storage.direct_upload:
            self.stdout.write('Local storage: nothing to clean.')
            return
        # Keep a grace period after the signed URL expires for in-flight PUTs.
        cutoff = timezone.now() - timedelta(days=1)
        ids = list(UploadIntent.objects.filter(expires_at__lt=cutoff).values_list('pk', flat=True))
        self.stdout.write(f'{len(ids)} expired upload records; apply={options["apply"]}')
        if not options['apply']:
            return
        failures = 0
        for pk in ids:
            with transaction.atomic():
                intent = UploadIntent.objects.select_for_update().filter(pk=pk, expires_at__lt=cutoff).first()
                if intent is None:
                    continue
                try:
                    storage.delete(intent.staging_key)
                    if not intent.completed_at:
                        storage.delete(intent.final_key)
                except StorageError:
                    failures += 1
                    continue  # Keep the record for the next retry.
                intent.delete()
        if failures:
            raise CommandError(f'{failures} records retained for retry; storage unavailable.')
