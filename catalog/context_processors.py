"""Context processors для каталога."""

from django.core.cache import cache

from .cache_utils import CACHE_KEY_CITIES, CACHE_KEY_SECTIONS
from .cart_services import get_cart_count, get_favorite_product_ids
from .models import CatalogSection, City

_CACHE_TTL = 300  # 5 минут


def catalog_menu(request):
    """Разделы каталога с категориями для выпадающего меню в шапке; счётчик корзины; города."""
    sections = cache.get(CACHE_KEY_SECTIONS)
    if sections is None:
        sections = list(
            CatalogSection.objects.prefetch_related('categories').order_by('order', 'name')
        )
        cache.set(CACHE_KEY_SECTIONS, sections, _CACHE_TTL)
    result = {'catalog_sections': sections}

    result['favorites_count'] = len(get_favorite_product_ids(request))

    from .cart_services import get_cart_count, get_cart_items
    items = get_cart_items(request)
    result['cart_count'] = get_cart_count(request)
    result['cart_total'] = sum(i.get('subtotal', 0) for i in items)

    cities = cache.get(CACHE_KEY_CITIES)
    if cities is None:
        cities = list(City.objects.order_by('order', 'name'))
        cache.set(CACHE_KEY_CITIES, cities, _CACHE_TTL)
    result['cities'] = cities
    selected_city_id = request.session.get('selected_city_id')
    result['selected_city'] = next((c for c in cities if c.pk == selected_city_id), None)
    return result
