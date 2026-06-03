"""Базовые тесты аккаунта и аутентификации."""
import json
import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core import mail
from django.test import Client, SimpleTestCase, TestCase, override_settings, tag
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from config.env import parse_bool_value
from config.legal_docs import LEGAL_BUNDLE_VERSION
from catalog.models import Category, City, PickupPoint, Product, ProductStock
from orders.models import Order

from accounts.models import (
    CommercialProposalContact,
    EmailVerificationCode,
    NotificationPreference,
    PhoneVerificationCode,
    Profile,
    SavedAddress,
)
from accounts.tests.factories import create_user
from accounts.views.profile import _build_profile_setup_checklist
from catalog.tests.factories import create_category, create_product
from orders.tests.factories import create_order

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
    """Страница входа, регистрация и публичный auth-контракт."""

    def setUp(self):
        cache.clear()

    def test_login_page_returns_200(self):
        resp = self.client.get(reverse('accounts:login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Вход по email и паролю')
        self.assertContains(resp, 'Email')
        self.assertContains(resp, 'Пароль')
        self.assertNotContains(resp, 'Телефон')
        self.assertNotContains(resp, 'Получить код на email')
        self.assertNotContains(resp, 'Войти по коду')

    def test_login_page_does_not_render_sms_turnstile(self):
        resp = self.client.get(reverse('accounts:login'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'cf-turnstile')
        self.assertNotContains(resp, 'Получить код по SMS')

    def test_register_page_uses_same_template_with_register_panel(self):
        resp = self.client.get(reverse('accounts:register'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Создать аккаунт с паролем')
        self.assertContains(resp, 'Этот email станет вашим логином и адресом сервисных писем.')
        self.assertContains(resp, 'registrationOpen: true', html=False)

    def test_login_page_opens_registration_form_for_mode_register(self):
        resp = self.client.get(reverse('accounts:login'), {'mode': 'register'})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'registrationOpen: true', html=False)

    def test_cart_template_uses_register_route_for_account_creation(self):
        template = (Path(settings.BASE_DIR) / 'templates/catalog/partials/cart_page_content.html').read_text(encoding='utf-8')

        self.assertIn("{% url 'accounts:register' %}?next={% url 'orders:checkout' %}", template)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='BizonVR <no-reply@bizonvr.ru>',
        EMAIL_VERIFICATION_SUBJECT='Код подтверждения BizonVR',
        SITE_URL='https://bizonvr.ru',
    )
    @patch('accounts.services.generate_code', return_value='112233')
    def test_register_creates_unverified_account_and_redirects_to_email_confirmation(self, mocked_generate_code):
        response = self.client.post(reverse('accounts:register'), {
            'contact_name': 'Иван Иванов',
            'email': 'client@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_privacy': 'on',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('accounts:register_confirm')}?email=client%40example.com")

        user = User.objects.get(email='client@example.com')
        profile = Profile.objects.get(user=user)
        self.assertTrue(user.check_password('StrongPass123!'))
        self.assertNotEqual(user.username, 'client@example.com')
        self.assertEqual(profile.contact_name, 'Иван Иванов')
        self.assertFalse(bool(profile.email_verified_at))
        self.assertIsNotNone(profile.privacy_agreed_at)
        self.assertEqual(profile.privacy_policy_version, LEGAL_BUNDLE_VERSION)
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        self.assertTrue(EmailVerificationCode.objects.filter(user=user, email='client@example.com', used_at__isnull=True).exists())
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Код подтверждения BizonVR')
        self.assertIn('Код подтверждения: 112233', message.body)
        self.assertEqual(len(message.alternatives), 1)
        self.assertIn('Код подтверждения: 112233', message.alternatives[0].content)
        self.assertIn('https://bizonvr.ru/accounts/register/confirm/', message.body)
        self.assertIn(reverse('accounts:register_confirm'), message.body)

    def test_register_confirm_template_supports_one_time_code_autofill(self):
        response = self.client.get(reverse('accounts:register_confirm'), {'email': 'client@example.com'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'autocomplete="one-time-code"', html=False)
        self.assertContains(response, 'inputmode="numeric"', html=False)
        self.assertContains(response, 'pattern="[0-9]{6}"', html=False)
        self.assertContains(response, 'maxlength="6"', html=False)

    def test_register_confirm_success_logs_user_in_and_marks_email_verified(self):
        user = User.objects.create_user(
            username='user_confirm_success',
            email='client@example.com',
            password='StrongPass123!',
        )
        profile = Profile.objects.create(
            user=user,
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        EmailVerificationCode.objects.create(user=user, email='client@example.com', code='123456')

        response = self.client.post(reverse('accounts:register_confirm'), {
            'email': 'client@example.com',
            'code': '123456',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.pk))
        profile.refresh_from_db()
        self.assertIsNotNone(profile.email_verified_at)
        self.assertFalse(EmailVerificationCode.objects.filter(user=user, used_at__isnull=True).exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='BizonVR <no-reply@bizonvr.ru>',
        EMAIL_CODE_COOLDOWN_SECONDS=0,
    )
    @patch('accounts.services.generate_code', return_value='654321')
    def test_register_confirm_resend_creates_new_code_and_invalidates_previous(self, mocked_generate_code):
        user = User.objects.create_user(
            username='user_resend_email',
            email='client@example.com',
            password='StrongPass123!',
        )
        Profile.objects.create(user=user, contact_name='Иван Иванов')
        old_code = EmailVerificationCode.objects.create(user=user, email='client@example.com', code='123456')

        response = self.client.post(reverse('accounts:register_confirm'), {
            'action': 'resend_email',
            'email': 'client@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Письмо с новым кодом отправлено.')
        old_code.refresh_from_db()
        self.assertIsNotNone(old_code.used_at)
        self.assertTrue(EmailVerificationCode.objects.filter(user=user, email='client@example.com', code='654321', used_at__isnull=True).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Код подтверждения: 654321', mail.outbox[0].body)

    def test_register_confirm_rejects_wrong_expired_and_used_codes(self):
        scenarios = (
            ('wrong@example.com', '123456', '000000', None),
            ('expired@example.com', '222222', '222222', timezone.now() - timezone.timedelta(minutes=16)),
            ('used@example.com', '333333', '333333', 'used'),
        )

        for email, stored_code, posted_code, created_at in scenarios:
            with self.subTest(email=email):
                user = User.objects.create_user(
                    username=f'user_{email.split("@")[0]}',
                    email=email,
                    password='StrongPass123!',
                )
                profile = Profile.objects.create(user=user, contact_name='Иван Иванов')
                record = EmailVerificationCode.objects.create(user=user, email=email, code=stored_code)
                if created_at == 'used':
                    record.used_at = timezone.now()
                    record.save(update_fields=['used_at'])
                elif created_at is not None:
                    record.created_at = created_at
                    record.save(update_fields=['created_at'])

                response = self.client.post(reverse('accounts:register_confirm'), {
                    'email': email,
                    'code': posted_code,
                })

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Неверный или устаревший код')
                profile.refresh_from_db()
                self.assertIsNone(profile.email_verified_at)

    def test_register_rejects_duplicate_email(self):
        existing = User.objects.create_user(
            username='9991234567',
            email='client@example.com',
            password='OldPassword123!',
        )
        Profile.objects.create(
            user=existing,
            phone='9991234567',
            email_verified_at=timezone.now(),
        )

        response = self.client.post(reverse('accounts:register'), {
            'contact_name': 'Иван Иванов',
            'email': 'client@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_privacy': 'on',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Аккаунт с таким email уже существует.')
        self.assertEqual(User.objects.filter(email='client@example.com').count(), 1)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='BizonVR <no-reply@bizonvr.ru>',
        SITE_URL='https://bizonvr.ru',
        EMAIL_CODE_COOLDOWN_SECONDS=60,
    )
    @patch('accounts.services.generate_code', return_value='112233')
    def test_register_throttling_blocks_repeated_attempts_without_sending_email(
        self,
        mocked_generate_code,
    ):
        first_response = self.client.post(reverse('accounts:register'), {
            'contact_name': 'Иван Иванов',
            'email': 'client@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_privacy': 'on',
        })

        second_response = self.client.post(reverse('accounts:register'), {
            'contact_name': 'Петр Петров',
            'email': 'next@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'agree_privacy': 'on',
        })

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, 'Подождите 60 сек. перед новой регистрацией.')
        self.assertTrue(User.objects.filter(email='client@example.com').exists())
        self.assertFalse(User.objects.filter(email='next@example.com').exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_password_login_accepts_registered_email_without_phone(self):
        user = User.objects.create_user(
            username='user_test_login',
            email='client@example.com',
            password='StrongPass123!',
        )
        Profile.objects.create(
            user=user,
            phone=None,
            contact_name='Иван Иванов',
            email_verified_at=timezone.now(),
            privacy_agreed_at=timezone.now(),
        )

        response = self.client.post(reverse('accounts:password_login'), {
            'login': 'client@example.com',
            'password': 'StrongPass123!',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))
        self.assertEqual(self.client.session.get('_auth_user_id'), str(user.pk))

    def test_password_login_rejects_unverified_email_account(self):
        user = User.objects.create_user(
            username='user_email_only',
            email='oneboardshol@gmail.com',
            password='StrongPass123!',
        )

        response = self.client.post(reverse('accounts:password_login'), {
            'login': 'oneboardshol@gmail.com',
            'password': 'StrongPass123!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Подтвердите email')
        self.assertIsNone(self.client.session.get('_auth_user_id'))
        self.assertTrue(Profile.objects.filter(user=user).exists())

    @patch('accounts.services.generate_code', return_value='654321')
    @patch('accounts.services.send_sms', return_value=False)
    def test_failed_sms_does_not_leave_valid_code(self, mocked_send_sms, mocked_generate_code):
        from accounts.services import create_and_send_code

        ok, error = create_and_send_code('79991234567')
        self.assertFalse(ok)
        self.assertIn('Не удалось отправить SMS', error)
        self.assertFalse(PhoneVerificationCode.objects.filter(phone='9991234567').exists())

    def test_logout_requires_post(self):
        user = User.objects.create_user(username='79995554433', password='testpass')
        self.client.force_login(user)

        get_response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse('accounts:logout'))
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(post_response.url, reverse('home'))
        self.assertNotIn('_auth_user_id', self.client.session)


class OtpLifecycleTest(TestCase):
    @patch('accounts.services.generate_code', return_value='222222')
    @patch('accounts.services.send_sms', return_value=True)
    def test_new_code_invalidates_previous_active_code(self, mocked_send_sms, mocked_generate_code):
        old_code = PhoneVerificationCode.objects.create(phone='9991234567', code='111111')
        old_code.created_at = timezone.now() - timezone.timedelta(seconds=61)
        old_code.save(update_fields=['created_at'])

        from accounts.services import create_and_send_code, verify_sms_code

        ok, error = create_and_send_code('79991234567')
        self.assertTrue(ok)
        self.assertEqual(error, '')

        old_code.refresh_from_db()
        self.assertIsNotNone(old_code.used_at)
        self.assertTrue(PhoneVerificationCode.objects.filter(phone='9991234567', code='222222', used_at__isnull=True).exists())
        self.assertEqual(verify_sms_code('79991234567', '111111')[0], False)
        self.assertEqual(verify_sms_code('79991234567', '222222')[0], True)

    def test_used_code_cannot_be_reused(self):
        from accounts.services import verify_sms_code

        PhoneVerificationCode.objects.create(phone='9991234567', code='123456')

        first_ok, _ = verify_sms_code('79991234567', '123456', consume=True)
        second_ok, second_error = verify_sms_code('79991234567', '123456', consume=True)

        self.assertTrue(first_ok)
        self.assertFalse(second_ok)
        self.assertEqual(second_error, 'Неверный или устаревший код')


class PasswordAccessRecoveryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(
            username='9991234567',
            password='OldPassword123!',
            email='verified@example.com',
        )
        cls.profile = Profile.objects.create(
            user=cls.user,
            phone='9991234567',
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
            email_verified_at=timezone.now(),
        )

    def setUp(self):
        cache.clear()

    def test_password_reset_request_page_uses_email_only(self):
        response = self.client.get(reverse('accounts:password_reset_request'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'только через подтверждённый email')
        self.assertContains(response, 'Email')
        self.assertNotContains(response, 'Номер телефона')
        self.assertNotContains(response, 'Способ восстановления')

    def test_password_reset_does_not_reveal_unverified_email_account(self):
        unverified_user = User.objects.create_user(
            username='user_unverified_email',
            password='OldPassword123!',
            email='oneboardshol@gmail.com',
        )
        Profile.objects.create(user=unverified_user)

        response = self.client.post(reverse('accounts:password_reset_request'), {
            'email': 'oneboardshol@gmail.com',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('accounts:password_reset_request')}?sent=email")
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_does_not_reveal_unknown_email(self):
        response = self.client.post(reverse('accounts:password_reset_request'), {
            'email': 'unknown@example.com',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('accounts:password_reset_request')}?sent=email")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        PASSWORD_RESET_EMAIL_SUBJECT='Восстановление пароля BizonVR',
        PASSWORD_RESET_TIMEOUT=900,
        SITE_URL='https://bizonvr.ru',
    )
    def test_email_password_reset_sends_mail_and_sets_new_password(self):
        request_response = self.client.post(reverse('accounts:password_reset_request'), {
            'email': 'verified@example.com',
        })

        self.assertEqual(request_response.status_code, 302)
        self.assertEqual(request_response.url, f"{reverse('accounts:password_reset_request')}?sent=email")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Восстановление пароля BizonVR')
        self.assertIn('https://bizonvr.ru/accounts/password-reset/confirm/', message.body)
        self.assertIn('/accounts/password-reset/confirm/', message.body)
        self.assertIn('Ссылка действует 15 минут', message.body)
        self.assertEqual(len(message.alternatives), 1)
        self.assertIn('/accounts/password-reset/confirm/', message.alternatives[0].content)

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

        reused_response = self.client.get(
            reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token}),
        )
        self.assertEqual(reused_response.status_code, 200)
        self.assertContains(reused_response, 'Ссылка недействительна или уже использована.')

    @patch('accounts.views.password_reset.send_password_reset_email', return_value=(False, 'Не удалось отправить письмо. Попробуйте позже или свяжитесь с поддержкой.'))
    def test_password_reset_send_failure_does_not_redirect_to_success(self, mocked_send_password_reset_email):
        response = self.client.post(reverse('accounts:password_reset_request'), {
            'email': 'verified@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Не удалось отправить письмо. Попробуйте позже или свяжитесь с поддержкой.')
        self.assertEqual(len(mail.outbox), 0)
        mocked_send_password_reset_email.assert_called_once()


@tag('slow')
class SmsServiceTest(SimpleTestCase):
    @override_settings(SMS_CODE_TTL_MINUTES=15)
    def test_build_sms_message_uses_pretty_default_template(self):
        from accounts.services import build_sms_message

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SMS_MESSAGE_TEMPLATE', None)
            message = build_sms_message('123456')

        self.assertEqual(message, 'BizonVR: код 123456. Действует 15 мин. Не сообщайте его никому.')

    @override_settings(SMS_CODE_TTL_MINUTES=7)
    def test_build_sms_message_supports_custom_template(self):
        from accounts.services import build_sms_message

        with patch.dict(os.environ, {'SMS_MESSAGE_TEMPLATE': 'Код входа {code}, срок {ttl_minutes} мин.'}, clear=False):
            message = build_sms_message('654321')

        self.assertEqual(message, 'Код входа 654321, срок 7 мин.')

    @override_settings(SMS_CODE_TTL_MINUTES=9)
    def test_build_sms_message_falls_back_on_invalid_template(self):
        from accounts.services import build_sms_message

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
        from accounts.services import _send_exolve

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
        from accounts.services import _send_exolve

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError('bad payload')
        mocked_post.return_value = response

        self.assertFalse(_send_exolve('79991234567', '123456'))

    @patch('accounts.services.requests.post')
    def test_smsru_request_uses_message_template_and_sender(self, mocked_post):
        from accounts.services import _send_smsru

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
@tag('slow')
class EmailVerificationServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='9991234567', password='testpass')
        cls.profile = Profile.objects.create(user=cls.user, phone='9991234567')

    @patch('accounts.services.generate_code', return_value='112233')
    def test_create_and_send_email_code_sends_html_email(self, mocked_generate_code):
        from accounts.services import create_and_send_email_code

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
        from accounts.services import confirm_email_verification

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


@tag('slow')
class TurnstileServiceTest(SimpleTestCase):
    @override_settings(DEBUG=True, TURNSTILE_SITE_KEY='', TURNSTILE_SECRET_KEY='')
    def test_turnstile_bypasses_in_debug_without_keys(self):
        from accounts.services import verify_turnstile_token

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
        from accounts.services import verify_turnstile_token

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
        from accounts.services import verify_turnstile_token

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'success': False, 'error-codes': ['invalid-input-response']}
        mocked_post.return_value = response

        ok, error = verify_turnstile_token('bad-token')

        self.assertFalse(ok)
        self.assertIn('проверку', error)


class CompleteRegistrationLegalVersionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')

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
        self.assertEqual(response.url, f"{reverse('accounts:profile_settings')}#security")
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
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='9991234567', password='testpass')
        cls.profile = Profile.objects.create(
            user=cls.user,
            phone='9991234567',
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        create_order(user=cls.user, status=Order.STATUS_NEW, total=Decimal('1000.00'))
        create_order(user=cls.user, status=Order.STATUS_PAID, total=Decimal('2500.00'))
        create_order(user=cls.user, status=Order.STATUS_DONE, total=Decimal('5000.00'))

    def setUp(self):
        cache.clear()

    def test_profile_requires_login(self):
        resp = self.client.get(reverse('accounts:profile'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))

    def test_profile_dashboard_without_balance_block(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('accounts:profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Личный кабинет')
        self.assertContains(resp, 'Последние заказы')
        self.assertContains(resp, 'Чек-лист быстрого оформления')
        self.assertEqual(resp.context['profile_setup_checklist']['progress_label'], '1 из 4 выполнено')

    def test_profile_setup_checklist_prioritizes_incomplete_steps(self):
        preferences = NotificationPreference.objects.create(
            user=self.user,
            sms_order_updates_enabled=True,
            marketing_email_enabled=False,
            back_in_stock_enabled=False,
        )

        checklist = _build_profile_setup_checklist(
            profile=self.profile,
            saved_addresses=[],
            notification_preferences=preferences,
        )

        self.assertEqual(checklist['progress_label'], '1 из 4 выполнено')
        self.assertEqual([step['title'] for step in checklist['pending_steps']], ['Сохранить адрес', 'Подтвердить email', 'Настроить уведомления'])
        self.assertEqual([step['title'] for step in checklist['completed_steps']], ['Добавить данные'])
        self.assertEqual([step['title'] for step in checklist['steps'][:2]], ['Сохранить адрес', 'Подтвердить email'])

    def test_profile_dashboard_empty_order_state_uses_more_direct_copy(self):
        Order.objects.filter(user=self.user).exclude(status=Order.STATUS_DONE).delete()
        self.client.force_login(self.user)

        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Заказов в работе нет')
        self.assertContains(response, 'Активные этапы завершены.')
        self.assertContains(response, 'История уже собрана. Сейчас главное действие')

    def test_profile_settings_route_renders_edit_mode(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('accounts:profile_settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Профиль и настройки')
        self.assertContains(resp, 'Данные получателя')
        self.assertContains(resp, 'data-account-section-link="notifications"', html=False)
        self.assertContains(resp, '+7 (999) 123-45-67')
        self.assertContains(resp, 'Email не указан')
        self.assertContains(resp, 'Подтверждение регистрации и сервисные письма приходят только на email.')
        self.assertNotContains(resp, 'SMS')
        self.assertNotContains(resp, 'id="profile-edit-form"', html=False)
        self.assertNotContains(resp, 'id="notification-form"', html=False)

    def test_profile_settings_opens_profile_form_only_by_explicit_action(self):
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('accounts:profile_settings')}?edit_profile=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="profile-edit-form"', html=False)
        self.assertContains(response, 'Есть несохранённые изменения')

    def test_profile_settings_opens_security_tools_only_by_explicit_action(self):
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('accounts:profile_settings')}?edit_security=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Инструменты доступа открыты')
        self.assertContains(response, 'Подтверждение email')
        self.assertContains(response, 'Телефон в профиле')
        self.assertContains(response, 'подтверждение guest-заказов больше завязаны только на email')

    def test_profile_settings_opens_notification_form_only_by_explicit_action(self):
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('accounts:profile_settings')}?edit_notifications=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="notification-form"', html=False)
        self.assertContains(response, 'Есть несохранённые изменения')

    def test_invalid_profile_save_keeps_profile_edit_mode_open(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('accounts:profile_settings'), {
            'action': 'save_profile',
            'contact_name': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="profile-edit-form"', html=False)
        self.assertContains(response, 'Не удалось сохранить профиль. Проверьте поля формы.')

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

    def test_save_profile_requires_privacy_consent_when_missing(self):
        self.profile.privacy_agreed_at = None
        self.profile.privacy_policy_version = ''
        self.profile.save(update_fields=['privacy_agreed_at', 'privacy_policy_version'])
        self.client.force_login(self.user)

        response = self.client.post(reverse('accounts:profile'), {
            'action': 'save_profile',
            'contact_name': 'Петров Петр Петрович',
        })

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.privacy_agreed_at)
        self.assertContains(response, 'Подтвердите согласие с юридическими документами.')

    def test_save_profile_stores_privacy_metadata_when_consent_checked(self):
        self.profile.privacy_agreed_at = None
        self.profile.privacy_policy_version = ''
        self.profile.save(update_fields=['privacy_agreed_at', 'privacy_policy_version'])
        self.client.force_login(self.user)

        response = self.client.post(reverse('accounts:profile'), {
            'action': 'save_profile',
            'contact_name': 'Петров Петр Петрович',
            'agree_privacy': 'on',
        })

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.contact_name, 'Петров Петр Петрович')
        self.assertIsNotNone(self.profile.privacy_agreed_at)
        self.assertEqual(self.profile.privacy_policy_version, LEGAL_BUNDLE_VERSION)

    def test_profile_ignores_removed_phone_confirmation_actions(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('accounts:profile'), {
            'action': 'send_phone_code',
            'new_phone': '+7 (922) 111-22-33',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Неизвестное действие формы.')
        self.assertFalse(PhoneVerificationCode.objects.filter(phone='9221112233').exists())

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
        self.assertContains(resp, 'Письмо с кодом подтверждения отправлено.')

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

    def test_save_notification_preferences_updates_persistent_settings(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('accounts:profile'), {
            'action': 'save_notification_preferences',
            'marketing_email_enabled': 'on',
            'back_in_stock_enabled': 'on',
        })

        self.assertEqual(response.status_code, 200)
        preferences = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(preferences.sms_order_updates_enabled)
        self.assertTrue(preferences.marketing_email_enabled)
        self.assertTrue(preferences.back_in_stock_enabled)
        self.assertContains(response, 'Настройки уведомлений сохранены.')

    def test_balance_history_route_still_available(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('accounts:balance_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Редактировать профиль')


class GuestOrderAutoClaimTest(TestCase):
    def setUp(self):
        pass

    def test_password_login_auto_claims_guest_orders_by_verified_email(self):
        user = User.objects.create_user(
            username='9991234567',
            password='testpass123',
            email='verified@example.com',
        )
        Profile.objects.create(
            user=user,
            phone='9991234567',
            email_verified_at=timezone.now(),
            phone_verified_at=timezone.now(),
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        guest_order = Order.objects.create(
            user=None,
            status=Order.STATUS_NEW,
            total=Decimal('100.00'),
            phone='+7 900 000 00 01',
            email='verified@example.com',
            first_name='Гость',
        )

        response = self.client.post(reverse('accounts:password_login'), {
            'login': 'verified@example.com',
            'password': 'testpass123',
        })

        self.assertEqual(response.status_code, 302)
        guest_order.refresh_from_db()
        self.assertEqual(guest_order.user, user)
        self.assertTrue(NotificationPreference.objects.filter(user=user).exists())

    def test_confirm_email_verification_auto_claims_guest_orders(self):
        user = User.objects.create_user(username='9991234567', password='testpass')
        Profile.objects.create(
            user=user,
            phone='9991234567',
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        guest_order = Order.objects.create(
            user=None,
            status=Order.STATUS_NEW,
            total=Decimal('100.00'),
            phone='+7 900 000 00 03',
            email='claim@example.com',
            first_name='Гость',
        )
        EmailVerificationCode.objects.create(user=user, email='claim@example.com', code='123456')
        self.client.force_login(user)

        response = self.client.post(reverse('accounts:profile'), {
            'action': 'confirm_email_code',
            'email': 'claim@example.com',
            'code': '123456',
        })

        self.assertEqual(response.status_code, 200)
        guest_order.refresh_from_db()
        self.assertEqual(guest_order.user, user)

class SavedAddressAndCheckoutTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='9991234567', password='testpass')
        cls.profile = Profile.objects.create(
            user=cls.user,
            phone='9991234567',
            contact_name='Иван Иванов',
        )
        cls.category = create_category(name='Тест', slug='test-address')
        cls.product = create_product(
            category=cls.category,
            name='Товар для checkout',
            slug='checkout-product',
            price=Decimal('100.00'),
            is_active=True,
        )
        cls.city = City.objects.create(name='Екатеринбург', slug='ekb-account-checkout')
        cls.pickup_point = PickupPoint.objects.create(city=cls.city, name='Основной ПВЗ')
        ProductStock.objects.create(product=cls.product, pickup_point=cls.pickup_point, quantity=10)

    def _address_payload(self, **overrides):
        payload = {
            'action': 'save_address',
            'label': 'Дом',
            'recipient_name': 'Иван Иванов',
            'phone': '+7 (999) 123-45-67',
            'email': 'user@example.com',
            'city': 'Екатеринбург',
            'address': 'ул. Мира, 1',
            'comment': 'Позвонить заранее',
            'is_default': 'on',
        }
        payload.update(overrides)
        return payload

    def _checkout_payload(self, **overrides):
        payload = {
            'promo_code': '',
            'first_name': 'Петров',
            'last_name': 'Петр',
            'phone': '+7 999 123 45 67',
            'email': 'client@example.com',
            'contact_channel': Order.CONTACT_CHANNEL_CALL,
            'contact_handle': '',
            'delivery_type': Order.DELIVERY_CDEK_PVZ,
            'city_text': 'Екатеринбург',
            'address_line': 'ул. Мира, 1',
            'delivery_comment': '',
            'cdek_office_snapshot_raw': json.dumps({
                'city_code': 250,
                'city': 'Екатеринбург',
                'type': 'PVZ',
                'postal_code': '620000',
                'country_code': 'RU',
                'have_cashless': True,
                'have_cash': False,
                'allowed_cod': False,
                'is_dressing_room': False,
                'code': 'EKB001',
                'name': 'ПВЗ СДЭК',
                'address': 'Екатеринбург, ул. Мира, 1',
                'work_time': 'Пн-Пт 10:00-19:00',
                'location': [60.6122, 56.8519],
            }),
            'cdek_tariff_snapshot_raw': json.dumps({
                'tariff_code': 136,
                'tariff_name': 'Посылка склад-склад',
            }),
            'recipient_is_customer': 'on',
            'payment_method': Order.PAYMENT_METHOD_MANAGER_CONTACT,
            'comment': '',
            'agree_personal_data': 'on',
            'agree_offer': 'on',
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

    def test_profile_settings_opens_address_form_only_by_explicit_action(self):
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('accounts:profile_settings')}?add_address=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="address-edit-form"', html=False)
        self.assertContains(response, 'Есть несохранённые изменения')

    def test_profile_can_edit_saved_address(self):
        address = SavedAddress.objects.create(
            user=self.user,
            label='Дом',
            recipient_name='Иван Иванов',
            phone='9991234567',
            email='old@example.com',
            city='Екатеринбург',
            address='Старый адрес',
            is_default=True,
        )
        self.client.force_login(self.user)
        resp = self.client.post(reverse('accounts:profile'), self._address_payload(
            address_id=str(address.pk),
            label='Офис',
            city='Москва',
            address='Новый адрес',
            is_default='',
        ))
        self.assertEqual(resp.status_code, 200)
        address.refresh_from_db()
        self.assertEqual(address.label, 'Офис')
        self.assertEqual(address.city, 'Москва')
        self.assertEqual(address.address, 'Новый адрес')
        self.assertTrue(address.is_default)
        self.assertContains(resp, 'Офис')

    def test_delete_default_address_promotes_next_one(self):
        default_address = SavedAddress.objects.create(
            user=self.user,
            label='Дом',
            recipient_name='Иван Иванов',
            phone='9991234567',
            city='Екатеринбург',
            address='Домашний адрес',
            is_default=True,
        )
        other_address = SavedAddress.objects.create(
            user=self.user,
            label='Офис',
            recipient_name='Иван Иванов',
            phone='9991234567',
            city='Екатеринбург',
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
            city='Екатеринбург',
            address='Домашний адрес',
            is_default=True,
        )
        second = SavedAddress.objects.create(
            user=self.user,
            label='Офис',
            recipient_name='Иван Иванов',
            phone='9991234567',
            city='Екатеринбург',
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
            city='Екатеринбург',
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
            city='Екатеринбург',
            address='ул. Мира, 1',
            comment='Комментарий к доставке',
            is_default=True,
        )
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_saved_address_id'], SavedAddress.objects.get(user=self.user).pk)
        self.assertEqual(resp.context['form'].initial['first_name'], 'Петров')
        self.assertEqual(resp.context['form'].initial['last_name'], 'Петр')
        self.assertEqual(resp.context['form'].initial['city_text'], 'Екатеринбург')
        self.assertEqual(resp.context['form'].initial['address_line'], 'ул. Мира, 1')
        self.assertEqual(resp.context['form'].initial['email'], 'delivery@example.com')
        self.assertEqual(resp.context['form'].initial['recipient_name'], 'Петров Петр')
        self.assertContains(resp, 'Комментарий к доставке')
        self.assertNotContains(resp, 'CDEK')

    def test_checkout_prefills_verified_account_email_when_no_saved_address(self):
        self.user.email = 'client@example.com'
        self.user.save(update_fields=['email'])
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.get(reverse('orders:checkout'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial['email'], 'client@example.com')

    def test_checkout_saves_contact_name_and_privacy_to_profile_for_next_orders(self):
        self.profile.contact_name = ''
        self.profile.privacy_agreed_at = None
        self.profile.privacy_policy_version = ''
        self.profile.save(update_fields=['contact_name', 'privacy_agreed_at', 'privacy_policy_version'])
        self.client.force_login(self.user)
        self.client.post(reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk}), {'quantity': 1})

        response = self.client.post(reverse('orders:checkout'), self._checkout_payload())

        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.contact_name, 'Петров Петр')
        self.assertIsNotNone(self.profile.privacy_agreed_at)
        self.assertEqual(self.profile.privacy_policy_version, LEGAL_BUNDLE_VERSION)
