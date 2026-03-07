"""Сервисы аккаунтов: SMS-коды, email-верификация и служебные проверки."""
import logging
import random
import string
from datetime import timedelta

import requests

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from decouple import config

from .models import EmailVerificationCode, PhoneVerificationCode, Profile

User = get_user_model()
logger = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str:
    """Нормализация телефона: только цифры, для России — 10 цифр."""
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in ('7', '8'):
        return digits[1:]
    return digits


def get_sms_provider() -> str:
    return getattr(settings, 'SMS_PROVIDER', 'exolve').strip().lower()


def is_turnstile_enabled() -> bool:
    return bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)


def is_turnstile_debug_bypass() -> bool:
    return settings.DEBUG and not is_turnstile_enabled()


def is_sms_debug_mode() -> bool:
    """True, если SMS не отправляется провайдером, а код выводится локально."""
    provider = get_sms_provider()
    if provider == 'exolve':
        return not bool(settings.EXOLVE_API_KEY and settings.EXOLVE_SENDER)
    if provider == 'smsru':
        return not bool(config('SMS_API_KEY', default='').strip())
    return True


def build_sms_message(code: str) -> str:
    """Собирает текст SMS с кодом подтверждения."""
    ttl_minutes = getattr(settings, 'SMS_CODE_TTL_MINUTES', 10)
    template = (
        config('SMS_MESSAGE_TEMPLATE', default='').strip()
        or 'BizonVR: код {code}. Действует {ttl_minutes} мин. Не сообщайте его никому.'
    )
    try:
        return template.format(code=code, ttl_minutes=ttl_minutes)
    except (KeyError, IndexError, ValueError):
        logger.warning('Некорректный SMS_MESSAGE_TEMPLATE, использован шаблон по умолчанию')
        return f'BizonVR: код {code}. Действует {ttl_minutes} мин. Не сообщайте его никому.'


def normalize_email(raw: str) -> str:
    return (raw or '').strip().lower()


def get_user_by_phone(phone: str):
    phone = normalize_phone(phone)
    if len(phone) < 10:
        return None
    return (
        User.objects
        .filter(Q(username=phone) | Q(profile__phone=phone), is_active=True)
        .distinct()
        .first()
    )


def get_user_by_email(email: str):
    email = normalize_email(email)
    if not email:
        return None

    queryset = User.objects.filter(
        email__iexact=email,
        is_active=True,
        profile__email_verified_at__isnull=False,
    )
    if queryset.count() != 1:
        return None
    return queryset.first()


def authenticate_by_login_identifier(identifier: str, password: str, request=None) -> tuple[object | None, str]:
    identifier = (identifier or '').strip()
    if not identifier:
        return None, 'Укажите телефон или email.'

    if '@' in identifier:
        user = get_user_by_email(identifier)
    else:
        user = get_user_by_phone(identifier)

    if user is None:
        return None, 'Неверный телефон, email или пароль.'
    if not user.has_usable_password():
        return None, 'Для этого аккаунта пароль ещё не задан. Восстановите доступ по номеру или email.'

    authenticated_user = authenticate(request, username=user.username, password=password)
    if authenticated_user is None:
        return None, 'Неверный телефон, email или пароль.'
    return authenticated_user, ''


def build_email_verification_subject() -> str:
    return getattr(settings, 'EMAIL_VERIFICATION_SUBJECT', 'Подтверждение email для BizonVR').strip()


def build_email_verification_plain_message(code: str) -> str:
    ttl_minutes = getattr(settings, 'EMAIL_CODE_TTL_MINUTES', 15)
    return (
        'Подтверждение email для BizonVR\n\n'
        f'Ваш код: {code}\n'
        f'Код действует {ttl_minutes} минут.\n'
        'Если вы не запрашивали подтверждение, просто проигнорируйте это письмо.'
    )


def send_email_verification(email: str, code: str) -> bool:
    context = {
        'brand': getattr(settings, 'SITE_BRAND', 'BizonVR'),
        'site_url': getattr(settings, 'SITE_URL', '').rstrip('/'),
        'code': code,
        'ttl_minutes': getattr(settings, 'EMAIL_CODE_TTL_MINUTES', 15),
        'support_email': getattr(settings, 'SITE_CONTACT_EMAIL', '').strip(),
        'support_phone': getattr(settings, 'SITE_CONTACT_PHONE', '').strip(),
    }
    subject = build_email_verification_subject()
    text_body = build_email_verification_plain_message(code)
    html_body = render_to_string('emails/email_verification.html', context)

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        message.attach_alternative(html_body, 'text/html')
        message.send(fail_silently=False)
    except Exception:
        logger.exception('Email verification send failed for %s', email)
        return False
    return True


def send_password_reset_email(user, *, request=None) -> tuple[bool, str]:
    email = normalize_email(getattr(user, 'email', ''))
    if not email:
        return False, 'У аккаунта не указан email для восстановления доступа.'

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
    reset_url = request.build_absolute_uri(path) if request is not None else f'{settings.SITE_URL}{path}'
    subject = getattr(settings, 'PASSWORD_RESET_EMAIL_SUBJECT', 'Восстановление доступа BizonVR').strip()
    text_body = (
        'Здравствуйте!\n\n'
        'Чтобы установить новый пароль для аккаунта BizonVR, перейдите по ссылке:\n'
        f'{reset_url}\n\n'
        'Если вы не запрашивали восстановление доступа, просто проигнорируйте это письмо.'
    )

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        message.send(fail_silently=False)
    except Exception:
        logger.exception('Password reset email send failed for %s', email)
        return False, 'Не удалось отправить письмо. Попробуйте позже.'
    return True, ''


def verify_turnstile_token(token: str, *, client_ip: str = '') -> tuple[bool, str]:
    """Проверяет ответ Cloudflare Turnstile."""
    if not is_turnstile_enabled():
        if is_turnstile_debug_bypass():
            return True, ''
        logger.error('Turnstile не настроен: отсутствуют TURNSTILE_SITE_KEY/TURNSTILE_SECRET_KEY')
        return False, 'Защита формы временно недоступна. Попробуйте позже.'

    if not token.strip():
        return False, 'Подтвердите, что вы не робот.'

    payload = {
        'secret': settings.TURNSTILE_SECRET_KEY,
        'response': token.strip(),
    }
    if client_ip:
        payload['remoteip'] = client_ip

    try:
        response = requests.post(
            settings.TURNSTILE_VERIFY_URL,
            data=payload,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.exception('Turnstile verification failed: %s', exc)
        return False, 'Не удалось проверить капчу. Попробуйте ещё раз.'

    if data.get('success') is True:
        return True, ''

    logger.warning('Turnstile rejected token: %s', data)
    return False, 'Не удалось пройти проверку. Попробуйте ещё раз.'


def send_sms(phone: str, code: str, *, client_ip: str = '') -> bool:
    """
    Отправка SMS с кодом. В разработке без API-ключа — логируем код.
    В production используется выбранный провайдер из настроек.
    """
    if is_sms_debug_mode():
        msg = f'SMS (dev): код {code} для номера {phone}'
        logger.warning(msg)
        print(f'\n>>> {msg} <<<\n')  # всегда видно в консоли runserver/gunicorn
        return True
    provider = get_sms_provider()
    if provider == 'exolve':
        return _send_exolve(phone, code)
    if provider == 'smsru':
        api_key = config('SMS_API_KEY', default='')
        return _send_smsru(phone, code, api_key, client_ip=client_ip)
    logger.warning('Неизвестный SMS_PROVIDER=%s, код залогирован', provider)
    return True


def _send_exolve(phone: str, code: str) -> bool:
    """Отправка через MTS Exolve API."""
    destination = normalize_phone(phone)
    if len(destination) == 10:
        destination = '7' + destination

    payload = {
        'number': settings.EXOLVE_SENDER,
        'destination': destination,
        'text': build_sms_message(code),
    }
    headers = {
        'Authorization': f'Bearer {settings.EXOLVE_API_KEY}',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(
            f'{settings.EXOLVE_API_BASE}/SendSMS',
            json=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        response.json()
        return True
    except (requests.RequestException, ValueError) as exc:
        response_text = ''
        if 'response' in locals():
            response_text = str(getattr(response, 'text', ''))[:500]
        logger.exception('Exolve request failed: %s; response=%s', exc, response_text)
        return False


def _send_smsru(phone: str, code: str, api_key: str, *, client_ip: str = '') -> bool:
    """Отправка через SMS.ru API."""
    try:
        to = '7' + normalize_phone(phone) if len(normalize_phone(phone)) == 10 else phone
        params = {
            'api_id': api_key,
            'to': to,
            'msg': build_sms_message(code),
            'json': 1,
        }
        sender = config('SMS_SENDER_NAME', default='').strip()
        if sender:
            params['from'] = sender
        if client_ip:
            params['ip'] = client_ip

        r = requests.post(
            'https://sms.ru/sms/send',
            data=params,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get('status') == 'OK':
            return True
        logger.error('SMS.ru error: %s', data)
        return False
    except (requests.RequestException, ValueError) as e:
        logger.exception('SMS.ru request failed: %s', e)
        return False


def generate_code(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def create_and_send_code(phone: str, *, client_ip: str = '') -> tuple[bool, str]:
    """
    Создать код, сохранить в БД, отправить SMS.
    Возвращает (успех, сообщение об ошибке или пустая строка).
    """
    phone = normalize_phone(phone)
    if len(phone) < 10:
        return False, 'Введите корректный номер телефона'

    now = timezone.now()
    cooldown = getattr(settings, 'SMS_COOLDOWN_SECONDS', 60)
    since = now - timedelta(seconds=cooldown)

    if PhoneVerificationCode.objects.filter(phone=phone, used_at__isnull=True, created_at__gt=since).exists():
        return False, f'Код уже отправлен. Повторите через {cooldown} сек.'

    code = generate_code()
    if not send_sms(phone, code, client_ip=client_ip):
        return False, 'Не удалось отправить SMS. Попробуйте позже.'

    PhoneVerificationCode.objects.filter(phone=phone, used_at__isnull=True).update(used_at=now)
    PhoneVerificationCode.objects.create(phone=phone, code=code)
    return True, ''


def get_pending_email_verification(user):
    ttl_minutes = getattr(settings, 'EMAIL_CODE_TTL_MINUTES', 15)
    since = timezone.now() - timedelta(minutes=ttl_minutes)
    return (
        EmailVerificationCode.objects
        .filter(user=user, used_at__isnull=True, created_at__gt=since)
        .order_by('-created_at')
        .first()
    )


def create_and_send_email_code(user, email: str) -> tuple[bool, str]:
    """
    Создать и отправить код подтверждения email.
    Подтверждение выполняется один раз: после успешной верификации email больше не меняется.
    """
    email = normalize_email(email)
    profile, _ = Profile.objects.get_or_create(user=user, defaults={'phone': user.username})
    if profile.email_verified_at:
        return False, 'Email уже подтверждён и больше не требует повторной верификации.'
    if not email:
        return False, 'Введите корректный email.'
    if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        return False, 'Этот email уже подтверждён в другом аккаунте.'

    now = timezone.now()
    cooldown = getattr(settings, 'EMAIL_CODE_COOLDOWN_SECONDS', 60)
    since = now - timedelta(seconds=cooldown)
    if EmailVerificationCode.objects.filter(user=user, email__iexact=email, used_at__isnull=True, created_at__gt=since).exists():
        return False, f'Код уже отправлен. Повторите через {cooldown} сек.'

    code = generate_code()
    if not send_email_verification(email, code):
        return False, 'Не удалось отправить письмо. Проверьте настройки почты и попробуйте позже.'

    EmailVerificationCode.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
    EmailVerificationCode.objects.create(user=user, email=email, code=code)
    return True, ''


def verify_email_code(user, email: str, code: str, *, consume: bool = False) -> tuple[bool, str]:
    email = normalize_email(email)
    if not email:
        return False, 'Введите корректный email.'

    ttl_minutes = getattr(settings, 'EMAIL_CODE_TTL_MINUTES', 15)
    since = timezone.now() - timedelta(minutes=ttl_minutes)
    latest_record = (
        EmailVerificationCode.objects
        .filter(user=user, email__iexact=email, used_at__isnull=True, created_at__gt=since)
        .order_by('-created_at')
        .first()
    )
    if not latest_record or latest_record.code != code.strip():
        return False, 'Неверный или устаревший код'

    if consume:
        latest_record.used_at = timezone.now()
        latest_record.save(update_fields=['used_at'])
    return True, ''


def confirm_email_verification(user, email: str, code: str) -> tuple[bool, str]:
    email = normalize_email(email)
    profile, _ = Profile.objects.get_or_create(user=user, defaults={'phone': user.username})
    if profile.email_verified_at:
        return False, 'Email уже подтверждён.'
    if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        return False, 'Этот email уже подтверждён в другом аккаунте.'

    ok, error = verify_email_code(user, email, code, consume=True)
    if not ok:
        return False, error

    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        profile = Profile.objects.select_for_update().get(user=locked_user)
        if profile.email_verified_at:
            return False, 'Email уже подтверждён.'
        if User.objects.filter(email__iexact=email).exclude(pk=locked_user.pk).exists():
            return False, 'Этот email уже подтверждён в другом аккаунте.'
        locked_user.email = email
        locked_user.save(update_fields=['email'])
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=['email_verified_at'])

    return True, ''


def verify_sms_code(phone: str, code: str, *, consume: bool = False) -> tuple[bool, str]:
    """
    Проверить SMS-код для номера телефона без выполнения логина.
    Возвращает (успех, сообщение об ошибке или пустая строка).
    """
    phone = normalize_phone(phone)
    if len(phone) < 10:
        return False, 'Введите корректный номер телефона'

    ttl_minutes = getattr(settings, 'SMS_CODE_TTL_MINUTES', 10)
    since = timezone.now() - timedelta(minutes=ttl_minutes)

    latest_record = (
        PhoneVerificationCode.objects
        .filter(phone=phone, used_at__isnull=True, created_at__gt=since)
        .order_by('-created_at')
        .first()
    )
    if not latest_record or latest_record.code != code.strip():
        return False, 'Неверный или устаревший код'

    if consume:
        latest_record.used_at = timezone.now()
        latest_record.save(update_fields=['used_at'])
    return True, ''


def verify_code_and_login(phone: str, code: str, request) -> tuple[bool, str]:
    """
    Проверить код. Если верный — создать пользователя и профиль (если нет) и войти.
    Возвращает (успех, сообщение об ошибке или пустая строка).
    """
    from django.contrib.auth import login

    phone = normalize_phone(phone)
    ok, error = verify_sms_code(phone, code, consume=True)
    if not ok:
        return False, error

    user, created = User.objects.get_or_create(
        username=phone,
        defaults={'is_active': True},
    )
    if created:
        user.set_unusable_password()
        user.save()
    profile, profile_created = Profile.objects.get_or_create(user=user, defaults={'phone': phone})
    Profile.objects.filter(user=user).update(phone=phone)

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return True, ''
