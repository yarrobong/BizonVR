from decimal import Decimal

from django.urls import reverse

from orders.models import OrderItem

from manager_portal.models import Shipment, ShipmentItem
from manager_portal.services import (
    create_or_update_shipment_for_order,
    ensure_finance_deal_for_manager_deal,
    ensure_manager_deal_for_order,
    recalculate_finance_deal_totals,
    sync_finance_deal_lines_from_manager_deal,
)
from manager_portal.tests.test_manager_portal import ManagerPortalBaseTestCase


class ManagerPortalRegressionTests(ManagerPortalBaseTestCase):
    def test_sync_finance_lines_removes_stale_order_item_projection_rows(self):
        # Guards against deleted order lines lingering in finance projections and inflating revenue.
        base_item = self.order.items.order_by('id').first()
        extra_item = self.order.items.create(product=self.product_two, quantity=2, price=Decimal('5000.00'))
        deal = ensure_manager_deal_for_order(self.order)
        finance_deal = ensure_finance_deal_for_manager_deal(deal, actor=self.staff_user)

        self.assertCountEqual(
            list(finance_deal.lines.order_by('sort_order').values_list('order_item_id', flat=True)),
            [base_item.id, extra_item.id],
        )

        extra_item.delete()

        sync_finance_deal_lines_from_manager_deal(finance_deal)
        recalculate_finance_deal_totals(finance_deal, sync_lines=False)
        finance_deal.refresh_from_db()

        self.assertEqual(list(finance_deal.lines.values_list('order_item_id', flat=True)), [base_item.id])
        self.assertEqual(finance_deal.lines.count(), 1)
        self.assertEqual(finance_deal.revenue, Decimal('100000.00'))

    def test_create_or_update_shipment_keeps_unreconciled_historical_shipment_immutable(self):
        # Guards against rebuilding already shipped legacy documents and silently appending new lines.
        shipment = Shipment.objects.create(
            order=self.order,
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
            status=Shipment.STATUS_SHIPPED,
            tracking_number='LEGACY-1',
        )
        item = ShipmentItem.objects.create(
            shipment=shipment,
            order_item=self.order.items.get(),
            product=self.product,
            quantity=1,
        )
        extra_item = self.order.items.create(product=self.product_two, quantity=1, price=Decimal('5000.00'))

        updated = create_or_update_shipment_for_order(
            self.order,
            shipment=shipment,
            tracking_number='LEGACY-2',
        )

        updated.refresh_from_db()
        self.assertEqual(updated.pk, shipment.pk)
        self.assertEqual(updated.status, Shipment.STATUS_SHIPPED)
        self.assertEqual(updated.tracking_number, 'LEGACY-2')
        self.assertEqual(updated.items.count(), 1)
        self.assertTrue(updated.items.filter(pk=item.pk, quantity=1).exists())
        self.assertFalse(updated.items.filter(order_item=extra_item).exists())

    def test_legacy_deal_search_route_redirects_to_deal_list(self):
        # Guards against the removed legacy search screen coming back as a dead-end route.
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_search'), follow=True)

        self.assertRedirects(response, reverse('manager_portal:deal_list'))
        self.assertContains(response, 'Глобальный поиск перенесен в верхнюю панель shell')

    def test_legacy_deal_search_route_preserves_query_in_deal_list_redirect(self):
        # Guards against losing the operator query string during the legacy-to-canonical redirect.
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_search'), {'q': 'Quest'}, follow=True)

        self.assertRedirects(response, f"{reverse('manager_portal:deal_list')}?q=Quest")
        self.assertContains(response, 'Глобальный поиск перенесен в верхнюю панель shell')

    def test_deal_detail_excludes_custom_lines_from_uncovered_counts(self):
        # Guards against custom non-stock lines being counted as uncovered logistics debt.
        self.login_staff()
        self.order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Индивидуальный комплект клиента',
            quantity=1,
            price=Decimal('25000.00'),
        )
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['logistics_summary']['coverage_detail'], 'Не обеспечено строк: 1.')
