from io import StringIO
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from catalog.models import Product
from integrations.models import SiteLeadRequest
from orders.models import Order, OrderItem

from manager_portal.models import Cargo, CargoItem, ManagerDeal, Purchase, PurchaseItem, Reservation, ReservationItem, Shipment, ShipmentItem
from manager_portal.services import (
    import_bitrix_deal_into_operations,
    link_manual_order_item_to_catalog_product,
    sync_bitrix_deal_into_operations,
)
from manager_portal.tests.test_manager_portal import ManagerPortalBaseTestCase


@override_settings(
    BITRIX_WEBHOOK_URL='https://portal.example/rest/1/webhook',
    BITRIX_INGEST_TOKEN='bitrix-secret',
)
class BitrixDealImportTests(ManagerPortalBaseTestCase):
    def _bitrix_response(self, result):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'result': result}
        return response

    def _mock_bitrix(
        self,
        mock_get,
        *,
        deal=None,
        rows=None,
        contact=None,
        company=None,
        catalog_products=None,
        contact_error=None,
        company_error=None,
    ):
        def side_effect(url, params=None, timeout=None):
            if url.endswith('/crm.deal.get.json'):
                return self._bitrix_response(deal or {})
            if url.endswith('/crm.deal.productrows.get.json'):
                return self._bitrix_response(rows or [])
            if url.endswith('/crm.contact.get.json'):
                if contact_error is not None:
                    raise contact_error
                return self._bitrix_response(contact or {})
            if url.endswith('/crm.company.get.json'):
                if company_error is not None:
                    raise company_error
                return self._bitrix_response(company or {})
            if url.endswith('/catalog.product.get.json'):
                product_id = str((params or {}).get('id') or '')
                payload = (catalog_products or {}).get(product_id, {})
                if isinstance(payload, Exception):
                    raise payload
                return self._bitrix_response(payload)
            raise AssertionError(f'Unexpected Bitrix URL: {url}')

        mock_get.side_effect = side_effect

    def _base_deal_payload(self):
        return {
            'ID': '6669',
            'TITLE': 'Meta Quest 3 для клиента',
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

    @patch('manager_portal.services.requests.get')
    def test_import_creates_order(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Meta Quest 3 Import',
            slug='meta-quest-3-import',
            sku='BITRIX-MQ3',
            price=Decimal('149990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-1',
                    'PRODUCT_NAME': product.name,
                    'SKU': product.sku,
                    'PRICE': '149990',
                    'QUANTITY': '1',
                }
            ],
        )

        initial_orders = Order.objects.count()
        result = import_bitrix_deal_into_operations('6669')

        self.assertEqual(Order.objects.count(), initial_orders + 1)
        self.assertEqual(result['order'].status, Order.STATUS_CONFIRMED)
        self.assertEqual(result['order'].payment_status, Order.PAYMENT_STATUS_PAID)
        self.assertEqual(result['manager_deal'].bitrix_deal_id, '6669')

    @patch('manager_portal.services.requests.get')
    def test_import_creates_order_item(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Pico 4 Ultra Site Product',
            slug='pico-4-ultra-site-product',
            sku='LOCAL-PICO4',
            price=Decimal('99990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-2',
                    'PRODUCT_ID': '501',
                    'PRODUCT_NAME': 'Bitrix synced Pico',
                    'SKU': 'BITRIX-PICO4',
                    'PRICE': '99990',
                    'QUANTITY': '2',
                }
            ],
            catalog_products={
                '501': {
                    'id': '501',
                    'property107': str(product.id),
                }
            },
        )

        result = import_bitrix_deal_into_operations('6669')
        line = result['order'].items.get()

        self.assertEqual(line.line_type, OrderItem.LINE_TYPE_CATALOG)
        self.assertEqual(line.product_id, product.id)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.metadata.get('bitrix_row_key'), 'row-2')

    @patch('manager_portal.services.requests.get')
    def test_repeat_import_does_not_create_duplicates(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Quest 3S Import',
            slug='quest-3s-import',
            sku='BITRIX-Q3S',
            price=Decimal('89990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-3',
                    'PRODUCT_NAME': product.name,
                    'SKU': product.sku,
                    'PRICE': '89990',
                    'QUANTITY': '1',
                }
            ],
        )

        import_bitrix_deal_into_operations('6669')
        import_bitrix_deal_into_operations('6669')

        self.assertEqual(ManagerDeal.objects.filter(bitrix_deal_id='6669').count(), 1)
        deal = ManagerDeal.objects.get(bitrix_deal_id='6669')
        self.assertTrue(Order.objects.filter(pk=deal.order_id).exists())
        self.assertEqual(deal.order.items.count(), 1)

    @patch('manager_portal.services.requests.get')
    def test_import_reuses_existing_website_order_linked_by_site_request(self, mock_get):
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-site-order',
                    'PRODUCT_NAME': self.product.name,
                    'SKU': self.product.sku,
                    'PRICE': '1000',
                    'QUANTITY': '1',
                }
            ],
        )
        initial_order_count = Order.objects.count()
        order = Order.objects.create(
            status=Order.STATUS_NEW,
            total=Decimal('1000.00'),
            payment_method=Order.PAYMENT_METHOD_MANAGER_CONTACT,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            phone='+7 912 000-10-10',
            email='bitrix-client@example.com',
            first_name='Иван',
            recipient_name='Иван Покупатель',
            recipient_phone='+7 912 000-10-10',
            city_text='Екатеринбург',
            address_line='ул. Ленина, 10',
        )
        existing_item = OrderItem.objects.create(
            order=order,
            line_type=OrderItem.LINE_TYPE_CATALOG,
            product=self.product,
            quantity=1,
            price=Decimal('1000.00'),
            product_name=self.product.name,
        )
        SiteLeadRequest.objects.create(
            source_type=SiteLeadRequest.SOURCE_CHECKOUT,
            order=order,
            phone=order.phone,
            email=order.email,
            page_url='http://testserver/orders/checkout/',
            spam_status=SiteLeadRequest.SPAM_STATUS_CLEAN,
            sync_status=SiteLeadRequest.SYNC_STATUS_SYNCED,
            bitrix_deal_id='6669',
        )

        result = sync_bitrix_deal_into_operations('6669')

        self.assertEqual(result['order'].pk, order.pk)
        self.assertEqual(Order.objects.count(), initial_order_count + 1)
        self.assertEqual(order.items.count(), 1)
        existing_item.refresh_from_db()
        self.assertEqual(existing_item.metadata.get('bitrix_row_key'), 'row-site-order')

    @patch('manager_portal.services.requests.get')
    def test_repeat_import_preserves_manual_catalog_link_and_related_supply_entities(self, mock_get):
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-manual-protect',
                    'PRODUCT_ID': '777',
                    'PRODUCT_NAME': 'Несвязанный VR-набор',
                    'PRICE': '120000',
                    'QUANTITY': '1',
                }
            ],
            catalog_products={'777': {'id': '777', 'property107': '0'}},
        )

        first_result = sync_bitrix_deal_into_operations('6669')
        order_item = first_result['order'].items.get()
        linked_item = link_manual_order_item_to_catalog_product(
            order_item,
            product=self.product,
            variant=self.variant,
            actor=self.staff_user,
        )
        purchase = Purchase.objects.create(
            date=first_result['order'].created_at.date(),
            supplier_name='Quest Supplier',
            currency='CNY',
            status=Purchase.STATUS_ORDERED,
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            variant=self.variant,
            order_item=linked_item,
            quantity=1,
            unit_cost=Decimal('450.00'),
        )
        cargo = Cargo.objects.create(
            cargo_number='CG-BITRIX-1',
            purchase=purchase,
            status=Cargo.STATUS_CREATED,
            destination_warehouse=self.warehouse,
        )
        cargo_item = CargoItem.objects.create(
            cargo=cargo,
            product=self.product,
            variant=self.variant,
            purchase_item=purchase_item,
            quantity=1,
        )
        reservation = Reservation.objects.create(
            manager_deal=first_result['manager_deal'],
            client=first_result['manager_client'],
            linked_order=first_result['order'],
            status=Reservation.STATUS_ACTIVE,
            source_type=Reservation.SOURCE_WAREHOUSE,
            source_warehouse=self.warehouse,
            target_warehouse=self.warehouse,
            comments='Ручной резерв для regression-теста',
        )
        reservation_item = ReservationItem.objects.create(
            reservation=reservation,
            order_item=linked_item,
            product=self.product,
            variant=self.variant,
            quantity=1,
        )
        shipment = Shipment.objects.create(
            order=first_result['order'],
            client=first_result['manager_client'],
            manager_deal=first_result['manager_deal'],
            reservation=reservation,
            source_warehouse=self.warehouse,
            target_warehouse=self.warehouse,
            status=Shipment.STATUS_DRAFT,
        )
        shipment_item = ShipmentItem.objects.create(
            shipment=shipment,
            order_item=linked_item,
            reservation_item=reservation_item,
            product=self.product,
            variant=self.variant,
            quantity=1,
        )

        second_result = sync_bitrix_deal_into_operations('6669')
        linked_item.refresh_from_db()
        purchase_item.refresh_from_db()
        cargo_item.refresh_from_db()
        reservation_item.refresh_from_db()
        shipment_item.refresh_from_db()

        self.assertEqual(linked_item.line_type, OrderItem.LINE_TYPE_CATALOG)
        self.assertEqual(linked_item.product_id, self.product.id)
        self.assertEqual(linked_item.custom_sku, '')
        self.assertTrue(linked_item.metadata.get('manual_link'))
        self.assertEqual(linked_item.metadata.get('manual_product_link', {}).get('product_id'), self.product.id)
        self.assertEqual(second_result['order'].items.get().pk, linked_item.pk)
        self.assertEqual(purchase_item.order_item_id, linked_item.id)
        self.assertEqual(cargo_item.purchase_item_id, purchase_item.id)
        self.assertEqual(reservation_item.order_item_id, linked_item.id)
        self.assertEqual(shipment_item.order_item_id, linked_item.id)

    def test_invalid_token_is_rejected(self):
        response = self.client.post(
            reverse('manager_portal:bitrix_deal_in_work'),
            {'token': 'wrong-token', 'deal_id': '6669'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertJSONEqual(response.content, {'ok': False, 'error': 'Неверный token.'})

    @patch('manager_portal.services.requests.get')
    def test_unknown_catalog_product_becomes_custom_order_item(self, mock_get):
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-4',
                    'PRODUCT_ID': '777',
                    'PRODUCT_NAME': 'Несвязанный VR-набор',
                    'SKU': 'UNKNOWN-SKU',
                    'PRICE': '120000',
                    'QUANTITY': '1',
                }
            ],
            catalog_products={
                '777': {
                    'id': '777',
                    'property107': '0',
                }
            },
        )

        result = import_bitrix_deal_into_operations('6669')
        line = result['order'].items.get()

        self.assertEqual(line.line_type, OrderItem.LINE_TYPE_CUSTOM)
        self.assertIsNone(line.product_id)
        self.assertEqual(line.product_name, 'Несвязанный VR-набор')
        self.assertEqual(line.custom_sku, 'UNKNOWN-SKU')

    @patch('manager_portal.services.requests.get')
    def test_contact_error_does_not_abort_import_and_is_idempotent(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Bitrix Contact Fallback Import',
            slug='bitrix-contact-fallback-import',
            sku='BITRIX-FALLBACK',
            price=Decimal('79990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact_error=requests.RequestException('contact endpoint failed'),
            rows=[
                {
                    'ID': 'row-5',
                    'PRODUCT_NAME': product.name,
                    'SKU': product.sku,
                    'PRICE': '79990',
                    'QUANTITY': '1',
                }
            ],
        )

        initial_order_count = Order.objects.count()
        initial_item_count = OrderItem.objects.count()
        first_result = import_bitrix_deal_into_operations('6669')
        second_result = import_bitrix_deal_into_operations('6669')

        self.assertEqual(Order.objects.count(), initial_order_count + 1)
        self.assertEqual(OrderItem.objects.count(), initial_item_count + 1)
        self.assertEqual(ManagerDeal.objects.filter(bitrix_deal_id='6669').count(), 1)
        self.assertEqual(first_result['order'].recipient_name, 'Meta Quest 3 для клиента')
        self.assertEqual(first_result['manager_client'].name, 'Meta Quest 3 для клиента')
        self.assertEqual(first_result['manager_client'].phone, '')
        self.assertEqual(first_result['manager_client'].email, '')
        self.assertTrue(first_result['warnings'])
        self.assertIn('Bitrix контакт #10 не импортирован', first_result['warnings'][0])
        self.assertEqual(second_result['order'].items.count(), 1)

    @patch('manager_portal.services.requests.get')
    def test_management_command_prints_warning_and_completes(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Bitrix Command Warning Import',
            slug='bitrix-command-warning-import',
            sku='BITRIX-CMD',
            price=Decimal('55990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact_error=requests.RequestException('contact endpoint failed'),
            rows=[
                {
                    'ID': 'row-6',
                    'PRODUCT_NAME': product.name,
                    'SKU': product.sku,
                    'PRICE': '55990',
                    'QUANTITY': '1',
                }
            ],
        )

        out = StringIO()
        call_command('import_bitrix_deal', '6669', stdout=out)
        output = out.getvalue()

        self.assertIn('Bitrix контакт #10 не импортирован', output)
        self.assertIn('Импорт завершен:', output)

    @override_settings(BITRIX_SITE_PRODUCT_ID_PROPERTY_ID=208)
    @patch('manager_portal.services.requests.get')
    def test_service_command_and_ops_endpoint_share_same_import_path(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Shared Import Product',
            slug='shared-import-product',
            sku='SHARED-IMPORT',
            price=Decimal('65990.00'),
            is_active=True,
        )
        self._mock_bitrix(
            mock_get,
            deal=self._base_deal_payload(),
            contact=self._base_contact_payload(),
            rows=[
                {
                    'ID': 'row-shared-path',
                    'PRODUCT_ID': '808',
                    'PRODUCT_NAME': 'Property linked product',
                    'PRICE': '65990',
                    'QUANTITY': '1',
                }
            ],
            catalog_products={'808': {'id': '808', 'property208': str(product.id)}},
        )

        service_result = sync_bitrix_deal_into_operations('6669')
        service_line = service_result['order'].items.get()
        self.assertEqual(service_line.line_type, OrderItem.LINE_TYPE_CATALOG)
        self.assertEqual(service_line.product_id, product.id)

        out = StringIO()
        call_command('import_bitrix_deal', '6669', stdout=out)
        command_output = out.getvalue()
        service_line.refresh_from_db()
        self.assertEqual(service_line.line_type, OrderItem.LINE_TYPE_CATALOG)
        self.assertEqual(service_line.product_id, product.id)
        self.assertIn('Импорт завершен:', command_output)

        response = self.client.post(
            reverse('operations:bitrix_deal_in_work'),
            {'token': 'bitrix-secret', 'deal_id': '6669'},
        )
        self.assertEqual(response.status_code, 200)
        service_line.refresh_from_db()
        self.assertEqual(service_line.line_type, OrderItem.LINE_TYPE_CATALOG)
        self.assertEqual(service_line.product_id, product.id)
        self.assertEqual(ManagerDeal.objects.filter(bitrix_deal_id='6669').count(), 1)

    @override_settings(
        BITRIX_FIELD_CITY='UF_CRM_1759839094222',
        BITRIX_FIELD_CLIENT_REQUEST='UF_CRM_1760611537498',
        BITRIX_FIELD_DELIVERY_ADDRESS='UF_CRM_1780009222676',
        BITRIX_FIELD_RECIPIENT_NAME='UF_CRM_1780009289695',
        BITRIX_FIELD_RECIPIENT_PHONE='UF_CRM_1780009362170',
    )
    @patch('manager_portal.services.requests.get')
    def test_inspect_management_command_prints_mapped_fields(self, mock_get):
        deal_payload = self._base_deal_payload()
        deal_payload['CONTACT_ID'] = '0'
        deal_payload['COMPANY_ID'] = None
        deal_payload['UF_CRM_1759839094222'] = 'Тест'
        deal_payload['UF_CRM_1760611537498'] = 'Запрос клиента'
        deal_payload['UF_CRM_1780009222676'] = '67575'
        deal_payload['UF_CRM_1780009289695'] = 'тест'
        deal_payload['UF_CRM_1780009362170'] = '+799999999999'
        self._mock_bitrix(
            mock_get,
            deal=deal_payload,
            rows=[
                {
                    'ID': 'row-inspect-1',
                    'PRODUCT_NAME': 'Inspect line',
                    'PRICE': '1000',
                    'QUANTITY': '1',
                }
            ],
        )

        out = StringIO()
        call_command('inspect_bitrix_deal', '6669', stdout=out)
        output = out.getvalue()

        self.assertIn('raw CONTACT_ID: 0', output)
        self.assertIn('raw COMPANY_ID: None', output)
        self.assertIn('mapped city: Тест', output)
        self.assertIn('mapped recipient_name: тест', output)
        self.assertIn('mapped recipient_phone: +799999999999', output)
        self.assertIn('mapped delivery_address: 67575', output)
        self.assertIn('mapped client_request: Запрос клиента', output)
        self.assertIn('product rows count: 1', output)

    @override_settings(
        BITRIX_FIELD_CITY='UF_CRM_1759839094222',
        BITRIX_FIELD_CLIENT_REQUEST='UF_CRM_1760611537498',
        BITRIX_FIELD_DELIVERY_ADDRESS='UF_CRM_1780009222676',
        BITRIX_FIELD_RECIPIENT_NAME='UF_CRM_1780009289695',
        BITRIX_FIELD_RECIPIENT_PHONE='UF_CRM_1780009362170',
    )
    @patch('manager_portal.services.requests.get')
    def test_contact_id_zero_uses_mapped_deal_fields_for_order_and_manager_client(self, mock_get):
        product = Product.objects.create(
            category=self.category,
            name='Bitrix Zero Contact Import',
            slug='bitrix-zero-contact-import',
            sku='BITRIX-ZERO-CONTACT',
            price=Decimal('45990.00'),
            is_active=True,
        )
        deal_payload = self._base_deal_payload()
        deal_payload['CONTACT_ID'] = '0'
        deal_payload['COMPANY_ID'] = None
        deal_payload['UF_CRM_1759839094222'] = 'Тест'
        deal_payload['UF_CRM_1760611537498'] = 'Запрос клиента'
        deal_payload['UF_CRM_1780009222676'] = '67575'
        deal_payload['UF_CRM_1780009289695'] = 'тест'
        deal_payload['UF_CRM_1780009362170'] = '+799999999999'
        self._mock_bitrix(
            mock_get,
            deal=deal_payload,
            rows=[
                {
                    'ID': 'row-7',
                    'PRODUCT_NAME': product.name,
                    'SKU': product.sku,
                    'PRICE': '45990',
                    'QUANTITY': '1',
                }
            ],
        )

        result = import_bitrix_deal_into_operations('6669')
        order = result['order']
        manager_client = result['manager_client']

        self.assertEqual(order.items.count(), 1)
        self.assertEqual(ManagerDeal.objects.filter(bitrix_deal_id='6669').count(), 1)
        self.assertEqual(result.get('warnings', []), [])
        self.assertEqual(order.recipient_name, 'тест')
        self.assertEqual(order.recipient_phone, '799999999999')
        self.assertEqual(order.phone, '799999999999')
        self.assertEqual(order.address, '67575')
        self.assertEqual(order.address_line, '67575')
        self.assertEqual(order.city_text, 'Тест')
        self.assertIn('Запрос клиента: Запрос клиента', order.comment)
        self.assertEqual(order.delivery_comment, 'Запрос клиента: Запрос клиента')
        self.assertEqual(manager_client.name, 'тест')
        self.assertEqual(manager_client.phone, '799999999999')
        self.assertEqual(manager_client.address, '67575')
        self.assertIn('Запрос клиента: Запрос клиента', manager_client.comments)
        self.assertIn('Bitrix deal id: 6669', manager_client.comments)
        called_urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertEqual(len(called_urls), 2)
        self.assertTrue(any(url.endswith('/crm.deal.get.json') for url in called_urls))
        self.assertTrue(any(url.endswith('/crm.deal.productrows.get.json') for url in called_urls))
        self.assertFalse(any(url.endswith('/crm.contact.get.json') for url in called_urls))
        self.assertFalse(any(url.endswith('/crm.company.get.json') for url in called_urls))
