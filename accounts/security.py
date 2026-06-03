import time
import uuid
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.core.cache import cache

from .services import normalize_email, normalize_phone

RATE_LIMIT_SESSION_KEY = 'accounts:rate_limit_session_key'


def get_client_ip(request):
    remote_addr = (request.META.get('REMOTE_ADDR') or '').strip()
    x_forwarded_for = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()

    if x_forwarded_for and _is_trusted_proxy(remote_addr):
        forwarded_ip = x_forwarded_for.split(',')[0].strip()
        if forwarded_ip:
            return forwarded_ip
    return remote_addr


def get_rate_limit_session_key(request):
    session_key = request.session.get(RATE_LIMIT_SESSION_KEY)
    if session_key:
        return session_key
    session_key = uuid.uuid4().hex
    request.session[RATE_LIMIT_SESSION_KEY] = session_key
    request.session.modified = True
    return session_key


def check_send_code_rate_limits(request, phone):
    phone = normalize_phone(phone)
    cooldown = getattr(settings, 'SMS_COOLDOWN_SECONDS', 60)
    checks = (
        ('cooldown', 'send-code', 'ip', get_client_ip(request), cooldown, f'Подождите {cooldown} сек. перед повторной отправкой.'),
        ('cooldown', 'send-code', 'phone', phone, cooldown, f'Код уже отправлен. Повторите через {cooldown} сек.'),
        ('cooldown', 'send-code', 'session', get_rate_limit_session_key(request), cooldown, f'Подождите {cooldown} сек. перед повторной отправкой.'),
        ('window', 'send-code', 'ip', get_client_ip(request), 10, 15 * 60, 'Слишком много запросов на отправку кода. Попробуйте позже.'),
        ('window', 'send-code', 'phone', phone, 6, 15 * 60, 'Слишком много запросов для этого номера. Попробуйте позже.'),
        ('window', 'send-code', 'session', get_rate_limit_session_key(request), 10, 15 * 60, 'Слишком много запросов на отправку кода. Попробуйте позже.'),
    )
    return _run_rate_limit_checks(checks)


def mark_send_code_success(request, phone):
    phone = normalize_phone(phone)
    cooldown = getattr(settings, 'SMS_COOLDOWN_SECONDS', 60)
    _set_cooldown('send-code', 'ip', get_client_ip(request), cooldown)
    _set_cooldown('send-code', 'phone', phone, cooldown)
    _set_cooldown('send-code', 'session', get_rate_limit_session_key(request), cooldown)


def check_send_email_rate_limits(request, email, *, endpoint='send-email-code'):
    email = normalize_email(email)
    cooldown = getattr(settings, 'EMAIL_CODE_COOLDOWN_SECONDS', 60)
    checks = (
        ('cooldown', endpoint, 'ip', get_client_ip(request), cooldown, f'Подождите {cooldown} сек. перед повторной отправкой.'),
        ('cooldown', endpoint, 'email', email, cooldown, f'Письмо уже отправлено. Повторите через {cooldown} сек.'),
        ('cooldown', endpoint, 'session', get_rate_limit_session_key(request), cooldown, f'Подождите {cooldown} сек. перед повторной отправкой.'),
        ('window', endpoint, 'ip', get_client_ip(request), 10, 15 * 60, 'Слишком много запросов на отправку писем. Попробуйте позже.'),
        ('window', endpoint, 'email', email, 6, 15 * 60, 'Слишком много запросов для этого email. Попробуйте позже.'),
        ('window', endpoint, 'session', get_rate_limit_session_key(request), 10, 15 * 60, 'Слишком много запросов на отправку писем. Попробуйте позже.'),
    )
    return _run_rate_limit_checks(checks)


def mark_send_email_success(request, email, *, endpoint='send-email-code'):
    email = normalize_email(email)
    cooldown = getattr(settings, 'EMAIL_CODE_COOLDOWN_SECONDS', 60)
    _set_cooldown(endpoint, 'ip', get_client_ip(request), cooldown)
    _set_cooldown(endpoint, 'email', email, cooldown)
    _set_cooldown(endpoint, 'session', get_rate_limit_session_key(request), cooldown)


def check_registration_rate_limits(request, email):
    email = normalize_email(email)
    cooldown = getattr(
        settings,
        'REGISTRATION_COOLDOWN_SECONDS',
        getattr(settings, 'EMAIL_CODE_COOLDOWN_SECONDS', 60),
    )
    window_seconds = getattr(settings, 'REGISTRATION_RATE_LIMIT_WINDOW_SECONDS', 15 * 60)
    checks = (
        (
            'cooldown',
            'registration',
            'ip',
            get_client_ip(request),
            cooldown,
            f'Подождите {cooldown} сек. перед новой регистрацией.',
        ),
        (
            'cooldown',
            'registration',
            'email',
            email,
            cooldown,
            f'Для этого email уже была недавняя попытка регистрации. Повторите через {cooldown} сек.',
        ),
        (
            'cooldown',
            'registration',
            'session',
            get_rate_limit_session_key(request),
            cooldown,
            f'Подождите {cooldown} сек. перед новой регистрацией.',
        ),
        (
            'window',
            'registration',
            'ip',
            get_client_ip(request),
            getattr(settings, 'REGISTRATION_RATE_LIMIT_IP_MAX_ATTEMPTS', 10),
            window_seconds,
            'Слишком много попыток регистрации. Попробуйте позже.',
        ),
        (
            'window',
            'registration',
            'email',
            email,
            getattr(settings, 'REGISTRATION_RATE_LIMIT_EMAIL_MAX_ATTEMPTS', 6),
            window_seconds,
            'Для этого email временно превышен лимит регистраций. Попробуйте позже.',
        ),
        (
            'window',
            'registration',
            'session',
            get_rate_limit_session_key(request),
            getattr(settings, 'REGISTRATION_RATE_LIMIT_SESSION_MAX_ATTEMPTS', 10),
            window_seconds,
            'Слишком много попыток регистрации. Попробуйте позже.',
        ),
    )
    return _run_rate_limit_checks(checks)


def mark_registration_success(request, email):
    email = normalize_email(email)
    cooldown = getattr(
        settings,
        'REGISTRATION_COOLDOWN_SECONDS',
        getattr(settings, 'EMAIL_CODE_COOLDOWN_SECONDS', 60),
    )
    _set_cooldown('registration', 'ip', get_client_ip(request), cooldown)
    _set_cooldown('registration', 'email', email, cooldown)
    _set_cooldown('registration', 'session', get_rate_limit_session_key(request), cooldown)


def check_verify_code_rate_limits(request, phone, *, endpoint='verify-code'):
    phone = normalize_phone(phone)
    checks = (
        ('window', endpoint, 'ip', get_client_ip(request), 10, 15 * 60, 'Слишком много попыток. Попробуйте через 15 минут.'),
        ('window', endpoint, 'phone', phone, 10, 15 * 60, 'Для этого номера превышен лимит попыток. Попробуйте через 15 минут.'),
        ('window', endpoint, 'session', get_rate_limit_session_key(request), 14, 15 * 60, 'Слишком много попыток в этой сессии. Попробуйте через 15 минут.'),
    )
    return _run_rate_limit_checks(checks)


def check_verify_email_code_rate_limits(request, email, *, endpoint='verify-email-code'):
    email = normalize_email(email)
    checks = (
        ('window', endpoint, 'ip', get_client_ip(request), 10, 15 * 60, 'Слишком много попыток. Попробуйте через 15 минут.'),
        ('window', endpoint, 'email', email, 10, 15 * 60, 'Для этого email превышен лимит попыток. Попробуйте через 15 минут.'),
        ('window', endpoint, 'session', get_rate_limit_session_key(request), 14, 15 * 60, 'Слишком много попыток в этой сессии. Попробуйте через 15 минут.'),
    )
    return _run_rate_limit_checks(checks)


def _run_rate_limit_checks(checks):
    for check in checks:
        check_type = check[0]
        if check_type == 'cooldown':
            _, endpoint, scope, value, timeout, error_message = check
            if value and _cooldown_active(endpoint, scope, value):
                return False, error_message
        elif check_type == 'window':
            _, endpoint, scope, value, max_attempts, window_seconds, error_message = check
            if value:
                ok, error = _consume_sliding_window(endpoint, scope, value, max_attempts, window_seconds, error_message)
                if not ok:
                    return False, error
    return True, None


def _cooldown_active(endpoint, scope, value):
    return bool(cache.get(_build_cache_key(endpoint, scope, value, 'cooldown')))


def _set_cooldown(endpoint, scope, value, timeout):
    cache.set(_build_cache_key(endpoint, scope, value, 'cooldown'), 1, timeout=timeout)


def _consume_sliding_window(endpoint, scope, value, max_attempts, window_seconds, error_message):
    now = time.time()
    cache_key = _build_cache_key(endpoint, scope, value, 'window')
    attempts = cache.get(cache_key) or []
    attempts = [attempt for attempt in attempts if now - attempt < window_seconds]
    if len(attempts) >= max_attempts:
        cache.set(cache_key, attempts, timeout=window_seconds)
        return False, error_message
    attempts.append(now)
    cache.set(cache_key, attempts, timeout=window_seconds)
    return True, None


def _build_cache_key(endpoint, scope, value, mode):
    return f'accounts:rate-limit:{endpoint}:{scope}:{mode}:{value}'


def _is_trusted_proxy(remote_addr):
    trusted_proxies = getattr(settings, 'TRUSTED_PROXY_IPS', []) or []
    if not remote_addr or not trusted_proxies:
        return False
    try:
        remote_ip = ip_address(remote_addr)
    except ValueError:
        return False

    for candidate in trusted_proxies:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            if '/' in candidate:
                if remote_ip in ip_network(candidate, strict=False):
                    return True
            elif remote_ip == ip_address(candidate):
                return True
        except ValueError:
            continue
    return False
