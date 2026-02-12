"""Шаблонные теги для каталога."""
import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def filter_url(context, **kwargs):
    """Строит query string с обновлёнными GET-параметрами. Удалить: param=None."""
    request = context.get('request')
    if not request:
        return ''
    params = request.GET.copy()
    for key, val in kwargs.items():
        if val is None or val == '':
            params.pop(key, None)
        else:
            params[key] = str(val)
    qs = params.urlencode()
    return ('?' + qs) if qs else ''


@register.simple_tag(takes_context=True)
def filter_url_set(context, key, value):
    """Строит query string с установленным/удалённым параметром (value='' удаляет)."""
    request = context.get('request')
    if not request:
        return ''
    params = request.GET.copy()
    if value:
        params[key] = str(value)
    else:
        params.pop(key, None)
    qs = params.urlencode()
    return ('?' + qs) if qs else '?'


@register.simple_tag(takes_context=True)
def filter_url_unset(context, key):
    """Строит query string без указанного параметра."""
    request = context.get('request')
    if not request:
        return ''
    params = request.GET.copy()
    params.pop(key, None)
    qs = params.urlencode()
    return ('?' + qs) if qs else '?'


@register.simple_tag(takes_context=True)
def filter_url_pagination(context, page):
    """Query string для пагинации с сохранением всех фильтров."""
    request = context.get('request')
    if not request:
        return '?page=' + str(page)
    params = request.GET.copy()
    params['page'] = str(page)
    qs = params.urlencode()
    return '?' + qs


@register.filter
def price_format(value):
    """Форматирует число как цену: 100000 → «100 000» (пробел как разделитель тысяч)."""
    if value is None:
        return '0'
    try:
        num = int(round(float(value)))
        return f'{num:,}'.replace(',', ' ')
    except (TypeError, ValueError):
        return str(value)


@register.filter
def absolute_uri(url, request):
    """Превращает относительный URL в абсолютный (чтобы фото грузились при любом контексте)."""
    if not url:
        return ''
    url = str(url).strip()
    if url.startswith(('http://', 'https://')):
        return url
    return request.build_absolute_uri(url)


@register.filter
def js_number(value):
    """Число для JavaScript: всегда точка как разделитель дробной части (500.00, не 500,00)."""
    if value is None:
        return '0'
    s = str(value).strip().replace(',', '.')
    try:
        float(s)
        return s
    except (TypeError, ValueError):
        return '0'


@register.filter
def get_item(d, key):
    """Вернуть d.get(key, 0) для доступа к значению в словаре по ключу (остаток по товару)."""
    if not isinstance(d, dict):
        return 0
    return d.get(key, 0)


@register.filter
def get_dict_item(d, key):
    """Вернуть d.get(key) для словаря (None если ключа нет)."""
    return d.get(key) if isinstance(d, dict) else None


@register.filter
def to_json(value):
    """Сериализовать значение в JSON для использования в JavaScript."""
    return mark_safe(json.dumps(value, default=str))
