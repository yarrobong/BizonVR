from django.contrib.auth import get_user_model, login
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from ..forms import PasswordResetPhoneVerifyForm, PasswordResetRequestForm, PasswordSetupForm
from ..models import Profile
from ..security import (
    check_send_code_rate_limits,
    check_send_email_rate_limits,
    check_verify_code_rate_limits,
    get_client_ip,
    mark_send_code_success,
    mark_send_email_success,
)
from ..services import (
    create_and_send_code,
    ensure_profile,
    get_user_by_email,
    get_user_by_phone,
    is_sms_debug_mode,
    send_password_reset_email,
    verify_sms_code,
)

User = get_user_model()
PASSWORD_RESET_PENDING_PHONE_SESSION_KEY = 'accounts:password-reset:pending-phone'
PASSWORD_RESET_VERIFIED_USER_SESSION_KEY = 'accounts:password-reset:verified-user-id'


def _set_password_reset_pending_phone(request, phone):
    request.session[PASSWORD_RESET_PENDING_PHONE_SESSION_KEY] = phone
    request.session.modified = True


def _clear_password_reset_pending_phone(request):
    if PASSWORD_RESET_PENDING_PHONE_SESSION_KEY in request.session:
        request.session.pop(PASSWORD_RESET_PENDING_PHONE_SESSION_KEY, None)
        request.session.modified = True


def _get_password_reset_pending_phone(request):
    return request.session.get(PASSWORD_RESET_PENDING_PHONE_SESSION_KEY, '') or ''


def _set_password_reset_verified_user(request, user):
    request.session[PASSWORD_RESET_VERIFIED_USER_SESSION_KEY] = user.pk
    request.session.modified = True


def _clear_password_reset_verified_user(request):
    if PASSWORD_RESET_VERIFIED_USER_SESSION_KEY in request.session:
        request.session.pop(PASSWORD_RESET_VERIFIED_USER_SESSION_KEY, None)
        request.session.modified = True


def _get_password_reset_verified_user(request):
    user_id = request.session.get(PASSWORD_RESET_VERIFIED_USER_SESSION_KEY)
    if not user_id:
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


def _complete_password_setup(request, user):
    ensure_profile(user)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    _clear_password_reset_pending_phone(request)
    _clear_password_reset_verified_user(request)
    return redirect('accounts:profile')


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def password_reset_request_view(request):
    success_channel = request.GET.get('sent', '')
    form = PasswordResetRequestForm(initial={'method': PasswordResetRequestForm.METHOD_PHONE})

    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            method = form.cleaned_data['method']

            if method == PasswordResetRequestForm.METHOD_PHONE:
                phone = form.cleaned_data['phone']
                user = get_user_by_phone(phone)
                if user is None:
                    form.add_error('phone', 'Аккаунт с таким номером не найден.')
                else:
                    ok_rate, rate_error = check_send_code_rate_limits(request, phone)
                    if not ok_rate:
                        form.add_error('phone', rate_error)
                    else:
                        ok, error = create_and_send_code(phone, client_ip=get_client_ip(request))
                        if ok:
                            mark_send_code_success(request, phone)
                            _set_password_reset_pending_phone(request, phone)
                            _clear_password_reset_verified_user(request)
                            return redirect(f"{reverse('accounts:password_reset_phone_verify')}?phone={phone}")
                        form.add_error('phone', error)
            else:
                email = form.cleaned_data['email']
                user = get_user_by_email(email)
                if user is None:
                    form.add_error('email', 'Аккаунт с таким email не найден.')
                else:
                    ok_rate, rate_error = check_send_email_rate_limits(
                        request,
                        email,
                        endpoint='password-reset-email',
                    )
                    if not ok_rate:
                        form.add_error('email', rate_error)
                    else:
                        ok, error = send_password_reset_email(user, request=request)
                        if ok:
                            mark_send_email_success(request, email, endpoint='password-reset-email')
                            _clear_password_reset_pending_phone(request)
                            _clear_password_reset_verified_user(request)
                            return redirect(f'{request.path}?sent=email')
                        form.add_error('email', error)

    return render(request, 'accounts/password_reset_request.html', {
        'form': form,
        'success_channel': success_channel,
    })


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def password_reset_phone_verify_view(request):
    pending_phone = _get_password_reset_pending_phone(request)
    phone = pending_phone or (request.GET.get('phone', '').strip())
    if not phone:
        return redirect('accounts:password_reset_request')

    if request.method == 'POST':
        form = PasswordResetPhoneVerifyForm(request.POST)
        phone = (request.POST.get('phone') or phone).strip()
        ok_rate, rate_error = check_verify_code_rate_limits(request, phone, endpoint='password-reset-phone-verify')
        if not ok_rate:
            return render(request, 'accounts/password_reset_phone_verify.html', {
                'form': form,
                'phone': phone,
                'error': rate_error,
                'sms_debug_mode': is_sms_debug_mode(),
            })
        if form.is_valid():
            phone = form.cleaned_data['phone']
            code = form.cleaned_data['code']
            ok, error = verify_sms_code(phone, code, consume=True)
            if ok:
                user = get_user_by_phone(phone)
                if user is None:
                    form.add_error('code', 'Аккаунт с таким номером не найден.')
                else:
                    _set_password_reset_verified_user(request, user)
                    _clear_password_reset_pending_phone(request)
                    return redirect('accounts:password_reset_set_password')
            else:
                form.add_error('code', error)
    else:
        form = PasswordResetPhoneVerifyForm(initial={'phone': phone})

    return render(request, 'accounts/password_reset_phone_verify.html', {
        'form': form,
        'phone': phone,
        'sms_debug_mode': is_sms_debug_mode(),
    })


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def password_reset_set_password_view(request):
    user = _get_password_reset_verified_user(request)
    if user is None:
        return redirect('accounts:password_reset_request')

    form = PasswordSetupForm(user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return _complete_password_setup(request, user)

    return render(request, 'accounts/password_reset_set_password.html', {
        'form': form,
        'recovery_method': 'phone',
        'invalid_link': False,
    })


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def password_reset_confirm_view(request, uidb64, token):
    user = None
    try:
        user_id = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.filter(pk=user_id, is_active=True).first()
    except Exception:
        user = None

    is_valid_link = bool(user and default_token_generator.check_token(user, token))
    form = PasswordSetupForm(user, request.POST or None) if is_valid_link else None

    if is_valid_link and request.method == 'POST' and form.is_valid():
        form.save()
        return _complete_password_setup(request, user)

    return render(request, 'accounts/password_reset_set_password.html', {
        'form': form,
        'recovery_method': 'email',
        'invalid_link': not is_valid_link,
    })
