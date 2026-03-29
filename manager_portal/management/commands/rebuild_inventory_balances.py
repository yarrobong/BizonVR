from django.core.management.base import BaseCommand

from manager_portal.services import rebuild_inventory_balance_cache


class Command(BaseCommand):
    help = 'Rebuild InventoryBalance cache from inventory lots.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--warehouse-id',
            action='append',
            dest='warehouse_ids',
            type=int,
            help='Limit rebuild to one or more warehouse IDs.',
        )

    def handle(self, *args, **options):
        warehouse_ids = options.get('warehouse_ids') or None
        rebuild_inventory_balance_cache(warehouse_ids=warehouse_ids)
        scope = ', '.join(str(value) for value in warehouse_ids) if warehouse_ids else 'all warehouses'
        self.stdout.write(self.style.SUCCESS(f'Inventory balances rebuilt for {scope}.'))
