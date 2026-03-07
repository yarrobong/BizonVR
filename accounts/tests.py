"""Базовые тесты входа по телефону (Фаза 6)."""
import os
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core import mail
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from config.env import parse_bool_value
from config.legal_docs import LEGAL_BUNDLE_VERSION
from catalog.models import Category, City, PickupPoint, Product
from orders.models import Order

from .models import CommercialProposalContact, EmailVerificationCode, PhoneVerificationCode, Profile, SavedAddress

User = get_user_model()


class ConfigBoolParsingTest(SimpleTestCase):
    def test_release_like_values_are_false(self):
        for value in ('release', 'production', 'prod', '0', 'false', 'off'):
            with self.subTest(value=value):
                self.assertFalse(parse_bool_value(value, default=True, name='DEBUG'))

    def test_debug_like_values_are_true(self):
        for value in ('debug', 'development', 'dev', '1', 'true', 'on'):
            with self.subTest(value=value):
                self.assertTrue(parse_bool_value(value, default=False, name='DEBUG'))

    def test_unknown_value_raises_clear_error(self):
        with self.assertRaisesMessage(ValueError, 'Invalid truth value for DEBUG: maybe'):
            parse_bool_value('maybe', name='DEBUG')


class LoginViewsTest(TestCase):
    """Страница входа и ограничение частоты запросов."""
    LOGIN_PENDING_PHONE_SESSION_KEY = 'accounts:login:pending_phone'
    LOGIN_PENDING_SENT_AT_SESSION_KEY = 'accounts:login:last_sent_at'

    def setUp(self):
        self.client = Client()
        cache.clear()

    def test_login_page_returns_200(self):
        resp = self.client.get(reverse('accounts:login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Вход по SMS-коду')
        self.assertNotContains(resp, 'Вход только по коду из SMS')
        self.assertNotContains(resp, 'Вход по паролю')

    @override_settings(TURNSTILE_SITE_KEY='site-key', TURNSTILE_SECRET_KEY='secret-key')
    def test_login_page_renders_turnstile_when_configured(self):
        resp = self.client.get(reverse('accounts:login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'cf-turnstile')
        self.assertContains(resp, 'site-key')

    @override_settings(DEBUG=True, TURNSTILE_SITE_KEY='', TURNSTILE_SECRET_KEY='')
    def test_login_page_shows_turnstile_disabled_note_in_debug_without_keys(self):
        resp = self.client.get(reverse('accounts:login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Капча отключена локально')

    def test_authenticated_login_view_ignores_external_next(self):
        user = User.objects.create_user(username='9991234567', password='testpass')
        self.client.force_login(user)

        resp = self.client.get(reverse('accounts:login'), {'next': 'https://evil.example/phish'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('accounts:profile'))

    @override_settings(TURNSTILE_SITE_KEY='site-key', TURNSTILE_SECRET_KEY='secret-key')
    def test_send_code_requires_turnstile_token_when_enabled(self):
        resp = self.client.post(
            reverse('accounts:send_code'),
            {
                'phone': '+7 (999) 123-45-67',
                'agree_privacy': 'on',
            },
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get('ok'))
        self.assertIn('робот', data.get('error', ''))

    def test_send_code_invalid_phone_returns_400(self):
        resp = self.client.post(
            reverse('accounts:send_code'),
            {'phone': '123'},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get('ok'))
        self.assertIn('error', data)

    @override_settings(TURNSTILE_SITE_KEY='site-key', TURNSTILE_SECRET_KEY='secret-key')
    @patch('accounts.views.auth.verify_turnstile_token', return_value=(True, ''))
    @patch('accounts.views.auth.create_and_send_code', return_value=(True, ''))
    def test_send_code_success_saves_pending_phone_in_session(
        self,
        mocked_create_and_send_code,
        mocked_turnstile,
    ):
        resp = self.client.post(
            reverse('accounts:send_code'),
            {
                'phone': '+7 (999) 123-45-67',
                'agree_privacy': 'on',
                'cf-turnstile-response': 'token',
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('phone'), '9991234567')
        session = self.client.session
        self.assertEqual(session.get(self.LOGIN_PENDING_PHONE_SESSION_KEY), '9991234567')
        self.assertIsInstance(session.get(self.LOGIN_PENDING_SENT_AT_SESSION_KEY), int)
        mocked_turnstile.assert_called_once()
        mocked_create_and_send_code.assert_called_once()

    @patch('accounts.services.generate_code', return_value='654321')
    @patch('accounts.services.send_sms', return_value=False)
    def test_failed_sms_does_not_leave_valid_code(self, mocked_send_sms, mocked_generate_code):
        from .services import create_and_send_code

        ok, error = create_and_send_code('79991234567')
        self.assertFalse(ok)
        self.assertIn('Не удалось отправить SMS', error)
        self.assertFalse(PhoneVerificationCode.objects.filter(phone='9991234567').exists())

    def test_verify_rate_limit_applies_per_phone_not_only_per_ip(self):
        PhoneVerificationCode.objects.create(phone='9991234567', code='123456')

        for attempt in range(5):
            response = self.client.post(
                reverse('accounts:verify_code'),
                {'phone': '9991234567', 'code': '000000'},
                REMOTE_ADDR=f'10.0.0.{attempt + 1}',
            )
            self.assertEqual(response.status_code, 200)

        blocked_response = self.client.post(
            reverse('accounts:verify_code'),
            {'phone': '9991234567', 'code': '000000'},
            REMOTE_ADDR='10.0.0.99',
        )
        self.assertEqual(blocked_response.status_code, 200)
        self.assertContains(blocked_response, 'лимит попыток')

    def test_logout_requires_post(self):
        user = User.objects.create_user(username='79995554433', password='testpass')
        self.client.force_login(user)

        get_response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse('accounts:logout'))
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(post_response.url, reverse('home'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_resend_code_without_pending_session_returns_400(self):
        resp = self.client.post(reverse('accounts:resend_code'))
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get('ok'))
        self.assertIn('истекла', data.get('error', ''))

    @override_settings(TURNSTILE_SITE_KEY='site-key', TURNSTILE_SECRET_KEY='secret-key')
    @patch('accounts.views.auth.verify_turnstile_token', return_value=(True, ''))
    @patch('accounts.views.auth.create_and_send_code', return_value=(True, ''))
    def test_resend_code_is_rate_limited_for_one_minute(
        self,
        mocked_create_and_send_code,
        mocked_turnstile,
    ):
        send_resp = self.client.post(
            reverse('accounts:send_code'),
            {
                'phone': '+7 (999) 123-45-67',
                'agree_privacy': 'on',
                'cf-turnstile-response': 'token',
            },
        )
        self.assertEqual(send_resp.status_code, 200)

        resend_resp = self.client.post(reverse('accounts:resend_code'))
        self.assertEqual(resend_resp.status_code, 429)
        data = resend_resp.json()
        self.assertFalse(data.get('ok'))
        self.assertGreater(data.get('resend_available_in', 0), 0)

    @patch('accounts.views.auth.verify_turnstile_token')
    @patch('accounts.views.auth.create_and_send_code', return_value=(True, ''))
    def test_resend_code_after_minute_succeeds_without_turnstile(
        self,
        mocked_create_and_send_code,
        mocked_turnstile,
    ):
        session = self.client.session
        session[self.LOGIN_PENDING_PHONE_SESSION_KEY] = '9991234567'
        session[self.LOGIN_PENDING_SENT_AT_SESSION_KEY] = int((timezone.now() - timezone.timedelta(seconds=61)).timestamp())
        session.save()
        cache.clear()

        resend_resp = self.client.post(reverse('accounts:resend_code'))
        self.assertEqual(resend_resp.status_code, 200)
        data = resend_resp.json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('resend_available_in'), 60)
        mocked_create_and_send_code.assert_called_once()
        mocked_turnstile.assert_not_called()


class OtpLifecycleTest(TestCase):
    @patch('accounts.services.generate_code', return_value='222222')
    @patch('accounts.services.send_sms', return_value=True)
    def test_new_code_invalidates_previous_active_code(self, mocked_send_sms, mocked_generate_code):
        old_code = PhoneVerificationCode.objects.create(phone='9991234567', code='111111')
        old_code.created_at = timezone.now() - timezone.timedelta(seconds=61)
        old_code.save(update_fields=['created_at'])

        from .services import create_and_send_code, verify_sms_code

        ok, error = create_and_send_code('79991234567')
        self.assertTrue(ok)
        self.assertEqual(error, '')

        old_code.refresh_from_db()
        self.assertIsNotNone(old_code.used_at)
        self.assertTrue(PhoneVerificationCode.objects.filter(phone='9991234567', code='222222', used_at__isnull=True).exists())
        self.assertEqual(verify_sms_code('79991234567', '111111')[0], False)
        self.assertEqual(verify_sms_code('79991234567', '222222')[0], True)

    def test_used_code_cannot_be_reused(self):
        from .services import verify_sms_code

        PhoneVerificationCode.objects.create(phone='9991234567', code='123456')

        first_ok, _ = verify_sms_code('79991234567', '123456', consume=True)
        second_ok, second_error = verify_sms_code('79991234567', '123456', consume=True)

        self.assertTrue(first_ok)
        self.assertFalse(second_ok)
        self.assertEqual(second_error, 'Неверный или устаревший код')


class PasswordAccessRecoveryTest(TestCase):
    PASSWORD_RESET_PENDING_PHONE_SESSION_KEY = 'accounts:password-reset:pending-phone'
    PASSWORD_RESET_VERIFIED_USER_SESSION_KEY = 'accounts:password-reset:verified-user-id'

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='9991234567',
            password='OldPassword123!',
            email='verified@example.com',
        )
        self.profile = Profile.objects.create(
            user=self.user,
            phone='9991234567',
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
            email_verified_at=timezone.now(),
        )
        cache.clear()

    def test_login_endpoint_does_not_accept_password_post(self):
        response = self.client.post(reverse('accounts:login'), {
            'login': '+7 (999) 123-45-67',
            'password': 'OldPassword123!',
        })

        self.assertEqual(response.status_code, 405)
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    @patch('accounts.services.generate_code', return_value='112233')
    def test_phone_password_reset_sets_new_password_and_logs_user_in(self, mocked_generate_code):
        request_response = self.client.post(reverse('accounts:password_reset_request'), {
            'method': 'phone',
            'phone': '+7 (999) 123-45-67',
        })
        self.assertEqual(request_response.status_code, 302)
        self.assertEqual(request_response.url, f"{reverse('accounts:password_reset_phone_verify')}?phone=9991234567")
        self.assertEqual(self.client.session.get(self.PASSWORD_RESET_PENDING_PHONE_SESSION_KEY), '9991234567')

        verify_response = self.client.post(reverse('accounts:password_reset_phone_verify'), {
            'phone': '9991234567',
            'code': '112233',
        })
        self.assertEqual(verify_response.status_code, 302)
        self.assertEqual(verify_response.url, reverse('accounts:password_reset_set_password'))
        self.assertEqual(self.client.session.get(self.PASSWORD_RESET_VERIFIED_USER_SESSION_KEY), self.user.pk)

        set_password_response = self.client.post(reverse('accounts:password_reset_set_password'), {
            'new_password1': 'NewStrongPass456!',
            'new_password2': 'NewStrongPass456!',
        })
        self.assertEqual(set_password_response.status_code, 302)
        self.assertEqual(set_password_response.url, reverse('accounts:profile'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPass456!'))
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))
        self.assertNotIn(self.PASSWORD_RESET_PENDING_PHONE_SESSION_KEY, self.client.session)
        self.assertNotIn(self.PASSWORD_RESET_VERIFIED_USER_SESSION_KEY, self.client.session)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        PASSWORD_RESET_EMAIL_SUBJECT='Восстановление доступа BizonVR',
    )
    def test_email_password_reset_sends_mail_and_sets_new_password(self):
        request_response = self.client.post(reverse('accounts:password_reset_request'), {
            'method': 'email',
            'email': 'verified@example.com',
        })

        self.assertEqual(request_response.status_code, 302)
        self.assertEqual(request_response.url, f"{reverse('accounts:password_reset_request')}?sent=email")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/password-reset/confirm/', mail.outbox[0].body)

        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        confirm_response = self.client.post(
            reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token}),
            {
                'new_password1': 'EmailStrong789!',
                'new_password2': 'EmailStrong789!',
            },
        )

        self.assertEqual(confirm_response.status_code, 302)
        self.assertEqual(confirm_response.url, reverse('accounts:profile'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('EmailStrong789!'))
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))


class SmsServiceTest(SimpleTestCase):
    @override_settings(SMS_CODE_TTL_MINUTES=15)
    def test_build_sms_message_uses_pretty_default_template(self):
        from .services import build_sms_message

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SMS_MESSAGE_TEMPLATE', None)
            message = build_sms_message('123456')

        self.assertEqual(message, 'BizonVR: код 123456. Действует 15 мин. Не сообщайте его никому.')

    @override_settings(SMS_CODE_TTL_MINUTES=7)
    def test_build_sms_message_supports_custom_template(self):
        from .services import build_sms_message

        with patch.dict(os.environ, {'SMS_MESSAGE_TEMPLATE': 'Код входа {code}, срок {ttl_minutes} мин.'}, clear=False):
            message = build_sms_message('654321')

        self.assertEqual(message, 'Код входа 654321, срок 7 мин.')

    @override_settings(SMS_CODE_TTL_MINUTES=9)
    def test_build_sms_message_falls_back_on_invalid_template(self):
        from .services import build_sms_message

        with patch.dict(os.environ, {'SMS_MESSAGE_TEMPLATE': 'Код {unknown}'}, clear=False):
            message = build_sms_message('111222')

        self.assertEqual(message, 'BizonVR: код 111222. Действует 9 мин. Не сообщайте его никому.')

    @override_settings(
        EXOLVE_API_KEY='secret-api-key',
        EXOLVE_SENDER='BizonVR',
        EXOLVE_API_BASE='https://api.exolve.ru/messaging/v1',
    )
    @patch('accounts.services.requests.post')
    def test_exolve_request_uses_bearer_and_json_payload(self, mocked_post):
        from .services import _send_exolve

        response = Mock()
        response.json.return_value = {'message_id': 'sms-id'}
        response.raise_for_status.return_value = None
        mocked_post.return_value = response

        ok = _send_exolve('79991234567', '123456')

        self.assertTrue(ok)
        mocked_post.assert_called_once_with(
            'https://api.exolve.ru/messaging/v1/SendSMS',
            json={
                'number': 'BizonVR',
                'destination': '79991234567',
                'text': 'BizonVR: код 123456. Действует 10 мин. Не сообщайте его никому.',
            },
            headers={
                'Authorization': 'Bearer secret-api-key',
                'Content-Type': 'application/json',
            },
            timeout=10,
        )

    @override_settings(
        EXOLVE_API_KEY='secret-api-key',
        EXOLVE_SENDER='BizonVR',
        EXOLVE_API_BASE='https://api.exolve.ru/messaging/v1',
    )
    @patch('accounts.services.requests.post')
    def test_exolve_request_returns_false_on_invalid_json(self, mocked_post):
        from .services import _send_exolve

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError('bad payload')
        mocked_post.return_value = response

        self.assertFalse(_send_exolve('79991234567', '123456'))

    @patch('accounts.services.requests.post')
    def test_smsru_request_uses_message_template_and_sender(self, mocked_post):
        from .services import _send_smsru

        response = Mock()
        response.json.return_value = {'status': 'OK'}
        response.raise_for_status.return_value = None
        mocked_post.return_value = response

        with patch.dict(
            os.environ,
            {
                'SMS_SENDER_NAME': 'BizonVR',
                'SMS_MESSAGE_TEMPLATE': 'Ваш код {code}. Срок {ttl_minutes} мин.',
            },
            clear=False,
        ):
            ok = _send_smsru('79991234567', '123456', 'secret-api-key', client_ip='203.0.113.10')

        self.assertTrue(ok)
        mocked_post.assert_called_once_with(
            'https://sms.ru/sms/send',
            data={
                'api_id': 'secret-api-key',
                'to': '79991234567',
                'msg': 'Ваш код 123456. Срок 10 мин.',
                'json': 1,
                'from': 'BizonVR',
                'ip': '203.0.113.10',
            },
            timeout=10,
        )


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='BizonVR <no-reply@bizonvr.ru>',
    SITE_URL='https://bizonvr.ru',
    SITE_CONTACT_EMAIL='support@bizonvr.ru',
    SITE_CONTACT_PHONE='+7 (932) 491-04-82',
    EMAIL_CODE_TTL_MINUTES=15,
)
class EmailVerificationServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='9991234567', password='testpass')
        self.profile = Profile.objects.create(user=self.user, phone='9991234567')

    @patch('accounts.services.generate_code', return_value='112233')
    def test_create_and_send_email_code_sends_html_email(self, mocked_generate_code):
        from .services import create_and_send_email_code

        ok, error = create_and_send_email_code(self.user, 'client@example.com')

        self.assertTrue(ok)
        self.assertEqual(error, '')
        self.assertTrue(EmailVerificationCode.objects.filter(user=self.user, email='client@example.com').exists())
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['client@example.com'])
        self.assertIn('112233', message.body)
        self.assertEqual(len(message.alternatives), 1)
        self.assertIn('112233', message.alternatives[0].content)

    def test_confirm_email_verification_sets_user_email_once(self):
        from .services import confirm_email_verification

        EmailVerificationCode.objects.create(user=self.user, email='client@example.com', code='445566')

        ok, error = confirm_email_verification(self.user, 'client@example.com', '445566')

        self.assertTrue(ok)
        self.assertEqual(error, '')
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.email, 'client@example.com')
        self.assertIsNotNone(self.profile.email_verified_at)

        second_ok, second_error = confirm_email_verification(self.user, 'client@example.com', '445566')
        self.assertFalse(second_ok)
        self.assertIn('уже подтверждён', second_error)


class TurnstileServiceTest(SimpleTestCase):
    @override_settings(DEBUG=True, TURNSTILE_SITE_KEY='', TURNSTILE_SECRET_KEY='')
    def test_turnstile_bypasses_in_debug_without_keys(self):
        from .services import verify_turnstile_token

        ok, error = verify_turnstile_token('')
        self.assertTrue(ok)
        self.assertEqual(error, '')

    @override_settings(
        DEBUG=False,
        TURNSTILE_SITE_KEY='site-key',
        TURNSTILE_SECRET_KEY='secret-key',
        TURNSTILE_VERIFY_URL='https://turnstile.test/siteverify',
    )
    @patch('accounts.services.requests.post')
    def test_turnstile_accepts_valid_token(self, mocked_post):
        from .services import verify_turnstile_token

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'success': True}
        mocked_post.return_value = response

        ok, error = verify_turnstile_token('token-123', client_ip='203.0.113.5')

        self.assertTrue(ok)
        self.assertEqual(error, '')
        mocked_post.assert_called_once_with(
            'https://turnstile.test/siteverify',
            data={
                'secret': 'secret-key',
                'response': 'token-123',
                'remoteip': '203.0.113.5',
            },
            timeout=10,
        )

    @override_settings(
        DEBUG=False,
        TURNSTILE_SITE_KEY='site-key',
        TURNSTILE_SECRET_KEY='secret-key',
        TURNSTILE_VERIFY_URL='https://turnstile.test/siteverify',
    )
    @patch('accounts.services.requests.post')
    def test_turnstile_rejects_invalid_token(self, mocked_post):
        from .services import verify_turnstile_token

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'success': False, 'error-codes': ['invalid-input-response']}
        mocked_post.return_value = response

        ok, error = verify_turnstile_token('bad-token')

        self.assertFalse(ok)
        self.assertIn('проверку', error)


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

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        SITE_URL='https://bizonvr.ru',
        DEFAULT_FROM_EMAIL='BizonVR <no-reply@bizonvr.ru>',
    )
    @patch('accounts.services.generate_code', return_value='551122')
    def test_complete_registration_with_email_sends_verification_and_redirects_to_profile(
        self,
        mocked_generate_code,
    ):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('accounts:complete_registration'),
            {
                'contact_name': 'Иванов Иван Иванович',
                'email': 'client@example.com',
                'agree_privacy': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('accounts:profile')}#security")
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.contact_name, 'Иванов Иван Иванович')
        self.assertIsNotNone(profile.privacy_agreed_at)
        self.assertTrue(
            EmailVerificationCode.objects.filter(
                user=self.user,
                email='client@example.com',
                used_at__isnull=True,
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('551122', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['client@example.com'])


class ProfileDashboardTest(TestCase):
    PHONE_CHANGE_SESSION_KEY = 'accounts:profile:phone_change_pending'

    def setUp(self):
        self.client = Client()
        cache.clear()
        self.user = User.objects.create_user(username='9991234567', password='testpass')
        self.profile = Profile.objects.create(
            user=self.user,
            phone='9991234567',
            contact_name='Иван Иванов',
        )
        Order.objects.create(user=self.user, status=Order.STATUS_NEW, total=Decimal('1000.00'))
        Order.objects.create(user=self.user, status=Order.STATUS_PAID, total=Decimal('2500.00'))
        Order.objects.create(user=self.user, status=Order.STATUS_DONE, total=Decimal('5000.00'))

    def test_profile_requires_login(self):
        resp = self.client.get(reverse('accounts:profile'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))

    def test_profile_dashboard_without_balance_block(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('accounts:profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Личный кабинет')
        self.assertNotContains(resp, '>Баланс<', html=False)
        self.assertContains(resp, 'Последние заказы')

    def test_save_profile_action_updates_only_profile(self):
        CommercialProposalContact.objects.create(
            user=self.user,
            phone='+7 (900) 000-00-01',
            email='admin-only@example.com',
        )
        self.client.force_login(self.user)
        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'save_profile',
            'contact_name': 'Петров Петр Петрович',
            'cp_phone': '+7 (922) 111-22-33',
            'cp_email': 'manager@example.com',
        })
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.contact_name, 'Петров Петр Петрович')
        cp_contact = CommercialProposalContact.objects.get(user=self.user)
        self.assertEqual(cp_contact.phone, '+7 (900) 000-00-01')
        self.assertEqual(cp_contact.email, 'admin-only@example.com')

    def test_send_phone_code_action_creates_pending_state_and_sms_code(self):
        self.client.force_login(self.user)
        new_phone = '9221112233'
        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'send_phone_code',
            'new_phone': '+7 (922) 111-22-33',
        })
        self.assertEqual(resp.status_code, 200)
        session = self.client.session
        self.assertEqual(session.get(self.PHONE_CHANGE_SESSION_KEY), new_phone)
        self.assertTrue(
            PhoneVerificationCode.objects.filter(phone=new_phone).exists(),
            msg='Ожидался созданный SMS-код для смены номера',
        )

    def test_confirm_phone_code_updates_login_phone_and_keeps_session(self):
        self.client.force_login(self.user)
        new_phone = '9221112233'
        session = self.client.session
        session[self.PHONE_CHANGE_SESSION_KEY] = new_phone
        session.save()
        PhoneVerificationCode.objects.create(phone=new_phone, code='123456')

        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'confirm_phone_code',
            'new_phone': '+7 (922) 111-22-33',
            'code': '123456',
        })
        self.assertEqual(resp.status_code, 200)

        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.username, new_phone)
        self.assertEqual(self.profile.phone, new_phone)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))
        self.assertNotIn(self.PHONE_CHANGE_SESSION_KEY, self.client.session)

    def test_confirm_phone_code_invalid_code_keeps_old_phone(self):
        self.client.force_login(self.user)
        new_phone = '9221112233'
        session = self.client.session
        session[self.PHONE_CHANGE_SESSION_KEY] = new_phone
        session.save()
        PhoneVerificationCode.objects.create(phone=new_phone, code='654321')

        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'confirm_phone_code',
            'new_phone': '+7 (922) 111-22-33',
            'code': '111111',
        })
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.username, '9991234567')
        self.assertEqual(self.profile.phone, '9991234567')

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='BizonVR <no-reply@bizonvr.ru>',
    )
    @patch('accounts.services.generate_code', return_value='332211')
    def test_send_email_code_action_creates_pending_code_and_mail(self, mocked_generate_code):
        self.client.force_login(self.user)

        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'send_email_code',
            'email': 'client@example.com',
        })

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            EmailVerificationCode.objects.filter(user=self.user, email='client@example.com', used_at__isnull=True).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(resp, 'Письмо отправлено на:')

    def test_confirm_email_code_updates_user_email_and_profile_status(self):
        self.client.force_login(self.user)
        EmailVerificationCode.objects.create(user=self.user, email='client@example.com', code='123456')

        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'confirm_email_code',
            'email': 'client@example.com',
            'code': '123456',
        })

        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.email, 'client@example.com')
        self.assertIsNotNone(self.profile.email_verified_at)

        second_resp = self.client.post(reverse('accounts:profile'), {
            'action': 'send_email_code',
            'email': 'new@example.com',
        })
        self.assertContains(second_resp, 'Email уже подтверждён')
        self.assertFalse(EmailVerificationCode.objects.filter(user=self.user, email='new@example.com').exists())

    def test_balance_history_route_still_available(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('accounts:balance_history'))
        self.assertEqual(resp.status_code, 200)


class SavedAddressAndCheckoutTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='9991234567', password='testpass')
        self.profile = Profile.objects.create(
            user=self.user,
            phone='9991234567',
            contact_name='Иван Иванов',
        )
        self.city = City.objects.create(name='Екатеринбург', slug='ekb')
        self.pickup_point = PickupPoint.objects.create(
            city=self.city,
            name='Пункт выдачи',
            address='ул. Мира, 1',
        )
        self.category = Category.objects.create(name='Тест', slug='test-address')
        self.product = Product.objects.create(
            category=self.category,
            name='Товар для checkout',
            slug='checkout-product',
            price=Decimal('100.00'),
            is_active=True,
        )

    def _address_payload(self, **overrides):
        payload = {
            'action': 'save_address',
            'label': 'Дом',
            'recipient_name': 'Иван Иванов',
            'phone': '+7 (999) 123-45-67',
            'email': 'user@example.com',
            'delivery_type': 'pickup',
            'pickup_point': str(self.pickup_point.pk),
            'address': '',
            'comment': 'Позвонить заранее',
            'is_default': 'on',
        }
        payload.update(overrides)
        return payload

    def test_profile_renders_saved_addresses_and_create_address(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse('accounts:profile'), self._address_payload())
        self.assertEqual(resp.status_code, 200)
        address = SavedAddress.objects.get(user=self.user)
        self.assertEqual(address.label, 'Дом')
        self.assertTrue(address.is_default)
        self.assertEqual(address.phone, '9991234567')
        self.assertContains(resp, 'Адрес сохранён.')
        self.assertContains(resp, 'Дом')

    def test_profile_can_edit_saved_address(self):
        address = SavedAddress.objects.create(
            user=self.user,
            label='Дом',
            recipient_name='Иван Иванов',
            phone='9991234567',
            email='old@example.com',
            delivery_type='courier',
            address='Старый адрес',
            is_default=True,
        )
        self.client.force_login(self.user)
        resp = self.client.post(reverse('accounts:profile'), self._address_payload(
            address_id=str(address.pk),
            label='Офис',
            delivery_type='courier',
            pickup_point='',
            address='Новый адрес',
            is_default='',
        ))
        self.assertEqual(resp.status_code, 200)
        address.refresh_from_db()
        self.assertEqual(address.label, 'Офис')
        self.assertEqual(address.address, 'Новый адрес')
        self.assertTrue(address.is_default)
        self.assertContains(resp, 'Офис')

    def test_delete_default_address_promotes_next_one(self):
        default_address = SavedAddress.objects.create(
            user=self.user,
            label='Дом',
            recipient_name='Иван Иванов',
            phone='9991234567',
            delivery_type='courier',
            address='Домашний адрес',
            is_default=True,
        )
        other_address = SavedAddress.objects.create(
            user=self.user,
            label='Офис',
            recipient_name='Иван Иванов',
            phone='9991234567',
            delivery_type='courier',
            address='Офисный адрес',
            is_default=False,
        )
        self.client.force_login(self.user)
        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'delete_address',
            'address_id': str(default_address.pk),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SavedAddress.objects.filter(pk=default_address.pk).exists())
        other_address.refresh_from_db()
        self.assertTrue(other_address.is_default)
        self.assertContains(resp, 'Адрес удалён.')

    def test_set_default_address_updates_only_user_addresses(self):
        first = SavedAddress.objects.create(
            user=self.user,
            label='Дом',
            recipient_name='Иван Иванов',
            phone='9991234567',
            delivery_type='courier',
            address='Домашний адрес',
            is_default=True,
        )
        second = SavedAddress.objects.create(
            user=self.user,
            label='Офис',
            recipient_name='Иван Иванов',
            phone='9991234567',
            delivery_type='courier',
            address='Офисный адрес',
            is_default=False,
        )
        self.client.force_login(self.user)
        resp = self.client.post(reverse('accounts:profile'), {
            'action': 'set_default_address',
            'address_id': str(second.pk),
        })
        self.assertEqual(resp.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertContains(resp, 'Адрес по умолчанию обновлён.')

    def test_foreign_address_cannot_be_edited_or_deleted(self):
        other_user = User.objects.create_user(username='9990000000', password='testpass')
        foreign_address = SavedAddress.objects.create(
            user=other_user,
            label='Чужой адрес',
            recipient_name='Другой пользователь',
            phone='9990000000',
            delivery_type='courier',
            address='Чужой адрес',
            is_default=True,
        )
        self.client.force_login(self.user)

        edit_resp = self.client.post(reverse('accounts:profile'), self._address_payload(
            address_id=str(foreign_address.pk),
            label='Попытка взлома',
        ))
        self.assertEqual(edit_resp.status_code, 200)
        self.assertContains(edit_resp, 'Адрес не найден.')
        self.assertEqual(SavedAddress.objects.filter(user=self.user).count(), 0)

        delete_resp = self.client.post(reverse('accounts:profile'), {
            'action': 'delete_address',
            'address_id': str(foreign_address.pk),
        })
        self.assertEqual(delete_resp.status_code, 200)
        self.assertContains(delete_resp, 'Адрес не найден.')
        self.assertTrue(SavedAddress.objects.filter(pk=foreign_address.pk).exists())

    def test_checkout_prefills_default_saved_address(self):
        SavedAddress.objects.create(
            user=self.user,
            label='Дом',
            recipient_name='Петров Петр',
            phone='9991234567',
            email='delivery@example.com',
            delivery_type='pickup',
            pickup_point=self.pickup_point,
            comment='Комментарий к доставке',
            is_default=True,
        )
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_saved_address_id'], SavedAddress.objects.get(user=self.user).pk)
        self.assertEqual(resp.context['form'].initial['delivery_type'], 'pickup')
        self.assertEqual(resp.context['form'].initial['pickup_point'], self.pickup_point.pk)
        self.assertEqual(resp.context['form'].initial['email'], 'delivery@example.com')
        self.assertContains(resp, 'Комментарий к доставке')


class VerifyCodeTemplateTest(TestCase):
    LOGIN_PENDING_PHONE_SESSION_KEY = 'accounts:login:pending_phone'
    LOGIN_PENDING_SENT_AT_SESSION_KEY = 'accounts:login:last_sent_at'

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='9991234567', password='testpass')
        cache.clear()

    @patch('accounts.views.auth.is_sms_debug_mode', return_value=True)
    def test_verify_code_page_shows_terminal_hint_in_debug_mode(self, mocked_debug):
        resp = self.client.get(reverse('accounts:verify_code'), {'phone': self.user.username})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'терминале, где запущен сервер')
        mocked_debug.assert_called()

    @patch('accounts.views.auth.is_sms_debug_mode', return_value=False)
    def test_verify_code_page_hides_terminal_hint_in_live_mode(self, mocked_debug):
        resp = self.client.get(reverse('accounts:verify_code'), {'phone': self.user.username})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'терминале, где запущен сервер')
        mocked_debug.assert_called()

    def test_verify_code_page_hides_login_info_block_when_session_pending(self):
        session = self.client.session
        session[self.LOGIN_PENDING_PHONE_SESSION_KEY] = self.user.username
        session[self.LOGIN_PENDING_SENT_AT_SESSION_KEY] = int(timezone.now().timestamp())
        session.save()

        resp = self.client.get(reverse('accounts:verify_code'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Подтвердить вход')
        self.assertContains(resp, 'Изменить номер')
        self.assertNotContains(resp, '6 цифр')

    def test_verify_code_page_shows_change_number_link_with_next(self):
        resp = self.client.get(reverse('accounts:verify_code'), {
            'phone': self.user.username,
            'next': '/orders/checkout/',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Код отправлен на')
        self.assertContains(resp, f'href="{reverse("accounts:login")}?next=/orders/checkout/"')
        self.assertNotContains(resp, '6 цифр')
