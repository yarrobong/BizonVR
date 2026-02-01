"""Базовые тесты входа по телефону (Фаза 6)."""
from django.test import Client, TestCase
from django.urls import reverse


class LoginViewsTest(TestCase):
    """Страница входа и ограничение частоты запросов."""

    def setUp(self):
        self.client = Client()

    def test_login_page_returns_200(self):
        resp = self.client.get(reverse('accounts:login'))
        self.assertEqual(resp.status_code, 200)

    def test_send_code_invalid_phone_returns_400(self):
        resp = self.client.post(
            reverse('accounts:send_code'),
            {'phone': '123'},
            content_type='application/x-www-form-urlencoded',
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get('ok'))
        self.assertIn('error', data)
