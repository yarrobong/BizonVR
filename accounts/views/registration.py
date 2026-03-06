from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from config.legal_consent import get_legal_bundle_version

from ..forms import CompleteRegistrationForm
from .auth import _safe_redirect_url


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
        form = CompleteRegistrationForm(request.POST)
        if form.is_valid():
            profile.contact_name = form.cleaned_data['contact_name'].strip()
            profile.privacy_agreed_at = timezone.now()
            profile.privacy_policy_version = get_legal_bundle_version()
            profile.save()
            return redirect(_safe_redirect_url(next_url, 'home'))
    else:
        form = CompleteRegistrationForm(initial={'contact_name': profile.contact_name or ''})
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
