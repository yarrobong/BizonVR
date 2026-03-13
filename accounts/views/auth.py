from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from config.legal_consent import get_legal_bundle_version

from ..forms import (
    CodeVerifyForm,
    EmailLoginRequestForm,
    EmailLoginVerifyForm,
    PasswordLoginForm,
    PhoneRequestForm,
    RegistrationForm,
)
from ..models import Profile
from ..security import (
    check_send_code_rate_limits,
    check_send_email_rate_limits,
    check_verify_code_rate_limits,
    check_verify_email_code_rate_limits,
    get_client_ip,
    mark_send_code_success,
    mark_send_email_success,
)
from ..services import (
    authenticate_by_login_identifier,
    auto_claim_guest_orders_for_user,
    build_phone_display,
    build_unique_email_username,
    create_and_send_code,
    create_and_send_email_login_code,
    ensure_profile,
    get_default_profile_phone,
    get_or_create_notification_preferences,
    is_sms_debug_mode,
    is_turnstile_enabled,
    login_with_email_code,
    normalize_phone,
    verify_code_and_login,
    verify_turnstile_token,
)

LOGIN_PENDING_PHONE_SESSION_KEY = 'accounts:login:pending_phone'
LOGIN_PENDING_SENT_AT_SESSION_KEY = 'accounts:login:last_sent_at'
User = get_user_model()


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


def _format_phone_display(phone):
    return build_phone_display(phone) or phone


def _redirect_after_successful_auth(request):
    ensure_profile(request.user)
    profile = request.user.profile
    next_path = request.POST.get('next') or request.GET.get('next') or ''

    if next_path:
        return redirect(_safe_redirect_url(next_path, 'home'))

    if not profile.contact_name or not profile.privacy_agreed_at:
        from django.urls import reverse

        return redirect(f"{reverse('accounts:profile_settings')}#profile")

    return redirect('home')


@require_http_methods(['GET'])
def login_view(request):
    """Публичный экран входа: email + пароль и регистрация."""
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.GET.get('next'), 'accounts:profile'))
    return render(request, 'accounts/login.html', {
        'password_form': PasswordLoginForm(),
        'register_form': RegistrationForm(),
        'next_url': request.GET.get('next', ''),
        'active_panel': 'login',
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
        'phone_display': _format_phone_display(phone),
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
def password_login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.POST.get('next'), 'accounts:profile'))

    form = PasswordLoginForm(request.POST)
    if form.is_valid():
        user, error = authenticate_by_login_identifier(
            form.cleaned_data['login'],
            request.POST.get('password', ''),
            request=request,
        )
        if user is not None:
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            get_or_create_notification_preferences(user)
            auto_claim_guest_orders_for_user(user)
            return _redirect_after_successful_auth(request)
        form.add_error(None, error)

    return render(request, 'accounts/login.html', {
        'password_form': form,
        'register_form': RegistrationForm(),
        'next_url': request.POST.get('next', ''),
        'active_panel': 'login',
    })


@require_POST
def send_email_login_code_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.POST.get('next'), 'accounts:profile'))

    form = EmailLoginRequestForm(request.POST)
    if form.is_valid():
        email = form.cleaned_data['email']
        ok_rate, rate_error = check_send_email_rate_limits(request, email, endpoint='login-email-code')
        if not ok_rate:
            form.add_error('email', rate_error)
        else:
            ok, error = create_and_send_email_login_code(email)
            if ok:
                mark_send_email_success(request, email, endpoint='login-email-code')
                next_url = request.POST.get('next', '')
                redirect_url = f"{reverse('accounts:verify_email_login')}?email={email}"
                if next_url:
                    redirect_url += f"&next={next_url}"
                return redirect(redirect_url)
            form.add_error('email', error)

    return render(request, 'accounts/login.html', {
        'password_form': PasswordLoginForm(initial={'login': request.POST.get('login', '')}),
        'register_form': RegistrationForm(),
        'next_url': request.POST.get('next', ''),
        'active_panel': 'login',
    })


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def verify_email_login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.GET.get('next'), 'accounts:profile'))

    email = (request.GET.get('email') or '').strip().lower()
    next_url = request.GET.get('next', '')
    if request.method == 'POST':
        form = EmailLoginVerifyForm(request.POST)
        email = (request.POST.get('email') or email).strip().lower()
        next_url = request.POST.get('next') or next_url
        ok_rate, rate_error = check_verify_email_code_rate_limits(
            request,
            email,
            endpoint='verify-email-login',
        )
        if not ok_rate:
            return render(request, 'accounts/verify_email_login.html', {
                'form': form,
                'email': email,
                'next_url': next_url,
                'error': rate_error,
            })
        if form.is_valid():
            ok, error, _user = login_with_email_code(email, form.cleaned_data['code'], request)
            if ok:
                return _redirect_after_successful_auth(request)
            form.add_error('code', error)
    else:
        form = EmailLoginVerifyForm(initial={'email': email})

    return render(request, 'accounts/verify_email_login.html', {
        'form': form,
        'email': email,
        'next_url': next_url,
    })


@require_POST
def logout_view(request):
    """Выход."""
    logout(request)
    return redirect('home')


@require_http_methods(['GET', 'POST'])
def register_view(request):
    if request.user.is_authenticated:
        target = request.POST.get('next') if request.method == 'POST' else request.GET.get('next')
        return redirect(_safe_redirect_url(target, 'accounts:profile'))

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=build_unique_email_username(),
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password1'],
                is_active=True,
            )
            Profile.objects.create(
                user=user,
                phone=get_default_profile_phone(user),
                contact_name=form.cleaned_data['contact_name'],
                email_verified_at=timezone.now(),
                privacy_agreed_at=timezone.now(),
                privacy_policy_version=get_legal_bundle_version(),
            )
            get_or_create_notification_preferences(user)
            auto_claim_guest_orders_for_user(user)
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return _redirect_after_successful_auth(request)
    else:
        form = RegistrationForm()

    return render(request, 'accounts/login.html', {
        'password_form': PasswordLoginForm(),
        'register_form': form,
        'next_url': request.POST.get('next', '') if request.method == 'POST' else request.GET.get('next', ''),
        'active_panel': 'register',
    })
