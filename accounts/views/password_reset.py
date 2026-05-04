from django.contrib.auth import get_user_model, login
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import redirect, render
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from ..forms import PasswordResetRequestForm, PasswordSetupForm
from ..security import check_send_email_rate_limits, mark_send_email_success
from ..services import (
    ensure_profile,
    get_user_by_email,
    send_password_reset_email,
)

User = get_user_model()


def _complete_password_setup(request, user):
    ensure_profile(user)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return redirect('accounts:profile')


def _password_reset_sent_redirect(request):
    return redirect(f'{request.path}?sent=email')


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def password_reset_request_view(request):
    success_channel = request.GET.get('sent', '')
    form = PasswordResetRequestForm()

    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            ok_rate, rate_error = check_send_email_rate_limits(
                request,
                email,
                endpoint='password-reset-email',
            )
            if not ok_rate:
                form.add_error('email', rate_error)
            else:
                user = get_user_by_email(email)
                if user is not None:
                    ok, error = send_password_reset_email(user, request=request)
                    if ok:
                        mark_send_email_success(request, email, endpoint='password-reset-email')
                else:
                    mark_send_email_success(request, email, endpoint='password-reset-email')
                return _password_reset_sent_redirect(request)

    return render(request, 'accounts/password_reset_request.html', {
        'form': form,
        'success_channel': success_channel,
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
