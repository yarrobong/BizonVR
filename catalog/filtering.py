from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
import re
from typing import Iterable

from django.db.models import Count, Max, Min, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.functional import cached_property

from .filter_presets import get_typed_value_sort_key
from .characteristic_sources import (
    get_definition_remove_keys,
    get_definition_source_names,
    map_definitions_by_source_name,
)
from .models import (
    CatalogSection,
    Category,
    CharacteristicDefinition,
    CharacteristicSourceAlias,
    CharacteristicValueAlias,
    FilterConfig,
    Product,
    ProductCharacteristic,
    ProductTag,
)
from .pricing import build_catalog_effective_price_expression

_SLUG_PREFIX_RE = re.compile(r'^[\w-]+', re.UNICODE)


@dataclass(frozen=True)
class ActiveCharacteristicFilter:
    position: int
    canonical_key: str
    label: str
    selected_value: str
    request_identifier: str
    remove_keys: tuple[str, ...]
    definition: CharacteristicDefinition | None = None


def _build_slug_candidates(raw_value: str) -> list[str]:
    cleaned_value = (raw_value or '').strip()
    if not cleaned_value:
        return []

    candidates = []
    seen = set()

    def _add(value: str):
        normalized = (value or '').strip().strip('/')
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    _add(cleaned_value)

    prefix_match = _SLUG_PREFIX_RE.match(cleaned_value)
    if prefix_match is not None:
        _add(prefix_match.group(0))

    for separator in ('?', '#', '&', '/'):
        if separator in cleaned_value:
            _add(cleaned_value.split(separator, 1)[0])

    return candidates


def _resolve_slug_object(queryset, raw_value: str):
    for candidate in _build_slug_candidates(raw_value):
        resolved = queryset.filter(slug=candidate).first()
        if resolved is not None:
            return resolved
    return None


def get_normalized_catalog_query_slugs(request) -> dict[str, str]:
    if request is None:
        return {'section': '', 'category': ''}

    cached_result = getattr(request, '_catalog_normalized_query_slugs', None)
    if cached_result is not None:
        return cached_result

    category = _resolve_slug_object(
        Category.objects.select_related('section'),
        request.GET.get('category', ''),
    )
    section = _resolve_slug_object(
        CatalogSection.objects.all(),
        request.GET.get('section', ''),
    )

    request._catalog_resolved_query_category = category
    request._catalog_resolved_query_section = section
    request._catalog_normalized_query_slugs = {
        'section': section.slug if section is not None else '',
        'category': category.slug if category is not None else '',
    }
    return request._catalog_normalized_query_slugs


def sanitize_catalog_query_params(request, params=None):
    if request is None:
        return params

    cleaned_params = params.copy() if params is not None else request.GET.copy()
    normalized_slugs = get_normalized_catalog_query_slugs(request)

    for key in ('section', 'category'):
        raw_value = (request.GET.get(key) or '').strip()
        normalized_value = normalized_slugs[key]
        if not raw_value:
            continue
        if normalized_value:
            cleaned_params[key] = normalized_value
        else:
            cleaned_params.pop(key, None)

    return cleaned_params


class CatalogFilterService:
    """Сборка каталоговых фильтров с поддержкой managed-конфига и legacy fallback."""

    def __init__(self, request):
        self.request = request

    def annotate_catalog_pricing(self, qs):
        return qs.annotate(
            catalog_stock_total=Coalesce(Sum('stocks__quantity'), Value(0)),
        ).annotate(
            catalog_effective_price=build_catalog_effective_price_expression(
                stock_total_field='catalog_stock_total',
            ),
        )

    def build_query_string(self, *, remove_keys: Iterable[str] | None = None, **updates) -> str:
        params = sanitize_catalog_query_params(self.request)
        for key in remove_keys or ():
            params.pop(key, None)
        for key, value in updates.items():
            if value is None or value == '':
                params.pop(key, None)
            else:
                params[key] = str(value)
        query_string = params.urlencode()
        return f'?{query_string}' if query_string else '?'

    def build_char_set_url(self, key: str, value: str, remove_keys: Iterable[str] | None = None) -> str:
        return self.build_query_string(remove_keys=remove_keys, **{f'char_{key}': value})

    def build_char_unset_url(self, key: str, remove_keys: Iterable[str] | None = None) -> str:
        keys_to_remove = list(remove_keys or [])
        param_key = f'char_{key}'
        if param_key not in keys_to_remove:
            keys_to_remove.append(param_key)
        return self.build_query_string(remove_keys=keys_to_remove)

    @cached_property
    def current_category_slug(self) -> str:
        return get_normalized_catalog_query_slugs(self.request)['category']

    @cached_property
    def current_section_slug(self) -> str:
        return get_normalized_catalog_query_slugs(self.request)['section']

    @cached_property
    def selected_category(self) -> Category | None:
        self.current_category_slug
        return getattr(self.request, '_catalog_resolved_query_category', None)

    @cached_property
    def selected_section(self):
        if self.selected_category and self.selected_category.section_id:
            return self.selected_category.section
        if not self.current_section_slug:
            return None
        return getattr(self.request, '_catalog_resolved_query_section', None)

    @cached_property
    def effective_section_slug(self) -> str:
        if self.current_section_slug:
            return self.current_section_slug
        if self.selected_category and self.selected_category.section:
            return self.selected_category.section.slug
        return ''

    @cached_property
    def active_definitions(self):
        return list(
            CharacteristicDefinition.objects
            .filter(is_active=True)
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
                )
            )
            .order_by('sort_order', 'name', 'code')
        )

    @cached_property
    def definitions_by_code(self):
        return {definition.code: definition for definition in self.active_definitions}

    @cached_property
    def definitions_by_source_name(self):
        return map_definitions_by_source_name(self.active_definitions)

    @cached_property
    def definitions_by_pk(self):
        return {definition.pk: definition for definition in self.active_definitions}

    def _get_alias_bundle(self, definition: CharacteristicDefinition):
        definition = self.definitions_by_pk.get(definition.pk, definition)
        raw_to_normalized = {}
        normalized_to_display = {}
        normalized_to_sort = {}
        display_to_normalized = {}
        normalized_to_raws = defaultdict(set)

        for alias in getattr(definition, 'active_value_aliases', []):
            raw_value = (alias.raw_value or '').strip()
            normalized_value = (alias.normalized_value or raw_value).strip()
            display_value = (alias.display_value or normalized_value).strip()
            if not raw_value or not normalized_value:
                continue
            raw_to_normalized[raw_value] = normalized_value
            normalized_to_display.setdefault(normalized_value, display_value)
            display_to_normalized.setdefault(display_value, normalized_value)
            normalized_to_raws[normalized_value].add(raw_value)
            current_sort = normalized_to_sort.get(normalized_value)
            alias_sort = alias.sort_order
            normalized_to_sort[normalized_value] = alias_sort if current_sort is None else min(current_sort, alias_sort)

        return {
            'raw_to_normalized': raw_to_normalized,
            'normalized_to_display': normalized_to_display,
            'normalized_to_sort': normalized_to_sort,
            'display_to_normalized': display_to_normalized,
            'normalized_to_raws': normalized_to_raws,
        }

    def _normalize_selected_value(self, definition: CharacteristicDefinition, value: str) -> str:
        cleaned_value = (value or '').strip()
        if not cleaned_value:
            return ''
        alias_bundle = self._get_alias_bundle(definition)
        if cleaned_value in alias_bundle['raw_to_normalized']:
            return alias_bundle['raw_to_normalized'][cleaned_value]
        if cleaned_value in alias_bundle['normalized_to_display']:
            return cleaned_value
        if cleaned_value in alias_bundle['display_to_normalized']:
            return alias_bundle['display_to_normalized'][cleaned_value]
        return cleaned_value

    @cached_property
    def active_characteristic_filters(self):
        char_entries = []
        for position, (key, value) in enumerate(self.request.GET.items()):
            if not key.startswith('char_') or not value:
                continue
            char_entries.append((position, key[5:], value))

        code_hits = {}
        source_hits = {}
        raw_hits = []

        for position, identifier, value in char_entries:
            if identifier in self.definitions_by_code:
                definition = self.definitions_by_code[identifier]
                existing = code_hits.get(definition.pk)
                if existing is None or position < existing[0]:
                    code_hits[definition.pk] = (position, identifier, value, definition)
            elif identifier in self.definitions_by_source_name:
                definition = self.definitions_by_source_name[identifier]
                existing = source_hits.get(definition.pk)
                if existing is None or position < existing[0]:
                    source_hits[definition.pk] = (position, identifier, value, definition)
            else:
                raw_hits.append((position, identifier, value))

        collected = []
        for definition_pk, entry in source_hits.items():
            if definition_pk in code_hits:
                continue
            collected.append(entry)
        collected.extend(code_hits.values())
        collected.sort(key=lambda entry: entry[0])

        parsed_filters = []
        for position, identifier, value, definition in collected:
            parsed_filters.append(
                ActiveCharacteristicFilter(
                    position=position,
                    canonical_key=definition.code,
                    label=definition.name,
                    selected_value=self._normalize_selected_value(definition, value),
                    request_identifier=identifier,
                    remove_keys=get_definition_remove_keys(definition),
                    definition=definition,
                )
            )

        for position, identifier, value in raw_hits:
            parsed_filters.append(
                ActiveCharacteristicFilter(
                    position=position,
                    canonical_key=identifier,
                    label=identifier,
                    selected_value=(value or '').strip(),
                    request_identifier=identifier,
                    remove_keys=(f'char_{identifier}',),
                    definition=None,
                )
            )

        parsed_filters.sort(key=lambda item: item.position)
        return parsed_filters

    @cached_property
    def active_characteristic_filter_map(self):
        return OrderedDict((item.canonical_key, item) for item in self.active_characteristic_filters)

    def build_filter_queryset(
        self,
        *,
        ignore_category=False,
        ignore_section=False,
        ignore_tag=False,
        ignore_price=False,
        include_char_filters=False,
        exclude_char_key=None,
    ):
        qs = Product.objects.filter(is_active=True)
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            qs = qs.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))

        if self.current_category_slug and not ignore_category:
            selected_category = self.selected_category
            if selected_category and getattr(selected_category, 'is_bundles_category', False):
                return Product.objects.none()
            qs = qs.filter(category__slug=self.current_category_slug)

        if self.current_section_slug and not ignore_section:
            qs = qs.filter(category__section__slug=self.current_section_slug)

        tag_slug = (self.request.GET.get('tag') or '').strip()
        if tag_slug and not ignore_tag:
            qs = qs.filter(tags__slug=tag_slug)

        qs = self.annotate_catalog_pricing(qs)

        if not ignore_price:
            price_min = self.request.GET.get('price_min')
            if price_min:
                try:
                    qs = qs.filter(catalog_effective_price__gte=float(price_min))
                except (TypeError, ValueError):
                    pass
            price_max = self.request.GET.get('price_max')
            if price_max:
                try:
                    qs = qs.filter(catalog_effective_price__lte=float(price_max))
                except (TypeError, ValueError):
                    pass

        if include_char_filters:
            for active_filter in self.active_characteristic_filters:
                if exclude_char_key and active_filter.canonical_key == exclude_char_key:
                    continue
                if active_filter.definition is not None:
                    allowed_values = set(
                        self._get_alias_bundle(active_filter.definition)['normalized_to_raws'].get(
                            active_filter.selected_value,
                            set(),
                        )
                    )
                    allowed_values.add(active_filter.selected_value)
                    qs = qs.filter(
                        characteristics__name__in=get_definition_source_names(active_filter.definition),
                        characteristics__value__in=allowed_values,
                    )
                else:
                    qs = qs.filter(
                        characteristics__name=active_filter.canonical_key,
                        characteristics__value=active_filter.selected_value,
                    )

        return qs.distinct()

    def get_filter_base_queryset(self):
        return self.build_filter_queryset()

    def get_price_bounds(self):
        price_bounds_qs = self.build_filter_queryset(include_char_filters=True, ignore_price=True)
        price_agg = price_bounds_qs.aggregate(min_p=Min('catalog_effective_price'), max_p=Max('catalog_effective_price'))
        return {
            'filter_price_min': int(price_agg['min_p']) if price_agg['min_p'] is not None else 0,
            'filter_price_max': int(price_agg['max_p']) if price_agg['max_p'] is not None else 0,
        }

    def get_product_tags(self):
        tags_base_qs = self.build_filter_queryset(ignore_tag=True, include_char_filters=True)
        tags_qs = (
            ProductTag.objects
            .filter(products__in=tags_base_qs)
            .annotate(result_count=Count('products', filter=Q(products__in=tags_base_qs), distinct=True))
            .order_by('order', 'name')
            .distinct()
        )
        return list(tags_qs)

    @cached_property
    def scope_filter_config(self):
        if self.selected_category is not None:
            category_configs = list(
                FilterConfig.objects
                .filter(
                    category=self.selected_category,
                    is_visible=True,
                    characteristic_definition__is_active=True,
                    characteristic_definition__is_filterable=True,
                )
                .select_related('characteristic_definition')
                .order_by('sort_order', 'characteristic_definition__sort_order', 'characteristic_definition__name', 'id')
            )
            if category_configs:
                return 'category', category_configs

        if self.selected_section is not None:
            section_configs = list(
                FilterConfig.objects
                .filter(
                    section=self.selected_section,
                    is_visible=True,
                    characteristic_definition__is_active=True,
                    characteristic_definition__is_filterable=True,
                )
                .select_related('characteristic_definition')
                .order_by('sort_order', 'characteristic_definition__sort_order', 'characteristic_definition__name', 'id')
            )
            if section_configs:
                return 'section', section_configs

        return 'legacy', []

    def _build_active_characteristic_filter_payloads(self):
        payloads = []
        for item in self.active_characteristic_filters:
            display_value = item.selected_value
            if item.definition is not None:
                display_value = self._get_alias_bundle(item.definition)['normalized_to_display'].get(
                    item.selected_value,
                    item.selected_value,
                )
            payloads.append(
                {
                    'key': item.canonical_key,
                    'label': item.label,
                    'value': display_value,
                    'selected_value': item.selected_value,
                    'remove_url': self.build_query_string(remove_keys=item.remove_keys),
                }
            )
        return payloads

    def _build_managed_filter_group(self, config):
        definition = config.characteristic_definition
        scoped_qs = self.build_filter_queryset(include_char_filters=True, exclude_char_key=definition.code)
        rows = (
            ProductCharacteristic.objects
            .filter(product__in=scoped_qs, name__in=get_definition_source_names(definition))
            .values_list('product_id', 'value')
            .distinct()
        )

        alias_bundle = self._get_alias_bundle(definition)
        buckets = {}
        selected_filter = self.active_characteristic_filter_map.get(definition.code)
        selected_value = selected_filter.selected_value if selected_filter else ''

        for product_id, raw_value in rows:
            raw_value = (raw_value or '').strip()
            if not raw_value:
                continue
            normalized_value = alias_bundle['raw_to_normalized'].get(raw_value, raw_value)
            display_value = alias_bundle['normalized_to_display'].get(normalized_value, normalized_value)
            bucket = buckets.setdefault(
                normalized_value,
                {
                    'value': normalized_value,
                    'label': display_value,
                    'count_product_ids': set(),
                    'sort_order': alias_bundle['normalized_to_sort'].get(normalized_value),
                },
            )
            bucket['count_product_ids'].add(product_id)
            alias_sort = alias_bundle['normalized_to_sort'].get(normalized_value)
            if alias_sort is not None:
                bucket['sort_order'] = alias_sort if bucket['sort_order'] is None else min(bucket['sort_order'], alias_sort)

        options = []
        for bucket in buckets.values():
            options.append(
                {
                    'value': bucket['value'],
                    'label': bucket['label'],
                    'count': len(bucket['count_product_ids']),
                    'selected': selected_value == bucket['value'],
                    'sort_order': bucket['sort_order'],
                    'typed_sort_key': get_typed_value_sort_key(bucket['label'], sorting_mode=definition.sorting_mode),
                    'url': self.build_char_set_url(
                        definition.code,
                        bucket['value'],
                        remove_keys=get_definition_remove_keys(definition),
                    ),
                }
            )

        options.sort(
            key=lambda option: (
                option['sort_order'] is None,
                option['sort_order'] if option['sort_order'] is not None else 0,
                option['typed_sort_key'],
                option['label'].lower(),
            )
        )

        if len(options) == 1 and config.hide_single_value:
            return None
        if not options:
            return None

        initial_visible_count = config.show_top_n or (5 if len(options) > 5 else len(options))
        return {
            'key': definition.code,
            'legacy_key': definition.source_name,
            'remove_keys_csv': ','.join(get_definition_remove_keys(definition)),
            'label': definition.name,
            'selected_value': selected_value,
            'all_url': self.build_char_unset_url(
                definition.code,
                remove_keys=get_definition_remove_keys(definition),
            ),
            'options': options,
            'show_as_list': len(options) > 6,
            'initial_visible_count': initial_visible_count,
            'has_more_values': len(options) > initial_visible_count,
            'is_quick_filter': config.is_quick_filter,
            'is_expanded_by_default': config.is_expanded_by_default,
        }

    def _build_legacy_filter_group(self, char_name: str):
        scoped_qs = self.build_filter_queryset(include_char_filters=True, exclude_char_key=char_name)
        value_rows = list(
            ProductCharacteristic.objects
            .filter(product__in=scoped_qs, name=char_name)
            .values('value')
            .annotate(total=Count('product', distinct=True))
            .order_by('value')
        )
        if len(value_rows) <= 1:
            return None

        selected_filter = self.active_characteristic_filter_map.get(char_name)
        selected_value = selected_filter.selected_value if selected_filter else ''
        options = []
        for row in value_rows:
            options.append(
                {
                    'value': row['value'],
                    'label': row['value'],
                    'count': row['total'],
                    'selected': selected_value == row['value'],
                    'url': self.build_char_set_url(char_name, row['value'], remove_keys=(f'char_{char_name}',)),
                }
            )

        initial_visible_count = 5 if len(options) > 5 else len(options)
        return {
            'key': char_name,
            'legacy_key': char_name,
            'remove_keys_csv': f'char_{char_name}',
            'label': char_name,
            'selected_value': selected_value,
            'all_url': self.build_char_unset_url(char_name, remove_keys=(f'char_{char_name}',)),
            'options': options,
            'show_as_list': len(options) > 6,
            'initial_visible_count': initial_visible_count,
            'has_more_values': len(options) > initial_visible_count,
            'is_quick_filter': False,
            'is_expanded_by_default': False,
        }

    def _build_legacy_characteristics(self):
        char_names = (
            ProductCharacteristic.objects
            .filter(product__in=self.get_filter_base_queryset())
            .values_list('name', flat=True)
            .distinct()
            .order_by('name')
        )
        groups = []
        for char_name in char_names:
            group = self._build_legacy_filter_group(char_name)
            if group is not None:
                groups.append(group)
        return groups

    def _build_managed_characteristics(self, configs):
        groups = []
        for config in configs:
            group = self._build_managed_filter_group(config)
            if group is not None:
                groups.append(group)
        return groups

    def get_characteristics_context(self):
        filter_mode, configs = self.scope_filter_config
        if filter_mode != 'legacy':
            managed_groups = self._build_managed_characteristics(configs)
            if managed_groups:
                return {
                    'filter_mode': filter_mode,
                    'characteristic_filters': managed_groups,
                    'quick_characteristic_filters': [group for group in managed_groups if group['is_quick_filter']],
                    'active_characteristic_filters': self._build_active_characteristic_filter_payloads(),
                    'char_filters': OrderedDict(
                        (item.canonical_key, item.selected_value)
                        for item in self.active_characteristic_filters
                    ),
                }

        legacy_groups = self._build_legacy_characteristics()
        return {
            'filter_mode': 'legacy',
            'characteristic_filters': legacy_groups,
            'quick_characteristic_filters': legacy_groups[:2],
            'active_characteristic_filters': self._build_active_characteristic_filter_payloads(),
            'char_filters': OrderedDict(
                (item.canonical_key, item.selected_value)
                for item in self.active_characteristic_filters
            ),
        }
