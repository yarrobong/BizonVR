from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..forms import CodeVerifyForm, PhoneRequestForm
from ..security import check_send_code_rate_limits, check_verify_code_rate_limits, mark_send_code_success
from ..services import create_and_send_code, is_sms_debug_mode, verify_code_and_login


def _safe_redirect_url(next_path, default='home'):
    """Разрешить редирект только на внутренний путь (без открытого редиректа)."""
    if not next_path or not next_path.startswith('/') or next_path.startswith('//'):
        return default
    return next_path


@require_GET
def login_view(request):
    """Страница входа: шаг 1 — ввод телефона."""
    if request.user.is_authenticated:
        return redirect(request.GET.get('next') or 'accounts:profile')
    return render(request, 'accounts/login.html', {
        'form': PhoneRequestForm(),
        'next_url': request.GET.get('next', ''),
    })


@require_POST
def send_code_view(request):
    """API: отправить код на телефон. Ограничение по IP и по номеру."""
    form = PhoneRequestForm(request.POST)
    if not form.is_valid():
        err_list = form.errors.get('phone') or form.errors.get('agree_privacy') or form.errors.get('__all__', ['Введите корректные данные'])
        msg = err_list[0] if err_list else 'Введите корректные данные'
        return JsonResponse({'ok': False, 'error': str(msg)}, status=400)
    phone = form.cleaned_data['phone']
    ok_rate, rate_error = check_send_code_rate_limits(request, phone)
    if not ok_rate:
        return JsonResponse({'ok': False, 'error': rate_error}, status=429)
    ok, error = create_and_send_code(phone)
    if ok:
        mark_send_code_success(request, phone)
        return JsonResponse({'ok': True, 'phone': phone})
    return JsonResponse({'ok': False, 'error': error}, status=400)


@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def verify_code_view(request):
    """Шаг 2: ввод кода. GET — форма с phone в query; POST — проверка и вход."""
    if request.user.is_authenticated:
        return redirect(_safe_redirect_url(request.GET.get('next'), 'accounts:profile'))
    phone = request.GET.get('phone', '').strip()
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
            })
        if form.is_valid():
            phone = form.cleaned_data['phone']
            code = form.cleaned_data['code']
            ok, error = verify_code_and_login(phone, code, request)
            if ok:
                profile = request.user.profile
                if not profile.contact_name or not profile.privacy_agreed_at:
                    next_q = request.POST.get('next') or request.GET.get('next') or ''
                    from urllib.parse import urlencode
                    from django.urls import reverse

                    url = reverse('accounts:complete_registration')
                    if next_q:
                        url += '?' + urlencode({'next': next_q})
                    return redirect(url)
                next_path = request.POST.get('next') or request.GET.get('next') or ''
                target = _safe_redirect_url(next_path, 'home')
                return redirect(target)
            form.add_error('code', error)
    else:
        form = CodeVerifyForm(initial={'phone': phone})
    return render(request, 'accounts/verify_code.html', {
        'form': form,
        'phone': phone,
        'next_url': next_url,
        'sms_debug_mode': is_sms_debug_mode(),
    })


@require_POST
def logout_view(request):
    """Выход."""
    logout(request)
    return redirect('home')
