"""Шаблонные теги для каталога."""
from django import template

register = template.Library()


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
def get_item(d, key):
    """Вернуть d.get(key, 0) для доступа к значению в словаре по ключу (остаток по товару)."""
    if not isinstance(d, dict):
        return 0
    return d.get(key, 0)
