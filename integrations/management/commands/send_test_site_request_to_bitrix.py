from django.core.management.base import BaseCommand, CommandError

from integrations.bitrix_site_requests import BitrixSiteRequestSyncError, send_site_request_to_bitrix
from integrations.models import SiteLeadRequest


class Command(BaseCommand):
    help = 'Создаёт тестовую заявку и отправляет её в Bitrix.'

    def handle(self, *args, **options):
        site_request = SiteLeadRequest.objects.create(
            source_type=SiteLeadRequest.SOURCE_TEST,
            name='Тест BizonVR',
            phone='+7 900 000-00-00',
            email='test-lead@example.com',
            city='Екатеринбург',
            message='Тестовая заявка для проверки Bitrix intake.',
            page_url='https://bizonvr.ru/test-site-request',
            spam_status=SiteLeadRequest.SPAM_STATUS_CLEAN,
            sync_status=SiteLeadRequest.SYNC_STATUS_PENDING,
        )
        try:
            result = send_site_request_to_bitrix(site_request)
        except BitrixSiteRequestSyncError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Site request #{site_request.pk} synced: contact={result['contact_id'] or '-'}, deal={result['deal_id'] or '-'}"
            )
        )
