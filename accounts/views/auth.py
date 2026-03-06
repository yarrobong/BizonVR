import time

from django.conf import settings
from django.contrib.auth import logout
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..forms import CodeVerifyForm, PhoneRequestForm
from ..services import create_and_send_code, verify_code_and_login


def _get_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _safe_redirect_url(next_path, default='home'):
    """Разрешить редирект только на внутренний путь (без открытого редиректа)."""
    if not next_path or not next_path.startswith('/') or next_path.startswith('//'):
        return default
    return next_path


def _check_verify_rate_limit(ip):
    """Не более 5 попыток ввода кода за 15 минут с одного IP. Возвращает (ok, error_message)."""
    max_attempts = 5
    window_seconds = 15 * 60
    now = time.time()
    cache_key = f'accounts:verify_attempts:{ip}'
    times = cache.get(cache_key) or []
    times = [t for t in times if now - t < window_seconds]
    if len(times) >= max_attempts:
        return False, 'Слишком много попыток. Попробуйте через 15 минут.'
    times.append(now)
    cache.set(cache_key, times, timeout=window_seconds)
    return True, None


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
    cooldown = getattr(settings, 'SMS_COOLDOWN_SECONDS', 60)
    ip = _get_client_ip(request)
    cache_key = f'accounts:sms_cooldown:{ip}'
    if cache.get(cache_key):
        return JsonResponse({'ok': False, 'error': f'Подождите {cooldown} сек. перед повторной отправкой.'}, status=429)
    form = PhoneRequestForm(request.POST)
    if not form.is_valid():
        err_list = form.errors.get('phone') or form.errors.get('agree_privacy') or form.errors.get('__all__', ['Введите корректные данные'])
        msg = err_list[0] if err_list else 'Введите корректные данные'
        return JsonResponse({'ok': False, 'error': str(msg)}, status=400)
    phone = form.cleaned_data['phone']
    ok, error = create_and_send_code(phone)
    if ok:
        cache.set(cache_key, 1, timeout=cooldown)
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
        ip = _get_client_ip(request)
        ok_rate, err_rate = _check_verify_rate_limit(ip)
        if not ok_rate:
            return render(request, 'accounts/verify_code.html', {
                'form': CodeVerifyForm(request.POST),
                'phone': phone,
                'next_url': next_url,
                'error': err_rate,
            })
        form = CodeVerifyForm(request.POST)
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
        'form': form, 'phone': phone, 'next_url': next_url,
    })


@require_GET
def logout_view(request):
    """Выход."""
    logout(request)
    return redirect('home')
