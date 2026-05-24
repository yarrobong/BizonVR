from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.views.auth import _safe_redirect_url

User = get_user_model()


class AuthRegressionTests(TestCase):
    def test_safe_redirect_rejects_external_next_url(self):
        # Guards against open redirects from the public auth entrypoints.
        self.assertEqual(_safe_redirect_url('https://evil.example/phish', 'accounts:profile'), 'accounts:profile')
        self.assertEqual(_safe_redirect_url('//evil.example/phish', 'accounts:profile'), 'accounts:profile')
        self.assertEqual(_safe_redirect_url('/accounts/profile/', 'accounts:profile'), '/accounts/profile/')

    def test_authenticated_login_view_ignores_external_next(self):
        # Guards against authenticated users being bounced to untrusted domains via next=.
        user = User.objects.create_user(username='9991234567', password='testpass')
        self.client.force_login(user)

        resp = self.client.get(reverse('accounts:login'), {'next': 'https://evil.example/phish'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('accounts:profile'))

    def test_legacy_code_login_endpoints_are_not_publicly_available(self):
        # Guards against restoring deprecated SMS/email code auth routes on the public website.
        for path in (
            '/accounts/send-code/',
            '/accounts/resend-code/',
            '/accounts/verify/',
            '/accounts/login/email-code/',
            '/accounts/login/email-code/verify/',
            '/accounts/password-reset/verify/',
            '/accounts/password-reset/set-password/',
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)

    def test_login_endpoint_does_not_accept_password_post(self):
        # Guards against the public GET login screen silently reviving POST password handling.
        response = self.client.post(reverse('accounts:login'), {
            'login': '+7 (999) 123-45-67',
            'password': 'OldPassword123!',
        })

        self.assertEqual(response.status_code, 405)
        self.assertIsNone(self.client.session.get('_auth_user_id'))
