from django.conf import settings
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import CodeVerifyForm, PasswordLoginForm, PhoneRequestForm
from ..models import Profile
from ..security import check_send_code_rate_limits, check_verify_code_rate_limits, get_client_ip, mark_send_code_success
from ..services import (
    authenticate_by_login_identifier,
    create_and_send_code,
    is_sms_debug_mode,
    is_turnstile_debug_bypass,
    is_turnstile_enabled,
    normalize_phone,
    verify_code_and_login,
    verify_turnstile_token,
)

LOGIN_PENDING_PHONE_SESSION_KEY = 'accounts:login:pending_phone'
LOGIN_PENDING_SENT_AT_SESSION_KEY = 'accounts:login:last_sent_at'


def _safe_redirect_url(next_path, default='home'):
    """Разрешить редирект только на внутренний путь (без открытого редиректа)."""
    if not next_path or not next_path.startswith('/') or next_path.startswith('//'):
        return default
    return next_path


def _set_login_pending_state(request, phone):
    request.session[LOGIN_PENDING_PHONE_SESSION_KEY] = normalize_phone(phone)
    request.session[LOGIN_PENDING_SENT_AT_SESSION_KEY] = int(timezone.now().timestamp())
    request.session.modified = True


def _clear_login_pending_state(request):
    had_changes = False
    for key in (LOGIN_PENDING_PHONE_SESSION_KEY, LOGIN_PENDING_SENT_AT_SESSION_KEY):
        if key in request.session:
            request.session.pop(key, None)
            had_changes = True
    if had_changes:
        request.session.modified = True


def _get_login_pending_phone(request):
    return normalize_phone(request.session.get(LOGIN_PENDING_PHONE_SESSION_KEY, '') or '')


def _get_login_resend_available_in(request):
    sent_at_ts = request.session.get(LOGIN_PENDING_SENT_AT_SESSION_KEY)
    phone = _get_login_pending_phone(request)
    if not phone or sent_at_ts is None:
        return 0
    try:
        sent_at_ts = int(sent_at_ts)
    except (TypeError, ValueError):
        return 0
    cooldown = getattr(settings, 'SMS_COOLDOWN_SECONDS', 60)
    elapsed = max(0, int(timezone.now().timestamp()) - sent_at_ts)
    return max(0, cooldown - elapsed)


def _redirect_after_successful_auth(request):
    Profile.objects.get_or_create(user=request.user, defaults={'phone': request.user.username})
    profile = request.user.profile
    next_path = request.POST.get('next') or request.GET.get('next') or ''

    if not profile.contact_name or not profile.privacy_agreed_at:
        from urllib.parse import urlencode
        from django.urls import reverse

        url = reverse('accounts:complete_registration')
        if next_path:
            url += '?' + urlencode({'next': next_path})
        return redirect(url)

    return redirect(_safe_redirect_url(next_path, 'home'))


@require_http_methods(['GET', 'POST'])
def login_view(request):
    """Страница входа: пароль по телефону/email или вход по SMS."""
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.GET.get('next'), 'accounts:profile'))
    password_form = PasswordLoginForm()
    if request.method == 'POST':
        password_form = PasswordLoginForm(request.POST)
        if password_form.is_valid():
            user, error = authenticate_by_login_identifier(
                password_form.cleaned_data['login'],
                password_form.cleaned_data['password'],
                request=request,
            )
            if user is not None:
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return _redirect_after_successful_auth(request)
            password_form.add_error(None, error)

    return render(request, 'accounts/login.html', {
        'form': PhoneRequestForm(),
        'password_form': password_form,
        'next_url': request.GET.get('next', '') or request.POST.get('next', ''),
        'turnstile_enabled': is_turnstile_enabled(),
        'turnstile_site_key': settings.TURNSTILE_SITE_KEY,
        'turnstile_disabled_locally': is_turnstile_debug_bypass(),
    })


@require_POST
def send_code_view(request):
    """API: отправить код на телефон. Ограничение по IP и по номеру."""
    client_ip = get_client_ip(request)
    turnstile_ok, turnstile_error = verify_turnstile_token(
        request.POST.get('cf-turnstile-response', '') or '',
        client_ip=client_ip,
    )
    if not turnstile_ok:
        return JsonResponse({'ok': False, 'error': turnstile_error}, status=400)
    form = PhoneRequestForm(request.POST)
    if not form.is_valid():
        err_list = form.errors.get('phone') or form.errors.get('agree_privacy') or form.errors.get('__all__', ['Введите корректные данные'])
        msg = err_list[0] if err_list else 'Введите корректные данные'
        return JsonResponse({'ok': False, 'error': str(msg)}, status=400)
    phone = form.cleaned_data['phone']
    ok_rate, rate_error = check_send_code_rate_limits(request, phone)
    if not ok_rate:
        return JsonResponse({'ok': False, 'error': rate_error}, status=429)
    ok, error = create_and_send_code(phone, client_ip=client_ip)
    if ok:
        mark_send_code_success(request, phone)
        _set_login_pending_state(request, phone)
        return JsonResponse({
            'ok': True,
            'phone': phone,
            'cooldown_seconds': getattr(settings, 'SMS_COOLDOWN_SECONDS', 60),
        })
    return JsonResponse({'ok': False, 'error': error}, status=400)


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def verify_code_view(request):
    """Шаг 2: ввод кода. GET — форма с phone в query; POST — проверка и вход."""
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.GET.get('next'), 'accounts:profile'))
    pending_phone = _get_login_pending_phone(request)
    phone = pending_phone or request.GET.get('phone', '').strip()
    next_url = request.GET.get('next', '')
    if request.method == 'POST':
        form = CodeVerifyForm(request.POST)
        phone = (request.POST.get('phone') or phone).strip()
        next_url = request.POST.get('next') or next_url
        ok_rate, err_rate = check_verify_code_rate_limits(request, phone, endpoint='verify-code')
        if not ok_rate:
            return render(request, 'accounts/verify_code.html', {
                'form': form,
                'phone': phone,
                'next_url': next_url,
                'error': err_rate,
                'sms_debug_mode': is_sms_debug_mode(),
                'can_resend_code': bool(pending_phone),
                'resend_available_in': _get_login_resend_available_in(request),
            })
        if form.is_valid():
            phone = form.cleaned_data['phone']
            code = form.cleaned_data['code']
            ok, error = verify_code_and_login(phone, code, request)
            if ok:
                _clear_login_pending_state(request)
                return _redirect_after_successful_auth(request)
            form.add_error('code', error)
    else:
        form = CodeVerifyForm(initial={'phone': phone})
    return render(request, 'accounts/verify_code.html', {
        'form': form,
        'phone': phone,
        'next_url': next_url,
        'sms_debug_mode': is_sms_debug_mode(),
        'can_resend_code': bool(pending_phone),
        'resend_available_in': _get_login_resend_available_in(request),
    })


@require_POST
def resend_code_view(request):
    """API: повторно отправить код на номер из текущей login-сессии."""
    phone = _get_login_pending_phone(request)
    if not phone:
        return JsonResponse({
            'ok': False,
            'error': 'Сессия подтверждения истекла. Запросите код заново.',
        }, status=400)

    ok_rate, rate_error = check_send_code_rate_limits(request, phone)
    if not ok_rate:
        return JsonResponse({
            'ok': False,
            'error': rate_error,
            'resend_available_in': _get_login_resend_available_in(request),
        }, status=429)

    ok, error = create_and_send_code(phone, client_ip=get_client_ip(request))
    if ok:
        mark_send_code_success(request, phone)
        _set_login_pending_state(request, phone)
        return JsonResponse({
            'ok': True,
            'phone': phone,
            'resend_available_in': getattr(settings, 'SMS_COOLDOWN_SECONDS', 60),
        })

    return JsonResponse({
        'ok': False,
        'error': error,
        'resend_available_in': _get_login_resend_available_in(request),
    }, status=400)


@require_POST
def logout_view(request):
    """Выход."""
    logout(request)
    return redirect('home')
