from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import override_settings
from django.urls import reverse

from catalog.models import Product
from manager_portal.models import (
    Cargo,
    CargoItem,
    DealActivity,
    InventoryBalance,
    InventoryMovement,
    ManagerDeal,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    Shipment,
)
from manager_portal.services import (
    ensure_manager_deal_for_order,
    import_bitrix_deal_into_operations,
    receive_cargo_item,
    receipt_inventory,
    reserve_order_item_for_manager_deal,
)
from manager_portal.tests.test_manager_portal import ManagerPortalBaseTestCase
from orders.models import Order, OrderItem


@override_settings(
    BITRIX_WEBHOOK_URL='https://portal.example/rest/1/webhook',
    BITRIX_INGEST_TOKEN='bitrix-secret',
    BITRIX_SITE_PRODUCT_ID_PROPERTY_ID=107,
)
class OperationsPortalTests(ManagerPortalBaseTestCase):
    def _bitrix_response(self, result):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'result': result}
        return response

    def _mock_bitrix(self, mock_get, *, deal=None, rows=None, contact=None, catalog_products=None):
        def side_effect(url, params=None, timeout=None):
            if url.endswith('/crm.deal.get.json'):
                return self._bitrix_response(deal or {})
            if url.endswith('/crm.deal.productrows.get.json'):
                return self._bitrix_response(rows or [])
            if url.endswith('/crm.contact.get.json'):
                return self._bitrix_response(contact or {})
            if url.endswith('/catalog.product.get.json'):
                product_id = str((params or {}).get('id') or '')
                payload = (catalog_products or {}).get(product_id, {})
                return self._bitrix_response(payload)
            raise AssertionError(f'Unexpected Bitrix URL: {url}')

        mock_get.side_effect = side_effect

    def _base_deal_payload(self):
        return {
            'ID': '7001',
            'TITLE': 'Bitrix import for ops',
            'CONTACT_ID': '10',
            'OPPORTUNITY': '149990',
            'DATE_CREATE': '2026-05-30T10:15:00+05:00',
            'COMMENTS': 'Оплачено в Bitrix',
        }

    def _base_contact_payload(self):
        return {
            'ID': '10',
            'NAME': 'Иван',
            'LAST_NAME': 'Покупатель',
            'PHONE': [{'VALUE': '+7 912 000-10-10'}],
            'EMAIL': [{'VALUE': 'bitrix-client@example.com'}],
            'ADDRESS_CITY': 'Екатеринбург',
            'ADDRESS': 'ул. Ленина, 10',
        }

    def _prepare_paid_deal(self, *, delivery_type=Order.DELIVERY_PICKUP, pickup_point=None):
        order = self.create_order(
            phone='+7 999 444 55 66',
            email='reserve@example.com',
            first_name='Резерв',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=delivery_type,
            pickup_point=pickup_point,
        )
        deal = ensure_manager_deal_for_order(order)
        deal.responsible_manager = self.staff_user
        deal.prepayment_amount = order.total
        deal.payment_state = ManagerDeal.PAYMENT_STATE_PAID
        deal.save(update_fields=['responsible_manager', 'prepayment_amount', 'payment_state', 'updated_at'])
        return deal, order.items.get()

    def _receive_single_item_to_stock(self, *, deal, order_item):
        purchase = Purchase.objects.create(
            supplier_name='Quest Supplier',
            date=deal.order.created_at.date(),
            status=Purchase.STATUS_ORDERED,
            currency='CNY',
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=order_item.product,
            variant=order_item.variant,
            order_item=order_item,
            quantity=1,
            unit_cost=Decimal('450.00'),
        )
        cargo = Cargo.objects.create(
            cargo_number='CG-OPS-RESERVE-1',
            purchase=purchase,
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
        )
        cargo_item = CargoItem.objects.create(
            cargo=cargo,
            product=order_item.product,
            variant=order_item.variant,
            purchase_item=purchase_item,
            quantity=1,
        )
        receive_cargo_item(
            cargo_item,
            quantity=1,
            warehouse=self.warehouse,
            received_at=date(2026, 6, 1),
            author=self.staff_user,
            comment='Приняли для последующего резерва',
        )
        cargo_item.refresh_from_db()
        purchase_item.refresh_from_db()
        cargo.refresh_from_db()
        return purchase, purchase_item, cargo, cargo_item

    def _reserve_single_item_via_ops(self, *, deal, order_item, quantity=1, comment='Резерв под отгрузку'):
        return self.client.post(
            reverse('operations:deal_reserve_create', kwargs={'pk': deal.pk}),
            {
                'order_item': str(order_item.id),
                'product': str(order_item.product_id),
                'warehouse': str(self.warehouse.id),
                'quantity': str(quantity),
                'comment': comment,
            },
        )

    def _create_shipment_via_ops(self, *, deal):
        return self.client.post(
            reverse('operations:deal_detail', kwargs={'pk': deal.pk}),
            {'action': 'create_shipment'},
        )

    def test_ops_dashboard_is_available_for_staff_operations_user(self):
        self.login_staff()

        response = self.client.get(reverse('operations:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Операторский портал')

    def test_dashboard_groups_deals_by_operation_status(self):
        self.login_staff()
        needs_link_order = self.create_order(
            phone='+7 999 111 22 33',
            email='custom@example.com',
            first_name='Кастом',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        needs_link_order.items.all().delete()
        needs_link_order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Bitrix Custom Set',
            quantity=1,
            price=Decimal('50000.00'),
        )
        needs_link_deal = ensure_manager_deal_for_order(needs_link_order)

        ready_order = self.create_order(
            phone='+7 999 444 22 33',
            email='ready@example.com',
            first_name='Готов',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        ready_deal = ensure_manager_deal_for_order(ready_order)
        ready_deal.responsible_manager = self.staff_user
        ready_deal.prepayment_amount = ready_order.total
        ready_deal.payment_state = ManagerDeal.PAYMENT_STATE_PAID
        ready_deal.save(update_fields=['responsible_manager', 'prepayment_amount', 'payment_state', 'updated_at'])
        self.create_reservation(
            client=self.manager_client,
            linked_order=ready_order,
            source_warehouse=self.warehouse,
            target_warehouse=self.warehouse,
        )
        self.warehouse.inventory_balances.create(product=self.product, variant=self.variant, quantity=3)

        response = self.client.get(reverse('operations:dashboard'))

        self.assertEqual(response.status_code, 200)
        groups = {group['code']: group for group in response.context['dashboard_groups']}
        self.assertIn(needs_link_deal, groups['needs_link_products']['items'])
        self.assertGreaterEqual(groups['needs_link_products']['count'], 1)
        self.assertIn('Готово к отправке', response.content.decode())

    @patch('manager_portal.services.requests.get')
    def test_ops_bitrix_endpoint_imports_deal(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Ops Bitrix Product',
            slug='ops-bitrix-product',
            sku='OPS-BITRIX',
            price=Decimal('149990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-ops-1',
                    'PRODUCT_ID': '501',
                    'PRODUCT_NAME': 'Bitrix synced product',
                    'SKU': 'OPS-BITRIX',
                    'PRICE': '149990',
                    'QUANTITY': '1',
                }
            ],
            catalog_products={'501': {'id': '501', 'property107': str(product.id)}},
        )

        response = self.client.post(
            reverse('operations:bitrix_deal_in_work'),
            {'token': 'bitrix-secret', 'deal_id': '7001'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['manager_deal_id'], ManagerDeal.objects.get(bitrix_deal_id='7001').pk)
        self.assertEqual(response.json()['items_count'], 1)
        self.assertEqual(ManagerDeal.objects.filter(bitrix_deal_id='7001').count(), 1)

    @patch('manager_portal.services.requests.get')
    def test_repeat_import_via_ops_endpoint_does_not_create_duplicates(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Ops Repeat Product',
            slug='ops-repeat-product',
            sku='OPS-REPEAT',
            price=Decimal('99990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-ops-2',
                    'PRODUCT_NAME': product.name,
                    'SKU': product.sku,
                    'PRICE': '99990',
                    'QUANTITY': '1',
                }
            ],
        )

        self.client.post(reverse('operations:bitrix_deal_in_work'), {'token': 'bitrix-secret', 'deal_id': '7001'})
        self.client.post(reverse('operations:bitrix_deal_in_work'), {'token': 'bitrix-secret', 'deal_id': '7001'})

        self.assertEqual(ManagerDeal.objects.filter(bitrix_deal_id='7001').count(), 1)
        self.assertEqual(ManagerDeal.objects.get(bitrix_deal_id='7001').order.items.count(), 1)

    @patch('manager_portal.services.requests.get')
    def test_ops_deals_list_shows_imported_bitrix_deals(self, mock_get):
        self.login_staff()
        product = Product.objects.create(
            category=self.category,
            name='Ops List Product',
            slug='ops-list-product',
            sku='OPS-LIST',
            price=Decimal('88990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[{'ID': 'row-ops-list', 'PRODUCT_NAME': product.name, 'SKU': product.sku, 'PRICE': '88990', 'QUANTITY': '1'}],
        )
        import_bitrix_deal_into_operations('7001')

        response = self.client.get(reverse('operations:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bitrix #7001')
        self.assertContains(response, 'Ops List Product')

    @patch('manager_portal.services.requests.get')
    def test_ops_deal_detail_shows_bitrix_link_and_order_items(self, mock_get):
        self.login_staff()
        product = Product.objects.create(
            category=self.category,
            name='Ops Detail Product',
            slug='ops-detail-product',
            sku='OPS-DETAIL',
            price=Decimal('119990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[{'ID': 'row-ops-detail', 'PRODUCT_NAME': product.name, 'SKU': product.sku, 'PRICE': '119990', 'QUANTITY': '1'}],
        )
        result = import_bitrix_deal_into_operations('7001')

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': result['manager_deal'].pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Открыть в Bitrix')
        self.assertContains(response, 'Ops Detail Product')

    def test_invalid_token_is_rejected_for_ops_endpoint(self):
        response = self.client.post(
            reverse('operations:bitrix_deal_in_work'),
            {'token': 'wrong-token', 'deal_id': '7001'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertJSONEqual(response.content, {'ok': False, 'error': 'Неверный token.'})

    @patch('manager_portal.services.requests.get')
    @override_settings(BITRIX_SITE_PRODUCT_ID_PROPERTY_ID=208)
    def test_bitrix_product_property_links_catalog_order_item_via_ops_endpoint(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Ops Property Product',
            slug='ops-property-product',
            sku='OPS-PROP',
            price=Decimal('99990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-ops-prop',
                    'PRODUCT_ID': '808',
                    'PRODUCT_NAME': 'Property linked product',
                    'PRICE': '99990',
                    'QUANTITY': '1',
                }
            ],
            catalog_products={'808': {'id': '808', 'property208': str(product.id)}},
        )

        response = self.client.post(
            reverse('operations:bitrix_deal_in_work'),
            {'token': 'bitrix-secret', 'deal_id': '7001'},
        )

        self.assertEqual(response.status_code, 200)
        line = ManagerDeal.objects.get(bitrix_deal_id='7001').order.items.get()
        self.assertEqual(line.line_type, OrderItem.LINE_TYPE_CATALOG)
        self.assertEqual(line.product_id, product.id)

    @patch('manager_portal.services.requests.get')
    def test_bitrix_product_without_site_link_stays_custom_order_item(self, mock_get):
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-ops-custom',
                    'PRODUCT_ID': '909',
                    'PRODUCT_NAME': 'Custom only row',
                    'PRICE': '55550',
                    'QUANTITY': '1',
                }
            ],
            catalog_products={'909': {'id': '909', 'property107': '0'}},
        )

        response = self.client.post(
            reverse('operations:bitrix_deal_in_work'),
            {'token': 'bitrix-secret', 'deal_id': '7001'},
        )

        self.assertEqual(response.status_code, 200)
        line = ManagerDeal.objects.get(bitrix_deal_id='7001').order.items.get()
        self.assertEqual(line.line_type, OrderItem.LINE_TYPE_CUSTOM)
        self.assertTrue(line.custom_sku.startswith('bitrix-product-'))

    def test_custom_order_item_can_be_linked_to_catalog_product(self):
        self.login_staff()
        order = self.create_order(
            phone='+7 999 555 44 33',
            email='link@example.com',
            first_name='Связать',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        order.items.all().delete()
        order_item = order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Невязанный товар',
            quantity=1,
            price=Decimal('45000.00'),
        )
        deal = ensure_manager_deal_for_order(order)

        response = self.client.post(
            reverse('operations:deal_detail', kwargs={'pk': deal.pk}),
            {
                'action': 'link_product',
                'item-{}-item_id'.format(order_item.id): str(order_item.id),
                'item-{}-product'.format(order_item.id): str(self.product.id),
                'item-{}-variant'.format(order_item.id): str(self.variant.id),
            },
        )

        self.assertRedirects(response, reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        order_item.refresh_from_db()
        self.assertEqual(order_item.line_type, OrderItem.LINE_TYPE_CATALOG)
        self.assertEqual(order_item.product_id, self.product.id)
        self.assertEqual(order_item.custom_sku, '')
        self.assertEqual(len(order_item.metadata.get('manual_catalog_link_history', [])), 1)
        history_row = order_item.metadata['manual_catalog_link_history'][0]
        self.assertEqual(history_row['to_product_id'], self.product.id)
        self.assertEqual(history_row['to_variant_id'], self.variant.id)
        self.assertEqual(history_row['from_custom_sku'], '')

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})

        self.assertEqual(detail_response.status_code, 200)
        position_row = next(row for row in detail_response.context['position_rows'] if row['item'].id == order_item.id)
        self.assertTrue(position_row['warehouse_actions_enabled'])
        self.assertEqual(position_row['catalog_link_label'], 'Связан с каталогом')

    def test_detail_checklist_marks_missing_phone_and_address(self):
        self.login_staff()
        order = self.create_order(
            phone='',
            email='missing-data@example.com',
            first_name='Получатель',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_COURIER,
        )
        deal = ensure_manager_deal_for_order(order)

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        checklist = {item['code']: item for item in response.context['operation_snapshot']['checklist']}
        self.assertFalse(checklist['delivery']['is_ok'])
        self.assertEqual(checklist['delivery']['status_label'], 'Требует внимания')

    def test_checklist_uses_quantitative_progress_for_partial_deal(self):
        self.login_staff()
        order = self.create_order(
            phone='+7 999 123 45 67',
            email='partial-checklist@example.com',
            first_name='Частичный',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        order.items.create(
            product=self.product_two,
            variant=self.foreign_variant,
            quantity=1,
            price=Decimal('5000.00'),
        )
        order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Custom bundle',
            quantity=1,
            price=Decimal('25000.00'),
        )
        deal = ensure_manager_deal_for_order(order)
        first_line = order.items.order_by('id').first()
        purchase = Purchase.objects.create(
            date=deal.order.created_at.date(),
            supplier_name='Partial Supplier',
            status=Purchase.STATUS_ORDERED,
            currency='CNY',
        )
        PurchaseItem.objects.create(
            purchase=purchase,
            product=first_line.product,
            variant=first_line.variant,
            order_item=first_line,
            quantity=1,
            unit_cost=Decimal('450.00'),
        )

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        checklist = {item['code']: item for item in response.context['operation_snapshot']['checklist']}
        self.assertIn('2/3', checklist['catalog_links']['detail'])
        self.assertIn('1/3', checklist['secured']['detail'])
        self.assertIn('0/3', checklist['reservation']['detail'])

    def test_goods_tab_hides_reserve_debug_without_explicit_debug_flag(self):
        self.login_staff()
        order = self.create_order(
            phone='+7 999 123 45 67',
            email='reserve-debug@example.com',
            first_name='Debug',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Custom bundle',
            quantity=1,
            price=Decimal('25000.00'),
        )
        deal = ensure_manager_deal_for_order(order)

        response = self.client.get(
            reverse('operations:deal_detail', kwargs={'pk': deal.pk}),
            {'tab': 'goods', 'mode': 'advanced'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Reserve debug:')

    def test_delivery_form_updates_order_and_clears_delivery_blockers(self):
        self.login_staff()
        order = self.create_order(
            phone='',
            email='delivery-form@example.com',
            first_name='Получатель',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_COURIER,
        )
        deal = ensure_manager_deal_for_order(order)

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        self.assertContains(detail_response, 'Заполнить доставку')
        self.assertIn('Не указан телефон получателя', detail_response.context['operation_snapshot']['blockers'])
        self.assertIn('Не указан адрес доставки', detail_response.context['operation_snapshot']['blockers'])

        response = self.client.post(
            reverse('operations:deal_delivery_edit', kwargs={'pk': deal.pk}),
            {
                'recipient_name': 'Иван Получатель',
                'recipient_phone': '+7 912 123-45-67',
                'delivery_type': Order.DELIVERY_PICKUP,
                'city_text': 'Екатеринбург',
                'address': 'ул. Ленина, 10',
                'delivery_comment': 'Позвонить за час',
            },
        )

        self.assertRedirects(response, reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        order.refresh_from_db()
        deal.refresh_from_db()
        self.assertEqual(order.recipient_name, 'Иван Получатель')
        self.assertEqual(order.recipient_phone, '+7 912 123-45-67')
        self.assertEqual(order.delivery_type, Order.DELIVERY_PICKUP)
        self.assertEqual(order.city_text, 'Екатеринбург')
        self.assertEqual(order.address, 'ул. Ленина, 10')
        self.assertEqual(order.address_line, 'ул. Ленина, 10')
        self.assertEqual(order.delivery_comment, 'Позвонить за час')
        self.assertEqual(deal.delivery_method, ManagerDeal.DELIVERY_PICKUP)
        self.assertEqual(deal.delivery_to_city, 'Екатеринбург')
        self.assertEqual(deal.shipping_comment, 'Позвонить за час')

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        blockers = detail_response.context['operation_snapshot']['blockers']
        self.assertNotIn('Не указан телефон получателя', blockers)
        self.assertNotIn('Не указан адрес доставки', blockers)
        self.assertEqual(detail_response.context['client_summary']['data_source'], 'Вручную')
        self.assertContains(detail_response, 'Иван Получатель')
        self.assertContains(detail_response, '+7 912 123-45-67')
        self.assertContains(detail_response, 'Самовывоз')
        self.assertContains(detail_response, 'Позвонить за час')

    def test_filled_recipient_phone_and_address_remove_delivery_blockers(self):
        self.login_staff()
        order = self.create_order(
            phone='',
            email='delivery-ready@example.com',
            first_name='Получатель',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_COURIER,
        )
        order.recipient_name = 'Иван Получатель'
        order.recipient_phone = '+7 912 555-44-33'
        order.address = 'ул. Малышева, 15'
        order.address_line = 'ул. Малышева, 15'
        order.save(update_fields=['recipient_name', 'recipient_phone', 'address', 'address_line', 'updated_at'])
        deal = ensure_manager_deal_for_order(order)

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        blockers = response.context['operation_snapshot']['blockers']
        checklist = {item['code']: item for item in response.context['operation_snapshot']['checklist']}
        self.assertNotIn('Не указан телефон получателя', blockers)
        self.assertNotIn('Не указан адрес доставки', blockers)
        self.assertTrue(checklist['delivery']['is_ok'])

    def test_custom_item_blocks_warehouse_actions(self):
        self.login_staff()
        order = self.create_order(
            phone='+7 999 111 22 33',
            email='custom-block@example.com',
            first_name='Кастом',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        order.items.all().delete()
        order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Custom bundle',
            quantity=1,
            price=Decimal('50000.00'),
        )
        deal = ensure_manager_deal_for_order(order)

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})

        self.assertEqual(response.status_code, 200)
        position_row = response.context['position_rows'][0]
        self.assertFalse(position_row['warehouse_actions_enabled'])
        self.assertFalse(position_row['cargo_actions_enabled'])
        self.assertEqual(position_row['warehouse_actions_note'], 'Сначала свяжите товар с каталогом сайта.')
        self.assertEqual(position_row['cargo_actions_note'], 'Сначала свяжите товар с каталогом сайта.')
        self.assertContains(response, 'Связать с товаром сайта')
        self.assertContains(response, 'Сначала свяжите товар с каталогом')

    def test_catalog_item_allows_warehouse_actions(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        position_row = response.context['position_rows'][0]
        self.assertTrue(position_row['warehouse_actions_enabled'])
        self.assertFalse(position_row['cargo_actions_enabled'])
        self.assertEqual(position_row['cargo_actions_note'], 'Сначала создайте закупку.')
        self.assertEqual(position_row['catalog_link_label'], 'Связан с каталогом')

    def test_purchase_form_rejects_custom_order_item_until_linked(self):
        self.login_staff()
        order = self.create_order(
            phone='+7 999 111 22 33',
            email='custom-purchase@example.com',
            first_name='Кастом',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        order.items.all().delete()
        order_item = order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Автосимулятор 360 Racing 6DOF',
            custom_sku='bitrix-product-6669',
            quantity=1,
            price=Decimal('50000.00'),
        )
        deal = ensure_manager_deal_for_order(order)

        response = self.client.get(reverse('operations:purchase_form', kwargs={'pk': deal.pk, 'item_pk': order_item.pk}))

        self.assertRedirects(response, reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        self.assertFalse(PurchaseItem.objects.filter(order_item=order_item).exists())

    def test_purchase_form_in_ops_creates_or_updates_procurement_for_order_item(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        order_item = self.order.items.get()

        response = self.client.post(
            reverse('operations:purchase_form', kwargs={'pk': deal.pk, 'item_pk': order_item.pk}),
            {
                'supplier_name': 'Shenzhen VR Supplier',
                'quantity': '3',
                'unit_cost': '82500.50',
                'currency': 'CNY',
                'status': Purchase.STATUS_ORDERED,
                'comments': 'Согласовали первую закупку',
            },
        )

        self.assertRedirects(response, reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        purchase_item = PurchaseItem.objects.select_related('purchase', 'order_item').get(order_item=order_item)
        self.assertEqual(purchase_item.quantity, 3)
        self.assertEqual(purchase_item.unit_cost, Decimal('82500.50'))
        self.assertEqual(purchase_item.order_item_id, order_item.id)
        self.assertEqual(purchase_item.purchase.supplier_name, 'Shenzhen VR Supplier')
        self.assertEqual(purchase_item.purchase.currency, 'CNY')
        self.assertEqual(purchase_item.purchase.status, Purchase.STATUS_ORDERED)
        self.assertEqual(purchase_item.purchase.comments, 'Согласовали первую закупку')

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'purchases'})

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, 'Shenzhen VR Supplier')
        self.assertContains(detail_response, '82500,50')
        self.assertContains(detail_response, 'CNY')

    def test_purchase_form_in_ops_requires_supplier_name(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        order_item = self.order.items.get()

        response = self.client.post(
            reverse('operations:purchase_form', kwargs={'pk': deal.pk, 'item_pk': order_item.pk}),
            {
                'supplier_name': '',
                'quantity': '3',
                'unit_cost': '82500.50',
                'currency': 'CNY',
                'status': Purchase.STATUS_ORDERED,
                'comments': 'Без поставщика сохранять нельзя',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'supplier_name', 'Обязательное поле.')
        self.assertFalse(PurchaseItem.objects.filter(order_item=order_item).exists())

    def test_purchase_form_in_ops_updates_existing_purchase_fields(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        order_item = self.order.items.get()
        purchase = Purchase.objects.create(
            supplier_name='Old Supplier',
            date=self.order.created_at.date(),
            status=Purchase.STATUS_DRAFT,
            currency='RUB',
            comments='Старый комментарий',
        )
        PurchaseItem.objects.create(
            purchase=purchase,
            product=order_item.product,
            variant=order_item.variant,
            order_item=order_item,
            quantity=1,
            unit_cost=Decimal('100.00'),
        )

        response = self.client.post(
            reverse('operations:purchase_form', kwargs={'pk': deal.pk, 'item_pk': order_item.pk}),
            {
                'supplier_name': 'Updated Supplier',
                'quantity': '4',
                'unit_cost': '910.75',
                'currency': 'CNY',
                'status': Purchase.STATUS_ORDERED,
                'comments': 'Обновили закупку через ops',
            },
        )

        self.assertRedirects(response, reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        purchase.refresh_from_db()
        purchase_item = PurchaseItem.objects.get(order_item=order_item)
        self.assertEqual(purchase.supplier_name, 'Updated Supplier')
        self.assertEqual(purchase.currency, 'CNY')
        self.assertEqual(purchase.status, Purchase.STATUS_ORDERED)
        self.assertEqual(purchase.comments, 'Обновили закупку через ops')
        self.assertEqual(purchase_item.quantity, 4)
        self.assertEqual(purchase_item.unit_cost, Decimal('910.75'))

    def test_create_cargo_via_ops_creates_cargo_and_cargo_item_for_purchase_item(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        order_item = self.order.items.get()
        purchase = Purchase.objects.create(
            supplier_name='Quest Supplier',
            date=self.order.created_at.date(),
            status=Purchase.STATUS_ORDERED,
            currency='CNY',
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=order_item.product,
            variant=order_item.variant,
            order_item=order_item,
            quantity=2,
            unit_cost=Decimal('450.00'),
        )

        response = self.client.post(
            reverse('operations:deal_cargo_create', kwargs={'pk': deal.pk}),
            {
                'purchase_item': str(purchase_item.id),
                'quantity': '2',
                'destination_warehouse': str(self.warehouse.id),
                'eta': '2026-06-15',
                'status': Cargo.STATUS_IN_TRANSIT,
                'comments': 'Отправили первой партией',
                'cargo_number': 'CG-OPS-TEST-1',
            },
        )

        self.assertRedirects(response, reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        cargo = Cargo.objects.get()
        cargo_item = CargoItem.objects.get()
        self.assertEqual(cargo.purchase, purchase)
        self.assertEqual(cargo.destination_warehouse, self.warehouse)
        self.assertEqual(cargo.status, Cargo.STATUS_IN_TRANSIT)
        self.assertEqual(str(cargo.eta), '2026-06-15')
        self.assertEqual(cargo.cargo_number, 'CG-OPS-TEST-1')
        self.assertEqual(cargo.comments, 'Отправили первой партией')
        self.assertEqual(cargo_item.cargo, cargo)
        self.assertEqual(cargo_item.purchase_item, purchase_item)
        self.assertEqual(cargo_item.purchase_item.order_item, order_item)
        self.assertEqual(cargo_item.quantity, 2)

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'cargos'})

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, 'CG-OPS-TEST-1')
        self.assertContains(detail_response, 'В пути')
        self.assertContains(detail_response, '15.06.2026')
        self.assertContains(detail_response, 'Количество 2')
        self.assertContains(detail_response, 'Принято 0')
        self.assertContains(detail_response, 'Принять груз')

    def test_receive_cargo_via_ops_updates_supply_and_marks_cargo_received(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        order_item = self.order.items.get()
        purchase = Purchase.objects.create(
            supplier_name='Quest Supplier',
            date=self.order.created_at.date(),
            status=Purchase.STATUS_ORDERED,
            currency='CNY',
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=order_item.product,
            variant=order_item.variant,
            order_item=order_item,
            quantity=1,
            unit_cost=Decimal('450.00'),
        )
        cargo = Cargo.objects.create(
            cargo_number='CG-OPS-RECEIVE-1',
            purchase=purchase,
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
        )
        cargo_item = CargoItem.objects.create(
            cargo=cargo,
            product=order_item.product,
            variant=order_item.variant,
            purchase_item=purchase_item,
            quantity=1,
        )

        detail_before = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'cargos'})

        self.assertEqual(detail_before.status_code, 200)
        self.assertContains(
            detail_before,
            f'{reverse("operations:deal_cargo_receive", kwargs={"pk": deal.pk})}?item={cargo_item.id}',
        )

        response = self.client.post(
            reverse('operations:deal_cargo_receive', kwargs={'pk': deal.pk}),
            {
                'cargo_item': str(cargo_item.id),
                'quantity': '1',
                'warehouse': str(self.warehouse.id),
                'received_date': '2026-06-01',
                'comment': 'Приняли на основном складе',
            },
        )

        self.assertRedirects(response, reverse('operations:deal_detail', kwargs={'pk': deal.pk}))
        cargo_item.refresh_from_db()
        purchase_item.refresh_from_db()
        cargo.refresh_from_db()
        balance = InventoryBalance.objects.get(
            warehouse=self.warehouse,
            product=order_item.product,
            variant=order_item.variant,
        )
        self.assertEqual(cargo_item.received_quantity, 1)
        self.assertEqual(purchase_item.received_quantity, 1)
        self.assertEqual(str(purchase_item.received_at.date()), '2026-06-01')
        self.assertEqual(cargo.status, Cargo.STATUS_RECEIVED)
        self.assertEqual(balance.quantity, 1)

        detail_after = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})
        cargo_after = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'cargos'})

        self.assertEqual(detail_after.status_code, 200)
        position_row = next(row for row in detail_after.context['position_rows'] if row['item'].id == order_item.id)
        self.assertEqual(position_row['received'], 1)
        self.assertEqual(position_row['available_to_reserve'], 1)
        self.assertEqual(position_row['in_transit'], 0)
        self.assertEqual(position_row['missing'], 0)
        self.assertEqual(position_row['reserve_missing'], 1)
        self.assertEqual(position_row['status_label'], 'Нужно зарезервировать')
        self.assertContains(cargo_after, 'Принят')

    def test_received_stock_can_be_reserved_via_ops_form(self):
        self.login_staff()
        deal, order_item = self._prepare_paid_deal(pickup_point=self.pickup_point)
        _purchase, _purchase_item, cargo, _cargo_item = self._receive_single_item_to_stock(deal=deal, order_item=order_item)

        self.assertTrue(
            InventoryMovement.objects.filter(
                reference_type='cargo',
                reference_id=cargo.id,
                movement_type=InventoryMovement.TYPE_RECEIPT,
            ).exists()
        )

        detail_before = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})

        self.assertEqual(detail_before.status_code, 200)
        self.assertContains(
            detail_before,
            f'{reverse("operations:deal_reserve_create", kwargs={"pk": deal.pk})}?item={order_item.id}',
        )
        reserve_form_response = self.client.get(
            reverse('operations:deal_reserve_create', kwargs={'pk': deal.pk}),
            {'item': order_item.id},
        )
        self.assertEqual(reserve_form_response.status_code, 200)
        self.assertContains(reserve_form_response, 'Создать резерв')

        response = self.client.post(
            reverse('operations:deal_reserve_create', kwargs={'pk': deal.pk}),
            {
                'order_item': str(order_item.id),
                'product': str(order_item.product_id),
                'warehouse': str(self.warehouse.id),
                'quantity': '1',
                'comment': 'Резерв после приемки',
            },
        )

        self.assertRedirects(response, f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=goods')
        reservation_item = ReservationItem.objects.get(order_item=order_item)
        reservation = reservation_item.reservation
        movement = InventoryMovement.objects.get(
            reference_type='reservation',
            reference_id=reservation.id,
            movement_type=InventoryMovement.TYPE_RESERVE,
        )
        self.assertEqual(reservation.manager_deal, deal)
        self.assertEqual(reservation.linked_order, deal.order)
        self.assertEqual(reservation.source_warehouse, self.warehouse)
        self.assertEqual(reservation.status, Reservation.STATUS_ACTIVE)
        self.assertEqual(reservation_item.product, order_item.product)
        self.assertEqual(reservation_item.order_item, order_item)
        self.assertEqual(reservation_item.quantity, 1)
        self.assertEqual(movement.quantity, 1)

    def test_received_cargo_shows_reserve_action_in_ops_card(self):
        self.login_staff()
        deal, order_item = self._prepare_paid_deal(pickup_point=self.pickup_point)
        _purchase, _purchase_item, cargo, _cargo_item = self._receive_single_item_to_stock(deal=deal, order_item=order_item)

        self.assertTrue(
            InventoryMovement.objects.filter(
                reference_type='cargo',
                reference_id=cargo.id,
                movement_type=InventoryMovement.TYPE_RECEIPT,
            ).exists()
        )

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})

        self.assertEqual(response.status_code, 200)
        position_row = next(row for row in response.context['position_rows'] if row['item'].id == order_item.id)
        reserve_actions = [action for action in position_row['actions'] if action['code'] == 'reserve_stock']
        self.assertEqual(position_row['available_to_reserve'], 1)
        self.assertEqual(len(reserve_actions), 1)
        self.assertEqual(
            reserve_actions[0]['url'],
            f'{reverse("operations:deal_reserve_create", kwargs={"pk": deal.pk})}?item={order_item.id}',
        )

    def test_reservation_updates_reserved_quantity_in_ops_card(self):
        self.login_staff()
        deal, order_item = self._prepare_paid_deal(pickup_point=self.pickup_point)
        InventoryBalance.objects.create(warehouse=self.warehouse, product=order_item.product, variant=order_item.variant, quantity=1)

        response = self.client.post(
            reverse('operations:deal_reserve_create', kwargs={'pk': deal.pk}),
            {
                'order_item': str(order_item.id),
                'product': str(order_item.product_id),
                'warehouse': str(self.warehouse.id),
                'quantity': '1',
                'comment': 'Резервируем из свободного остатка',
            },
        )
        self.assertRedirects(response, f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=goods')

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})
        self.assertEqual(detail_response.status_code, 200)
        position_row = next(row for row in detail_response.context['position_rows'] if row['item'].id == order_item.id)
        self.assertEqual(position_row['reserved'], 1)
        self.assertEqual(position_row['missing'], 0)

    def test_full_reservation_marks_position_and_deal_ready_to_ship(self):
        self.login_staff()
        deal, order_item = self._prepare_paid_deal(pickup_point=self.pickup_point)
        InventoryBalance.objects.create(warehouse=self.warehouse, product=order_item.product, variant=order_item.variant, quantity=1)

        self.client.post(
            reverse('operations:deal_reserve_create', kwargs={'pk': deal.pk}),
            {
                'order_item': str(order_item.id),
                'product': str(order_item.product_id),
                'warehouse': str(self.warehouse.id),
                'quantity': '1',
                'comment': 'Полный резерв под отгрузку',
            },
        )

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})

        self.assertEqual(detail_response.status_code, 200)
        position_row = next(row for row in detail_response.context['position_rows'] if row['item'].id == order_item.id)
        self.assertEqual(position_row['status_label'], 'Готово к отгрузке')
        self.assertTrue(any(action['post_action'] == 'create_shipment' for action in position_row['actions'] if action['kind'] == 'post'))
        self.assertEqual(detail_response.context['operation_snapshot']['status_code'], 'ready_to_ship')
        self.assertTrue(detail_response.context['shipment_action_enabled'])

    def test_pending_shipment_can_be_sent_via_ops_and_creates_inventory_write_off(self):
        self.login_staff()
        deal, order_item = self._prepare_paid_deal(pickup_point=self.pickup_point)
        InventoryBalance.objects.create(warehouse=self.warehouse, product=order_item.product, variant=order_item.variant, quantity=1)

        self._reserve_single_item_via_ops(deal=deal, order_item=order_item, comment='Резерв перед отправкой')
        create_response = self._create_shipment_via_ops(deal=deal)
        self.assertRedirects(
            create_response,
            f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments',
        )

        shipment = Shipment.objects.get(manager_deal=deal)
        detail_before = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'shipments'})
        self.assertEqual(detail_before.context['primary_action']['label'], 'Отправить отгрузку')

        response = self.client.post(
            reverse('operations:deal_shipment_dispatch', kwargs={'pk': deal.pk, 'shipment_pk': shipment.pk}),
            {
                'carrier': 'CDEK',
                'tracking_number': 'OPS-TRACK-1001',
                'shipped_at': '2026-06-01',
                'comment': 'Передали в доставку из OPS',
            },
        )

        self.assertRedirects(response, f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments')
        shipment.refresh_from_db()
        order_item.refresh_from_db()
        reservation_item = ReservationItem.objects.get(order_item=order_item)
        balance = InventoryBalance.objects.get(warehouse=self.warehouse, product=order_item.product, variant=order_item.variant)

        self.assertEqual(shipment.status, Shipment.STATUS_SHIPPED)
        self.assertEqual(shipment.delivery_provider_name, 'CDEK')
        self.assertEqual(shipment.tracking_number, 'OPS-TRACK-1001')
        self.assertIsNotNone(shipment.shipped_at)
        self.assertEqual(balance.quantity, 0)
        self.assertEqual(order_item.shipped_quantity, 1)
        self.assertEqual(reservation_item.fulfilled_quantity, 1)
        self.assertTrue(
            InventoryMovement.objects.filter(
                reference_type='shipment',
                reference_id=shipment.id,
                movement_type=InventoryMovement.TYPE_RELEASE,
                quantity=1,
            ).exists()
        )

        goods_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'goods'})
        position_row = next(row for row in goods_response.context['position_rows'] if row['item'].id == order_item.id)
        self.assertEqual(position_row['shipped'], 1)
        self.assertEqual(position_row['status_label'], 'Отгружено')

        shipments_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'shipments'})
        self.assertEqual(shipments_response.context['primary_action']['label'], 'Отметить доставлено')
        self.assertContains(shipments_response, 'OPS-TRACK-1001')
        self.assertContains(shipments_response, 'CDEK')

    def test_shipped_shipment_can_be_marked_delivered_via_ops(self):
        self.login_staff()
        deal, order_item = self._prepare_paid_deal(pickup_point=self.pickup_point)
        InventoryBalance.objects.create(warehouse=self.warehouse, product=order_item.product, variant=order_item.variant, quantity=1)

        self._reserve_single_item_via_ops(deal=deal, order_item=order_item)
        self._create_shipment_via_ops(deal=deal)
        shipment = Shipment.objects.get(manager_deal=deal)
        self.client.post(
            reverse('operations:deal_shipment_dispatch', kwargs={'pk': deal.pk, 'shipment_pk': shipment.pk}),
            {
                'carrier': 'Boxberry',
                'tracking_number': 'OPS-TRACK-1002',
                'shipped_at': '2026-06-01',
                'comment': 'Уехало к клиенту',
            },
        )

        response = self.client.post(
            reverse('operations:deal_detail', kwargs={'pk': deal.pk}),
            {'action': 'deliver_shipment', 'shipment_id': str(shipment.id)},
        )

        self.assertRedirects(response, f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments')
        shipment.refresh_from_db()
        deal.refresh_from_db()

        self.assertEqual(shipment.status, Shipment.STATUS_DELIVERED)
        self.assertIsNotNone(shipment.delivered_at)
        self.assertEqual(deal.case_status, ManagerDeal.CASE_STATUS_COMPLETED)
        self.assertEqual(deal.delivery_status, ManagerDeal.DELIVERY_STATUS_DELIVERED)
        self.assertEqual(deal.shipment_status, ManagerDeal.SHIPMENT_DELIVERED)
        self.assertEqual(deal.fulfillment_status, ManagerDeal.FULFILLMENT_STATUS_FULFILLED)
        self.assertEqual(deal.next_step_code, ManagerDeal.NEXT_STEP_COMPLETED)

        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'shipments'})
        self.assertEqual(detail_response.context['primary_action']['label'], 'Сделка исполнена')
        self.assertEqual(detail_response.context['operation_snapshot']['status_code'], 'completed')
        self.assertNotContains(detail_response, 'Создать закупку')
        self.assertNotContains(detail_response, 'Создать груз')
        self.assertNotContains(detail_response, 'Создать отгрузку')

    def test_delivered_deal_does_not_show_reserve_attention_for_fully_shipped_positions(self):
        self.login_staff()
        order = self.create_order(
            phone='+7 999 777 66 55',
            email='delivered-reserve@example.com',
            first_name='Доставлен',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
        )
        order.items.create(
            product=self.product_two,
            quantity=1,
            price=Decimal('5000.00'),
        )
        order.items.create(
            product=self.product,
            quantity=1,
            price=Decimal('100000.00'),
        )
        deal = ensure_manager_deal_for_order(order)
        deal.responsible_manager = self.staff_user
        deal.prepayment_amount = order.total
        deal.payment_state = ManagerDeal.PAYMENT_STATE_PAID
        deal.save(update_fields=['responsible_manager', 'prepayment_amount', 'payment_state', 'updated_at'])

        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=2, author=self.staff_user)
        receipt_inventory(warehouse=self.warehouse, product=self.product_two, quantity=1, author=self.staff_user)

        for order_item in order.items.order_by('id'):
            reserve_order_item_for_manager_deal(
                deal=deal,
                order_item=order_item,
                warehouse=self.warehouse,
                quantity=1,
                comment='Резервируем перед полной отгрузкой',
                actor=self.staff_user,
            )

        create_response = self._create_shipment_via_ops(deal=deal)
        self.assertRedirects(
            create_response,
            f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments',
        )
        shipment = Shipment.objects.get(manager_deal=deal)

        dispatch_response = self.client.post(
            reverse('operations:deal_shipment_dispatch', kwargs={'pk': deal.pk, 'shipment_pk': shipment.pk}),
            {
                'carrier': 'CDEK',
                'tracking_number': 'OPS-TRACK-DELIVERED-RESERVE',
                'shipped_at': '2026-06-01',
                'comment': 'Полностью отгружено по всем строкам',
            },
        )
        self.assertRedirects(
            dispatch_response,
            f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments',
        )

        deliver_response = self.client.post(
            reverse('operations:deal_detail', kwargs={'pk': deal.pk}),
            {'action': 'deliver_shipment', 'shipment_id': str(shipment.id)},
        )
        self.assertRedirects(
            deliver_response,
            f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments',
        )

        deal.refresh_from_db()
        detail_response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'shipments'})

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(deal.case_status, ManagerDeal.CASE_STATUS_COMPLETED)
        self.assertEqual(detail_response.context['operation_snapshot']['status_code'], 'completed')
        checklist = {item['code']: item for item in detail_response.context['operation_snapshot']['checklist']}
        self.assertFalse(checklist['reservation']['needs_attention'])
        self.assertNotEqual(checklist['reservation']['status_label'], 'Требует внимания')
        self.assertEqual(checklist['reservation']['status_label'], 'OK')
        self.assertIn('3/3', checklist['reservation']['detail'])
        self.assertNotIn(
            'reserve_stock',
            {action['code'] for action in detail_response.context['operation_snapshot']['next_actions']},
        )

    def test_delivered_shipments_remove_deal_from_active_ops_dashboard(self):
        self.login_staff()
        deal, order_item = self._prepare_paid_deal(pickup_point=self.pickup_point)
        InventoryBalance.objects.create(warehouse=self.warehouse, product=order_item.product, variant=order_item.variant, quantity=1)

        self._reserve_single_item_via_ops(deal=deal, order_item=order_item)
        self._create_shipment_via_ops(deal=deal)
        shipment = Shipment.objects.get(manager_deal=deal)
        self.client.post(
            reverse('operations:deal_shipment_dispatch', kwargs={'pk': deal.pk, 'shipment_pk': shipment.pk}),
            {
                'carrier': 'CDEK',
                'tracking_number': 'OPS-TRACK-1003',
                'shipped_at': '2026-06-01',
                'comment': 'Ушло к клиенту',
            },
        )
        self.client.post(
            reverse('operations:deal_detail', kwargs={'pk': deal.pk}),
            {'action': 'deliver_shipment', 'shipment_id': str(shipment.id)},
        )

        deal.refresh_from_db()
        self.assertEqual(deal.case_status, ManagerDeal.CASE_STATUS_COMPLETED)
        self.assertFalse(
            ManagerDeal.objects.exclude(
                case_status__in=[ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED]
            ).filter(pk=deal.pk).exists()
        )

    def test_create_cargo_via_ops_requires_eta_for_non_created_status(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        order_item = self.order.items.get()
        purchase = Purchase.objects.create(
            supplier_name='Quest Supplier',
            date=self.order.created_at.date(),
            status=Purchase.STATUS_ORDERED,
            currency='CNY',
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=order_item.product,
            variant=order_item.variant,
            order_item=order_item,
            quantity=2,
            unit_cost=Decimal('450.00'),
        )

        response = self.client.post(
            reverse('operations:deal_cargo_create', kwargs={'pk': deal.pk}),
            {
                'purchase_item': str(purchase_item.id),
                'quantity': '2',
                'destination_warehouse': str(self.warehouse.id),
                'eta': '',
                'status': Cargo.STATUS_IN_TRANSIT,
                'comments': 'ETA обязателен',
                'cargo_number': 'CG-OPS-TEST-ETA',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'],
            'eta',
            'Укажите ETA для груза, если он уже не в статусе "Создан".',
        )
        self.assertFalse(Cargo.objects.exists())

    def test_next_action_prioritizes_linking_before_other_issues(self):
        self.login_staff()
        order = self.create_order(
            phone='',
            email='priority@example.com',
            first_name='Приоритет',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_COURIER,
        )
        order.items.all().delete()
        order.items.create(
            line_type=OrderItem.LINE_TYPE_CUSTOM,
            product_name='Невязанный товар',
            quantity=1,
            price=Decimal('65000.00'),
        )
        deal = ensure_manager_deal_for_order(order)

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['operation_snapshot']['action_text'], 'Связать 1 товар с каталогом')
        self.assertEqual(
            response.context['operation_snapshot']['primary_blocker'],
            'Не все товары связаны с каталогом сайта',
        )

    def test_detail_does_not_render_crm_sales_stages(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.deal_status = ManagerDeal.DEAL_STATUS_NEW_REQUEST
        deal.case_status = ManagerDeal.CASE_STATUS_IN_PROGRESS
        deal.save(update_fields=['deal_status', 'case_status', 'updated_at'])

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, deal.get_deal_status_display())
        self.assertNotContains(response, 'Коммерческое предложение')
        self.assertNotContains(response, 'КП отправлено')
        self.assertNotContains(response, 'Решение клиента')
        self.assertNotContains(response, 'Не отвечает')

    def test_dashboard_shows_kpi_counters(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.responsible_manager = None
        deal.save(update_fields=['responsible_manager', 'updated_at'])

        purchase = Purchase.objects.create(
            supplier_name='Transit Supplier',
            date=self.order.created_at.date(),
            status=Purchase.STATUS_ORDERED,
            currency='CNY',
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            variant=self.variant,
            order_item=self.order.items.get(),
            quantity=1,
            unit_cost=Decimal('100.00'),
        )
        Cargo.objects.create(
            purchase=purchase,
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
            eta=None,
        )
        Cargo.objects.create(
            purchase=purchase,
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
            eta=self.order.created_at.date() - timedelta(days=1),
        )
        for cargo in Cargo.objects.filter(purchase=purchase):
            CargoItem.objects.create(
                cargo=cargo,
                product=self.product,
                variant=self.variant,
                purchase_item=purchase_item,
                quantity=1,
            )

        response = self.client.get(reverse('operations:dashboard'))

        self.assertEqual(response.status_code, 200)
        kpis = {row['code']: row['value'] for row in response.context['dashboard_kpis']}
        self.assertGreaterEqual(kpis['active_deals'], 1)
        self.assertGreaterEqual(kpis['deals_without_assignee'], 1)
        self.assertGreaterEqual(kpis['cargos_in_transit'], 2)
        self.assertGreaterEqual(kpis['cargos_without_eta'], 1)

    def test_detail_history_is_trimmed_by_default_and_expandable(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        for index in range(9):
            DealActivity.objects.create(
                manager_deal=deal,
                event_type='operations.delivery_updated',
                source=DealActivity.SOURCE_USER,
                payload={'index': index},
            )

        response = self.client.get(reverse('operations:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['history_rows']), 7)
        self.assertGreaterEqual(response.context['history_rows_total'], 9)
        self.assertContains(response, 'Показать всю историю')

        expanded = self.client.get(
            reverse('operations:deal_detail', kwargs={'pk': deal.pk}),
            {'tab': 'history', 'history': 'all'},
        )

        self.assertEqual(expanded.status_code, 200)
        self.assertEqual(len(expanded.context['history_rows']), response.context['history_rows_total'])

    def test_ops_history_page_is_available(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        DealActivity.objects.create(
            manager_deal=deal,
            event_type='operations.delivery_updated',
            source=DealActivity.SOURCE_USER,
        )

        response = self.client.get(reverse('operations:history'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'История исполнения')
        self.assertContains(response, 'Обновлены данные доставки')
