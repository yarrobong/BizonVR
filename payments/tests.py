from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product
from orders.models import Order

User = get_user_model()


class GuestPaymentAccessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')
        category = Category.objects.create(name='Оплата', slug='payment-category')
        product = Product.objects.create(
            category=category,
            name='VR шлем',
            slug='vr-helmet',
            price=Decimal('100.00'),
            is_active=True,
        )
        self.guest_order = Order.objects.create(
            user=None,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            phone='+7 999 111 22 33',
            email='guest@example.com',
            first_name='Гость',
            guest_access_token='guest-payment-token',
            guest_access_expires_at=timezone.now() + timezone.timedelta(days=7),
        )
        self.guest_order.items.create(product=product, quantity=1, price=Decimal('100.00'))

    def test_guest_create_payment_requires_access_token(self):
        response = self.client.get(reverse('payments:create_payment', kwargs={'order_id': self.guest_order.pk}))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))

    def test_guest_create_payment_invalid_token_returns_404(self):
        response = self.client.get(
            reverse('payments:create_payment', kwargs={'order_id': self.guest_order.pk}),
            {'access': 'invalid-token'},
        )

        self.assertEqual(response.status_code, 404)

    def test_guest_create_payment_redirects_to_order_confirmation_with_valid_token(self):
        response = self.client.get(
            reverse('payments:create_payment', kwargs={'order_id': self.guest_order.pk}),
            {'access': self.guest_order.guest_access_token},
        )

        self.assertEqual(response.status_code, 302)
        expected_url = f"{reverse('orders:order_created', kwargs={'order_id': self.guest_order.pk})}?access={self.guest_order.guest_access_token}"
        self.assertEqual(response.url, expected_url)

    def test_guest_payment_wait_redirects_to_order_confirmation_with_valid_token(self):

        response = self.client.get(
            reverse('payments:payment_wait', kwargs={'order_id': self.guest_order.pk}),
            {'access': self.guest_order.guest_access_token},
        )

        self.assertEqual(response.status_code, 302)
        expected_url = f"{reverse('orders:order_created', kwargs={'order_id': self.guest_order.pk})}?access={self.guest_order.guest_access_token}"
        self.assertEqual(response.url, expected_url)


class AuthenticatedPaymentAccessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')
        self.other_user = User.objects.create_user(username='79990000000', password='testpass')
        self.order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='client@example.com',
            first_name='Иван',
        )

    def test_foreign_authenticated_user_cannot_open_payment_page(self):
        self.client.force_login(self.other_user)

        response = self.client.get(reverse('payments:create_payment', kwargs={'order_id': self.order.pk}))

        self.assertEqual(response.status_code, 404)

    def test_owner_opening_payment_page_redirects_to_order_detail(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('payments:create_payment', kwargs={'order_id': self.order.pk}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('orders:order_detail', kwargs={'pk': self.order.pk}))
