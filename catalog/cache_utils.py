"""Ключи и утилиты кэша для каталога."""

from django.core.cache import cache

CACHE_KEY_SECTIONS = 'catalog:menu:sections'
CACHE_KEY_CITIES = 'catalog:menu:cities'
CACHE_KEY_PRODUCT_TAGS = 'catalog:product_tags'


def invalidate_catalog_cache():
    """Сброс кэша каталога при изменении в админке."""
    cache.delete(CACHE_KEY_SECTIONS)
    cache.delete(CACHE_KEY_CITIES)
    cache.delete(CACHE_KEY_PRODUCT_TAGS)
