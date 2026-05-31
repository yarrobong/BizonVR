from django.core.management.base import BaseCommand, CommandError

from manager_portal.services import BitrixImportError, sync_bitrix_deal_into_operations


class Command(BaseCommand):
    help = 'Импортирует оплаченную сделку из Bitrix24 в операционный контур manager_portal.'

    def add_arguments(self, parser):
        parser.add_argument('deal_id', help='ID сделки Bitrix24, например 6669')

    def handle(self, *args, **options):
        deal_id = options['deal_id']
        try:
            result = sync_bitrix_deal_into_operations(deal_id)
        except BitrixImportError as exc:
            raise CommandError(str(exc)) from exc

        for warning in result.get('warnings', []):
            self.stdout.write(self.style.WARNING(warning))
        self.stdout.write(
            self.style.SUCCESS(
                'Импорт завершен: '
                f'Bitrix #{result["manager_deal"].bitrix_deal_id} '
                f'-> deal #{result["manager_deal"].pk}, '
                f'order #{result["order"].pk}, '
                f'items={result["order_item_count"]}'
            )
        )
