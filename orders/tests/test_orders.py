"""Базовые тесты заказов (Фаза 6)."""
from decimal import Decimal
import json
from io import StringIO

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings, tag
from django.urls import reverse
from django.utils import timezone
from unittest.mock import Mock, patch

from accounts.models import NotificationPreference, Profile
from catalog.models import CartItem, CatalogSection, Category, City, GamePack, GamePackEntry, GamePackItem, GamePackServiceEntry, PickupPoint, Product, ProductGameMetadata, ProductStock, Service
from config.legal_docs import LEGAL_BUNDLE_VERSION
from config.utils.spam_protection import check_spam_submission
from manager_portal.models import ManagerClient, ManagerDeal, SaleLineAllocation
from payments.models import Payment

from accounts.tests.factories import create_user
from catalog.tests.factories import create_category, create_game_pack, create_product
from integrations.models import SiteLeadRequest
from orders.forms import CheckoutForm, PurchaseRequestForm
from orders.models import Order, OrderItem, OrderNotificationLog, PromoCode, PurchaseRequest
from orders.services import send_order_event_notifications, sync_order_state_side_effects
from orders.tests.factories import create_order, create_promocode

User = get_user_model()


class OrderViewsTest(TestCase):
    """Список заказов доступен только авторизованным."""

    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')

    def setUp(self):
        cache.clear()

    def test_order_list_requires_login(self):
        resp = self.client.get(reverse('orders:order_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))

    def test_order_list_authenticated_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('orders:order_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Фильтр меняет только список заказов')


@override_settings(RATELIMIT_ENABLE=False)
class CheckoutTest(TestCase):
    """Checkout создаёт заказ и очищает корзину (Фаза 6)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')
        cls.category = create_category(name='Тест', slug='test')
        cls.city = City.objects.create(name='Москва', slug='msk-checkout')
        cls.pickup_point = PickupPoint.objects.create(city=cls.city, name='Основной ПВЗ')
        cls.product = create_product(
            category=cls.category,
            name='Товар',
            slug='product',
            price=Decimal('100.00'),
            is_active=True,
        )
        cls.product_second = create_product(
            category=cls.category,
            name='Товар 2',
            slug='product-2',
            price=Decimal('200.00'),
            is_active=True,
        )
        ProductStock.objects.create(product=cls.product, pickup_point=cls.pickup_point, quantity=10)
        ProductStock.objects.create(product=cls.product_second, pickup_point=cls.pickup_point, quantity=10)
        cls.promo = create_promocode(code='BIZON500', discount_amount=Decimal('50.00'))

    def _checkout_payload(self, **overrides):
        payload = {
            'promo_code': '',
            'first_name': 'Иван Иванов',
            'last_name': '',
            'phone': '+7 999 123 45 67',
            'email': 'client@example.com',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'contact_handle': '',
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'city_text': '',
            'address_line': '',
            'delivery_comment': '',
            'cdek_office_snapshot_raw': json.dumps(self._office_snapshot()),
            'cdek_tariff_snapshot_raw': json.dumps(self._tariff_snapshot()),
            'recipient_is_customer': 'on',
            'payment_method': Order.PAYMENT_METHOD_MANAGER_CONTACT,
            'comment': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
            'business_company_name': '',
            'business_checking_account': '',
            'business_inn': '',
            'business_kpp': '',
            'business_bank_name': '',
            'business_bik': '',
            'business_correspondent_account': '',
            'business_phone': '',
            'business_telegram': '',
            'business_whatsapp': '',
            'website': '',
            'form_started_at': str(int(timezone.now().timestamp()) - 5),
        }
        payload.update(overrides)
        return payload

    def _office_snapshot(self, **overrides):
        payload = {
            'city_code': 44,
            'city': 'Москва',
            'type': 'PVZ',
            'postal_code': '125009',
            'country_code': 'RU',
            'have_cashless': True,
            'have_cash': False,
            'allowed_cod': True,
            'is_dressing_room': False,
            'code': 'MSK201',
            'name': 'ПВЗ СДЭК Тверская',
            'address': 'Москва, ул. Тверская, 10',
            'work_time': 'Пн-Вс 10:00-20:00',
            'location': [37.605, 55.757],
        }
        payload.update(overrides)
        return payload

    def _tariff_snapshot(self, **overrides):
        payload = {
            'tariff_code': 136,
            'tariff_name': 'Посылка склад-склад',
            'tariff_description': 'Доставка до ПВЗ',
            'delivery_mode': 1,
            'period_min': 2,
            'period_max': 4,
            'delivery_sum': 0,
        }
        payload.update(overrides)
        return payload

    def _bitrix_response(self, result):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'result': result}
        return response

    def _mock_bitrix_site_intake(
        self,
        mock_post,
        *,
        duplicate_contact_id='',
        contact_add_result='101',
        deal_add_result='202',
        catalog_product_id='',
        fail_on=None,
        captured=None,
    ):
        captured = captured if captured is not None else []

        def side_effect(url, data=None, timeout=None):
            if fail_on and fail_on in url:
                raise requests.RequestException('bitrix down')
            captured.append({'url': url, 'data': data})
            if url.endswith('/crm.duplicate.findbycomm.json'):
                result = {'CONTACT': [duplicate_contact_id]} if duplicate_contact_id else {'CONTACT': []}
                return self._bitrix_response(result)
            if url.endswith('/crm.contact.update.json'):
                return self._bitrix_response(True)
            if url.endswith('/crm.contact.add.json'):
                return self._bitrix_response(contact_add_result)
            if url.endswith('/crm.deal.add.json'):
                return self._bitrix_response(deal_add_result)
            if url.endswith('/crm.deal.productrows.set.json'):
                return self._bitrix_response(True)
            if url.endswith('/catalog.product.list.json'):
                return self._bitrix_response([{'id': catalog_product_id}] if catalog_product_id else [])
            raise AssertionError(f'Unexpected Bitrix URL: {url}')

        mock_post.side_effect = side_effect
        return captured

    def _set_buy_now_items(self, items):
        session = self.client.session
        session['buy_now_checkout'] = {'items': items}
        session.save()

    def _set_session_cart(self, items):
        session = self.client.session
        session['cart_items'] = items
        session.save()

    def _set_checkout_promo(self, *, cart=None, buy_now=None):
        session = self.client.session
        payload = {}
        if cart:
            payload['cart'] = cart
        if buy_now:
            payload['buy_now'] = buy_now
        if payload:
            session['checkout_applied_promos'] = payload
        else:
            session.pop('checkout_applied_promos', None)
        session.save()

    def test_checkout_available_for_guest(self):
        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Оформление заявки')
        self.assertContains(resp, 'Корзина пуста')
        self.assertNotContains(resp, 'Еще товары')
        self.assertNotContains(resp, 'checkout_cdek_widget')

    def test_checkout_get_authenticated_returns_200(self):
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.force_login(self.user)
        self.client.post(add_url, {'quantity': 1})
        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Оформление заявки')
        self.assertContains(resp, 'cdek-selection-empty')
        self.assertContains(resp, 'cdek-widget-modal')
        self.assertContains(resp, 'cdek-osm-map')
        self.assertContains(resp, 'cdek-city-search-input')
        self.assertContains(resp, 'Выбрать ПВЗ СДЭК')
        self.assertContains(resp, 'Скидка к заказу')
        self.assertContains(resp, 'Введите промокод')
        self.assertContains(resp, 'OpenStreetMap')
        self.assertContains(resp, 'checkout_cdek_widget')
        self.assertNotContains(resp, 'CDEKWidget')
        self.assertNotContains(resp, '<label for="id_city_text"', html=False)
        self.assertNotContains(resp, '<label for="id_address_line"', html=False)
        self.assertNotContains(resp, 'Еще товары')

    def test_checkout_promo_endpoint_applies_valid_code_and_updates_summary(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 2})

        response = self.client.post(
            reverse('orders:checkout_promo'),
            {
                'checkout_mode': '',
                'promo_action': 'apply',
                'promo_code_input': 'BIZON500',
            },
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['checkout_applied_promos']['cart'], 'BIZON500')
        self.assertContains(response, 'Промокод применён')
        self.assertContains(response, 'Скидка (BIZON500)')
        self.assertContains(response, '−50 ₽')
        self.assertContains(response, '50 ₽')

    def test_checkout_promo_endpoint_rejects_invalid_code(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout_promo'),
            {
                'checkout_mode': '',
                'promo_action': 'apply',
                'promo_code_input': 'NOPE',
            },
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('checkout_applied_promos', self.client.session)
        self.assertContains(response, 'Промокод не найден или недействителен.')

    def test_checkout_promo_endpoint_removes_applied_code(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        self._set_checkout_promo(cart='BIZON500')

        response = self.client.post(
            reverse('orders:checkout_promo'),
            {
                'checkout_mode': '',
                'promo_action': 'remove',
            },
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('checkout_applied_promos', self.client.session)
        self.assertContains(response, 'Введите промокод')
        self.assertNotContains(response, 'Промокод применён')

    def test_buy_now_checkout_get_uses_draft_instead_of_regular_cart(self):
        self._set_session_cart([{
            'product_id': self.product.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product.name,
            'price': 100.0,
            'quantity': 1,
            'image_url': '',
            'subtotal': 100.0,
        }])
        self._set_buy_now_items([{
            'product_id': self.product_second.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product_second.name,
            'price': 200.0,
            'quantity': 1,
            'image_url': '',
            'subtotal': 200.0,
        }])

        resp = self.client.get(reverse('orders:checkout'), {'mode': 'buy_now'})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['cart_items']), 1)
        self.assertEqual(resp.context['cart_items'][0]['product_id'], self.product_second.pk)
        self.assertTrue(resp.context['is_buy_now_checkout'])

    def test_checkout_creates_order_and_clears_cart(self):
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.force_login(self.user)
        self.client.post(add_url, {'quantity': 2})
        url = reverse('orders:checkout')
        resp = self.client.post(url, self._checkout_payload(promo_code='BIZON500'))
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.first()
        self.assertIsNotNone(order)
        self.assertEqual(resp.url, reverse('orders:order_created', kwargs={'order_id': order.pk}))
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.total, Decimal('200.00'))
        self.assertEqual(order.promo_discount, Decimal('50.00'))
        self.assertEqual(order.total_to_pay, Decimal('150.00'))
        self.assertEqual(order.phone, '+7 999 123 45 67')
        self.assertEqual(order.city_text, 'Москва')
        self.assertEqual(order.postal_code, '125009')
        self.assertEqual(order.address_line, 'MSK201 — ПВЗ СДЭК Тверская, Москва, ул. Тверская, 10')
        self.assertEqual(order.cdek_office_code, 'MSK201')
        self.assertEqual(order.cdek_office_address, 'Москва, ул. Тверская, 10')
        self.assertEqual(order.cdek_office_snapshot['name'], 'ПВЗ СДЭК Тверская')
        self.assertEqual(order.cdek_tariff_snapshot['tariff_code'], 136)
        self.assertEqual(order.payment_method, Order.PAYMENT_METHOD_MANAGER_CONTACT)
        self.assertEqual(order.email, 'client@example.com')
        self.assertEqual(order.contact_channel, Order.CONTACT_CHANNEL_CALL)
        self.assertEqual(order.contact_handle, '')
        self.assertEqual(order.delivery_type, Order.DELIVERY_CDEK_PVZ)
        self.assertEqual(order.delivery_cost, Decimal('0.00'))
        self.assertEqual(order.legal_docs_version, LEGAL_BUNDLE_VERSION)
        self.assertIsNotNone(order.legal_accepted_at)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().quantity, 2)
        self.assertEqual(self.client.session.get('cart_items', []), [])
        self.assertEqual(PurchaseRequest.objects.count(), 0)
        self.assertEqual(Payment.objects.filter(order=order).count(), 0)

    def test_checkout_creates_custom_game_pack_and_service_lines(self):
        game = Product.objects.create(
            category=self.product.category,
            name='Командная VR игра',
            slug='team-vr-game',
            price=Decimal('1000.00'),
            is_active=True,
        )
        ProductGameMetadata.objects.create(product=game, devices='Quest', genres='PvP', min_players=2, max_players=6)
        service = Service.objects.create(
            name='Инструкция персоналу',
            price=Decimal('2500.00'),
            service_kind=Service.KIND_STAFF_TRAINING,
            is_vr_club_service=True,
            is_active=True,
        )
        session = self.client.session
        session['cart_items'] = [
            {
                'product_id': None,
                'variant_id': None,
                'game_pack_id': None,
                'service_id': None,
                'name': 'Индивидуальный комплект игр для VR-клуба',
                'price': 1000.0,
                'quantity': 1,
                'subtotal': 1000.0,
                'purchase_mode': 'stock',
                'line_type': 'custom_game_pack',
                'custom_key': 'custom-games-test',
                'custom_snapshot': {'custom_key': 'custom-games-test', 'games': [{'id': game.pk, 'name': game.name}]},
            },
            {
                'product_id': None,
                'variant_id': None,
                'game_pack_id': None,
                'service_id': service.pk,
                'name': service.name,
                'price': 2500.0,
                'quantity': 1,
                'subtotal': 2500.0,
                'purchase_mode': 'stock',
                'line_type': 'service',
                'custom_key': '',
                'custom_snapshot': {'service_kind': service.service_kind},
            },
        ]
        session.save()

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.latest('id')
        self.assertEqual(order.items.count(), 2)
        names = set(order.items.values_list('product_name', flat=True))
        self.assertIn('Индивидуальный комплект игр для VR-клуба', names)
        self.assertIn(service.name, names)
        custom_line = order.items.get(product_name='Индивидуальный комплект игр для VR-клуба')
        self.assertEqual(custom_line.line_type, OrderItem.LINE_TYPE_CUSTOM)
        self.assertEqual(custom_line.metadata['custom_key'], 'custom-games-test')

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    @tag('slow')
    def test_checkout_sends_crm_email_after_creating_order(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(comment='Хочу уточнить доставку'),
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        crm_message = next(message for message in mail.outbox if message.to == ['crm@example.com'])
        self.assertEqual(crm_message.reply_to, ['client@example.com'])
        self.assertEqual(crm_message.subject, 'Заявка с сайта BizonVR: +7 999 123 45 67 — Иван Иванов')
        self.assertIn('Тип формы: Checkout', crm_message.body)
        self.assertIn('Город: Москва', crm_message.body)
        self.assertIn('Товар/услуга: Товар', crm_message.body)
        self.assertIn('Страница: http://testserver/orders/checkout/', crm_message.body)
        self.assertIn('Комментарий:\n', crm_message.body)
        self.assertEqual(order.items.count(), 1)

    def test_checkout_spam_redirects_to_success_without_creating_order(self):
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.post(add_url, {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(website='spam.example'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Заявка отправлена')
        self.assertEqual(Order.objects.count(), 0)
        self.assertTrue(self.client.session.get('cart_items'))
        self.assertEqual(SiteLeadRequest.objects.count(), 1)
        self.assertEqual(SiteLeadRequest.objects.get().spam_status, SiteLeadRequest.SPAM_STATUS_SPAM)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    @tag('slow')
    def test_checkout_spam_does_not_send_crm_email(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(website='spam.example'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_checkout_blocks_searchregister_spam_before_order_and_email(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(
                first_name='Craig Gonsalves',
                email='domains@search-bizonvr.ru',
                comment='Greetings feature bizonvr.ru in GoogleSearchIndex https://searchregister.info',
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Заявка отправлена')
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SiteLeadRequest.objects.count(), 1)
        self.assertEqual(SiteLeadRequest.objects.get().sync_status, SiteLeadRequest.SYNC_STATUS_SKIPPED)

    @override_settings(BITRIX_WEBHOOK_URL='https://portal.example/rest/1/webhook', BITRIX_SITE_REQUESTS_ENABLED=True)
    @patch('integrations.bitrix_site_requests.requests.post')
    def test_checkout_keeps_failed_site_request_when_bitrix_is_unavailable(self, mock_post):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        self._mock_bitrix_site_intake(mock_post, fail_on='/crm.contact.add.json')

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        site_request = SiteLeadRequest.objects.get(order=order)
        self.assertEqual(site_request.sync_status, SiteLeadRequest.SYNC_STATUS_FAILED)
        self.assertIn('Не удалось выполнить запрос Bitrix', site_request.sync_error)

    @override_settings(BITRIX_WEBHOOK_URL='https://portal.example/rest/1/webhook', BITRIX_SITE_REQUESTS_ENABLED=True)
    @patch('integrations.bitrix_site_requests.requests.post')
    def test_retry_command_resends_failed_site_requests(self, mock_post):
        site_request = SiteLeadRequest.objects.create(
            source_type=SiteLeadRequest.SOURCE_CONTACTS,
            name='Иван',
            phone='+7 999 123 45 67',
            email='client@example.com',
            message='Нужна консультация',
            page_url='http://testserver/contacts/',
            spam_status=SiteLeadRequest.SPAM_STATUS_CLEAN,
            sync_status=SiteLeadRequest.SYNC_STATUS_FAILED,
            sync_error='timeout',
        )
        self._mock_bitrix_site_intake(mock_post, duplicate_contact_id='701', deal_add_result='702')

        stdout = StringIO()
        call_command('sync_site_requests_to_bitrix', stdout=stdout)

        site_request.refresh_from_db()
        self.assertEqual(site_request.sync_status, SiteLeadRequest.SYNC_STATUS_SYNCED)
        self.assertEqual(site_request.bitrix_contact_id, '701')
        self.assertEqual(site_request.bitrix_deal_id, '702')
        self.assertIn('Processed: 1, synced: 1, failed: 0', stdout.getvalue())

    @override_settings(BITRIX_WEBHOOK_URL='https://portal.example/rest/1/webhook', BITRIX_SITE_REQUESTS_ENABLED=True)
    @patch('integrations.bitrix_site_requests.requests.post')
    def test_duplicate_contact_lookup_reuses_existing_bitrix_contact(self, mock_post):
        site_request = SiteLeadRequest.objects.create(
            source_type=SiteLeadRequest.SOURCE_CONTACTS,
            name='Иван',
            phone='+7 999 123 45 67',
            email='client@example.com',
            message='Нужна консультация',
            page_url='http://testserver/contacts/',
            spam_status=SiteLeadRequest.SPAM_STATUS_CLEAN,
            sync_status=SiteLeadRequest.SYNC_STATUS_PENDING,
        )
        captured = self._mock_bitrix_site_intake(mock_post, duplicate_contact_id='900', deal_add_result='901')

        from integrations.bitrix_site_requests import send_site_request_to_bitrix

        send_site_request_to_bitrix(site_request)

        self.assertTrue(any(call['url'].endswith('/crm.contact.update.json') for call in captured))
        self.assertFalse(any(call['url'].endswith('/crm.contact.add.json') for call in captured))
        site_request.refresh_from_db()
        self.assertEqual(site_request.bitrix_contact_id, '900')

    def test_guest_checkout_creates_guest_order_and_access_token(self):
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.post(add_url, {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertIsNone(order.user)
        self.assertTrue(order.guest_access_token)
        self.assertIn('access=', response.url)
        self.assertTrue(response.url.startswith(reverse('orders:order_created', kwargs={'order_id': order.pk})))

    def test_buy_now_checkout_creates_guest_order_and_preserves_regular_cart(self):
        self._set_session_cart([{
            'product_id': self.product.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product.name,
            'price': 100.0,
            'quantity': 1,
            'image_url': '',
            'subtotal': 100.0,
        }])
        self._set_buy_now_items([{
            'product_id': self.product_second.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product_second.name,
            'price': 200.0,
            'quantity': 1,
            'image_url': '',
            'subtotal': 200.0,
        }])

        response = self.client.post(f"{reverse('orders:checkout')}?mode=buy_now", self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertIsNone(order.user)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().product, self.product_second)
        self.assertEqual(len(self.client.session.get('cart_items', [])), 1)
        self.assertNotIn('buy_now_checkout', self.client.session)

    def test_checkout_uses_applied_session_promo_when_creating_order(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 2})
        self._set_checkout_promo(cart='BIZON500')

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.promo_code, self.promo)
        self.assertEqual(order.promo_discount, Decimal('50.00'))
        self.assertEqual(order.total_to_pay, Decimal('150.00'))
        self.assertNotIn('checkout_applied_promos', self.client.session)

    def test_buy_now_checkout_uses_applied_promo_for_its_source(self):
        self._set_session_cart([{
            'product_id': self.product.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product.name,
            'price': 100.0,
            'quantity': 1,
            'image_url': '',
            'subtotal': 100.0,
        }])
        self._set_buy_now_items([{
            'product_id': self.product_second.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product_second.name,
            'price': 200.0,
            'quantity': 1,
            'image_url': '',
            'subtotal': 200.0,
        }])
        self._set_checkout_promo(buy_now='BIZON500')

        response = self.client.post(f"{reverse('orders:checkout')}?mode=buy_now", self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.items.first().product, self.product_second)
        self.assertEqual(order.promo_code, self.promo)
        self.assertEqual(order.promo_discount, Decimal('50.00'))
        self.assertNotIn('checkout_applied_promos', self.client.session)

    def test_checkout_submit_rejects_stale_applied_promo(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        self._set_checkout_promo(cart='BIZON500')
        self.promo.is_active = False
        self.promo.save(update_fields=['is_active'])

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Промокод больше недействителен.')
        self.assertEqual(Order.objects.count(), 0)
        self.assertNotIn('checkout_applied_promos', self.client.session)

    def test_buy_now_checkout_creates_authenticated_order_and_preserves_regular_cart(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        self._set_buy_now_items([{
            'product_id': self.product_second.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product_second.name,
            'price': 200.0,
            'quantity': 1,
            'image_url': '',
            'subtotal': 200.0,
        }])

        response = self.client.post(f"{reverse('orders:checkout')}?mode=buy_now", self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().product, self.product_second)
        self.assertTrue(CartItem.objects.filter(user=self.user, product=self.product).exists())
        self.assertNotIn('buy_now_checkout', self.client.session)

    def test_add_to_cart_blocks_when_stock_missing_and_order_on_request_disabled(self):
        ProductStock.objects.filter(product=self.product).delete()
        self.product.allow_order_on_request = False
        self.product.save(update_fields=['allow_order_on_request'])
        self.client.force_login(self.user)
        resp = self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            CartItem.objects.filter(user=self.user, product=self.product).exists(),
            msg='Недоступный без заказа под заказ товар не должен попадать в корзину.',
        )

        checkout_resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(checkout_resp.status_code, 302)
        self.assertEqual(checkout_resp.url, reverse('orders:checkout'))
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_blocks_stale_cart_item_when_stock_missing_and_order_on_request_disabled(self):
        ProductStock.objects.filter(product=self.product).delete()
        self.product.allow_order_on_request = False
        self.product.save(update_fields=['allow_order_on_request'])
        self.client.force_login(self.user)
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)

        resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'В заявке не осталось доступных позиций для оформления.')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_marks_item_as_on_request_when_stock_missing_with_on_request_price(self):
        ProductStock.objects.filter(product=self.product).delete()
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price_on_request'])
        self.client.force_login(self.user)
        self.client.post(
            reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}),
            {'quantity': 1, 'purchase_mode': 'on_request'},
        )

        resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertTrue(order.items.get().is_on_request)
        self.assertEqual(order.items.get().price, Decimal('80.00'))

    def test_add_to_cart_blocks_when_in_stock_price_missing_even_if_stock_exists(self):
        self.product.price = None
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price', 'price_on_request'])
        self.client.force_login(self.user)

        resp = self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(CartItem.objects.filter(user=self.user, product=self.product).exists())

    def test_checkout_blocks_stale_stock_item_when_in_stock_price_missing(self):
        self.product.price = None
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price', 'price_on_request'])
        self.client.force_login(self.user)
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)

        resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'В заявке не осталось доступных позиций для оформления.')
        self.assertEqual(Order.objects.count(), 0)

    @override_settings(BITRIX_WEBHOOK_URL='https://portal.example/rest/1/webhook', BITRIX_SITE_REQUESTS_ENABLED=True)
    @patch('integrations.bitrix_site_requests.requests.post')
    def test_checkout_creates_site_lead_request_and_bitrix_deal(self, mock_post):
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price_on_request'])
        self.client.force_login(self.user)
        self.client.post(
            reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}),
            {'quantity': 1, 'purchase_mode': 'on_request'},
        )
        captured = self._mock_bitrix_site_intake(mock_post, catalog_product_id='555')

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        site_request = SiteLeadRequest.objects.get(order=order)
        self.assertEqual(site_request.source_type, SiteLeadRequest.SOURCE_CHECKOUT)
        self.assertEqual(site_request.sync_status, SiteLeadRequest.SYNC_STATUS_SYNCED)
        self.assertEqual(site_request.bitrix_deal_id, '202')
        self.assertFalse(ManagerClient.objects.filter(orders=order).exists())
        self.assertFalse(hasattr(order, 'manager_deal'))
        product_rows_call = next(call for call in captured if call['url'].endswith('/crm.deal.productrows.set.json'))
        rows = product_rows_call['data']['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['PRODUCT_ID'], '555')
        self.assertEqual(rows[0]['QUANTITY'], 1)
        self.assertEqual(rows[0]['PRICE'], '80.00')

    @patch('orders.views.checkout.sync_order_state_side_effects', side_effect=RuntimeError('manager workflow unavailable'))
    def test_checkout_succeeds_when_manager_workflow_fails(self, sync_side_effects):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        sync_side_effects.assert_called_once()

    def test_checkout_forces_manager_contact_payment_method(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(
                payment_method=Order.PAYMENT_METHOD_INVOICE,
            ),
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.payment_method, Order.PAYMENT_METHOD_MANAGER_CONTACT)
        self.assertFalse(hasattr(order, 'manager_deal'))

    def test_checkout_test_mode_creates_paid_order(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        with self.settings(TEST_ORDER_NO_PAYMENT=True):
            resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Order.objects.get().payment_status, Order.PAYMENT_STATUS_PAID)

    def test_checkout_preserves_public_email(self):
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price_on_request'])
        self.client.post(
            reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}),
            {'quantity': 1, 'purchase_mode': 'on_request'},
        )

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload(email='client@example.com'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.get().email, 'client@example.com')

    def test_checkout_infers_telegram_contact_from_username(self):
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price_on_request'])
        self.client.post(
            reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}),
            {'quantity': 1, 'purchase_mode': 'on_request'},
        )

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(contact_handle='@bizonvr'),
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.contact_channel, Order.CONTACT_CHANNEL_TELEGRAM)
        self.assertEqual(order.contact_handle, '@bizonvr')

    def test_product_detail_shows_request_only_form_when_out_of_stock_without_on_request_price(self):
        ProductStock.objects.filter(product=self.product).delete()
        response = self.client.get(self.product.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Оставить заявку')
        self.assertContains(response, reverse('orders:purchase_request_create'))
        self.assertContains(response, 'x-show="isRequestOnlySelection"', html=False)

    def test_product_card_links_to_request_form_when_out_of_stock_without_on_request_price(self):
        ProductStock.objects.filter(product=self.product).delete()
        response = self.client.get(reverse('catalog:product_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'{self.product.get_absolute_url()}#purchase-request')
        self.assertContains(response, 'Оставить заявку')

    def test_product_detail_shows_request_only_form_when_both_prices_missing(self):
        self.product.price = None
        self.product.price_on_request = None
        self.product.save(update_fields=['price', 'price_on_request'])
        response = self.client.get(self.product.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Оставить заявку')
        self.assertContains(response, 'class="purchase-request-panel', html=False)
        self.assertNotContains(response, 'Цена не указана')

    def test_purchase_request_create_saves_request_only_snapshot(self):
        ProductStock.objects.filter(product=self.product).delete()
        response = self.client.post(reverse('orders:purchase_request_create'), {
            'product_id': self.product.pk,
            'variant_id': '',
            'source_path': self.product.get_absolute_url(),
            'phone': '+7 999 123 45 67',
            'telegram': '',
            'agree_personal_data': 'on',
        })

        self.assertEqual(response.status_code, 302)
        purchase_request = PurchaseRequest.objects.get()
        self.assertEqual(response.url, reverse('orders:request_created', kwargs={'request_id': purchase_request.pk}))
        self.assertEqual(purchase_request.total, Decimal('0'))
        self.assertEqual(purchase_request.telegram, '')
        self.assertEqual(purchase_request.items[0]['product_id'], self.product.pk)
        self.assertEqual(purchase_request.items[0]['requested_mode'], 'request_only')
        self.assertEqual(purchase_request.items[0]['stock_total'], 0)
        self.assertEqual(purchase_request.items[0]['price_in_stock'], 100.0)
        self.assertIsNone(purchase_request.items[0]['price_on_request'])

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    @tag('slow')
    def test_purchase_request_create_sends_crm_email(self):
        ProductStock.objects.filter(product=self.product).delete()
        response = self.client.post(reverse('orders:purchase_request_create'), {
            'product_id': self.product.pk,
            'variant_id': '',
            'source_path': self.product.get_absolute_url(),
            'phone': '+7 999 123 45 67',
            'telegram': '@bizonvr',
            'agree_personal_data': 'on',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PurchaseRequest.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['crm@example.com'])
        self.assertEqual(message.subject, 'Заявка с сайта BizonVR: +7 999 123 45 67')
        self.assertIn('Тип формы: Карточка товара', message.body)
        self.assertIn('Товар/услуга: Товар', message.body)
        self.assertIn(f'Страница: http://testserver{self.product.get_absolute_url()}', message.body)
        self.assertIn('Комментарий:\nTelegram: @bizonvr', message.body)

    def test_purchase_request_spam_redirects_to_success_without_creating_request(self):
        ProductStock.objects.filter(product=self.product).delete()
        response = self.client.post(reverse('orders:purchase_request_create'), {
            'product_id': self.product.pk,
            'variant_id': '',
            'source_path': self.product.get_absolute_url(),
            'phone': '+7 999 123 45 67',
            'telegram': '',
            'agree_personal_data': 'on',
            'website': 'spam.example',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('orders:request_created', kwargs={'request_id': 0}))
        self.assertEqual(PurchaseRequest.objects.count(), 0)

    def test_fast_submit_gets_high_spam_score(self):
        request = RequestFactory().post('/orders/purchase-request/create/', {
            'phone': '+7 999 123 45 67',
            'form_started_at': str(int(timezone.now().timestamp() * 1000)),
        })

        result = check_spam_submission(request)

        self.assertFalse(result.is_spam)
        self.assertIn('submitted_too_fast', result.reasons)
        self.assertGreaterEqual(result.score, 25)

    def test_purchase_request_create_saves_null_in_stock_price_when_price_missing(self):
        self.product.price = None
        self.product.price_on_request = None
        self.product.save(update_fields=['price', 'price_on_request'])
        response = self.client.post(reverse('orders:purchase_request_create'), {
            'product_id': self.product.pk,
            'variant_id': '',
            'source_path': self.product.get_absolute_url(),
            'phone': '+7 999 123 45 67',
            'telegram': '',
            'agree_personal_data': 'on',
        })

        self.assertEqual(response.status_code, 302)
        purchase_request = PurchaseRequest.objects.get(phone='+7 999 123 45 67')
        self.assertIsNone(purchase_request.items[0]['price_in_stock'])

    def test_checkout_infers_whatsapp_contact_from_phone(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(contact_handle='+7 999 555 44 33'),
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.contact_channel, Order.CONTACT_CHANNEL_WHATSAPP)
        self.assertEqual(order.contact_handle, '+7 999 555 44 33')

    def test_product_detail_shows_game_pack_composition(self):
        game_pack = Product.objects.create(
            category=self.product.category,
            name='Пак VR Quest',
            slug='vr-quest-pack',
            product_kind=Product.PRODUCT_KIND_GAME_PACK,
            price=Decimal('4900.00'),
            is_active=True,
            allow_order_on_request=False,
        )
        GamePackItem.objects.create(product=game_pack, title='Beat Saber', platform='Meta Quest')
        GamePackItem.objects.create(product=game_pack, title='Pistol Whip', platform='Meta Quest', note='Подходит для вечеринок')

        response = self.client.get(game_pack.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Состав пака')
        self.assertContains(response, 'Beat Saber')
        self.assertContains(response, 'Pistol Whip')
        self.assertContains(response, 'Цифровой пакет')

    def test_add_to_cart_allows_game_pack_without_stock(self):
        game_pack = Product.objects.create(
            category=self.product.category,
            name='Пак VR Start',
            slug='vr-start-pack',
            product_kind=Product.PRODUCT_KIND_GAME_PACK,
            price=Decimal('3900.00'),
            is_active=True,
            allow_order_on_request=False,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('catalog:add_to_cart', kwargs={'product_id': game_pack.pk}),
            {'quantity': 1},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(CartItem.objects.filter(user=self.user, product=game_pack, quantity=1).exists())

    def test_checkout_creates_order_for_game_pack_without_stock(self):
        game_pack = Product.objects.create(
            category=self.product.category,
            name='Пак VR Pro',
            slug='vr-pro-pack',
            product_kind=Product.PRODUCT_KIND_GAME_PACK,
            price=Decimal('5900.00'),
            is_active=True,
            allow_order_on_request=False,
        )
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': game_pack.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().product, game_pack)
        self.assertFalse(order.items.first().is_on_request)

    def test_checkout_requires_pvz_code(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(cdek_office_snapshot_raw=''),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Выберите ПВЗ СДЭК на карте.')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_rejects_invalid_cdek_snapshot_json(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(cdek_office_snapshot_raw='{bad json'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Выберите ПВЗ СДЭК на карте.')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_uses_snapshot_over_legacy_manual_values(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(
                city_text='Подмена',
                address_line='LEGACY123',
            ),
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.city_text, 'Москва')
        self.assertEqual(order.address_line, 'MSK201 — ПВЗ СДЭК Тверская, Москва, ул. Тверская, 10')

    def test_order_created_page_prefers_structured_pvz_snapshot(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        created = self.client.get(response.url)
        self.assertEqual(created.status_code, 200)
        self.assertContains(created, 'MSK201')
        self.assertContains(created, 'ПВЗ СДЭК Тверская')
        self.assertContains(created, 'Москва, ул. Тверская, 10')

    def test_checkout_requires_recipient_fields_when_recipient_differs(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload(
            recipient_is_customer='',
            recipient_name='',
            recipient_phone='',
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Укажите ФИО получателя.')
        self.assertContains(response, 'Укажите телефон получателя.')
        self.assertEqual(Order.objects.count(), 0)


class CheckoutFormsLegalValidationTest(TestCase):
    def test_purchase_request_form_requires_personal_data_consent(self):
        form = PurchaseRequestForm(data={
            'product_id': 1,
            'phone': '+7 999 111 22 33',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('agree_personal_data', form.errors)

    def test_purchase_request_form_allows_blank_telegram(self):
        form = PurchaseRequestForm(data={
            'product_id': 1,
            'phone': '+7 999 111 22 33',
            'telegram': '',
            'agree_personal_data': 'on',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['telegram'], '')

    def test_checkout_form_requires_offer_and_personal_data_consents(self):
        form = CheckoutForm(data={
            'phone': '+7 999 111 22 33',
            'first_name': 'Иван Иванов',
            'last_name': '',
            'email': 'client@example.com',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'city_text': '',
            'address_line': '',
            'cdek_office_snapshot_raw': json.dumps({
                'city': 'Москва',
                'postal_code': '125009',
                'code': 'MSK201',
                'name': 'ПВЗ СДЭК Тверская',
                'address': 'Москва, ул. Тверская, 10',
            }),
            'cdek_tariff_snapshot_raw': json.dumps({
                'tariff_code': 136,
            }),
            'payment_method': Order.PAYMENT_METHOD_MANAGER_CONTACT,
            'comment': '',
            'promo_code': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('agree_personal_data', form.errors)
        self.assertIn('agree_offer', form.errors)

    def test_checkout_form_requires_cdek_office_snapshot(self):
        form = CheckoutForm(data={
            'phone': '+7 999 111 22 33',
            'first_name': 'Иван Иванов',
            'last_name': '',
            'email': 'client@example.com',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'payment_method': Order.PAYMENT_METHOD_MANAGER_CONTACT,
            'comment': '',
            'promo_code': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('cdek_office_snapshot_raw', form.errors)

    def test_checkout_form_uses_snapshot_to_fill_legacy_fields(self):
        form = CheckoutForm(data={
            'phone': '+7 999 111 22 33',
            'first_name': 'Иван Иванов',
            'last_name': '',
            'email': 'client@example.com',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'city_text': 'Подмена',
            'address_line': 'LEGACY999',
            'cdek_office_snapshot_raw': json.dumps({
                'city': 'Москва',
                'postal_code': '125009',
                'code': 'MSK201',
                'name': 'ПВЗ СДЭК Тверская',
                'address': 'Москва, ул. Тверская, 10',
            }),
            'cdek_tariff_snapshot_raw': json.dumps({'tariff_code': 136}),
            'recipient_is_customer': 'on',
            'payment_method': Order.PAYMENT_METHOD_MANAGER_CONTACT,
            'comment': '',
            'promo_code': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['city_text'], 'Москва')
        self.assertEqual(form.cleaned_data['postal_code'], '125009')
        self.assertEqual(form.cleaned_data['address_line'], 'MSK201 — ПВЗ СДЭК Тверская, Москва, ул. Тверская, 10')


class GuestOrderTest(TestCase):
    """Guest order открывается только по токену, legacy URL удалены."""

    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')
        cls.category = create_category(name='Тест', slug='test')
        cls.product = create_product(
            category=cls.category,
            name='Товар',
            slug='product',
            price=Decimal('100.00'),
            is_active=True,
        )
        cls.order = create_order(
            user=None,
            status=Order.STATUS_NEW,
            total=Decimal('100.00'),
            phone='+7 999 111 22 33',
            email='guest@test.com',
            first_name='Гость',
            last_name='',
            address='Адрес',
            guest_access_token='guest-token',
            guest_access_expires_at=timezone.now() + timezone.timedelta(days=7),
        )
        OrderItem.objects.create(order=cls.order, product=cls.product, quantity=1, price=Decimal('100.00'))

    def test_legacy_guest_lookup_route_is_removed(self):
        resp = self.client.get('/orders/guest/')
        self.assertEqual(resp.status_code, 404)

        post_resp = self.client.post('/orders/guest/', {'order_id': self.order.pk, 'phone': '+7 999 000 00 00'})
        self.assertEqual(post_resp.status_code, 404)

    def test_legacy_guest_detail_route_is_removed(self):
        resp = self.client.get(f'/orders/guest/{self.order.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_guest_order_detail_by_token_is_available_without_login(self):
        response = self.client.get(reverse('orders:guest_order_detail', kwargs={'token': self.order.guest_access_token}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Заказ #{self.order.pk}')
        self.assertContains(response, 'защищённой ссылке заказа')
        self.assertContains(response, 'Войти и сохранить заказ')

    def test_guest_order_detail_with_invalid_token_returns_404(self):
        response = self.client.get(reverse('orders:guest_order_detail', kwargs={'token': 'missing-token'}))
        self.assertEqual(response.status_code, 404)

    def test_guest_order_detail_with_expired_token_returns_404(self):
        self.order.guest_access_expires_at = timezone.now() - timezone.timedelta(minutes=1)
        self.order.save(update_fields=['guest_access_expires_at'])

        response = self.client.get(reverse('orders:guest_order_detail', kwargs={'token': self.order.guest_access_token}))
        self.assertEqual(response.status_code, 404)

    def test_authenticated_verified_email_user_claims_guest_order_from_token_page(self):
        self.user.email = self.order.email
        self.user.save(update_fields=['email'])
        Profile.objects.create(
            user=self.user,
            phone='9991234567',
            email_verified_at=timezone.now(),
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('orders:guest_order_detail', kwargs={'token': self.order.guest_access_token}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('orders:order_detail', kwargs={'pk': self.order.pk}))
        self.order.refresh_from_db()
        self.assertEqual(self.order.user, self.user)


@override_settings(
    CDEK_WIDGET_ACCOUNT='widget-account',
    CDEK_WIDGET_PASSWORD='widget-password',
    CDEK_WIDGET_API_BASE='https://api.cdek.test/v2',
)
@tag('slow')
class CdekWidgetProxyTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.url = reverse('orders:cdek_widget_service')

    def _auth_response(self):
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {'access_token': 'cached-token', 'expires_in': 3600}
        response.headers = {}
        response.text = json.dumps({'access_token': 'cached-token'})
        return response

    def _json_response(self, text):
        response = Mock()
        response.raise_for_status = Mock()
        response.headers = {'X-Test-Upstream': '1'}
        response.text = text
        return response

    def test_proxy_rejects_unknown_action(self):
        response = self.client.get(self.url, {'action': 'unknown'})
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {'message': 'Unknown action'})

    @patch('orders.views.cdek_widget.requests.get')
    @patch('orders.views.cdek_widget.requests.post')
    def test_proxy_forwards_offices_request(self, mock_post, mock_get):
        mock_post.return_value = self._auth_response()
        mock_get.return_value = self._json_response('[{"code":"MSK201"}]')

        response = self.client.get(self.url, {'action': 'offices', 'city_code': '44'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Service-Version'], '3.11.1')
        self.assertEqual(response['X-Test-Upstream'], '1')
        self.assertJSONEqual(response.content, [{'code': 'MSK201'}])
        self.assertEqual(mock_post.call_count, 1)
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs['params']['action'], 'offices')

    @patch('orders.views.cdek_widget.requests.get')
    @patch('orders.views.cdek_widget.requests.post')
    def test_proxy_forwards_cities_request(self, mock_post, mock_get):
        mock_post.return_value = self._auth_response()
        mock_get.return_value = self._json_response('[{"code":44,"city":"Москва"}]')

        response = self.client.get(self.url, {'action': 'cities', 'city': 'Москва', 'country_code': 'RU'})

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, [{'code': 44, 'city': 'Москва'}])
        self.assertEqual(mock_post.call_count, 1)
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.kwargs['params']['city'], 'Москва')
        self.assertEqual(mock_get.call_args.kwargs['params']['country_codes'], 'RU')
        self.assertNotIn('action', mock_get.call_args.kwargs['params'])

    @patch('orders.views.cdek_widget.requests.get')
    @patch('orders.views.cdek_widget.requests.post')
    def test_proxy_forwards_calculate_request(self, mock_post, mock_get):
        mock_post.side_effect = [
            self._auth_response(),
            self._json_response('{"office":[{"tariff_code":136}]}'),
        ]

        response = self.client.post(
            self.url,
            data=json.dumps({'action': 'calculate', 'city_code': 44}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'office': [{'tariff_code': 136}]})
        self.assertEqual(mock_post.call_count, 2)
        self.assertFalse(mock_get.called)
        calculate_call = mock_post.call_args_list[1]
        self.assertEqual(calculate_call.kwargs['json']['action'], 'calculate')

    @patch('orders.views.cdek_widget.requests.get')
    @patch('orders.views.cdek_widget.requests.post')
    def test_proxy_reuses_cached_auth_token(self, mock_post, mock_get):
        mock_post.return_value = self._auth_response()
        mock_get.return_value = self._json_response('[]')

        first = self.client.get(self.url, {'action': 'offices', 'city_code': '44'})
        second = self.client.get(self.url, {'action': 'offices', 'city_code': '44'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(mock_get.call_count, 2)


@tag('slow')
class OrderNotificationPolicyTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(
            username='9991234567',
            password='testpass',
            email='client@example.com',
        )
        Profile.objects.create(
            user=cls.user,
            phone='9991234567',
            email_verified_at=timezone.now(),
            phone_verified_at=timezone.now(),
        )

    def test_registered_user_order_notifications_are_email_only(self):
        NotificationPreference.objects.create(
            user=self.user,
            sms_order_updates_enabled=False,
            marketing_email_enabled=False,
            back_in_stock_enabled=False,
        )
        order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='client@example.com',
            first_name='Иван',
        )

        send_order_event_notifications(order, 'order_confirmed')

        self.assertEqual(OrderNotificationLog.objects.filter(order=order, channel='email').count(), 1)
        self.assertEqual(OrderNotificationLog.objects.filter(order=order, channel='sms').count(), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_guest_order_notifications_stay_email_only_and_idempotent(self):
        order = Order.objects.create(
            user=None,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='guest@example.com',
            first_name='Гость',
        )

        send_order_event_notifications(order, 'order_created')
        send_order_event_notifications(order, 'order_created')

        self.assertEqual(OrderNotificationLog.objects.filter(order=order, channel='email').count(), 1)
        self.assertEqual(OrderNotificationLog.objects.filter(order=order, channel='sms').count(), 0)
        self.assertEqual(len(mail.outbox), 1)

    @patch('orders.services._send_order_event_email', side_effect=RuntimeError('smtp unavailable'))
    def test_failed_order_notification_does_not_leave_stale_delivery_log(self, send_email):
        order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='client@example.com',
            first_name='Иван',
        )

        send_order_event_notifications(order, 'order_confirmed')

        self.assertFalse(OrderNotificationLog.objects.filter(order=order).exists())
        send_email.assert_called_once()


class OrderPaymentSideEffectsTest(TestCase):
    def test_paid_transition_does_not_decrease_stock_or_create_shipped_allocations(self):
        city = City.objects.create(name='Екатеринбург', slug='ekb-orders-stock')
        pickup_point = PickupPoint.objects.create(city=city, name='Основной ПВЗ')
        category = Category.objects.create(name='Stock', slug='stock-orders')
        product = Product.objects.create(
            category=category,
            name='Stock product',
            slug='stock-product',
            price=Decimal('100.00'),
            is_active=True,
        )
        ProductStock.objects.create(product=product, pickup_point=pickup_point, quantity=5)
        order = Order.objects.create(
            user=None,
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='client@example.com',
            first_name='Иван',
            city=city,
            pickup_point=pickup_point,
        )
        order_item = OrderItem.objects.create(order=order, product=product, quantity=2, price=Decimal('100.00'))

        sync_order_state_side_effects(
            order,
            previous_status=Order.STATUS_CONFIRMED,
            previous_payment_status=Order.PAYMENT_STATUS_UNPAID,
        )

        order.refresh_from_db()
        stock = ProductStock.objects.get(product=product, pickup_point=pickup_point)
        self.assertFalse(order.stock_decreased)
        self.assertEqual(stock.quantity, 5)
        self.assertFalse(SaleLineAllocation.objects.filter(order_item=order_item, status=SaleLineAllocation.STATUS_SHIPPED).exists())


class OrderLifecycleUiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='9991234567', password='testpass')
        Profile.objects.create(
            user=cls.user,
            phone='9991234567',
            phone_verified_at=timezone.now(),
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        cls.order = create_order(
            user=cls.user,
            status=Order.STATUS_READY_FOR_PICKUP,
            payment_status=Order.PAYMENT_STATUS_PAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='client@example.com',
            first_name='Иван',
        )

    def test_order_list_shows_status_and_payment_badges_with_next_step(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('orders:order_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Готов к выдаче')
        self.assertContains(response, 'Оплачено')
        self.assertContains(response, 'можно приехать', html=False)

    def test_order_detail_shows_consistent_status_summary(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('orders:order_detail', kwargs={'pk': self.order.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Статус заказа')
        self.assertContains(response, 'Готов к выдаче')
        self.assertContains(response, 'Оплачено')
        self.assertContains(response, 'можно приехать', html=False)


class StandaloneGamePackCheckoutTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79990001122', password='pass12345')
        cls.section = CatalogSection.objects.create(name='Решения для бизнеса', slug='business-game-packs')
        cls.category = create_category(name='Игровые паки', slug='game-pack-orders', section=cls.section)
        cls.games_category = create_category(name='Игры для паков', slug='games-for-packs')
        cls.game = create_product(
            category=cls.games_category,
            name='Arizona Sunshine',
            slug='arizona-sunshine',
            price=Decimal('1590.00'),
            is_active=True,
        )
        cls.training_service = Service.objects.create(
            name='Обучение персонала',
            short_description='Стартовое обучение',
            price=Decimal('3000.00'),
            service_kind=Service.KIND_STAFF_TRAINING,
            is_active=True,
        )
        cls.game_pack = create_game_pack(
            category=cls.category,
            name='Party VR Pack',
            slug='party-vr-pack',
            price=Decimal('7990.00'),
            is_active=True,
            allow_order_on_request=False,
        )
        GamePackEntry.objects.create(game_pack=cls.game_pack, product=cls.game, quantity=1, sort_order=0)
        GamePackServiceEntry.objects.create(game_pack=cls.game_pack, service=cls.training_service, quantity=1, price=Decimal('3000.00'))

    def setUp(self):
        self.client.force_login(self.user)

    def _checkout_payload(self):
        return {
            'promo_code': '',
            'first_name': 'Ivan',
            'last_name': 'Petrov',
            'phone': '+79990001122',
            'email': 'ivan@example.com',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'contact_handle': '',
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'city_text': '',
            'address_line': '',
            'delivery_comment': '',
            'cdek_office_snapshot_raw': json.dumps({'code': 'TEST1', 'city': 'Moscow', 'name': 'PVZ Test', 'address': 'Test address', 'postal_code': '101000'}),
            'cdek_tariff_snapshot_raw': json.dumps({'tariff_code': 136, 'delivery_sum': 0}),
            'recipient_is_customer': 'on',
            'payment_method': Order.PAYMENT_METHOD_MANAGER_CONTACT,
            'comment': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
            'business_company_name': '',
            'business_checking_account': '',
            'business_inn': '',
            'business_kpp': '',
            'business_bank_name': '',
            'business_bik': '',
            'business_correspondent_account': '',
            'business_phone': '',
            'business_telegram': '',
            'business_whatsapp': '',
            'website': '',
            'form_started_at': str(int(timezone.now().timestamp()) - 5),
        }

    def test_add_game_pack_to_cart_creates_standalone_cart_item(self):
        response = self.client.post(
            reverse('catalog:add_game_pack_to_cart', kwargs={'game_pack_id': self.game_pack.pk}),
            {'quantity': 1},
        )

        self.assertEqual(response.status_code, 302)
        cart_item = CartItem.objects.get(user=self.user)
        self.assertEqual(cart_item.game_pack, self.game_pack)
        self.assertIsNone(cart_item.product)
        self.assertEqual(cart_item.quantity, 1)
        self.assertEqual(cart_item.price_override, Decimal('4590.00'))

    def test_game_pack_price_is_sum_of_games_and_services(self):
        self.assertEqual(self.game_pack.in_stock_price, Decimal('4590.00'))

    def test_checkout_creates_order_item_for_game_pack(self):
        self.client.post(reverse('catalog:add_game_pack_to_cart', kwargs={'game_pack_id': self.game_pack.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order_item = OrderItem.objects.get()
        self.assertEqual(order_item.game_pack, self.game_pack)
        self.assertIsNone(order_item.product)
        self.assertEqual(order_item.product_name, self.game_pack.name)
        self.assertEqual(order_item.price, Decimal('4590.00'))
        self.assertEqual(order_item.metadata['games'][0]['name'], self.game.name)
        self.assertEqual(order_item.metadata['services'][0]['name'], self.training_service.name)

    def test_game_pack_card_shows_games_and_included_services(self):
        response = self.client.get(f"{reverse('catalog:product_list')}?category={self.category.slug}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Игры:')
        self.assertContains(response, self.game.name)
        self.assertContains(response, 'Услуги включены:')
        self.assertContains(response, self.training_service.name)

    def test_game_pack_price_filter_uses_computed_price(self):
        response = self.client.get(f"{reverse('catalog:product_list')}?category={self.category.slug}&price_min=4500&price_max=4700")
        self.assertContains(response, self.game_pack.name)

        response = self.client.get(f"{reverse('catalog:product_list')}?category={self.category.slug}&price_min=7900&price_max=8100")
        self.assertNotContains(response, self.game_pack.name)
