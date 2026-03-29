import json

from django.core.management.base import BaseCommand

from manager_portal.models import Shipment


class Command(BaseCommand):
    help = 'Показывает исторические shipped/delivered shipment без inventory_consumed_at.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--json',
            action='store_true',
            dest='as_json',
            help='Вывести результат в JSON.',
        )

    def handle(self, *args, **options):
        shipments = list(
            Shipment.objects.select_related('order', 'reservation', 'client')
            .filter(
                status__in=[Shipment.STATUS_SHIPPED, Shipment.STATUS_DELIVERED],
                inventory_consumed_at__isnull=True,
            )
            .order_by('created_at', 'id')
        )
        rows = [
            {
                'shipment_id': shipment.id,
                'code': shipment.code or '',
                'status': shipment.status,
                'client': shipment.client.name if shipment.client_id else '',
                'order_id': shipment.order_id,
                'reservation_id': shipment.reservation_id,
                'classification': 'manual_review_required',
            }
            for shipment in shipments
        ]
        if options['as_json']:
            self.stdout.write(json.dumps({'count': len(rows), 'shipments': rows}, ensure_ascii=False, indent=2))
            return
        if not rows:
            self.stdout.write(self.style.SUCCESS('Исторических shipment без inventory_consumed_at не найдено.'))
            return
        self.stdout.write(self.style.WARNING(f'Найдено {len(rows)} shipment без inventory_consumed_at:'))
        for row in rows:
            self.stdout.write(
                f"[manual_review_required] shipment={row['shipment_id']} code={row['code'] or '-'} "
                f"status={row['status']} order={row['order_id'] or '-'} reservation={row['reservation_id'] or '-'} "
                f"client={row['client'] or '-'}"
            )
