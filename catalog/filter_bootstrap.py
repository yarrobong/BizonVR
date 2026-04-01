from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

from .characteristic_codes import generate_unique_characteristic_code
from .characteristic_normalization import normalize_characteristic_value
from .models import (
    CatalogSection,
    Category,
    CategoryFilterConfig,
    CharacteristicDefinition,
    CharacteristicValueAlias,
    ProductCharacteristic,
    SectionFilterConfig,
)


@dataclass(frozen=True)
class AliasSuggestionValue:
    raw_value: str
    product_count: int
    alias_exists: bool
    alias_is_active: bool
    existing_normalized_value: str
    existing_display_value: str


def get_distinct_characteristic_source_names(*, source_name: str = '', starts_with: str = '', contains: str = '') -> list[str]:
    queryset = ProductCharacteristic.objects.order_by('name').values_list('name', flat=True).distinct()
    if source_name:
        queryset = queryset.filter(name=source_name)
    if starts_with:
        queryset = queryset.filter(name__istartswith=starts_with)
    if contains:
        queryset = queryset.filter(name__icontains=contains)
    return list(queryset)


def bootstrap_characteristic_definitions(
    *,
    apply: bool = False,
    only_missing: bool = True,
    source_name: str = '',
    starts_with: str = '',
    contains: str = '',
):
    source_names = get_distinct_characteristic_source_names(
        source_name=source_name,
        starts_with=starts_with,
        contains=contains,
    )
    existing_by_source = {
        definition.source_name: definition
        for definition in CharacteristicDefinition.objects.filter(source_name__in=source_names)
    }
    results = []

    for current_source_name in source_names:
        existing = existing_by_source.get(current_source_name)
        if existing is not None:
            results.append(
                {
                    'source_name': current_source_name,
                    'code': existing.code,
                    'action': 'existing',
                    'definition_id': existing.pk,
                }
            )
            continue
        code = generate_unique_characteristic_code(current_source_name)
        results.append(
            {
                'source_name': current_source_name,
                'code': code,
                'action': 'would_create' if not apply else 'created',
                'definition_id': None,
            }
        )
        if apply:
            definition = CharacteristicDefinition.objects.create(
                code=code,
                name=current_source_name,
                source_name=current_source_name,
                is_filterable=True,
                is_active=True,
                sort_order=0,
            )
            results[-1]['definition_id'] = definition.pk

    return results


def resolve_characteristic_definition(definition_ref: str) -> CharacteristicDefinition:
    cleaned_ref = (definition_ref or '').strip()
    if not cleaned_ref:
        raise CharacteristicDefinition.DoesNotExist('Definition reference is required.')
    queryset = CharacteristicDefinition.objects.all()
    if cleaned_ref.isdigit():
        return queryset.get(pk=int(cleaned_ref))
    return queryset.get(code=cleaned_ref)


def build_alias_suggestions(definition: CharacteristicDefinition):
    rows = (
        ProductCharacteristic.objects
        .filter(name=definition.source_name)
        .values_list('product_id', 'value')
        .distinct()
    )
    product_ids_by_raw_value = defaultdict(set)
    for product_id, raw_value in rows:
        cleaned_value = (raw_value or '').strip()
        if cleaned_value:
            product_ids_by_raw_value[cleaned_value].add(product_id)

    aliases = {
        alias.raw_value: alias
        for alias in CharacteristicValueAlias.objects.filter(characteristic_definition=definition)
    }

    groups = {}
    for raw_value, product_ids in product_ids_by_raw_value.items():
        suggestion = normalize_characteristic_value(raw_value)
        group = groups.setdefault(
            suggestion.normalized_key,
            {
                'normalized_key': suggestion.normalized_key,
                'suggested_display': suggestion.suggested_display,
                'product_ids': set(),
                'raw_values': [],
            },
        )
        alias = aliases.get(raw_value)
        group['product_ids'].update(product_ids)
        group['raw_values'].append(
            AliasSuggestionValue(
                raw_value=raw_value,
                product_count=len(product_ids),
                alias_exists=alias is not None,
                alias_is_active=bool(alias and alias.is_active),
                existing_normalized_value=(alias.normalized_value if alias else ''),
                existing_display_value=(alias.display_value if alias else ''),
            )
        )

    suggestions = []
    for group in groups.values():
        raw_values = sorted(group['raw_values'], key=lambda item: (item.alias_exists, item.raw_value.lower()))
        suggestions.append(
            {
                'normalized_key': group['normalized_key'],
                'suggested_display': group['suggested_display'],
                'product_count': len(group['product_ids']),
                'raw_values': raw_values,
                'already_covered': all(item.alias_exists for item in raw_values),
                'missing_count': sum(1 for item in raw_values if not item.alias_exists),
            }
        )

    suggestions.sort(key=lambda item: (item['already_covered'], item['suggested_display'].lower(), item['normalized_key']))
    return suggestions


@transaction.atomic
def create_aliases_from_suggestions(
    definition: CharacteristicDefinition,
    *,
    selected_normalized_keys: list[str],
    display_overrides: dict[str, str] | None = None,
):
    display_overrides = display_overrides or {}
    suggestions = build_alias_suggestions(definition)
    created = 0
    skipped_existing = 0

    for suggestion in suggestions:
        normalized_key = suggestion['normalized_key']
        if normalized_key not in selected_normalized_keys:
            continue
        display_value = (display_overrides.get(normalized_key) or suggestion['suggested_display']).strip()
        for raw_value_info in suggestion['raw_values']:
            alias, was_created = CharacteristicValueAlias.objects.get_or_create(
                characteristic_definition=definition,
                raw_value=raw_value_info.raw_value,
                defaults={
                    'normalized_value': normalized_key,
                    'display_value': display_value,
                    'sort_order': 0,
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
            else:
                skipped_existing += 1

    return {
        'created': created,
        'skipped_existing': skipped_existing,
    }


def resolve_catalog_category(category_ref: str) -> Category:
    cleaned_ref = (category_ref or '').strip()
    if cleaned_ref.isdigit():
        return Category.objects.select_related('section').get(pk=int(cleaned_ref))
    return Category.objects.select_related('section').get(slug=cleaned_ref)


def resolve_catalog_section(section_ref: str) -> CatalogSection:
    cleaned_ref = (section_ref or '').strip()
    if cleaned_ref.isdigit():
        return CatalogSection.objects.get(pk=int(cleaned_ref))
    return CatalogSection.objects.get(slug=cleaned_ref)


def _collect_definition_candidates_for_category(category: Category):
    source_names = (
        ProductCharacteristic.objects
        .filter(product__category=category)
        .values_list('name', flat=True)
        .distinct()
    )
    return list(
        CharacteristicDefinition.objects
        .filter(source_name__in=source_names, is_filterable=True)
        .order_by('sort_order', 'name', 'code')
    )


def _collect_definition_candidates_for_section(section: CatalogSection):
    source_names = (
        ProductCharacteristic.objects
        .filter(product__category__section=section)
        .values_list('name', flat=True)
        .distinct()
    )
    return list(
        CharacteristicDefinition.objects
        .filter(source_name__in=source_names, is_filterable=True)
        .order_by('sort_order', 'name', 'code')
    )


def bootstrap_category_filter_configs(category: Category, *, apply: bool = False, skip_existing: bool = True):
    definitions = _collect_definition_candidates_for_category(category)
    existing_definition_ids = set(
        CategoryFilterConfig.objects.filter(category=category).values_list('characteristic_definition_id', flat=True)
    )
    results = []

    for definition in definitions:
        if definition.pk in existing_definition_ids and skip_existing:
            results.append({'definition': definition, 'action': 'existing'})
            continue
        results.append({'definition': definition, 'action': 'would_create' if not apply else 'created'})
        if apply and definition.pk not in existing_definition_ids:
            CategoryFilterConfig.objects.create(
                category=category,
                characteristic_definition=definition,
                sort_order=definition.sort_order,
                hide_single_value=True,
                is_quick_filter=False,
                is_visible=definition.is_filterable and definition.is_active,
                is_expanded_by_default=False,
                show_top_n=None,
            )
            existing_definition_ids.add(definition.pk)

    return results


def bootstrap_section_filter_configs(section: CatalogSection, *, apply: bool = False, skip_existing: bool = True):
    definitions = _collect_definition_candidates_for_section(section)
    existing_definition_ids = set(
        SectionFilterConfig.objects.filter(section=section).values_list('characteristic_definition_id', flat=True)
    )
    results = []

    for definition in definitions:
        if definition.pk in existing_definition_ids and skip_existing:
            results.append({'definition': definition, 'action': 'existing'})
            continue
        results.append({'definition': definition, 'action': 'would_create' if not apply else 'created'})
        if apply and definition.pk not in existing_definition_ids:
            SectionFilterConfig.objects.create(
                section=section,
                characteristic_definition=definition,
                sort_order=definition.sort_order,
                hide_single_value=True,
                is_quick_filter=False,
                is_visible=definition.is_filterable and definition.is_active,
                is_expanded_by_default=False,
                show_top_n=None,
            )
            existing_definition_ids.add(definition.pk)

    return results
