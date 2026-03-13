from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from manager_portal.legacy_imports import import_legacy_docuflow


class Command(BaseCommand):
    help = 'Import legacy DocuFlow SQLite data into manager_portal contract models.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            default=str(Path('legacy') / 'docuflow (2)' / 'server' / 'data.sqlite'),
            help='Path to legacy DocuFlow SQLite database.',
        )
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true', help='Analyze without changing product data.')
        mode.add_argument('--apply', action='store_true', help='Write imported data and provenance records.')

    def handle(self, *args, **options):
        batch = import_legacy_docuflow(options['source'], dry_run=bool(options['dry_run']))
        self.stdout.write(self.style.NOTICE(f'Batch #{batch.pk} status={batch.status} source={batch.source_ref}'))
        self.stdout.write(f'Summary: {batch.summary}')
        if batch.error_text:
            raise CommandError(batch.error_text)
        return None
