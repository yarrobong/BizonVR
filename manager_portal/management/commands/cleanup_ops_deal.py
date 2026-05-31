from django.core.management.base import BaseCommand, CommandError

from manager_portal.ops_cleanup import build_cleanup_plan, execute_cleanup_plan
from manager_portal.models import ManagerDeal, InventoryBalance
from orders.models import Order


class Command(BaseCommand):
    help = 'Очистить операционный хвост конкретной Bitrix-сделки в /ops/.'

    def add_arguments(self, parser):
        parser.add_argument('deal_id', help='ID сделки Bitrix24, например 6669')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Только показать план удаления без изменения данных.',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Выполнить cleanup по показанному плану.',
        )

    def handle(self, *args, **options):
        deal_id = options['deal_id']
        dry_run = options['dry_run'] or not options['confirm']
        confirm = options['confirm']
        if options['dry_run'] and options['confirm']:
            raise CommandError('Используйте только один режим: --dry-run или --confirm.')

        plan = build_cleanup_plan(deal_id)
        self._print_plan(plan)

        if not plan.exists:
            self.stdout.write(self.style.WARNING(f'Bitrix deal #{deal_id} не найдена в operations.'))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    'Dry-run завершён: данные не изменялись. Запустите с --confirm для выполнения cleanup.'
                )
            )
            if plan.has_blocking_warnings:
                raise CommandError('Обнаружены blocking warnings. Cleanup с --confirm сейчас небезопасен.')
            return

        if plan.has_blocking_warnings:
            raise CommandError('Cleanup остановлен: сначала разберите blocking warnings из плана удаления.')

        result = execute_cleanup_plan(plan)
        self.stdout.write(self.style.SUCCESS(f'Cleanup выполнен для Bitrix #{deal_id}.'))
        self.stdout.write(
            f'Удалено: deal={result["deleted"]["deal_id"]}, order={result["deleted"]["order_id"]}, '
            f'order_items={result["deleted"]["order_items"]}, purchases={result["deleted"]["purchases"]}, '
            f'cargos={result["deleted"]["cargos"]}, reservations={result["deleted"]["reservations"]}, '
            f'shipments={result["deleted"]["shipments"]}, movements={result["deleted"]["inventory_movements"]}.'
        )
        if result['retained']['purchases'] or result['retained']['cargos'] or result['retained']['manager_clients']:
            self.stdout.write(
                'Сохранено из-за внешних связей: '
                f'purchases={result["retained"]["purchases"]}, '
                f'cargos={result["retained"]["cargos"]}, '
                f'manager_clients={result["retained"]["manager_clients"]}.'
            )
        self._print_post_cleanup_status(deal_id, plan)

    def _print_plan(self, plan):
        self.stdout.write(f'Cleanup plan for Bitrix #{plan.bitrix_deal_id}')
        if not plan.exists:
            return
        deal = plan.deal
        order = plan.order
        self.stdout.write(
            f'  deal: id={deal.id} code={deal.code or "—"} status={deal.case_status} order_id={deal.order_id}'
        )
        self.stdout.write(
            f'  order: id={order.id} status={order.status} recipient={order.recipient_name or order.first_name or "—"}'
        )
        self.stdout.write('  order_items:')
        for item in plan.order_items:
            self.stdout.write(
                f'    - id={item.id} type={item.line_type} product_id={item.product_id} '
                f'variant_id={item.variant_id} qty={item.quantity} name={item.display_name}'
            )
        self.stdout.write('  purchase_items:')
        for item in plan.purchase_items:
            self.stdout.write(
                f'    - id={item.id} purchase_id={item.purchase_id} order_item_id={item.order_item_id} '
                f'product_id={item.product_id} qty={item.quantity} received={item.received_quantity}'
            )
        self.stdout.write('  cargo_items:')
        for item in plan.cargo_items:
            self.stdout.write(
                f'    - id={item.id} cargo_id={item.cargo_id} purchase_item_id={item.purchase_item_id} '
                f'product_id={item.product_id} qty={item.quantity} received={item.received_quantity}'
            )
        self.stdout.write('  reservation_items:')
        for item in plan.reservation_items:
            self.stdout.write(
                f'    - id={item.id} reservation_id={item.reservation_id} order_item_id={item.order_item_id} '
                f'product_id={item.product_id} qty={item.quantity} fulfilled={item.fulfilled_quantity}'
            )
        self.stdout.write('  shipment_items:')
        for item in plan.shipment_items:
            self.stdout.write(
                f'    - id={item.id} shipment_id={item.shipment_id} order_item_id={item.order_item_id} '
                f'reservation_item_id={item.reservation_item_id} product_id={item.product_id} qty={item.quantity}'
            )
        self.stdout.write('  inventory_movements:')
        for movement in plan.inventory_movements:
            self.stdout.write(
                f'    - id={movement.id} type={movement.movement_type} warehouse_id={movement.warehouse_id} '
                f'product_id={movement.product_id} variant_id={movement.variant_id} qty={movement.quantity} '
                f'ref={movement.reference_type}:{movement.reference_id}'
            )
        self.stdout.write('  balances:')
        if not plan.balances:
            self.stdout.write('    - none')
        for balance in plan.balances:
            self.stdout.write(
                f'    - id={balance.id} warehouse_id={balance.warehouse_id} product_id={balance.product_id} '
                f'variant_id={balance.variant_id} qty={balance.quantity}'
            )
        self.stdout.write(
            '  delete summary: '
            f'activities={len(plan.activities)}, finance_deals={len(plan.finance_deals)}, '
            f'inventory_lots={len(plan.inventory_lots)}, allocations={len(plan.sale_line_allocations)}, '
            f'manager_clients={len(plan.manager_clients)}.'
        )
        if plan.notes:
            self.stdout.write('  notes:')
            for note in plan.notes:
                self.stdout.write(f'    - {note}')
        if plan.warnings:
            self.stdout.write('  warnings:')
            for warning in plan.warnings:
                level = 'BLOCKING' if warning.blocking else 'warning'
                self.stdout.write(f'    - [{level}] {warning.code}: {warning.message}')
        else:
            self.stdout.write('  warnings: none')

    def _print_post_cleanup_status(self, deal_id, plan):
        deal_exists = ManagerDeal.objects.filter(bitrix_deal_id=str(deal_id).strip()).exists()
        order_exists = Order.objects.filter(pk=plan.order.pk).exists() if plan.order else False
        self.stdout.write(
            'Post-check: '
            f'manager_deal_exists={deal_exists}, '
            f'order_exists={order_exists}, '
            f'shipments={plan.shipments[0].__class__.objects.filter(id__in=[s.id for s in plan.shipments]).count() if plan.shipments else 0}, '
            f'reservations={plan.reservations[0].__class__.objects.filter(id__in=[r.id for r in plan.reservations]).count() if plan.reservations else 0}, '
            f'cargos={plan.cargos[0].__class__.objects.filter(id__in=[c.id for c in plan.cargos]).count() if plan.cargos else 0}, '
            f'purchases={plan.purchases[0].__class__.objects.filter(id__in=[p.id for p in plan.purchases]).count() if plan.purchases else 0}.'
        )
        touched_balances = list(
            InventoryBalance.objects.filter(
                warehouse_id__in=sorted(plan.touched_warehouse_ids or []),
            ).order_by('warehouse_id', 'product_id', 'variant_id')
        )
        if touched_balances:
            self.stdout.write('  recalculated balances:')
            for balance in touched_balances:
                self.stdout.write(
                    f'    - warehouse_id={balance.warehouse_id} product_id={balance.product_id} '
                    f'variant_id={balance.variant_id} qty={balance.quantity}'
                )
