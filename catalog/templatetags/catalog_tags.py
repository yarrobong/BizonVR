"""Шаблонные теги для каталога."""
import json

from django import template
from django.utils.safestring import mark_safe

from config.formatting import format_amount, format_currency_amount, format_decimal_amount

from ..filtering import sanitize_catalog_query_params
from ..pricing import get_purchase_mode_label
from ..stock import public_stock_status

register = template.Library()

_TAG_STYLE_BY_KEYWORD = (
    ('sale', 'background: rgba(239, 68, 68, 0.22); color: #fecaca; border-color: rgba(239, 68, 68, 0.5);'),
    ('распрод', 'background: rgba(239, 68, 68, 0.22); color: #fecaca; border-color: rgba(239, 68, 68, 0.5);'),
    ('акци', 'background: rgba(239, 68, 68, 0.22); color: #fecaca; border-color: rgba(239, 68, 68, 0.5);'),
    ('скид', 'background: rgba(239, 68, 68, 0.22); color: #fecaca; border-color: rgba(239, 68, 68, 0.5);'),
    ('hit', 'background: rgba(251, 191, 36, 0.22); color: #fef3c7; border-color: rgba(251, 191, 36, 0.5);'),
    ('хит', 'background: rgba(251, 191, 36, 0.22); color: #fef3c7; border-color: rgba(251, 191, 36, 0.5);'),
    ('bestseller', 'background: rgba(249, 115, 22, 0.22); color: #ffedd5; border-color: rgba(249, 115, 22, 0.5);'),
    ('new', 'background: rgba(16, 185, 129, 0.22); color: #d1fae5; border-color: rgba(16, 185, 129, 0.5);'),
    ('новин', 'background: rgba(16, 185, 129, 0.22); color: #d1fae5; border-color: rgba(16, 185, 129, 0.5);'),
    ('expert', 'background: rgba(139, 92, 246, 0.22); color: #ede9fe; border-color: rgba(139, 92, 246, 0.5);'),
)


def _iter_remove_keys(remove_keys):
    if not remove_keys:
        return []
    if isinstance(remove_keys, str):
        return [part.strip() for part in remove_keys.split(',') if part.strip()]
    return [str(part).strip() for part in remove_keys if str(part).strip()]


def _apply_query_updates(request, *, remove_keys=None, updates=None, empty_result=''):
    if not request:
        return empty_result
    params = sanitize_catalog_query_params(request)
    for key in _iter_remove_keys(remove_keys):
        params.pop(key, None)
    for key, value in (updates or {}).items():
        if value is None or value == '':
            params.pop(key, None)
        else:
            params[key] = str(value)
    qs = params.urlencode()
    return ('?' + qs) if qs else '?'


@register.simple_tag(takes_context=True)
def filter_url(context, **kwargs):
    """Строит query string с обновлёнными GET-параметрами. Удалить: param=None."""
    request = context.get('request')
    return _apply_query_updates(request, updates=kwargs, empty_result='')


@register.simple_tag(takes_context=True)
def filter_url_set(context, key, value):
    """Строит query string с установленным/удалённым параметром (value='' удаляет)."""
    request = context.get('request')
    return _apply_query_updates(
        request,
        updates={key: value},
        empty_result='',
    )


@register.simple_tag(takes_context=True)
def filter_url_unset(context, key):
    """Строит query string без указанного параметра."""
    request = context.get('request')
    return _apply_query_updates(request, remove_keys=[key], empty_result='')


@register.simple_tag(takes_context=True)
def filter_url_char_set(context, key, value, remove_keys=''):
    """Строит query string для char_* с возможностью очистить связанные legacy/canonical параметры."""
    request = context.get('request')
    return _apply_query_updates(
        request,
        remove_keys=remove_keys,
        updates={key: value},
        empty_result='',
    )


@register.simple_tag(takes_context=True)
def filter_url_char_unset(context, key, remove_keys=''):
    """Строит query string без указанного char_* параметра и его alias-ключей."""
    request = context.get('request')
    keys_to_remove = _iter_remove_keys(remove_keys)
    if key not in keys_to_remove:
        keys_to_remove.append(key)
    return _apply_query_updates(request, remove_keys=keys_to_remove, empty_result='')


@register.simple_tag(takes_context=True)
def filter_url_pagination(context, page):
    """Query string для пагинации с сохранением всех фильтров."""
    request = context.get('request')
    if not request:
        return '?page=' + str(page)
    params = sanitize_catalog_query_params(request)
    params['page'] = str(page)
    qs = params.urlencode()
    return '?' + qs


@register.simple_tag(takes_context=True)
def filter_url_section(context, section):
    """Query string для перехода в раздел с учётом bundle-only landing категории."""
    request = context.get('request')
    section_slug = getattr(section, 'slug', str(section))
    landing_categories = context.get('catalog_section_landing_categories') or {}
    category_slug = landing_categories.get(section_slug, '')
    if not request:
        if category_slug:
            return f'?section={section_slug}&category={category_slug}'
        return f'?section={section_slug}'
    return _apply_query_updates(
        request,
        updates={
            'section': section_slug,
            'category': category_slug,
        },
        empty_result='',
    )


@register.filter
def price_format(value):
    """Форматирует число как цену: 100000 -> 100 000, 100000.5 -> 100 000,50."""
    return format_amount(value)


@register.filter
def rub(value):
    """Форматирует сумму в рублях: 100000 -> 100 000 ₽."""
    return format_currency_amount(value, 'RUB')


@register.filter
def currency_amount(value, currency='RUB'):
    """Форматирует сумму с кодом валюты, для RUB использует символ ₽."""
    return format_currency_amount(value, currency)


@register.filter
def decimal_format(value):
    """Форматирует число с обязательными двумя знаками после запятой."""
    return format_decimal_amount(value)


@register.filter
def absolute_uri(url, request):
    """Превращает относительный URL в абсолютный (чтобы фото грузились при любом контексте)."""
    if not url:
        return ''
    url = str(url).strip()
    if url.startswith(('http://', 'https://')):
        return url
    # Относительный URL без ведущего / браузер разрешает от текущего path — ломает /catalog/ и т.д.
    if not url.startswith('/'):
        url = '/' + url
    if not request:
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
def ru_plural(value, forms):
    """Русское склонение: 'товар,товара,товаров'."""
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return ''
    choices = [part.strip() for part in str(forms).split(',')]
    if len(choices) != 3:
        return ''
    if 11 <= number % 100 <= 14:
        return choices[2]
    tail = number % 10
    if tail == 1:
        return choices[0]
    if 2 <= tail <= 4:
        return choices[1]
    return choices[2]


@register.filter
def to_json(value):
    """Сериализовать значение в JSON для использования в JavaScript."""
    return mark_safe(json.dumps(value, default=str))


@register.filter
def stock_status(quantity):
    """Публичный статус наличия по количеству."""
    return public_stock_status(quantity)


@register.filter
def purchase_mode_label(value):
    """Человекочитаемая подпись режима покупки."""
    return get_purchase_mode_label(value)


@register.filter
def tag_badge_style(tag):
    """Цвет бейджа тега по slug/name."""
    default_style = 'background: rgba(14, 165, 233, 0.22); color: #dbeafe; border-color: rgba(14, 165, 233, 0.5);'
    if not tag:
        return default_style

    slug = (getattr(tag, 'slug', '') or '').lower()
    name = (getattr(tag, 'name', '') or '').lower()
    lookup = f'{slug} {name}'

    for keyword, style in _TAG_STYLE_BY_KEYWORD:
        if keyword in lookup:
            return style
    return default_style
