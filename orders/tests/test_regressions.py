from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from catalog.tests.factories import create_category, create_product
from orders.models import Order, OrderItem, PurchaseRequest
from orders.tests.factories import create_order

from accounts.tests.factories import create_user


class OrderSecurityRegressionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')
        cls.other_user = create_user(username='79990000000', password='testpass')
        cls.category = create_category(name='Security', slug='security')
        cls.product = create_product(
            category=cls.category,
            name='Secure product',
            slug='secure-product',
            price=Decimal('100.00'),
            is_active=True,
        )
        cls.guest_order = create_order(
            user=None,
            status=Order.STATUS_NEW,
            total=Decimal('100.00'),
            phone='+7 999 111 22 33',
            email='guest@example.com',
            first_name='Гость',
            address='Тестовый адрес',
        )
        OrderItem.objects.create(order=cls.guest_order, product=cls.product, quantity=1, price=Decimal('100.00'))
        cls.user_order = create_order(
            user=cls.user,
            status=Order.STATUS_NEW,
            total=Decimal('100.00'),
            phone='+7 999 555 44 33',
            first_name='Пользователь',
            address='Адрес пользователя',
        )
        cls.request_obj = PurchaseRequest.objects.create(
            phone='+7 999 123 45 67',
            telegram='@secret_manager',
            items=[],
            total=Decimal('0.00'),
        )

    def test_order_created_page_no_longer_reveals_order_data_or_mutates_session(self):
        # Guards against guest success pages leaking order contacts or recreating session-based access.
        response = self.client.get(reverse('orders:order_created', kwargs={'order_id': self.guest_order.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.guest_order.phone)
        self.assertNotContains(
            response,
            f'Номер заказа: <span class="text-white font-bold">#{self.guest_order.pk}</span>',
            html=True,
        )
        self.assertNotIn('guest_order_ids', self.client.session)

    def test_request_created_page_no_longer_reveals_request_contacts(self):
        # Guards against request success pages showing raw phone/Telegram details back to anonymous visitors.
        response = self.client.get(reverse('orders:request_created', kwargs={'request_id': self.request_obj.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.request_obj.phone)
        self.assertNotContains(response, self.request_obj.telegram)

    def test_removed_legacy_guest_routes_return_404(self):
        # Guards against the deprecated guest lookup routes being accidentally published again.
        response = self.client.get(f'/orders/guest/{self.guest_order.pk}/')
        lookup_response = self.client.get('/orders/guest/')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(lookup_response.status_code, 404)

    def test_authenticated_user_cannot_open_foreign_order_detail(self):
        # Guards against authenticated users enumerating other customers' order pages.
        self.client.force_login(self.other_user)

        response = self.client.get(reverse('orders:order_detail', kwargs={'pk': self.user_order.pk}))

        self.assertEqual(response.status_code, 404)

    def test_guest_token_route_does_not_open_non_guest_order(self):
        # Guards against customer orders becoming readable through the guest token endpoint.
        self.user_order.refresh_guest_access(ttl_days=7)
        self.user_order.save(update_fields=['guest_access_token', 'guest_access_expires_at'])

        response = self.client.get(
            reverse('orders:guest_order_detail', kwargs={'token': self.user_order.guest_access_token})
        )

        self.assertEqual(response.status_code, 404)
