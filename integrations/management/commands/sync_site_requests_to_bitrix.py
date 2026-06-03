from django.core.management.base import BaseCommand

from integrations.bitrix_site_requests import sync_pending_site_requests


class Command(BaseCommand):
    help = 'Повторно отправляет pending/failed заявки сайта в Bitrix.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **options):
        summary = sync_pending_site_requests(limit=options['limit'] or None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed: {summary['processed']}, synced: {summary['succeeded']}, failed: {summary['failed']}"
            )
        )
