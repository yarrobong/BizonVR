from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from config.legal_consent import get_legal_bundle_version

from ..forms import CompleteRegistrationForm
from ..services import create_and_send_email_code
from .auth import _safe_redirect_url

PROFILE_PENDING_ALERTS_SESSION_KEY = 'accounts:profile:pending_alerts'


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def complete_registration_view(request):
    """Шаг 3: завершение регистрации — ФИО и согласие на обработку ПД."""
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    from ..models import Profile

    Profile.objects.get_or_create(user=request.user, defaults={'phone': request.user.username})
    profile = request.user.profile
    if profile.contact_name and profile.privacy_agreed_at:
        next_path = request.GET.get('next', '')
        return redirect(_safe_redirect_url(next_path, 'home'))
    next_url = request.GET.get('next', '') or request.POST.get('next', '')
    if request.method == 'POST':
        form = CompleteRegistrationForm(request.POST, current_user=request.user)
        if form.is_valid():
            profile.contact_name = form.cleaned_data['contact_name'].strip()
            profile.privacy_agreed_at = timezone.now()
            profile.privacy_policy_version = get_legal_bundle_version()
            profile.save()
            email = form.cleaned_data.get('email', '')
            if email and not profile.email_verified_at:
                ok, error = create_and_send_email_code(request.user, email)
                if ok:
                    pending_alerts = list(request.session.get(PROFILE_PENDING_ALERTS_SESSION_KEY, []))
                    pending_alerts.append({
                        'level': 'success',
                        'text': f'Письмо с кодом подтверждения отправлено на {email}.',
                    })
                    request.session[PROFILE_PENDING_ALERTS_SESSION_KEY] = pending_alerts
                    request.session.modified = True
                    return redirect(f"{reverse('accounts:profile')}#security")
                form.add_error('email', error)
            else:
                return redirect(_safe_redirect_url(next_url, 'home'))
    else:
        form = CompleteRegistrationForm(initial={
            'contact_name': profile.contact_name or '',
            'email': request.user.email or '',
        }, current_user=request.user)
    digits = profile.phone
    if len(digits) == 10 and digits.isdigit():
        phone_display = f'+7 ({digits[:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}'
    else:
        phone_display = profile.phone
    return render(request, 'accounts/complete_registration.html', {
        'form': form,
        'phone': phone_display,
        'next_url': next_url,
    })
