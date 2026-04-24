"""Базовые тесты заказов (Фаза 6)."""
from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import Mock, patch

from accounts.models import NotificationPreference, Profile
from catalog.models import CartItem, Category, City, PickupPoint, Product, ProductStock
from config.legal_docs import LEGAL_BUNDLE_VERSION
from manager_portal.models import ManagerClient, ManagerDeal, SaleLineAllocation

from .forms import CheckoutForm, PurchaseRequestForm
from .models import Order, OrderItem, OrderNotificationLog, PromoCode, PurchaseRequest
from .services import send_order_event_notifications, sync_order_state_side_effects

User = get_user_model()


class OrderViewsTest(TestCase):
    """Список заказов доступен только авторизованным."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')

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

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')
        cat = Category.objects.create(name='Тест', slug='test')
        self.city = City.objects.create(name='Москва', slug='msk-checkout')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Основной ПВЗ')
        self.product = Product.objects.create(
            category=cat,
            name='Товар',
            slug='product',
            price=Decimal('100.00'),
            is_active=True,
        )
        self.product_second = Product.objects.create(
            category=cat,
            name='Товар 2',
            slug='product-2',
            price=Decimal('200.00'),
            is_active=True,
        )
        ProductStock.objects.create(product=self.product, pickup_point=self.pickup_point, quantity=10)
        ProductStock.objects.create(product=self.product_second, pickup_point=self.pickup_point, quantity=10)
        self.promo = PromoCode.objects.create(code='BIZON500', discount_amount=Decimal('50.00'))

    def _checkout_payload(self, **overrides):
        payload = {
            'promo_code': '',
            'first_name': 'Иван Иванов',
            'last_name': '',
            'phone': '+7 999 123 45 67',
            'email': '',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'contact_handle': '',
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'city_text': '',
            'address_line': '',
            'delivery_comment': '',
            'cdek_office_snapshot_raw': json.dumps(self._office_snapshot()),
            'cdek_tariff_snapshot_raw': json.dumps(self._tariff_snapshot()),
            'recipient_is_customer': 'on',
            'payment_method': Order.PAYMENT_METHOD_SBP,
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
        self.assertEqual(order.payment_method, Order.PAYMENT_METHOD_SBP)
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

    def test_checkout_creates_manager_portal_entities_for_website_order(self):
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price_on_request'])
        self.client.force_login(self.user)
        self.client.post(
            reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}),
            {'quantity': 1, 'purchase_mode': 'on_request'},
        )

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertTrue(ManagerClient.objects.filter(orders=order).exists())
        self.assertTrue(hasattr(order, 'manager_deal'))
        self.assertEqual(order.manager_deal.customer_source, ManagerDeal.SOURCE_WEBSITE)
        self.assertEqual(order.manager_deal.deal_type, ManagerDeal.DEAL_SALE_ON_REQUEST)

    def test_checkout_ignores_public_payment_override(self):
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
        self.assertEqual(order.payment_method, Order.PAYMENT_METHOD_SBP)
        self.assertEqual(order.manager_deal.buyer_type, ManagerDeal.BUYER_INDIVIDUAL)

    def test_checkout_test_mode_creates_paid_order(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        with self.settings(TEST_ORDER_NO_PAYMENT=True):
            resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Order.objects.get().payment_status, Order.PAYMENT_STATUS_PAID)

    def test_checkout_discards_public_email_override(self):
        self.product.price_on_request = Decimal('80.00')
        self.product.save(update_fields=['price_on_request'])
        self.client.post(
            reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}),
            {'quantity': 1, 'purchase_mode': 'on_request'},
        )

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload(email='client@example.com'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.get().email, '')

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
            'email': '',
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
            'payment_method': Order.PAYMENT_METHOD_SBP,
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
            'email': '',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'payment_method': Order.PAYMENT_METHOD_SBP,
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
            'email': '',
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
            'payment_method': Order.PAYMENT_METHOD_SBP,
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
    """Guest order теперь открывается по токену, старые URL по id закрыты."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')
        cat = Category.objects.create(name='Тест', slug='test')
        self.product = Product.objects.create(
            category=cat,
            name='Товар',
            slug='product',
            price=Decimal('100.00'),
            is_active=True,
        )
        self.order = Order.objects.create(
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
        OrderItem.objects.create(order=self.order, product=self.product, quantity=1, price=Decimal('100.00'))

    def test_guest_lookup_requires_login(self):
        url = reverse('orders:order_guest_lookup')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))
        resp = self.client.post(url, {'order_id': self.order.pk, 'phone': '+7 999 000 00 00'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))
        self.assertNotIn('guest_order_ids', self.client.session)

    def test_guest_lookup_authenticated_redirects_to_order_list(self):
        self.client.force_login(self.user)
        url = reverse('orders:order_guest_lookup')
        resp = self.client.post(url, {'order_id': self.order.pk, 'phone': '+7 999 111 22 33'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('orders:order_list'))

    def test_guest_order_detail_requires_login(self):
        resp = self.client.get(reverse('orders:order_guest', kwargs={'order_id': self.order.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))

    def test_guest_order_detail_authenticated_redirects_to_order_list_for_guest_order(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('orders:order_guest', kwargs={'order_id': self.order.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('orders:order_list'))

    def test_guest_order_detail_by_token_is_available_without_login(self):
        response = self.client.get(reverse('orders:guest_order_detail', kwargs={'token': self.order.guest_access_token}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Заказ #{self.order.pk}')


@override_settings(
    CDEK_WIDGET_ACCOUNT='widget-account',
    CDEK_WIDGET_PASSWORD='widget-password',
    CDEK_WIDGET_API_BASE='https://api.cdek.test/v2',
)
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


class OrderSecurityRegressionTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')
        self.other_user = User.objects.create_user(username='79990000000', password='testpass')
        category = Category.objects.create(name='Security', slug='security')
        self.product = Product.objects.create(
            category=category,
            name='Secure product',
            slug='secure-product',
            price=Decimal('100.00'),
            is_active=True,
        )
        self.guest_order = Order.objects.create(
            user=None,
            status=Order.STATUS_NEW,
            total=Decimal('100.00'),
            phone='+7 999 111 22 33',
            email='guest@example.com',
            first_name='Гость',
            address='Тестовый адрес',
        )
        OrderItem.objects.create(order=self.guest_order, product=self.product, quantity=1, price=Decimal('100.00'))
        self.user_order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_NEW,
            total=Decimal('100.00'),
            phone='+7 999 555 44 33',
            first_name='Пользователь',
            address='Адрес пользователя',
        )
        self.request_obj = PurchaseRequest.objects.create(
            phone='+7 999 123 45 67',
            telegram='@secret_manager',
            items=[],
            total=Decimal('0.00'),
        )

    def test_order_created_page_no_longer_reveals_order_data_or_mutates_session(self):
        response = self.client.get(reverse('orders:order_created', kwargs={'order_id': self.guest_order.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.guest_order.phone)
        self.assertNotContains(response, f'Номер заказа: <span class="text-white font-bold">#{self.guest_order.pk}</span>', html=True)
        self.assertNotIn('guest_order_ids', self.client.session)

    def test_request_created_page_no_longer_reveals_request_contacts(self):
        response = self.client.get(reverse('orders:request_created', kwargs={'request_id': self.request_obj.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.request_obj.phone)
        self.assertNotContains(response, self.request_obj.telegram)

    def test_guest_order_detail_requires_login(self):
        response = self.client.get(reverse('orders:order_guest', kwargs={'order_id': self.guest_order.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))

    def test_guest_order_post_without_login_does_not_mutate_session(self):
        response = self.client.post(
            reverse('orders:order_guest', kwargs={'order_id': self.guest_order.pk}),
            {'phone': '+7 999 000 00 00'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))
        self.assertNotIn('guest_order_ids', self.client.session)

    def test_authenticated_user_cannot_open_foreign_order_detail(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse('orders:order_detail', kwargs={'pk': self.user_order.pk}))
        self.assertEqual(response.status_code, 404)

    def test_authenticated_user_guest_route_redirects_to_own_order_detail(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('orders:order_guest', kwargs={'order_id': self.user_order.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('orders:order_detail', kwargs={'pk': self.user_order.pk}))


class OrderNotificationPolicyTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='9991234567',
            password='testpass',
            email='client@example.com',
        )
        Profile.objects.create(
            user=self.user,
            phone='9991234567',
            email_verified_at=timezone.now(),
            phone_verified_at=timezone.now(),
        )

    @patch('orders.services.send_sms_message')
    def test_registered_user_sms_notifications_respect_preferences(self, mocked_sms):
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
        mocked_sms.assert_not_called()

    @patch('orders.services.send_sms_message')
    def test_guest_order_sms_notifications_allowed_by_default_and_idempotent(self, mocked_sms):
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
        self.assertEqual(OrderNotificationLog.objects.filter(order=order, channel='sms').count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        mocked_sms.assert_called_once()


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
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='9991234567', password='testpass')
        Profile.objects.create(
            user=self.user,
            phone='9991234567',
            phone_verified_at=timezone.now(),
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        self.order = Order.objects.create(
            user=self.user,
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
