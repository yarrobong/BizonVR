"""Базовые тесты заказов (Фаза 6)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

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


class CheckoutTest(TestCase):
    """Checkout создаёт заказ и очищает корзину (Фаза 6)."""

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
        self.promo = PromoCode.objects.create(code='BIZON500', discount_amount=Decimal('50.00'))

    def _checkout_payload(self, **overrides):
        payload = {
            'promo_code': '',
            'first_name': 'Иван',
            'last_name': 'Иванов',
            'phone': '+7 999 123 45 67',
            'email': '',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'contact_handle': '',
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'city_text': 'Москва',
            'address_line': '',
            'delivery_comment': 'Позвонить перед доставкой',
            'recipient_is_customer': 'on',
            'payment_method': Order.PAYMENT_METHOD_SBP,
            'comment': 'Позвонить за час',
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

    def test_checkout_available_for_guest(self):
        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Оформление заказа')
        self.assertNotContains(resp, 'CDEK')

    def test_checkout_get_authenticated_returns_200(self):
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.force_login(self.user)
        self.client.post(add_url, {'quantity': 1})
        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Оформление заказа')

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
        self.assertEqual(order.address_line, '')
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

    def test_add_to_cart_blocks_when_stock_missing_and_order_on_request_disabled(self):
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
        self.product.allow_order_on_request = False
        self.product.save(update_fields=['allow_order_on_request'])
        self.client.force_login(self.user)
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)

        resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Недостаточно товара')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_marks_item_as_on_request_when_stock_missing(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertTrue(order.items.get().is_on_request)

    def test_checkout_creates_manager_portal_entities_for_website_order(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertTrue(ManagerClient.objects.filter(orders=order).exists())
        self.assertTrue(hasattr(order, 'manager_deal'))
        self.assertEqual(order.manager_deal.customer_source, ManagerDeal.SOURCE_WEBSITE)
        self.assertEqual(order.manager_deal.deal_type, ManagerDeal.DEAL_SALE_ON_REQUEST)

    def test_checkout_invoice_marks_manager_deal_as_business_without_requiring_requisites(self):
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
        self.assertEqual(order.payment_method, Order.PAYMENT_METHOD_INVOICE)
        self.assertEqual(order.manager_deal.buyer_type, ManagerDeal.BUYER_BUSINESS)
        self.assertEqual(order.manager_deal.business_phone, '+7 999 123 45 67')

    def test_checkout_test_mode_creates_paid_order(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        with self.settings(TEST_ORDER_NO_PAYMENT=True):
            resp = self.client.post(reverse('orders:checkout'), self._checkout_payload())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Order.objects.get().payment_status, Order.PAYMENT_STATUS_PAID)

    def test_checkout_allows_call_without_email(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload(email=''))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)

    def test_checkout_requires_email_when_email_channel_selected(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(contact_channel=Order.CONTACT_CHANNEL_EMAIL, email=''),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Укажите email для связи.')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_requires_contact_handle_for_telegram(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(contact_channel=Order.CONTACT_CHANNEL_TELEGRAM, contact_handle=''),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Укажите контакт в выбранном мессенджере.')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_pickup_does_not_require_address(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(delivery_type=Order.DELIVERY_PICKUP, address_line=''),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.get().address_line, '')

    def test_checkout_courier_delivery_requires_address(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(
            reverse('orders:checkout'),
            self._checkout_payload(delivery_type=Order.DELIVERY_CDEK_COURIER, address_line=''),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Укажите адрес доставки.')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_requires_recipient_fields_when_recipient_differs(self):
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload(
            recipient_is_customer='',
            recipient_name='',
            recipient_phone='',
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Укажите имя и фамилию получателя.')
        self.assertContains(response, 'Укажите телефон получателя.')
        self.assertEqual(Order.objects.count(), 0)


class CheckoutFormsLegalValidationTest(TestCase):
    def test_purchase_request_form_requires_personal_data_consent(self):
        form = PurchaseRequestForm(data={
            'phone': '+7 999 111 22 33',
            'telegram': '@test',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('agree_personal_data', form.errors)

    def test_checkout_form_requires_offer_and_personal_data_consents(self):
        form = CheckoutForm(data={
            'phone': '+7 999 111 22 33',
            'first_name': 'Иван',
            'last_name': 'Иванов',
            'email': '',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'delivery_type': Order.DELIVERY_PICKUP,
            'city_text': 'Москва',
            'address_line': '',
            'payment_method': Order.PAYMENT_METHOD_SBP,
            'comment': '',
            'promo_code': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('agree_personal_data', form.errors)
        self.assertIn('agree_offer', form.errors)


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
