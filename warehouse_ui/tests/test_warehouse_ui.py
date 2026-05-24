from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from manager_portal.models import Cargo, CargoItem, InventoryBalance, InventoryLot, InventoryMovement, Reservation, ReservationItem
from manager_portal.services import receipt_inventory, sync_public_stock_for_warehouse
from manager_portal.tests.test_manager_portal import ManagerPortalBaseTestCase
from warehouse_ui.models import WarehouseTransfer


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
class WarehouseUiViewTests(ManagerPortalBaseTestCase):
    def setUp(self):
        super().setUp()
        self.login_staff()

    def test_staff_can_open_warehouse_screen_and_non_staff_cannot(self):
        response = self.client.get(reverse('admin:warehouse_ui_index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BizonVR Warehouse')

        self.client.force_login(self.user)
        denied_response = self.client.get(reverse('admin:warehouse_ui_index'))
        self.assertIn(denied_response.status_code, {302, 403})

    def test_matrix_context_uses_real_aggregates(self):
        receipt_inventory(
            warehouse=self.warehouse,
            product=self.product,
            quantity=5,
            author=self.staff_user,
            comment='seed',
            reference_type='test',
        )
        reservation = self.create_reservation(
            source_type=Reservation.SOURCE_WAREHOUSE,
            source_warehouse=self.warehouse,
        )
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=2)
        cargo = Cargo.objects.create(
            purchase=None,
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
            comments='incoming',
        )
        CargoItem.objects.create(cargo=cargo, product=self.product, quantity=4, received_quantity=1)
        sync_public_stock_for_warehouse(self.warehouse)

        response = self.client.get(reverse('admin:warehouse_ui_matrix'))

        self.assertEqual(response.status_code, 200)
        rows = response.context['matrix']['rows']
        row = next(item for item in rows if item['product_id'] == self.product.id and item['variant_id'] is None)
        self.assertEqual(row['totals']['on_hand'], 5)
        self.assertEqual(row['totals']['reserved'], 2)
        self.assertEqual(row['totals']['available'], 3)
        self.assertEqual(row['totals']['inbound'], 3)

    def test_receipt_action_updates_balance_and_public_stock(self):
        response = self.client.post(
            reverse('admin:warehouse_ui_receipt_action'),
            {
                'sku_key': f'{self.product.id}:0',
                'product': self.product.id,
                'warehouse': self.warehouse.id,
                'quantity': 4,
                'unit_cost': '99000.00',
                'comment': 'new stock',
            },
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        balance = InventoryBalance.objects.get(warehouse=self.warehouse, product=self.product, variant__isnull=True)
        self.assertEqual(balance.quantity, 4)
        stock = self.pickup_point.stocks.get(product=self.product, variant__isnull=True)
        self.assertEqual(stock.quantity, 4)

    def test_adjustment_action_writes_fifo_and_adjustment_movement(self):
        receipt_inventory(
            warehouse=self.warehouse,
            product=self.product,
            quantity=5,
            unit_cost=Decimal('100.00'),
            author=self.staff_user,
            comment='seed',
            reference_type='test',
        )

        response = self.client.post(
            reverse('admin:warehouse_ui_adjustment_action'),
            {
                'sku_key': f'{self.product.id}:0',
                'product': self.product.id,
                'warehouse': self.warehouse.id,
                'quantity_delta': -2,
                'comment': 'manual shrink',
            },
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        balance = InventoryBalance.objects.get(warehouse=self.warehouse, product=self.product, variant__isnull=True)
        self.assertEqual(balance.quantity, 3)
        lot = InventoryLot.objects.get(warehouse=self.warehouse, product=self.product, variant__isnull=True)
        self.assertEqual(lot.remaining_qty, 3)
        self.assertTrue(
            InventoryMovement.objects.filter(
                warehouse=self.warehouse,
                product=self.product,
                movement_type=InventoryMovement.TYPE_ADJUSTMENT,
                quantity=2,
            ).exists()
        )

    def test_transfer_action_creates_audit_document_and_balances(self):
        receipt_inventory(
            warehouse=self.warehouse,
            product=self.product,
            quantity=5,
            unit_cost=Decimal('123.45'),
            author=self.staff_user,
            comment='seed',
            reference_type='test',
        )

        response = self.client.post(
            reverse('admin:warehouse_ui_transfer_action'),
            {
                'sku_key': f'{self.product.id}:0',
                'product': self.product.id,
                'source_warehouse': self.warehouse.id,
                'target_warehouse': self.other_warehouse.id,
                'quantity': 2,
                'comment': 'move to branch',
            },
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            InventoryBalance.objects.get(warehouse=self.warehouse, product=self.product, variant__isnull=True).quantity,
            3,
        )
        self.assertEqual(
            InventoryBalance.objects.get(warehouse=self.other_warehouse, product=self.product, variant__isnull=True).quantity,
            2,
        )
        transfer = WarehouseTransfer.objects.get(source_warehouse=self.warehouse, target_warehouse=self.other_warehouse)
        self.assertEqual(transfer.lines.count(), 1)
        self.assertTrue(
            InventoryMovement.objects.filter(
                warehouse=self.warehouse,
                product=self.product,
                movement_type=InventoryMovement.TYPE_TRANSFER_OUT,
                reference_id=transfer.id,
            ).exists()
        )
        self.assertTrue(
            InventoryMovement.objects.filter(
                warehouse=self.other_warehouse,
                product=self.product,
                movement_type=InventoryMovement.TYPE_TRANSFER_IN,
                reference_id=transfer.id,
            ).exists()
        )
