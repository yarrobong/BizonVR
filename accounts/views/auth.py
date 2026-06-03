from urllib.parse import urlencode

from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from config.legal_consent import get_legal_bundle_version

from ..forms import (
    PasswordLoginForm,
    RegistrationEmailConfirmForm,
    RegistrationForm,
)
from ..models import Profile
from ..security import (
    check_registration_rate_limits,
    check_send_email_rate_limits,
    check_verify_email_code_rate_limits,
    mark_registration_success,
    mark_send_email_success,
)
from ..services import (
    authenticate_by_login_identifier,
    auto_claim_guest_orders_for_user,
    build_absolute_url,
    confirm_email_verification,
    create_and_send_email_code,
    build_unique_email_username,
    ensure_profile,
    get_or_create_notification_preferences,
    get_default_profile_phone,
    normalize_email,
)

User = get_user_model()
REGISTER_CONFIRM_TEMPLATE = 'accounts/register_confirm.html'


def _safe_redirect_url(next_path, default='home'):
    """Разрешить редирект только на внутренний путь (без открытого редиректа)."""
    if not next_path or not next_path.startswith('/') or next_path.startswith('//'):
        return default
    return next_path


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


def _render_login_page(
    request,
    *,
    next_url='',
    password_form=None,
    register_form=None,
    show_password_registration=False,
):
    return render(request, 'accounts/login.html', {
        'password_form': password_form or PasswordLoginForm(),
        'register_form': register_form or RegistrationForm(),
        'next_url': next_url,
        'show_password_registration': show_password_registration,
    })


def _get_unverified_registered_user(email):
    email = normalize_email(email)
    if not email:
        return None
    return (
        User.objects
        .filter(email__iexact=email, is_active=True, profile__email_verified_at__isnull=True)
        .first()
    )


def _build_register_confirm_url(request, email, next_url=''):
    query = {'email': normalize_email(email)}
    if next_url:
        query['next'] = next_url
    return build_absolute_url(f"{reverse('accounts:register_confirm')}?{urlencode(query)}", request=request)


def _should_show_registration_form(request):
    return (request.GET.get('mode') or '').strip().lower() == 'register'


@require_http_methods(['GET'])
def login_view(request):
    """Публичный экран входа: только email + пароль и регистрация."""
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.GET.get('next'), 'accounts:profile'))
    return _render_login_page(
        request,
        next_url=request.GET.get('next', ''),
        show_password_registration=_should_show_registration_form(request),
    )


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

    return _render_login_page(
        request,
        next_url=request.POST.get('next', ''),
        password_form=form,
    )


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
            next_url = request.POST.get('next', '')
            ok_rate, rate_error = check_registration_rate_limits(request, form.cleaned_data['email'])
            if not ok_rate:
                form.add_error('email', rate_error)
            else:
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
                    privacy_agreed_at=timezone.now(),
                    privacy_policy_version=get_legal_bundle_version(),
                )
                ok, error = create_and_send_email_code(
                    user,
                    form.cleaned_data['email'],
                    action_url=_build_register_confirm_url(request, form.cleaned_data['email'], next_url),
                )
                if not ok:
                    user.delete()
                    form.add_error('email', error)
                else:
                    mark_registration_success(request, form.cleaned_data['email'])
                    confirm_url = reverse('accounts:register_confirm')
                    query = {'email': form.cleaned_data['email']}
                    if next_url:
                        query['next'] = next_url
                    confirm_url = f'{confirm_url}?{urlencode(query)}'
                    return redirect(confirm_url)
    else:
        form = RegistrationForm()

    return _render_login_page(
        request,
        next_url=request.POST.get('next', '') if request.method == 'POST' else request.GET.get('next', ''),
        register_form=form,
        show_password_registration=True,
    )


@require_http_methods(['GET', 'POST'])
def register_confirm_view(request):
    next_url = request.POST.get('next', '') if request.method == 'POST' else request.GET.get('next', '')
    initial_email = request.POST.get('email', '') if request.method == 'POST' else request.GET.get('email', '')
    resend_error = ''
    resend_success = ''

    if request.method == 'POST' and (request.POST.get('action') or 'confirm_email') == 'resend_email':
        email = normalize_email(request.POST.get('email') or '')
        confirm_form = RegistrationEmailConfirmForm(initial={'email': email})
        user = _get_unverified_registered_user(email)
        if user is None:
            resend_error = 'Регистрация с таким email не найдена или уже завершена.'
        else:
            ok_rate, rate_error = check_send_email_rate_limits(
                request,
                email,
                endpoint='registration-email-code',
            )
            if not ok_rate:
                ok, error = False, rate_error
            else:
                ok, error = create_and_send_email_code(
                    user,
                    email,
                    action_url=_build_register_confirm_url(request, email, next_url),
                )
            if ok:
                mark_send_email_success(request, email, endpoint='registration-email-code')
                resend_success = 'Письмо с новым кодом отправлено.'
            else:
                resend_error = error
        return render(request, REGISTER_CONFIRM_TEMPLATE, {
            'form': confirm_form,
            'email': email,
            'next_url': next_url,
            'resend_error': resend_error,
            'resend_success': resend_success,
        })

    form = RegistrationEmailConfirmForm(request.POST or None, initial={'email': initial_email})
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        ok_rate, rate_error = check_verify_email_code_rate_limits(
            request,
            email,
            endpoint='registration-email-code',
        )
        user = _get_unverified_registered_user(email)
        if not ok_rate:
            form.add_error('code', rate_error)
        elif user is None:
            form.add_error('email', 'Регистрация с таким email не найдена или уже завершена.')
        else:
            ok, error = confirm_email_verification(user, email, form.cleaned_data['code'])
            if ok:
                get_or_create_notification_preferences(user)
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect(_safe_redirect_url(next_url, 'home'))
            form.add_error('code', error)

    return render(request, REGISTER_CONFIRM_TEMPLATE, {
        'form': form,
        'email': initial_email,
        'next_url': next_url,
        'resend_error': resend_error,
        'resend_success': resend_success,
    })
