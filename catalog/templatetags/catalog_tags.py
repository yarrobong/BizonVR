"""Шаблонные теги для каталога."""
import json
import re
from functools import lru_cache

from django import template
from django.contrib.staticfiles import finders
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from PIL import Image, UnidentifiedImageError

from config.formatting import format_amount, format_currency_amount, format_decimal_amount

from ..filtering import sanitize_catalog_query_params
from ..image_utils import build_responsive_image_data
from ..pricing import get_purchase_mode_label
from ..stock import public_product_stock_status, public_stock_status

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

_INLINE_LUCIDE_ICONS = {
    'home': (
        ('path', {'d': 'M3 10.5 12 3l9 7.5'}),
        ('path', {'d': 'M5 9.8V21h14V9.8'}),
    ),
    'search': (
        ('circle', {'cx': '11', 'cy': '11', 'r': '8'}),
        ('path', {'d': 'm21 21-4.3-4.3'}),
    ),
    'heart': (
        ('path', {'d': 'm12 21-1.45-1.32C5.4 15.36 2 12.28 2 8.5A4.5 4.5 0 0 1 6.5 4c1.74 0 3.41.81 4.5 2.09A6 6 0 0 1 17.5 4 4.5 4.5 0 0 1 22 8.5c0 3.78-3.4 6.86-8.55 11.18Z'}),
    ),
    'shopping-cart': (
        ('circle', {'cx': '8', 'cy': '21', 'r': '1'}),
        ('circle', {'cx': '19', 'cy': '21', 'r': '1'}),
        ('path', {'d': 'M2.05 2H4l2.68 12.39A2 2 0 0 0 8.63 16H18.4a2 2 0 0 0 1.95-1.57L22 6H6'}),
    ),
    'user': (
        ('path', {'d': 'M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2'}),
        ('circle', {'cx': '12', 'cy': '7', 'r': '4'}),
    ),
    'log-in': (
        ('path', {'d': 'M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4'}),
        ('polyline', {'points': '10 17 15 12 10 7'}),
        ('line', {'x1': '15', 'y1': '12', 'x2': '3', 'y2': '12'}),
    ),
    'shopping-bag': (
        ('path', {'d': 'M6 2h12l1 5H5z'}),
        ('path', {'d': 'M3 7h18l-1 13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2L3 7z'}),
        ('path', {'d': 'M9 10a3 3 0 0 0 6 0'}),
    ),
    'send': (
        ('path', {'d': 'm22 2-7 20-4-9-9-4Z'}),
        ('path', {'d': 'M22 2 11 13'}),
    ),
    'phone': (
        ('path', {'d': 'M22 16.92v3a2 2 0 0 1-2.18 2 19.86 19.86 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.86 19.86 0 0 1 2.11 4.18 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.78.62 2.61a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.47-1.18a2 2 0 0 1 2.11-.45c.83.29 1.71.5 2.61.62A2 2 0 0 1 22 16.92z'}),
    ),
    'layout-grid': (
        ('rect', {'x': '3', 'y': '3', 'width': '7', 'height': '7', 'rx': '1'}),
        ('rect', {'x': '14', 'y': '3', 'width': '7', 'height': '7', 'rx': '1'}),
        ('rect', {'x': '14', 'y': '14', 'width': '7', 'height': '7', 'rx': '1'}),
        ('rect', {'x': '3', 'y': '14', 'width': '7', 'height': '7', 'rx': '1'}),
    ),
    'x': (
        ('path', {'d': 'M18 6 6 18'}),
        ('path', {'d': 'M6 6 18 18'}),
    ),
    'image-off': (
        ('path', {'d': 'm2 2 20 20'}),
        ('path', {'d': 'M10.41 10.41a2 2 0 0 0 2.83 2.83'}),
        ('path', {'d': 'M13.5 13.5 18 18H6a2 2 0 0 1-2-2V6l4.5 4.5'}),
        ('path', {'d': 'M18 12V6a2 2 0 0 0-2-2H8'}),
        ('path', {'d': 'm9 9 1.5-1.5a2 2 0 0 1 2.83 0L18 12'}),
    ),
    'package': (
        ('path', {'d': 'm16.5 9.4-9-5.19'}),
        ('path', {'d': 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z'}),
        ('path', {'d': 'M3.3 7 12 12l8.7-5'}),
        ('path', {'d': 'M12 22V12'}),
    ),
    'chevron-left': (
        ('path', {'d': 'm15 18-6-6 6-6'}),
    ),
    'chevron-right': (
        ('path', {'d': 'm9 18 6-6-6-6'}),
    ),
    'glasses': (
        ('circle', {'cx': '6', 'cy': '15', 'r': '4'}),
        ('circle', {'cx': '18', 'cy': '15', 'r': '4'}),
        ('path', {'d': 'M14 15a2 2 0 0 0-2-2 2 2 0 0 0-2 2'}),
        ('path', {'d': 'M2.5 13 5 7c.7-1.3 1.4-2 3-2'}),
        ('path', {'d': 'M21.5 13 19 7c-.7-1.3-1.5-2-3-2'}),
    ),
    'briefcase': (
        ('path', {'d': 'M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16'}),
        ('rect', {'width': '20', 'height': '14', 'x': '2', 'y': '6', 'rx': '2'}),
    ),
    'arrow-right': (
        ('path', {'d': 'M5 12h14'}),
        ('path', {'d': 'm12 5 7 7-7 7'}),
    ),
    'youtube': (
        ('path', {'d': 'M2.5 17a24.12 24.12 0 0 1 0-10 2 2 0 0 1 1.4-1.4 49.56 49.56 0 0 1 16.2 0A2 2 0 0 1 21.5 7a24.12 24.12 0 0 1 0 10 2 2 0 0 1-1.4 1.4 49.55 49.55 0 0 1-16.2 0A2 2 0 0 1 2.5 17'}),
        ('path', {'d': 'm10 15 5-3-5-3z'}),
    ),
    'arrow-up-right': (
        ('path', {'d': 'M7 7h10v10'}),
        ('path', {'d': 'M7 17 17 7'}),
    ),
    'music': (
        ('path', {'d': 'M9 18V5l12-2v13'}),
        ('circle', {'cx': '6', 'cy': '18', 'r': '3'}),
        ('circle', {'cx': '18', 'cy': '16', 'r': '3'}),
    ),
    'store': (
        ('path', {'d': 'm2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7'}),
        ('path', {'d': 'M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8'}),
        ('path', {'d': 'M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4'}),
        ('path', {'d': 'M2 7h20'}),
        ('path', {'d': 'M22 7v3a2 2 0 0 1-2 2a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 16 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 12 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 8 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 4 12a2 2 0 0 1-2-2V7'}),
    ),
    'arrow-up-down': (
        ('path', {'d': 'm21 16-4 4-4-4'}),
        ('path', {'d': 'M17 20V4'}),
        ('path', {'d': 'm3 8 4-4 4 4'}),
        ('path', {'d': 'M7 4v16'}),
    ),
    'sliders-horizontal': (
        ('line', {'x1': '21', 'x2': '14', 'y1': '4', 'y2': '4'}),
        ('line', {'x1': '10', 'x2': '3', 'y1': '4', 'y2': '4'}),
        ('line', {'x1': '21', 'x2': '12', 'y1': '12', 'y2': '12'}),
        ('line', {'x1': '8', 'x2': '3', 'y1': '12', 'y2': '12'}),
        ('line', {'x1': '21', 'x2': '16', 'y1': '20', 'y2': '20'}),
        ('line', {'x1': '12', 'x2': '3', 'y1': '20', 'y2': '20'}),
        ('line', {'x1': '14', 'x2': '14', 'y1': '2', 'y2': '6'}),
        ('line', {'x1': '8', 'x2': '8', 'y1': '10', 'y2': '14'}),
        ('line', {'x1': '16', 'x2': '16', 'y1': '18', 'y2': '22'}),
    ),
    'share-2': (
        ('circle', {'cx': '18', 'cy': '5', 'r': '3'}),
        ('circle', {'cx': '6', 'cy': '12', 'r': '3'}),
        ('circle', {'cx': '18', 'cy': '19', 'r': '3'}),
        ('line', {'x1': '8.59', 'x2': '15.42', 'y1': '13.51', 'y2': '17.49'}),
        ('line', {'x1': '15.41', 'x2': '8.59', 'y1': '6.51', 'y2': '10.49'}),
    ),
    'arrow-left': (
        ('path', {'d': 'm12 19-7-7 7-7'}),
        ('path', {'d': 'M19 12H5'}),
    ),
}

_INLINE_LUCIDE_BOOLEAN_ATTRS = {'x-cloak'}


def _iter_remove_keys(remove_keys):
    if not remove_keys:
        return []
    if isinstance(remove_keys, str):
        return [part.strip() for part in remove_keys.split(',') if part.strip()]
    return [str(part).strip() for part in remove_keys if str(part).strip()]


def _normalize_inline_icon_attr_name(name):
    return str(name).strip().rstrip('_').replace('_', '-')


def _render_inline_icon_attrs(attrs):
    rendered = []
    for raw_name, value in attrs.items():
        name = _normalize_inline_icon_attr_name(raw_name)
        if not name or value in (None, False, ''):
            continue
        if name in _INLINE_LUCIDE_BOOLEAN_ATTRS and value:
            rendered.append(format_html(' {}', name))
            continue
        rendered.append(format_html(' {}="{}"', name, value))
    return mark_safe(''.join(rendered))


def _render_inline_icon_nodes(nodes):
    return format_html_join(
        '',
        '<{0}{1}></{0}>',
        (
            (tag_name, _render_inline_icon_attrs(tag_attrs))
            for tag_name, tag_attrs in nodes
        ),
    )


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


@register.simple_tag
def lucide_icon(name, classes='', **attrs):
    icon_name = (str(name).strip().lower()) if name else ''
    nodes = _INLINE_LUCIDE_ICONS.get(icon_name)
    if not nodes:
        return ''

    svg_attrs = {
        'xmlns': 'http://www.w3.org/2000/svg',
        'viewBox': '0 0 24 24',
        'fill': 'none',
        'stroke': 'currentColor',
        'stroke-width': '2',
        'stroke-linecap': 'round',
        'stroke-linejoin': 'round',
        'width': '24',
        'height': '24',
        'aria-hidden': 'true',
        'focusable': 'false',
        'class': f'lucide-icon lucide-icon--{icon_name}'.strip(),
    }
    if classes:
        svg_attrs['class'] = f"{svg_attrs['class']} {classes}".strip()

    for raw_name, value in attrs.items():
        normalized_name = _normalize_inline_icon_attr_name(raw_name)
        if not normalized_name:
            continue
        svg_attrs[normalized_name] = value

    return format_html(
        '<svg{0}>{1}</svg>',
        _render_inline_icon_attrs(svg_attrs),
        _render_inline_icon_nodes(nodes),
    )


@register.simple_tag(takes_context=True)
def filter_url_set(context, key, value):
    """Строит query string с установленным/удалённым параметром (value='' удаляет)."""
    request = context.get('request')
    return _apply_query_updates(
        request,
        updates={key: value},
        empty_result='',
    )


PRODUCT_CARD_GALLERY_LIMIT = 5


def build_product_card_gallery_images(product, card_variant=None):
    images = []
    seen_keys = set()

    def build_image_key(image_field):
        if not image_field:
            return ''
        name = getattr(image_field, 'name', '') or ''
        return re.sub(r'_[A-Za-z0-9]{7}(?=\.[^.]+$)', '', name)

    def add_image(image_field):
        if not image_field:
            return
        key = build_image_key(image_field)
        if not key:
            return
        if key in seen_keys:
            return
        seen_keys.add(key)
        images.append(image_field)

    if card_variant is not None:
        add_image(getattr(card_variant, 'image', None))
    add_image(getattr(product, 'image', None))
    for extra_image in getattr(product, 'images', []).all() if hasattr(getattr(product, 'images', None), 'all') else []:
        add_image(getattr(extra_image, 'image', None))
    return images[:PRODUCT_CARD_GALLERY_LIMIT]


@register.simple_tag
def product_card_gallery_images(product, card_variant=None):
    return build_product_card_gallery_images(product, card_variant=card_variant)


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


@register.simple_tag
def product_stock_status(product, quantity):
    """Публичный статус наличия с учётом типа товара."""
    return public_product_stock_status(product, quantity)


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


def _resolve_image_dimensions(value):
    if isinstance(value, dict):
        width = value.get('width')
        height = value.get('height')
    else:
        try:
            width = getattr(value, 'width', None)
            height = getattr(value, 'height', None)
        except (ValueError, OSError, FileNotFoundError):
            return None, None
    try:
        width = int(width or 0)
        height = int(height or 0)
    except (TypeError, ValueError):
        return None, None
    if width <= 0 or height <= 0:
        return None, None
    return width, height


@register.filter
def image_dimension_attrs(value):
    """Вернуть готовые width/height атрибуты для img или пустую строку."""
    width, height = _resolve_image_dimensions(value)
    if width is None or height is None:
        return ''
    return mark_safe(f'width="{width}" height="{height}"')


@lru_cache(maxsize=256)
def _resolve_static_image_dimensions(path):
    resolved_path = finders.find(str(path or '').strip())
    if not resolved_path or not isinstance(resolved_path, str):
        return None, None
    try:
        with Image.open(resolved_path) as image:
            width, height = image.size
    except (FileNotFoundError, OSError, ValueError, UnidentifiedImageError):
        return None, None
    try:
        width = int(width or 0)
        height = int(height or 0)
    except (TypeError, ValueError):
        return None, None
    if width <= 0 or height <= 0:
        return None, None
    return width, height


@register.simple_tag
def static_image_dimension_attrs(path):
    """Вернуть готовые width/height атрибуты для static-изображения или пустую строку."""
    width, height = _resolve_static_image_dimensions(path)
    if width is None or height is None:
        return ''
    return mark_safe(f'width="{width}" height="{height}"')


@register.filter
def image_variant_url(value, width):
    """Вернуть URL уменьшенной версии изображения для указанной ширины."""
    try:
        target_width = int(width or 0)
    except (TypeError, ValueError):
        return ''
    if target_width <= 0:
        return ''
    data = build_responsive_image_data(value, widths=(target_width,), default_width=target_width)
    return data.get('src', '')


@register.filter
def image_srcset(value, widths):
    """Вернуть srcset для изображения по списку ширин через запятую."""
    raw_values = str(widths or '').split(',')
    parsed_widths = []
    for raw_value in raw_values:
        raw_value = raw_value.strip()
        if not raw_value:
            continue
        try:
            parsed_widths.append(int(raw_value))
        except (TypeError, ValueError):
            continue
    if not parsed_widths:
        return ''
    data = build_responsive_image_data(value, widths=parsed_widths, default_width=max(parsed_widths))
    return mark_safe(data.get('srcset', ''))
