from django.core.management.base import BaseCommand, CommandError

from manager_portal.legacy_imports import import_legacy_business_finance


class Command(BaseCommand):
    help = 'Import legacy BusinessFinance PostgreSQL data into manager_portal finance models.'

    def add_arguments(self, parser):
        parser.add_argument('--source-dsn', required=True, help='PostgreSQL DSN for the legacy BusinessFinance database.')
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true', help='Analyze without changing product data.')
        mode.add_argument('--apply', action='store_true', help='Write imported data and provenance records.')

    def handle(self, *args, **options):
        batch = import_legacy_business_finance(options['source_dsn'], dry_run=bool(options['dry_run']))
        self.stdout.write(self.style.NOTICE(f'Batch #{batch.pk} status={batch.status} source={batch.source_ref}'))
        self.stdout.write(f'Summary: {batch.summary}')
        if batch.error_text:
            raise CommandError(batch.error_text)
        return None
