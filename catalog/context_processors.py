"""Context processors для каталога."""

from django.core.cache import cache
from django.db.models import Min

from .cache_utils import CACHE_KEY_SECTIONS
from .cart_services import get_cart_count, get_favorite_product_ids
from .models import CatalogSection, City, Product

_CACHE_TTL = 300  # 5 минут


def _get_active_section(request):
    """Определяет активную секцию меню на основе текущего URL."""
    path = request.path
    
    # Каталог/Поиск
    if path.startswith('/catalog/') and not path.startswith('/catalog/favorites') and not path.startswith('/catalog/cart'):
        return 'catalog'
    
    # Избранное
    if path.startswith('/catalog/favorites'):
        return 'favorites'
    
    # Корзина
    if path.startswith('/catalog/cart'):
        return 'cart'
    
    # Профиль (все страницы accounts)
    if path.startswith('/accounts/'):
        return 'profile'
    
    # Главная (по умолчанию для /, /arenda/, /contacts/, карточек товаров)
    return 'home'


def catalog_menu(request):
    """Разделы каталога с категориями для выпадающего меню в шапке; счётчик корзины; города."""
    sections = cache.get(CACHE_KEY_SECTIONS)
    if sections is None:
        sections = list(
            CatalogSection.objects.prefetch_related('categories').order_by('order', 'name')
        )
        cache.set(CACHE_KEY_SECTIONS, sections, _CACHE_TTL)
    result = {'catalog_sections': sections}

    # Превью-фото для плиток категорий: главное фото первого товара с изображением в категории
    category_ids = [c.pk for s in sections for c in s.categories.all()]
    preview_data = {}
    if category_ids:
        qs = (
            Product.objects.filter(category_id__in=category_ids)
            .exclude(image='')
            .exclude(image__isnull=True)
            .values('category_id')
            .annotate(min_id=Min('id'))
        )
        preview_data = dict(qs.values_list('category_id', 'min_id'))
    products = {}
    if preview_data:
        products = Product.objects.filter(id__in=preview_data.values()).in_bulk()
    result['catalog_category_previews'] = {}
    for cid, pid in preview_data.items():
        p = products.get(pid)
        if p and p.image:
            result['catalog_category_previews'][cid] = request.build_absolute_uri(p.image.url)

    result['favorites_count'] = len(get_favorite_product_ids(request))

    from .cart_services import get_cart_count, get_cart_items
    items = get_cart_items(request)
    result['cart_count'] = get_cart_count(request)
    result['cart_total'] = sum(i.get('subtotal', 0) for i in items)

    # Города всегда из БД (таблица catalog_city — та же, что в админке «Каталог → Города»), без кэша
    result['cities'] = list(City.objects.order_by('order', 'name'))
    selected_city_id = request.session.get('selected_city_id')
    result['selected_city'] = next((c for c in result['cities'] if c.pk == selected_city_id), None)
    
    # Активная секция для подсветки в мобильном меню
    result['active_section'] = _get_active_section(request)
    
    return result
