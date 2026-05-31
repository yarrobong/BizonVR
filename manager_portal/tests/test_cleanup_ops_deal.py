from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from manager_portal.models import (
    Cargo,
    CargoItem,
    InventoryBalance,
    InventoryLot,
    InventoryMovement,
    ManagerClient,
    ManagerDeal,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    SaleLineAllocation,
    Shipment,
    ShipmentItem,
)
from manager_portal.services import (
    allocate_inventory_to_order_item,
    create_or_update_reservation_movements,
    dispatch_shipment,
    ensure_manager_deal_for_order,
    receive_cargo_item,
)
from manager_portal.tests.test_manager_portal import ManagerPortalBaseTestCase
from orders.models import Order


class CleanupOpsDealCommandTests(ManagerPortalBaseTestCase):
    def _create_ops_graph(self, *, bitrix_deal_id='6669', receipt_quantity=1):
        order = self.create_order(
            phone='+7 912 000 55 55',
            email='ops@example.com',
            first_name='Smoke',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_COURIER,
            created_at=timezone.now() - timedelta(hours=2),
        )
        order_item = order.items.select_related('product', 'variant').get()
        client = ManagerClient.objects.create(
            name='Тестовый клиент cleanup',
            phone='+7 912 555-00-00',
            email='cleanup@example.com',
        )
        client.orders.add(order)
        deal = ensure_manager_deal_for_order(order, customer_source=ManagerDeal.SOURCE_OTHER)
        deal.bitrix_deal_id = bitrix_deal_id
        deal.save(update_fields=['bitrix_deal_id', 'updated_at'])

        purchase = Purchase.objects.create(
            date=timezone.localdate(),
            supplier_name='Cleanup Supplier',
            currency='CNY',
            status=Purchase.STATUS_ORDERED,
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            order_item=order_item,
            quantity=receipt_quantity,
            unit_cost=Decimal('450.00'),
        )
        cargo = Cargo.objects.create(
            purchase=purchase,
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
            eta=timezone.localdate() + timedelta(days=3),
        )
        cargo_item = CargoItem.objects.create(
            cargo=cargo,
            product=self.product,
            purchase_item=purchase_item,
            quantity=receipt_quantity,
        )
        receive_cargo_item(
            cargo_item,
            quantity=receipt_quantity,
            author=self.staff_user,
            warehouse=self.warehouse,
            comment='cleanup receipt',
        )

        reservation = Reservation.objects.create(
            manager_deal=deal,
            client=client,
            linked_order=order,
            status=Reservation.STATUS_ACTIVE,
            source_type=Reservation.SOURCE_WAREHOUSE,
            source_warehouse=self.warehouse,
            target_warehouse=self.warehouse,
            comments='cleanup reserve',
        )
        reservation_item = ReservationItem.objects.create(
            reservation=reservation,
            order_item=order_item,
            product=self.product,
            quantity=1,
        )
        create_or_update_reservation_movements(
            reservation,
            movement_type=InventoryMovement.TYPE_RESERVE,
            author=self.staff_user,
            comment='cleanup reserve',
        )

        shipment = Shipment.objects.create(
            order=order,
            client=client,
            manager_deal=deal,
            reservation=reservation,
            source_warehouse=self.warehouse,
            target_warehouse=self.warehouse,
            status=Shipment.STATUS_PENDING,
        )
        ShipmentItem.objects.create(
            shipment=shipment,
            order_item=order_item,
            reservation_item=reservation_item,
            product=self.product,
            quantity=1,
        )
        dispatch_shipment(shipment, author=self.staff_user, comment='cleanup ship')

        return {
            'order': order,
            'order_item': order_item,
            'client': client,
            'deal': deal,
            'purchase': purchase,
            'purchase_item': purchase_item,
            'cargo': cargo,
            'cargo_item': cargo_item,
            'reservation': reservation,
            'reservation_item': reservation_item,
            'shipment': shipment,
        }

    def test_cleanup_ops_deal_dry_run_and_confirm(self):
        graph = self._create_ops_graph()
        out = StringIO()

        call_command('cleanup_ops_deal', '6669', '--dry-run', stdout=out)
        dry_run_output = out.getvalue()

        self.assertIn('Cleanup plan for Bitrix #6669', dry_run_output)
        self.assertIn('Dry-run завершён', dry_run_output)
        self.assertTrue(ManagerDeal.objects.filter(pk=graph['deal'].pk).exists())
        self.assertTrue(Order.objects.filter(pk=graph['order'].pk).exists())

        out = StringIO()
        call_command('cleanup_ops_deal', '6669', '--confirm', stdout=out)
        confirm_output = out.getvalue()

        self.assertIn('Cleanup выполнен для Bitrix #6669', confirm_output)
        self.assertFalse(ManagerDeal.objects.filter(pk=graph['deal'].pk).exists())
        self.assertFalse(Order.objects.filter(pk=graph['order'].pk).exists())
        self.assertFalse(Purchase.objects.filter(pk=graph['purchase'].pk).exists())
        self.assertFalse(Cargo.objects.filter(pk=graph['cargo'].pk).exists())
        self.assertFalse(Reservation.objects.filter(pk=graph['reservation'].pk).exists())
        self.assertFalse(Shipment.objects.filter(pk=graph['shipment'].pk).exists())
        self.assertFalse(InventoryLot.objects.filter(purchase_item=graph['purchase_item']).exists())
        self.assertFalse(SaleLineAllocation.objects.filter(order_item=graph['order_item']).exists())
        self.assertFalse(
            InventoryMovement.objects.filter(
                reference_type__in=['cargo', 'reservation', 'shipment'],
                reference_id__in=[graph['cargo'].pk, graph['reservation'].pk, graph['shipment'].pk],
            ).exists()
        )
        balance = InventoryBalance.objects.get(warehouse=self.warehouse, product=self.product, variant=None)
        self.assertEqual(balance.quantity, 0)
        self.assertTrue(self.product.__class__.objects.filter(pk=self.product.pk).exists())
        self.assertTrue(graph['client'].__class__.objects.filter(pk=graph['client'].pk).exists() is False)
        self.assertTrue(self.warehouse.__class__.objects.filter(pk=self.warehouse.pk).exists())

    def test_cleanup_ops_deal_stops_on_shared_inventory_lot(self):
        graph = self._create_ops_graph(receipt_quantity=2)
        foreign_order_item = self.order_two.items.get()
        allocate_inventory_to_order_item(
            order_item=foreign_order_item,
            warehouse=self.warehouse,
            quantity=1,
            mode=SaleLineAllocation.STATUS_SHIPPED,
        )

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('cleanup_ops_deal', '6669', '--dry-run', stdout=out)

        output = out.getvalue()
        self.assertIn('shared_inventory_lot', output)
        self.assertTrue(ManagerDeal.objects.filter(pk=graph['deal'].pk).exists())
