from django.conf import settings
from django.db import connection
from django.http import Http404, HttpResponse

from catalog.models import City


def debug_cities_view(request):
    """Только при DEBUG: сколько городов в БД и какие — для проверки, что сайт и админка видят одну БД."""
    if not settings.DEBUG:
        raise Http404()
    db_name = connection.settings_dict.get('NAME', '?')
    cities = list(City.objects.order_by('order', 'name').values_list('name', flat=True))
    count = len(cities)
    body = (
        f"Database: {db_name}\n"
        f"Engine: {connection.settings_dict.get('ENGINE', '?')}\n"
        f"Host: {connection.settings_dict.get('HOST', '?')}\n"
        f"Городов в БД: {count}\n"
        f"Список: {', '.join(cities) or '(пусто)'}\n"
    )
    return HttpResponse(body, content_type='text/plain; charset=utf-8')
