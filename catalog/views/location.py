from urllib.parse import urlparse

from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import City
from .common import _safe_redirect_target


@require_POST
def set_city_view(request):
    """Установить выбранный город в сессии. Редирект на next, referer или каталог."""
    city_id = request.POST.get('city_id')
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if not _safe_redirect_target(next_url, request):
        next_url = reverse('catalog:product_list')
    # На главной при смене города — в каталог, чтобы сразу видеть наличие
    if next_url:
        path = urlparse(next_url).path if '//' in next_url else next_url
        if path.rstrip('/') == '':
            next_url = reverse('catalog:product_list')
    if city_id:
        try:
            city_id = int(city_id)
            if City.objects.filter(pk=city_id).exists():
                request.session['selected_city_id'] = city_id
                request.session.modified = True
        except (TypeError, ValueError):
            pass
    else:
        request.session.pop('selected_city_id', None)
        request.session.modified = True
    return redirect(next_url)
