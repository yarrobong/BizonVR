import mimetypes
import os
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from catalog.models import CallbackRequest, ContactRequest, Service
from config.solution_landings import get_solution_landing
from config.views.solutions import build_solution_hub_cards

from ..forms import CallbackForm, CompactVRForm
from ..legal_consent import build_legal_acceptance_payload

CONFERENCE_ATTRACTIONS_DIRNAME = 'Конференция (Аттракционы)'
INVEST_DIRNAME = 'invest (sponsor) 2'
INVEST_2_DIRNAME = 'invest_2'


def _serve_public_directory_file(base_dir, requested_path='', *, default_file=None):
    requested_path = requested_path or default_file
    if not requested_path:
        raise Http404()

    normalized_path = os.path.normpath(str(requested_path)).lstrip('/').lstrip('\\')
    if normalized_path in {'.', ''}:
        normalized_path = default_file or ''
    if not normalized_path or '..' in normalized_path or normalized_path.startswith('/'):
        raise Http404()

    base_dir = os.path.abspath(os.path.realpath(str(base_dir)))
    full_path = os.path.abspath(os.path.realpath(os.path.join(base_dir, normalized_path)))
    if os.path.commonpath([base_dir, full_path]) != base_dir:
        raise Http404()
    if os.path.isdir(full_path) or not os.path.exists(full_path):
        raise Http404()

    content_type, _ = mimetypes.guess_type(full_path)
    return FileResponse(
        open(full_path, 'rb'),
        as_attachment=False,
        content_type=content_type or 'application/octet-stream',
    )


def favicon_view(request):
    """Отдаём favicon по ожидаемому пути /favicon.ico."""
    candidates = [
        ('favicon.ico', 'image/x-icon'),
        ('images/favicon.ico', 'image/x-icon'),
        ('images/favicon-32x32.png', 'image/png'),
        ('images/favicon.svg', 'image/svg+xml'),
    ]
    for rel_path, content_type in candidates:
        full_path = finders.find(rel_path)
        if full_path:
            resp = FileResponse(open(full_path, 'rb'), content_type=content_type)
            resp['Cache-Control'] = 'public, max-age=31536000, immutable'
            return resp
    raise Http404()


def robots_txt_view(request):
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /accounts/',
        '',
        'Allow: /',
        '',
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
        '',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')


def serve_media(request, path):
    """Раздача медиа при DEBUG или SERVE_MEDIA=1."""
    return _serve_public_directory_file(settings.MEDIA_ROOT, path)


def conference_attractions_view(request, path=''):
    """Standalone-лендинг VR-аттракционов и его локальные ассеты."""
    landing_root = settings.BASE_DIR / CONFERENCE_ATTRACTIONS_DIRNAME
    return _serve_public_directory_file(landing_root, path, default_file='index.html')


def invest_view(request, path=''):
    """Standalone-инвестиционный лендинг и его локальные ассеты."""
    landing_root = settings.BASE_DIR / INVEST_DIRNAME
    return _serve_public_directory_file(landing_root, path, default_file='index.html')


def invest_2_view(request, path=''):
    """Альтернативный URL для standalone-инвестиционного лендинга."""
    landing_root = settings.BASE_DIR / INVEST_DIRNAME
    return _serve_public_directory_file(landing_root, path, default_file='index.html')


def invest_2_new_view(request, path=''):
    """Standalone-лендинг для папки invest_2 и его локальные ассеты."""
    landing_root = settings.BASE_DIR / INVEST_2_DIRNAME
    return _serve_public_directory_file(landing_root, path, default_file='index.html')


def solutions_index_view(request):
    """Индекс standalone-лендингов под /solutions/."""
    return render(
        request,
        'solutions/index.html',
        {
            'solution_landings': build_solution_hub_cards(),
            'hide_footer_products': True,
        },
    )


def solution_landing_view(request, slug, path=''):
    """Generic standalone-лендинг из реестра solution_landings."""
    if request.method == 'GET' and request.headers.get('HX-Boosted') == 'true':
        response = HttpResponse(status=204)
        response['HX-Redirect'] = request.get_full_path()
        return response

    landing = get_solution_landing(slug)
    if landing is None:
        raise Http404()
    return _serve_public_directory_file(landing.root_dir, path, default_file='index.html')


def compact_vr_view(request):
    """Лендинг компактной VR-арены под ключ и его локальные ассеты."""
    if request.method == 'GET' and request.headers.get('HX-Boosted') == 'true':
        response = HttpResponse(status=204)
        response['HX-Redirect'] = request.get_full_path()
        return response

    lead_form = CompactVRForm()
    if request.method == 'POST' and request.POST.get('form_type') == 'compact_vr':
        lead_form = CompactVRForm(request.POST)
        if lead_form.is_valid():
            d = lead_form.cleaned_data
            message_parts = [f'Город: {d["city"]}', f'Формат: {d["format"]}']
            if d.get('premises'):
                message_parts.append(f'Площадь / помещение: {d["premises"]}')
            if d.get('comment'):
                message_parts.append(f'Комментарий: {d["comment"]}')
            ContactRequest.objects.create(
                name=d['name'],
                email=d.get('email', ''),
                phone=d['contact'],
                message='\n'.join(message_parts),
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Заявка отправлена! Мы свяжемся с вами в ближайшее время.')
            return redirect(reverse('compact_vr') + '#contact')

    return render(
        request,
        'compact_vr.html',
        {
            'lead_form': lead_form,
            'hide_footer_products': True,
        },
    )


def not_found_view(request, exception=None, unmatched_path=''):
    requested_path = request.path
    if unmatched_path:
        requested_path = '/' + unmatched_path.lstrip('/')
    return render(
        request,
        '404.html',
        {
            'requested_path': requested_path,
        },
        status=404,
    )


def permission_denied_view(request, exception=None):
    return render(
        request,
        '403.html',
        status=403,
    )


def arenda_view(request):
    """Страница аренды VR-шлемов Meta Quest."""
    media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'

    def build_media_url(relative_path):
        if not relative_path:
            return ''
        encoded = '/'.join(quote(part, safe='') for part in relative_path.lstrip('/').split('/'))
        return request.build_absolute_uri(media_url + encoded)

    callback_form = CallbackForm()
    if request.method == 'POST' and request.POST.get('form_type') == 'callback':
        callback_form = CallbackForm(request.POST)
        if callback_form.is_valid():
            CallbackRequest.objects.create(
                name=callback_form.cleaned_data.get('name', '').strip(),
                phone=callback_form.cleaned_data['phone'],
                source='arenda',
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Заявка отправлена! Мы перезвоним в ближайшее время.')
            return redirect(reverse('arenda') + '#contacts')

    return render(request, 'arenda.html', {
        'quest3_image_url': build_media_url('rent/Quest 3.webp'),
        'quest2_image_url': build_media_url('rent/Quest 2.webp'),
        'callback_form': callback_form,
    })


def uslugi_view(request):
    """Страница услуг компании."""
    services = Service.objects.filter(is_active=True).order_by('order', 'name')
    callback_form = CallbackForm()

    if request.method == 'POST' and request.POST.get('form_type') == 'callback':
        callback_form = CallbackForm(request.POST)
        if callback_form.is_valid():
            CallbackRequest.objects.create(
                name=callback_form.cleaned_data.get('name', '').strip(),
                phone=callback_form.cleaned_data['phone'],
                source='uslugi',
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Заявка отправлена! Мы перезвоним в ближайшее время.')
            return redirect(reverse('uslugi') + '#contacts')

    return render(
        request,
        'uslugi.html',
        {
            'services': services,
            'callback_form': callback_form,
        },
    )
