"""Ключи и утилиты кэша для каталога."""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Min

from .models import CatalogSection, Product, ProductTag

_CACHE_TTL = 300

CACHE_KEY_SECTIONS = 'catalog:menu:sections'
CACHE_KEY_CITIES = 'catalog:menu:cities'
CACHE_KEY_CATEGORY_PREVIEWS = 'catalog:menu:category_previews'
CACHE_KEY_PRODUCT_TAGS = 'catalog:product_tags'
CACHE_KEY_ACTIVE_CATEGORY_IDS = 'catalog:active_category_ids'
CACHE_KEY_HOME_CATEGORY_BG_MAP = 'catalog:home:category_bg_map'


def get_catalog_sections():
    """Разделы каталога с предзагруженными категориями."""
    sections = cache.get(CACHE_KEY_SECTIONS)
    if sections is None:
        sections = list(
            CatalogSection.objects.prefetch_related('categories').order_by('order', 'name')
        )
        cache.set(CACHE_KEY_SECTIONS, sections, _CACHE_TTL)
    return sections


def get_catalog_category_previews():
    """Превью категорий для меню и плитки каталога."""
    previews = cache.get(CACHE_KEY_CATEGORY_PREVIEWS)
    if previews is None:
        preview_rows = (
            Product.objects
            .exclude(image='')
            .exclude(image__isnull=True)
            .values('category_id')
            .annotate(min_id=Min('id'))
        )
        preview_data = dict(preview_rows.values_list('category_id', 'min_id'))
        products = Product.objects.filter(id__in=preview_data.values()).only('id', 'image').in_bulk()
        previews = {}
        for category_id, product_id in preview_data.items():
            product = products.get(product_id)
            if product and product.image:
                previews[category_id] = product.image.url
        cache.set(CACHE_KEY_CATEGORY_PREVIEWS, previews, _CACHE_TTL)
    return previews


def get_catalog_product_tags():
    """Теги товаров для публичных страниц."""
    product_tags = cache.get(CACHE_KEY_PRODUCT_TAGS)
    if product_tags is None:
        product_tags = list(ProductTag.objects.order_by('order', 'name'))
        cache.set(CACHE_KEY_PRODUCT_TAGS, product_tags, _CACHE_TTL)
    return product_tags


def get_active_category_ids():
    """Категории, в которых есть активные товары."""
    category_ids = cache.get(CACHE_KEY_ACTIVE_CATEGORY_IDS)
    if category_ids is None:
        category_ids = list(
            Product.objects
            .filter(is_active=True)
            .order_by()
            .values_list('category_id', flat=True)
            .distinct()
        )
        cache.set(CACHE_KEY_ACTIVE_CATEGORY_IDS, category_ids, _CACHE_TTL)
    return category_ids


def get_home_category_backgrounds():
    """Фоновые изображения категорий на главной."""
    category_bg_map = cache.get(CACHE_KEY_HOME_CATEGORY_BG_MAP)
    if category_bg_map is None:
        media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'
        category_bg_map = {}
        latest_category_images = (
            Product.objects
            .filter(is_active=True, image__isnull=False)
            .exclude(image='')
            .order_by('category_id', '-updated_at')
            .distinct('category_id')
            .values_list('category__slug', 'image')
        )
        for slug, image in latest_category_images:
            if slug and image:
                category_bg_map[slug] = media_url + str(image).lstrip('/')
        cache.set(CACHE_KEY_HOME_CATEGORY_BG_MAP, category_bg_map, _CACHE_TTL)
    return category_bg_map


def invalidate_catalog_cache():
    """Сброс кэша каталога при изменении в админке."""
    cache.delete_many([
        CACHE_KEY_SECTIONS,
        CACHE_KEY_CITIES,
        CACHE_KEY_CATEGORY_PREVIEWS,
        CACHE_KEY_PRODUCT_TAGS,
        CACHE_KEY_ACTIVE_CATEGORY_IDS,
        CACHE_KEY_HOME_CATEGORY_BG_MAP,
    ])
