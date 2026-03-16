import mimetypes
import os
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from catalog.models import CallbackRequest, Service

from ..forms import CallbackForm
from ..legal_consent import build_legal_acceptance_payload


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
    path = os.path.normpath(path).lstrip('/').lstrip('\\')
    if '..' in path or path.startswith('/'):
        raise Http404()
    media_root = os.path.abspath(os.path.realpath(str(settings.MEDIA_ROOT)))
    full_path = os.path.abspath(os.path.join(media_root, path))
    if not full_path.startswith(media_root):
        raise Http404()
    if os.path.isdir(full_path):
        raise Http404()
    if not os.path.exists(full_path):
        raise Http404()
    content_type, _ = mimetypes.guess_type(full_path)
    return FileResponse(
        open(full_path, 'rb'),
        as_attachment=False,
        content_type=content_type or 'application/octet-stream',
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
