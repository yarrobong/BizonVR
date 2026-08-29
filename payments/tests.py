from decimal import Decimal
import hashlib
import hmac
import json
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from unittest.mock import patch
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import create_user
from catalog.tests.factories import create_category, create_product
from orders.models import Order
from orders.tests.factories import create_order
from payments.models import Payment
from payments.views.checkout import _get_payment_order_access

User = get_user_model()


class PaymentAccessHelperTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')
        cls.other_user = create_user(username='79990000000', password='testpass')
        category = create_category(name='Оплата', slug='payment-category')
        product = create_product(
            category=category,
            name='VR шлем',
            slug='vr-helmet',
            price=Decimal('100.00'),
            is_active=True,
        )
        cls.guest_order = create_order(
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
        cls.guest_order.items.create(product=product, quantity=1, price=Decimal('100.00'))
        cls.order = create_order(
            user=cls.user,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='client@example.com',
            first_name='Иван',
        )

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path, *, user=None, params=None):
        request = self.factory.get(path, data=params or {})
        request.user = user if user is not None else AnonymousUser()
        return request

    def test_guest_access_without_token_returns_login_redirect_target(self):
        request = self._request(
            reverse('payments:create_payment', kwargs={'order_id': self.guest_order.pk}),
        )

        order, redirect_target = _get_payment_order_access(request, self.guest_order.pk)

        self.assertIsNone(order)
        self.assertTrue(redirect_target.startswith(reverse('accounts:login')))

    def test_guest_access_with_invalid_token_raises_404(self):
        request = self._request(
            reverse('payments:create_payment', kwargs={'order_id': self.guest_order.pk}),
            params={'access': 'invalid-token'},
        )

        with self.assertRaises(Http404):
            _get_payment_order_access(request, self.guest_order.pk)

    def test_guest_access_with_valid_token_returns_order_and_token(self):
        request = self._request(
            reverse('payments:create_payment', kwargs={'order_id': self.guest_order.pk}),
            params={'access': self.guest_order.guest_access_token},
        )

        order, access_token = _get_payment_order_access(request, self.guest_order.pk)

        self.assertEqual(order, self.guest_order)
        self.assertEqual(access_token, self.guest_order.guest_access_token)

    def test_foreign_authenticated_user_cannot_open_payment_page(self):
        request = self._request(
            reverse('payments:create_payment', kwargs={'order_id': self.order.pk}),
            user=self.other_user,
        )

        with self.assertRaises(Http404):
            _get_payment_order_access(request, self.order.pk)

    def test_owner_opening_payment_page_gets_order_without_guest_token(self):
        request = self._request(
            reverse('payments:create_payment', kwargs={'order_id': self.order.pk}),
            user=self.user,
        )

        order, access_token = _get_payment_order_access(request, self.order.pk)

        self.assertEqual(order, self.order)
        self.assertEqual(access_token, '')


class PaymentRedirectViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')
        category = create_category(name='Оплата', slug='payment-category-view')
        product = create_product(
            category=category,
            name='VR шлем',
            slug='vr-helmet-view',
            price=Decimal('100.00'),
            is_active=True,
        )
        cls.guest_order = create_order(
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
        cls.guest_order.items.create(product=product, quantity=1, price=Decimal('100.00'))
        cls.order = create_order(
            user=cls.user,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            phone='+7 999 123 45 67',
            email='client@example.com',
            first_name='Иван',
        )

    def test_guest_create_payment_redirects_to_order_confirmation_with_valid_token(self):
        response = self.client.get(
            reverse('payments:create_payment', kwargs={'order_id': self.guest_order.pk}),
            {'access': self.guest_order.guest_access_token},
        )

        self.assertEqual(response.status_code, 302)
        expected_url = (
            f"{reverse('orders:order_created', kwargs={'order_id': self.guest_order.pk})}"
            f"?access={self.guest_order.guest_access_token}"
        )
        self.assertEqual(response.url, expected_url)

    def test_guest_payment_wait_redirects_to_order_confirmation_with_valid_token(self):
        response = self.client.get(
            reverse('payments:payment_wait', kwargs={'order_id': self.guest_order.pk}),
            {'access': self.guest_order.guest_access_token},
        )

        self.assertEqual(response.status_code, 302)
        expected_url = (
            f"{reverse('orders:order_created', kwargs={'order_id': self.guest_order.pk})}"
            f"?access={self.guest_order.guest_access_token}"
        )
        self.assertEqual(response.url, expected_url)

    def test_owner_opening_payment_page_redirects_to_order_detail(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('payments:create_payment', kwargs={'order_id': self.order.pk}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('orders:order_detail', kwargs={'pk': self.order.pk}))


class PaymentWebhookTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = create_category(name='Webhook', slug='payment-webhook-category')
        product = create_product(
            category=category,
            name='Webhook product',
            slug='payment-webhook-product',
            price=Decimal('100.00'),
            is_active=True,
        )
        cls.order = create_order(
            user=None,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            total=Decimal('100.00'),
            email='guest@example.com',
        )
        cls.order.items.create(product=product, quantity=1, price=Decimal('100.00'))
        cls.payment = Payment.objects.create(
            order=cls.order,
            external_id='external-payment-1',
            price_amount=Decimal('100.00'),
        )

    def _signed_payload(self, **overrides):
        data = {
            'payment_id': self.payment.external_id,
            'order_id': str(self.order.pk),
            'payment_status': 'finished',
        }
        data.update(overrides)
        body = json.dumps(data, sort_keys=True, separators=(',', ':'))
        signature = hmac.new(b'test-ipn-secret', body.encode('utf-8'), hashlib.sha512).hexdigest()
        return body, signature

    @override_settings(PAYMENT_GATEWAY_IPN_SECRET='test-ipn-secret')
    @patch('payments.views.webhook.sync_order_state_side_effects')
    def test_duplicate_finished_webhook_runs_order_side_effects_once(self, sync_side_effects):
        body, signature = self._signed_payload()

        first = self.client.post(
            reverse('payments:webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )
        second = self.client.post(
            reverse('payments:webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(sync_side_effects.call_count, 1)
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PAYMENT_STATUS_PAID)
        self.assertEqual(self.payment.status, Payment.STATUS_FINISHED)

    @override_settings(PAYMENT_GATEWAY_IPN_SECRET='test-ipn-secret')
    def test_malformed_order_id_returns_bad_request(self):
        body, signature = self._signed_payload(order_id='not-an-integer')

        response = self.client.post(
            reverse('payments:webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(PAYMENT_GATEWAY_IPN_SECRET='test-ipn-secret')
    def test_malformed_payload_returns_bad_request(self):
        body = '[]'
        signature = hmac.new(b'test-ipn-secret', body.encode('utf-8'), hashlib.sha512).hexdigest()

        response = self.client.post(
            reverse('payments:webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(PAYMENT_GATEWAY_IPN_SECRET='test-ipn-secret')
    def test_finished_payment_rejects_status_regression(self):
        self.payment.status = Payment.STATUS_FINISHED
        self.payment.save(update_fields=['status'])
        body, signature = self._signed_payload(payment_status='waiting')

        response = self.client.post(
            reverse('payments:webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(response.status_code, 409)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.STATUS_FINISHED)

    @override_settings(PAYMENT_GATEWAY_IPN_SECRET='test-ipn-secret')
    def test_finished_webhook_does_not_mark_refunded_order_payment_finished(self):
        self.order.payment_status = Order.PAYMENT_STATUS_REFUNDED
        self.order.save(update_fields=['payment_status'])
        body, signature = self._signed_payload()

        response = self.client.post(
            reverse('payments:webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(response.status_code, 409)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.STATUS_PENDING)

    @override_settings(PAYMENT_GATEWAY_IPN_SECRET='test-ipn-secret')
    @patch('payments.views.webhook.sync_order_state_side_effects', side_effect=RuntimeError('manager workflow unavailable'))
    def test_manager_workflow_failure_does_not_rollback_paid_webhook(self, sync_side_effects):
        body, signature = self._signed_payload()

        response = self.client.post(
            reverse('payments:webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_NOWPAYMENTS_SIG=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PAYMENT_STATUS_PAID)
        self.assertEqual(self.payment.status, Payment.STATUS_FINISHED)
        sync_side_effects.assert_called_once()
