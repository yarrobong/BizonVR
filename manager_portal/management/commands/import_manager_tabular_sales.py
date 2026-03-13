from django.core.management.base import BaseCommand, CommandError

from manager_portal.legacy_imports import import_manager_tabular_sales


class Command(BaseCommand):
    help = 'Import normalized Avito and supply sales tables into manager_portal deals.'

    def add_arguments(self, parser):
        parser.add_argument('--source-dir', required=True, help='Directory with normalized CSV/JSON files.')
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true', help='Analyze without writing imported entities.')
        mode.add_argument('--apply', action='store_true', help='Write imported entities and provenance records.')

    def handle(self, *args, **options):
        batch = import_manager_tabular_sales(options['source_dir'], dry_run=bool(options['dry_run']))
        self.stdout.write(self.style.NOTICE(f'Batch #{batch.pk} status={batch.status} source={batch.source_ref}'))
        self.stdout.write(f'Summary: {batch.summary}')
        if batch.error_text:
            raise CommandError(batch.error_text)
        return None
