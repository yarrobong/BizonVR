from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Max, Prefetch
from django.utils import timezone

from .characteristic_normalization import normalize_characteristic_value
from .characteristic_sources import get_definition_source_names
from .models import (
    CatalogSection,
    Category,
    CharacteristicDefinition,
    CharacteristicSourceAlias,
    CharacteristicValueAlias,
    FilterConfig,
    Product,
    ProductCharacteristic,
)


DEFAULT_AUDIT_DAYS = 7


def sync_catalog_filter_audit_snapshots():
    """Compatibility shim for the old management command.

    Snapshot tables were removed in the simplified filter model, so the audit
    is now computed directly from live catalog data.
    """

    return {
        'mode': 'live',
        'uncovered_source_count': len(get_uncovered_source_names()),
        'uncovered_value_count': len(get_uncovered_raw_values()),
    }


def _definitions_with_sources():
    return list(
        CharacteristicDefinition.objects
        .prefetch_related(
            Prefetch(
                'source_aliases',
                queryset=CharacteristicSourceAlias.objects.filter(is_active=True).order_by('sort_order', 'id'),
                to_attr='active_source_aliases',
            ),
            Prefetch(
                'value_aliases',
                queryset=CharacteristicValueAlias.objects.filter(is_active=True).order_by('sort_order', 'id'),
                to_attr='active_value_aliases',
            ),
        )
        .order_by('sort_order', 'name', 'code')
    )


def _covered_source_name_map():
    mapping = {}
    for definition in _definitions_with_sources():
        for source_name in get_definition_source_names(definition):
            mapping[source_name] = definition
    return mapping


def _runtime_filter_configs():
    return (
        FilterConfig.objects
        .filter(
            is_visible=True,
            characteristic_definition__is_active=True,
            characteristic_definition__is_filterable=True,
        )
        .select_related('characteristic_definition', 'category__section', 'section')
    )


def _recent_source_usage_map(*, days: int):
    cutoff = timezone.now() - timedelta(days=days)
    rows = (
        ProductCharacteristic.objects
        .filter(product__updated_at__gte=cutoff)
        .values('name')
        .annotate(
            recent_product_count=Count('product', distinct=True),
            last_product_updated_at=Max('product__updated_at'),
        )
    )
    return {row['name']: row for row in rows}


def _recent_value_usage_map(*, days: int):
    cutoff = timezone.now() - timedelta(days=days)
    rows = (
        ProductCharacteristic.objects
        .filter(product__updated_at__gte=cutoff)
        .values('name', 'value')
        .annotate(
            recent_product_count=Count('product', distinct=True),
            last_product_updated_at=Max('product__updated_at'),
        )
    )
    return {(row['name'], row['value']): row for row in rows}


def get_uncovered_source_names():
    covered_source_names = set(_covered_source_name_map().keys())
    rows = (
        ProductCharacteristic.objects
        .exclude(name__in=covered_source_names)
        .values('name')
        .annotate(product_count=Count('product', distinct=True))
        .order_by('-product_count', 'name')
    )
    return list(rows)


def get_uncovered_raw_values():
    uncovered = []
    for definition in _definitions_with_sources():
        if not definition.is_active or not definition.is_filterable:
            continue
        source_names = get_definition_source_names(definition)
        alias_raw_values = {
            ((alias.raw_value or '').strip())
            for alias in getattr(definition, 'active_value_aliases', [])
            if (alias.raw_value or '').strip()
        }
        rows = (
            ProductCharacteristic.objects
            .filter(name__in=source_names)
            .values('name', 'value')
            .annotate(product_count=Count('product', distinct=True))
            .order_by('name', 'value')
        )
        for row in rows:
            raw_value = (row['value'] or '').strip()
            if not raw_value or raw_value in alias_raw_values:
                continue
            uncovered.append(
                {
                    'definition': definition,
                    'source_name': row['name'],
                    'raw_source_name': row['name'],
                    'raw_value': raw_value,
                    'product_count': row['product_count'],
                    'normalized_preview': normalize_characteristic_value(raw_value).suggested_display,
                }
            )

    uncovered.sort(
        key=lambda item: (
            -item['product_count'],
            item['definition'].name.lower(),
            item['raw_value'].lower(),
        )
    )
    return uncovered


def get_disabled_definitions_with_raw_data():
    rows = []
    for definition in _definitions_with_sources():
        if definition.is_active and definition.is_filterable:
            continue
        source_names = get_definition_source_names(definition)
        product_count = (
            ProductCharacteristic.objects
            .filter(name__in=source_names)
            .values('product')
            .distinct()
            .count()
        )
        if product_count:
            rows.append({'definition': definition, 'product_count': product_count})

    rows.sort(key=lambda item: (-item['product_count'], item['definition'].name.lower()))
    return rows


def get_legacy_categories():
    active_category_ids = Product.objects.filter(is_active=True).values_list('category_id', flat=True).distinct()
    managed_category_ids = (
        _runtime_filter_configs()
        .filter(category__isnull=False)
        .values_list('category_id', flat=True)
        .distinct()
    )
    return list(
        Category.objects
        .filter(pk__in=active_category_ids)
        .exclude(pk__in=managed_category_ids)
        .select_related('section')
        .order_by('section__name', 'name')
    )


def get_legacy_sections():
    active_section_ids = (
        Product.objects
        .filter(is_active=True, category__section__isnull=False)
        .values_list('category__section_id', flat=True)
        .distinct()
    )
    managed_section_ids = set(
        _runtime_filter_configs()
        .filter(section__isnull=False)
        .values_list('section_id', flat=True)
        .distinct()
    )
    managed_section_ids.update(
        _runtime_filter_configs()
        .filter(category__section__isnull=False)
        .values_list('category__section_id', flat=True)
        .distinct()
    )
    return list(
        CatalogSection.objects
        .filter(pk__in=active_section_ids)
        .exclude(pk__in=managed_section_ids)
        .order_by('order', 'name')
    )


def get_managed_categories_without_quick_filters():
    managed_category_ids = (
        _runtime_filter_configs()
        .filter(category__isnull=False)
        .values_list('category_id', flat=True)
        .distinct()
    )
    quick_category_ids = (
        _runtime_filter_configs()
        .filter(category__isnull=False, is_quick_filter=True)
        .values_list('category_id', flat=True)
        .distinct()
    )
    return list(
        Category.objects
        .filter(pk__in=managed_category_ids)
        .exclude(pk__in=quick_category_ids)
        .select_related('section')
        .order_by('section__name', 'name')
    )


def get_managed_sections_without_quick_filters():
    managed_section_ids = (
        _runtime_filter_configs()
        .filter(section__isnull=False)
        .values_list('section_id', flat=True)
        .distinct()
    )
    quick_section_ids = (
        _runtime_filter_configs()
        .filter(section__isnull=False, is_quick_filter=True)
        .values_list('section_id', flat=True)
        .distinct()
    )
    return list(
        CatalogSection.objects
        .filter(pk__in=managed_section_ids)
        .exclude(pk__in=quick_section_ids)
        .order_by('order', 'name')
    )


def _definition_visible_in_scope(definition, product_qs, hide_single_value: bool):
    source_names = get_definition_source_names(definition)
    rows = (
        ProductCharacteristic.objects
        .filter(product__in=product_qs, name__in=source_names)
        .values_list('product_id', 'value')
        .distinct()
    )
    buckets = defaultdict(set)
    alias_normalized_by_raw = {
        ((alias.raw_value or '').strip()): ((alias.normalized_value or alias.raw_value or '').strip())
        for alias in getattr(definition, 'active_value_aliases', [])
        if (alias.raw_value or '').strip()
    }
    for product_id, raw_value in rows:
        cleaned_value = (raw_value or '').strip()
        if not cleaned_value:
            continue
        buckets[alias_normalized_by_raw.get(cleaned_value, cleaned_value)].add(product_id)
    if not buckets:
        return False
    if len(buckets) == 1 and hide_single_value:
        return False
    return True


def get_weak_managed_categories():
    rows = []
    category_ids = (
        _runtime_filter_configs()
        .filter(category__isnull=False)
        .values_list('category_id', flat=True)
        .distinct()
    )
    for category in Category.objects.filter(pk__in=category_ids).select_related('section'):
        configs = list(
            _runtime_filter_configs()
            .filter(category=category)
            .select_related('characteristic_definition')
        )
        product_qs = Product.objects.filter(is_active=True, category=category)
        if any(
            _definition_visible_in_scope(
                config.characteristic_definition,
                product_qs,
                config.hide_single_value,
            )
            for config in configs
        ):
            continue
        rows.append(category)
    return rows


def get_weak_managed_sections():
    rows = []
    section_ids = (
        _runtime_filter_configs()
        .filter(section__isnull=False)
        .values_list('section_id', flat=True)
        .distinct()
    )
    for section in CatalogSection.objects.filter(pk__in=section_ids):
        configs = list(
            _runtime_filter_configs()
            .filter(section=section)
            .select_related('characteristic_definition')
        )
        product_qs = Product.objects.filter(is_active=True, category__section=section)
        if any(
            _definition_visible_in_scope(
                config.characteristic_definition,
                product_qs,
                config.hide_single_value,
            )
            for config in configs
        ):
            continue
        rows.append(section)
    return rows


def get_new_uncovered_sources(days: int = DEFAULT_AUDIT_DAYS):
    recent_usage = _recent_source_usage_map(days=days)
    rows = []
    for row in get_uncovered_source_names():
        recent_row = recent_usage.get(row['name'])
        if recent_row is None:
            continue
        rows.append(
            {
                'raw_source_name': row['name'],
                'product_count': row['product_count'],
                'recent_product_count': recent_row['recent_product_count'],
                'last_product_updated_at': recent_row['last_product_updated_at'],
            }
        )
    rows.sort(
        key=lambda item: (
            item['last_product_updated_at'] is None,
            -(item['last_product_updated_at'].timestamp() if item['last_product_updated_at'] else 0),
            item['raw_source_name'].lower(),
        )
    )
    return rows


def get_new_uncovered_values(days: int = DEFAULT_AUDIT_DAYS):
    uncovered_values = get_uncovered_raw_values()
    uncovered_pairs = {
        (item['raw_source_name'], item['raw_value'])
        for item in uncovered_values
    }
    recent_usage = _recent_value_usage_map(days=days)
    rows = []
    for item in uncovered_values:
        recent_row = recent_usage.get((item['raw_source_name'], item['raw_value']))
        if recent_row is None:
            continue
        rows.append(
            {
                **item,
                'recent_product_count': recent_row['recent_product_count'],
                'last_product_updated_at': recent_row['last_product_updated_at'],
            }
        )
    rows.sort(
        key=lambda item: (
            item['last_product_updated_at'] is None,
            -(item['last_product_updated_at'].timestamp() if item['last_product_updated_at'] else 0),
            item['definition'].name.lower(),
            item['raw_value'].lower(),
        )
    )
    return rows, uncovered_pairs


def build_filter_audit_dashboard_context(days: int = DEFAULT_AUDIT_DAYS):
    new_uncovered_values, uncovered_pairs = get_new_uncovered_values(days=days)
    return {
        'days': days,
        'is_live_audit': True,
        'supports_historical_snapshots': False,
        'uncovered_source_names': get_uncovered_source_names(),
        'uncovered_raw_values': get_uncovered_raw_values(),
        'legacy_categories': get_legacy_categories(),
        'legacy_sections': get_legacy_sections(),
        'managed_categories_without_quick_filters': get_managed_categories_without_quick_filters(),
        'managed_sections_without_quick_filters': get_managed_sections_without_quick_filters(),
        'weak_managed_categories': get_weak_managed_categories(),
        'weak_managed_sections': get_weak_managed_sections(),
        'disabled_definitions_with_raw_data': get_disabled_definitions_with_raw_data(),
        'new_uncovered_sources': get_new_uncovered_sources(days=days),
        'new_uncovered_values': [
            item
            for item in new_uncovered_values
            if (item['raw_source_name'], item['raw_value']) in uncovered_pairs
        ],
    }
