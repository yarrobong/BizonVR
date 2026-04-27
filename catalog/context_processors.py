"""Context processors для каталога."""

from datetime import date

from django.conf import settings

from .cache_utils import (
    get_catalog_category_previews,
    get_catalog_section_landing_categories,
    get_catalog_sections,
)
from .cart_services import get_cart_items, get_favorite_product_ids


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
    sections = get_catalog_sections()
    result = {'catalog_sections': sections}
    result['catalog_category_previews'] = get_catalog_category_previews()
    result['catalog_section_landing_categories'] = get_catalog_section_landing_categories()

    favorite_product_ids = get_favorite_product_ids(request)
    items = get_cart_items(request)

    result['favorites_count'] = len(favorite_product_ids)
    result['cart_count'] = sum(item.get('quantity', 0) for item in items)
    result['cart_total'] = sum(i.get('subtotal', 0) for i in items)

    # Активная секция для подсветки в мобильном меню
    result['active_section'] = _get_active_section(request)

    # Общие публичные данные сайта для шаблонов
    result['site_brand'] = getattr(settings, 'SITE_BRAND', 'BizonVR')
    result['site_description'] = getattr(settings, 'SITE_DESCRIPTION', '')
    result['site_contact_phone'] = getattr(settings, 'SITE_CONTACT_PHONE', '')
    result['site_contact_phone_href'] = getattr(settings, 'SITE_CONTACT_PHONE_HREF', '')
    result['site_contact_email'] = getattr(settings, 'SITE_CONTACT_EMAIL', '')
    result['site_contact_address'] = getattr(settings, 'SITE_CONTACT_ADDRESS', '')
    result['site_contact_telegram'] = getattr(settings, 'SITE_CONTACT_TELEGRAM', '')
    result['site_contact_telegram_handle'] = getattr(settings, 'SITE_CONTACT_TELEGRAM_HANDLE', '')
    result['site_avito_url'] = getattr(settings, 'SITE_AVITO_URL', '')
    result['site_work_hours'] = getattr(settings, 'SITE_WORK_HOURS', '')
    result['site_blog_url'] = getattr(settings, 'SITE_BLOG_URL', '')
    result['site_clubs_url'] = getattr(settings, 'SITE_CLUBS_URL', '')
    result['site_instructions_url'] = getattr(settings, 'SITE_INSTRUCTIONS_URL', '')
    result['site_youtube_url'] = getattr(settings, 'SITE_YOUTUBE_URL', '')
    result['site_tiktok_url'] = getattr(settings, 'SITE_TIKTOK_URL', '')
    result['current_year'] = date.today().year
    
    return result
