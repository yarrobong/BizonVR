"""
Сервисы Фазы 2: отправка SMS и работа с кодами подтверждения.
"""
import logging
import random
import string
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model

from decouple import config

from .models import PhoneVerificationCode, Profile

User = get_user_model()
logger = logging.getLogger(__name__)


def normalize_phone(raw: str) -> str:
    """Нормализация телефона: только цифры, для России — 10 цифр."""
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in ('7', '8'):
        return digits[1:]
    return digits


def send_sms(phone: str, code: str) -> bool:
    """
    Отправка SMS с кодом. В разработке без API-ключа — логируем код.
    С провайдером SMS.ru — реальная отправка (см. .env.example).
    """
    api_key = config('SMS_API_KEY', default='')
    if not api_key:
        msg = f'SMS (dev): код {code} для номера {phone}'
        logger.warning(msg)
        print(f'\n>>> {msg} <<<\n')  # всегда видно в консоли runserver/gunicorn
        return True
    provider = config('SMS_PROVIDER', default='smsru').lower()
    if provider == 'smsru':
        return _send_smsru(phone, code, api_key)
    logger.warning('Неизвестный SMS_PROVIDER=%s, код залогирован', provider)
    return True


def _send_smsru(phone: str, code: str, api_key: str) -> bool:
    """Отправка через SMS.ru API."""
    try:
        import requests
        to = '7' + normalize_phone(phone) if len(normalize_phone(phone)) == 10 else phone
        text = f'Код BizonVR: {code}'
        r = requests.get(
            'https://sms.ru/sms/send',
            params={'api_id': api_key, 'to': to, 'msg': text, 'json': 1},
            timeout=10,
        )
        data = r.json()
        if data.get('status') == 'OK':
            return True
        logger.error('SMS.ru error: %s', data)
        return False
    except Exception as e:
        logger.exception('SMS.ru request failed: %s', e)
        return False


def generate_code(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def create_and_send_code(phone: str) -> tuple[bool, str]:
    """
    Создать код, сохранить в БД, отправить SMS.
    Возвращает (успех, сообщение об ошибке или пустая строка).
    """
    phone = normalize_phone(phone)
    if len(phone) < 10:
        return False, 'Введите корректный номер телефона'

    cooldown = getattr(settings, 'SMS_COOLDOWN_SECONDS', 60)
    since = timezone.now() - timedelta(seconds=cooldown)

    if PhoneVerificationCode.objects.filter(phone=phone, created_at__gt=since).exists():
        return False, f'Код уже отправлен. Повторите через {cooldown} сек.'

    code = generate_code()
    PhoneVerificationCode.objects.create(phone=phone, code=code)
    if send_sms(phone, code):
        return True, ''
    return False, 'Не удалось отправить SMS. Попробуйте позже.'


def verify_code_and_login(phone: str, code: str, request) -> tuple[bool, str]:
    """
    Проверить код. Если верный — создать пользователя и профиль (если нет) и войти.
    Возвращает (успех, сообщение об ошибке или пустая строка).
    """
    from django.contrib.auth import login

    phone = normalize_phone(phone)
    if len(phone) < 10:
        return False, 'Введите корректный номер телефона'

    ttl_minutes = getattr(settings, 'SMS_CODE_TTL_MINUTES', 10)
    since = timezone.now() - timedelta(minutes=ttl_minutes)

    record = (
        PhoneVerificationCode.objects
        .filter(phone=phone, code=code.strip(), created_at__gt=since)
        .order_by('-created_at')
        .first()
    )
    if not record:
        return False, 'Неверный или устаревший код'

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
    record.delete()
    PhoneVerificationCode.objects.filter(phone=phone).delete()
    return True, ''
