"""Базовые тесты заказов (Фаза 6)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from catalog.models import Category, Product
from config.legal_docs import LEGAL_BUNDLE_VERSION

from .forms import CheckoutForm, PurchaseRequestForm
from .models import Order, OrderItem, PurchaseRequest

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
        cat = Category.objects.create(name='Тест', slug='test')
        self.product = Product.objects.create(
            category=cat,
            name='Товар',
            slug='product',
            price=Decimal('100.00'),
            is_active=True,
        )

    def test_checkout_creates_request_and_clears_cart(self):
        """Оформление заявки: создаётся PurchaseRequest, корзина очищается."""
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.post(add_url, {'quantity': 2})
        url = reverse('orders:checkout')
        resp = self.client.post(url, {
            'phone': '+7 999 123 45 67',
            'telegram': '@testuser',
            'agree_personal_data': 'on',
        })
        self.assertEqual(resp.status_code, 302, msg=f'Got {resp.status_code}. URL: {getattr(resp, "url", "")}. Content: {resp.content.decode()[:300] if resp.content else ""}')
        self.assertIn('request-created', resp.url, msg=f'Expected redirect to request_created, got {resp.url}')
        req = PurchaseRequest.objects.first()
        self.assertIsNotNone(req, msg=f'PurchaseRequest was not created. Redirect URL: {resp.url}')
        self.assertEqual(req.total, Decimal('200.00'))
        self.assertEqual(req.phone, '+7 999 123 45 67')
        self.assertEqual(len(req.items), 1)
        self.assertIsNotNone(req.legal_accepted_at)
        self.assertEqual(req.legal_docs_version, LEGAL_BUNDLE_VERSION)
        self.assertTrue(req.legal_acceptance_user_agent == '' or isinstance(req.legal_acceptance_user_agent, str))
        # После оформления корзина пуста (сессия для анонима)
        self.assertEqual(self.client.session.get('cart_items', []), [])


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
    """Гостевой заказ: доступ по номеру заказа + телефон (Фаза 6)."""

    def setUp(self):
        self.client = Client()
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

    def test_guest_lookup_requires_phone_match(self):
        url = reverse('orders:order_guest_lookup')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(url, {'order_id': self.order.pk, 'phone': '+7 999 000 00 00'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Телефон не совпадает')

    def test_guest_lookup_success_redirects_to_order(self):
        url = reverse('orders:order_guest_lookup')
        resp = self.client.post(url, {'order_id': self.order.pk, 'phone': '+7 999 111 22 33'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('orders:order_guest', kwargs={'order_id': self.order.pk}))
        resp = self.client.get(resp.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'Заказ #{self.order.pk}')
