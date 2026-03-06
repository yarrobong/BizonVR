"""Базовые тесты входа по телефону (Фаза 6)."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from config.env import parse_bool_value
from config.legal_docs import LEGAL_BUNDLE_VERSION
from catalog.models import Category, City, PickupPoint, Product
from orders.models import Order

from .models import CommercialProposalContact, PhoneVerificationCode, Profile, SavedAddress

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


class ProfileDashboardTest(TestCase):
    PHONE_CHANGE_SESSION_KEY = 'accounts:profile:phone_change_pending'

    def setUp(self):
        self.client = Client()
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
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='9991234567', password='testpass')
        Profile.objects.create(
            user=self.user,
            phone='9991234567',
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )

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
