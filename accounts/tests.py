"""Базовые тесты входа по телефону (Фаза 6)."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from config.legal_docs import LEGAL_BUNDLE_VERSION

from .models import Profile

User = get_user_model()


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


class CompleteRegistrationLegalVersionTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')

    def test_complete_registration_saves_privacy_policy_version(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('accounts:complete_registration'),
            {
                'contact_name': 'Иванов Иван Иванович',
                'agree_privacy': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        profile = Profile.objects.get(user=self.user)
        self.assertIsNotNone(profile.privacy_agreed_at)
        self.assertEqual(profile.privacy_policy_version, LEGAL_BUNDLE_VERSION)
