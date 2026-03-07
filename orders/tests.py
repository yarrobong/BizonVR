"""Базовые тесты заказов (Фаза 6)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from catalog.models import CartItem, Category, Product
from config.legal_docs import LEGAL_BUNDLE_VERSION

from .forms import CheckoutForm, PurchaseRequestForm
from .models import Order, OrderItem, PromoCode, PurchaseRequest

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

    def test_checkout_requires_login(self):
        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))

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
        resp = self.client.post(url, {
            'promo_code': 'BIZON500',
            'phone': '+7 999 123 45 67',
            'first_name': 'Иван',
            'last_name': 'Иванов',
            'email': 'test@example.com',
            'address': 'Москва, ул. Тестовая, д. 1',
            'delivery_type': 'courier',
            'comment': 'Позвонить за час',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
        })
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.first()
        self.assertIsNotNone(order)
        self.assertEqual(resp.url, reverse('orders:order_detail', kwargs={'pk': order.pk}))
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.total, Decimal('200.00'))
        self.assertEqual(order.promo_discount, Decimal('50.00'))
        self.assertEqual(order.phone, '+7 999 123 45 67')
        self.assertEqual(order.legal_docs_version, LEGAL_BUNDLE_VERSION)
        self.assertIsNotNone(order.legal_accepted_at)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().quantity, 2)
        self.assertEqual(self.client.session.get('cart_items', []), [])
        self.assertEqual(PurchaseRequest.objects.count(), 0)

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

        checkout_resp = self.client.post(reverse('orders:checkout'), {
            'promo_code': '',
            'phone': '+7 999 123 45 67',
            'first_name': 'Иван',
            'last_name': '',
            'email': '',
            'address': 'Москва, ул. Тестовая, д. 1',
            'delivery_type': 'courier',
            'comment': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
        })
        self.assertEqual(checkout_resp.status_code, 302)
        self.assertEqual(checkout_resp.url, reverse('orders:checkout'))
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_blocks_stale_cart_item_when_stock_missing_and_order_on_request_disabled(self):
        self.product.allow_order_on_request = False
        self.product.save(update_fields=['allow_order_on_request'])
        self.client.force_login(self.user)
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)

        resp = self.client.post(reverse('orders:checkout'), {
            'promo_code': '',
            'phone': '+7 999 123 45 67',
            'first_name': 'Иван',
            'last_name': '',
            'email': '',
            'address': 'Москва, ул. Тестовая, д. 1',
            'delivery_type': 'courier',
            'comment': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Недостаточно товара')
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_marks_item_as_on_request_when_stock_missing(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        resp = self.client.post(reverse('orders:checkout'), {
            'promo_code': '',
            'phone': '+7 999 123 45 67',
            'first_name': 'Иван',
            'last_name': '',
            'email': '',
            'address': 'Москва, ул. Тестовая, д. 1',
            'delivery_type': 'courier',
            'comment': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertTrue(order.items.get().is_on_request)

    def test_checkout_test_mode_creates_paid_order(self):
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})
        with self.settings(TEST_ORDER_NO_PAYMENT=True):
            resp = self.client.post(reverse('orders:checkout'), {
                'promo_code': '',
                'phone': '+7 999 123 45 67',
                'first_name': 'Иван',
                'last_name': '',
                'email': '',
                'address': 'Москва, ул. Тестовая, д. 1',
                'delivery_type': 'courier',
                'comment': '',
                'agree_personal_data': 'on',
                'agree_offer': 'on',
            })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Order.objects.get().status, Order.STATUS_PAID)


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
            'email': 'test@example.com',
            'address': 'Москва, ул. Тестовая, д. 1',
            'delivery_type': 'courier',
            'comment': '',
            'promo_code': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('agree_personal_data', form.errors)
        self.assertIn('agree_offer', form.errors)


class GuestOrderTest(TestCase):
    """Legacy guest URLs больше не открывают заказ без авторизации."""

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
