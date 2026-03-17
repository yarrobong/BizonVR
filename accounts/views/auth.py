from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from config.legal_consent import get_legal_bundle_version

from ..forms import (
    PasswordLoginForm,
    RegistrationForm,
)
from ..models import Profile
from ..services import (
    authenticate_by_login_identifier,
    auto_claim_guest_orders_for_user,
    build_unique_email_username,
    ensure_profile,
    get_default_profile_phone,
    get_or_create_notification_preferences,
)

User = get_user_model()


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


@require_http_methods(['GET'])
def login_view(request):
    """Публичный экран входа: только email + пароль и регистрация."""
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.GET.get('next'), 'accounts:profile'))
    return _render_login_page(request, next_url=request.GET.get('next', ''))


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

    return _render_login_page(
        request,
        next_url=request.POST.get('next', '') if request.method == 'POST' else request.GET.get('next', ''),
        register_form=form,
        show_password_registration=True,
    )
