"""Ключи и утилиты кэша для каталога."""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Min

from .models import CatalogSection, Category, Product, ProductBundle, ProductTag

_CACHE_TTL = 300

CACHE_KEY_SECTIONS = 'catalog:menu:sections'
CACHE_KEY_CITIES = 'catalog:menu:cities'
CACHE_KEY_CATEGORY_PREVIEWS = 'catalog:menu:category_previews'
CACHE_KEY_PRODUCT_TAGS = 'catalog:product_tags'
CACHE_KEY_ACTIVE_CATEGORY_IDS = 'catalog:active_category_ids'
CACHE_KEY_ACTIVE_BUNDLE_CATEGORY_IDS = 'catalog:active_bundle_category_ids'
CACHE_KEY_HOME_CATEGORY_BG_MAP = 'catalog:home:category_bg_map'
CACHE_KEY_SECTION_LANDING_CATEGORIES = 'catalog:menu:section_landing_categories'


def _build_media_url(path):
    if not path:
        return ''
    media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'
    return media_url + str(path).lstrip('/')


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
        previews = {
            category_id: _build_media_url(image)
            for category_id, image in Category.objects.exclude(image='').exclude(image__isnull=True).values_list('id', 'image')
            if image
        }
        missing_category_ids = list(
            Category.objects.exclude(id__in=previews.keys()).values_list('id', flat=True)
        )
        if missing_category_ids:
            bundle_rows = (
                ProductBundle.objects
                .filter(category_id__in=missing_category_ids)
                .exclude(image='')
                .exclude(image__isnull=True)
                .values('category_id')
                .annotate(min_id=Min('id'))
            )
            bundle_preview_data = dict(bundle_rows.values_list('category_id', 'min_id'))
            bundles = ProductBundle.objects.filter(id__in=bundle_preview_data.values()).only('id', 'image').in_bulk()
            for category_id, bundle_id in bundle_preview_data.items():
                bundle = bundles.get(bundle_id)
                if bundle and bundle.image:
                    previews[category_id] = bundle.image.url

        missing_category_ids = [
            category_id for category_id in missing_category_ids
            if category_id not in previews
        ]
        if missing_category_ids:
            preview_rows = (
                Product.objects
                .filter(category_id__in=missing_category_ids)
                .exclude(image='')
                .exclude(image__isnull=True)
                .values('category_id')
                .annotate(min_id=Min('id'))
            )
            preview_data = dict(preview_rows.values_list('category_id', 'min_id'))
            products = Product.objects.filter(id__in=preview_data.values()).only('id', 'image').in_bulk()
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
        category_bg_map = {
            slug: _build_media_url(image)
            for slug, image in Category.objects.exclude(image='').exclude(image__isnull=True).values_list('slug', 'image')
            if slug and image
        }
        missing_slugs = set(
            Category.objects.exclude(slug__in=category_bg_map.keys()).values_list('slug', flat=True)
        )
        latest_category_images = (
            Product.objects
            .filter(is_active=True, image__isnull=False, category__slug__in=missing_slugs)
            .exclude(image='')
            .order_by('category_id', '-updated_at')
            .distinct('category_id')
            .values_list('category__slug', 'image')
        )
        for slug, image in latest_category_images:
            if slug and image:
                category_bg_map[slug] = _build_media_url(image)
        cache.set(CACHE_KEY_HOME_CATEGORY_BG_MAP, category_bg_map, _CACHE_TTL)
    return category_bg_map


def get_active_bundle_category_ids():
    """Bundle-категории, в которых есть опубликованные наборы."""
    category_ids = cache.get(CACHE_KEY_ACTIVE_BUNDLE_CATEGORY_IDS)
    if category_ids is None:
        category_ids = list(
            ProductBundle.objects
            .filter(category__isnull=False)
            .values_list('category_id', flat=True)
            .distinct()
        )
        cache.set(CACHE_KEY_ACTIVE_BUNDLE_CATEGORY_IDS, category_ids, _CACHE_TTL)
    return category_ids


def get_catalog_section_landing_categories():
    """Для bundle-only разделов возвращает slug единственной bundle-категории."""
    section_map = cache.get(CACHE_KEY_SECTION_LANDING_CATEGORIES)
    if section_map is None:
        active_product_ids = set(get_active_category_ids())
        active_bundle_ids = set(get_active_bundle_category_ids())
        section_map = {}
        for section in get_catalog_sections():
            visible_categories = [
                category
                for category in section.categories.all()
                if category.pk in active_product_ids or category.pk in active_bundle_ids
            ]
            if len(visible_categories) == 1 and visible_categories[0].is_bundles_category:
                section_map[section.slug] = visible_categories[0].slug
        cache.set(CACHE_KEY_SECTION_LANDING_CATEGORIES, section_map, _CACHE_TTL)
    return section_map


def invalidate_catalog_cache():
    """Сброс кэша каталога при изменении в админке."""
    cache.delete_many([
        CACHE_KEY_SECTIONS,
        CACHE_KEY_CITIES,
        CACHE_KEY_CATEGORY_PREVIEWS,
        CACHE_KEY_PRODUCT_TAGS,
        CACHE_KEY_ACTIVE_CATEGORY_IDS,
        CACHE_KEY_ACTIVE_BUNDLE_CATEGORY_IDS,
        CACHE_KEY_HOME_CATEGORY_BG_MAP,
        CACHE_KEY_SECTION_LANDING_CATEGORIES,
    ])
