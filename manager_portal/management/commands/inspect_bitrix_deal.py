from django.core.management.base import BaseCommand, CommandError

from manager_portal.services import BitrixImportError, inspect_bitrix_deal_payload


class Command(BaseCommand):
    help = 'Показывает диагностические данные сделки Bitrix24 перед импортом в operations.'

    def add_arguments(self, parser):
        parser.add_argument('deal_id', help='ID сделки Bitrix24, например 6669')

    def handle(self, *args, **options):
        deal_id = options['deal_id']
        try:
            payload = inspect_bitrix_deal_payload(deal_id)
        except BitrixImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f'Bitrix deal #{payload["deal_id"]}')
        self.stdout.write(f'raw CONTACT_ID: {payload["raw_contact_id"]}')
        self.stdout.write(f'raw COMPANY_ID: {payload["raw_company_id"]}')
        self.stdout.write(f'mapped city: {payload["mapped_city"]}')
        self.stdout.write(f'mapped recipient_name: {payload["mapped_recipient_name"]}')
        self.stdout.write(f'mapped recipient_phone: {payload["mapped_recipient_phone"]}')
        self.stdout.write(f'mapped delivery_address: {payload["mapped_delivery_address"]}')
        self.stdout.write(f'mapped client_request: {payload["mapped_client_request"]}')
        self.stdout.write(f'product rows count: {payload["product_rows_count"]}')
