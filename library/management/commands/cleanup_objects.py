from django.core.management.base import BaseCommand, CommandError

from library.models import ObjectDeletion
from library.services import retry_object_deletion


class Command(BaseCommand):
    help = 'Retry deletion of objects already removed from the library (dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        keys = list(ObjectDeletion.objects.values_list('storage_key', flat=True))
        self.stdout.write(f'{len(keys)} pending deletions; apply={options["apply"]}')
        if options['apply']:
            failures = sum(not retry_object_deletion(key) for key in keys)
            if failures:
                raise CommandError(f'{failures} deletions retained for retry.')
