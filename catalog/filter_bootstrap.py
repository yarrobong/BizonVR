from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

from .characteristic_codes import generate_unique_characteristic_code
from .characteristic_normalization import normalize_characteristic_value
from .characteristic_sources import get_definition_source_names, normalize_source_name_tokens, source_name_similarity_score
from .models import (
    CatalogSection,
    Category,
    CharacteristicDefinition,
    CharacteristicSourceAlias,
    CharacteristicValueAlias,
    FilterConfig,
    ProductCharacteristic,
)


SAFE_AUTO_APPLICABLE = 'safe_auto_applicable'
BLOCKED_BY_EXISTING_ALIAS = 'blocked_by_existing_alias'
CONFLICTING_GROUP = 'conflicting_group'
MANUAL_REVIEW_REQUIRED = 'manual_review_required'


@dataclass(frozen=True)
class AliasSuggestionValue:
    raw_value: str
    product_count: int
    alias_exists: bool
    alias_is_active: bool
    existing_normalized_value: str
    existing_display_value: str
    safe_merge_key: str


@dataclass(frozen=True)
class SourceAliasSuggestion:
    raw_source_name: str
    product_count: int
    similarity_score: int
    overlap_value_count: int
    tokens: tuple[str, ...]


def get_distinct_characteristic_source_names(*, source_name: str = '', starts_with: str = '', contains: str = '') -> list[str]:
    queryset = ProductCharacteristic.objects.order_by('name').values_list('name', flat=True).distinct()
    if source_name:
        queryset = queryset.filter(name=source_name)
    if starts_with:
        queryset = queryset.filter(name__istartswith=starts_with)
    if contains:
        queryset = queryset.filter(name__icontains=contains)
    return list(queryset)


def get_covered_definition_sources(definitions=None) -> dict[str, CharacteristicDefinition]:
    if definitions is None:
        definitions = list(
            CharacteristicDefinition.objects
            .all()
            .prefetch_related('source_aliases')
            .order_by('sort_order', 'name', 'code')
        )
    mapping = {}
    for definition in definitions:
        primary_source_name = (definition.source_name or '').strip()
        if primary_source_name:
            mapping[primary_source_name] = definition
        source_aliases = definition.source_aliases.all() if hasattr(definition.source_aliases, 'all') else definition.source_aliases
        for alias in source_aliases:
            if not getattr(alias, 'is_active', True):
                continue
            raw_source_name = (alias.raw_source_name or '').strip()
            if raw_source_name:
                mapping[raw_source_name] = definition
    return mapping


def bootstrap_characteristic_definitions(
    *,
    apply: bool = False,
    only_missing: bool = True,
    source_name: str = '',
    starts_with: str = '',
    contains: str = '',
):
    del only_missing
    source_names = get_distinct_characteristic_source_names(
        source_name=source_name,
        starts_with=starts_with,
        contains=contains,
    )
    definitions = list(CharacteristicDefinition.objects.prefetch_related('source_aliases').all())
    covered_by_source = get_covered_definition_sources(definitions)
    results = []

    for current_source_name in source_names:
        existing = covered_by_source.get(current_source_name)
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
            covered_by_source[current_source_name] = definition

    return results


def resolve_characteristic_definition(definition_ref: str) -> CharacteristicDefinition:
    cleaned_ref = (definition_ref or '').strip()
    if not cleaned_ref:
        raise CharacteristicDefinition.DoesNotExist('Definition reference is required.')
    queryset = CharacteristicDefinition.objects.prefetch_related('source_aliases').all()
    if cleaned_ref.isdigit():
        return queryset.get(pk=int(cleaned_ref))
    return queryset.get(code=cleaned_ref)


def _definition_characteristic_rows(definition: CharacteristicDefinition, *, product_ids=None):
    queryset = ProductCharacteristic.objects.filter(name__in=get_definition_source_names(definition))
    if product_ids is not None:
        queryset = queryset.filter(product_id__in=product_ids)
    return queryset.values_list('product_id', 'name', 'value').distinct()


def build_alias_suggestions(definition: CharacteristicDefinition, *, product_ids=None):
    rows = _definition_characteristic_rows(definition, product_ids=product_ids)
    product_ids_by_raw_value = defaultdict(set)
    for product_id, _source_name, raw_value in rows:
        cleaned_value = (raw_value or '').strip()
        if cleaned_value:
            product_ids_by_raw_value[cleaned_value].add(product_id)

    aliases = {
        alias.raw_value: alias
        for alias in CharacteristicValueAlias.objects.filter(characteristic_definition=definition)
    }

    groups = {}
    for raw_value, product_ids in product_ids_by_raw_value.items():
        normalized = normalize_characteristic_value(raw_value)
        group = groups.setdefault(
            normalized.normalized_key,
            {
                'normalized_key': normalized.normalized_key,
                'suggested_display': normalized.suggested_display,
                'product_ids': set(),
                'raw_values': [],
                'safe_merge_keys': set(),
                'existing_normalized_values': set(),
            },
        )
        alias = aliases.get(raw_value)
        group['product_ids'].update(product_ids)
        group['safe_merge_keys'].add(normalized.safe_merge_key)
        if alias is not None and alias.normalized_value:
            group['existing_normalized_values'].add(alias.normalized_value.strip())
        group['raw_values'].append(
            AliasSuggestionValue(
                raw_value=raw_value,
                product_count=len(product_ids),
                alias_exists=alias is not None,
                alias_is_active=bool(alias and alias.is_active),
                existing_normalized_value=(alias.normalized_value if alias else ''),
                existing_display_value=(alias.display_value if alias else ''),
                safe_merge_key=normalized.safe_merge_key,
            )
        )

    suggestions = []
    for group in groups.values():
        raw_values = sorted(group['raw_values'], key=lambda item: (item.alias_exists, item.raw_value.lower()))
        existing_normalized_values = {value for value in group['existing_normalized_values'] if value}
        missing_count = sum(1 for item in raw_values if not item.alias_exists)
        status = MANUAL_REVIEW_REQUIRED
        if len(existing_normalized_values) > 1:
            status = CONFLICTING_GROUP
        elif existing_normalized_values and existing_normalized_values != {group['normalized_key']}:
            status = BLOCKED_BY_EXISTING_ALIAS
        elif missing_count and len(group['safe_merge_keys']) == 1:
            status = SAFE_AUTO_APPLICABLE

        suggestions.append(
            {
                'normalized_key': group['normalized_key'],
                'suggested_display': group['suggested_display'],
                'product_count': len(group['product_ids']),
                'raw_values': raw_values,
                'already_covered': all(item.alias_exists for item in raw_values),
                'missing_count': missing_count,
                'status': status,
                'safe_auto_applicable': status == SAFE_AUTO_APPLICABLE,
            }
        )

    suggestions.sort(
        key=lambda item: (
            item['status'] != SAFE_AUTO_APPLICABLE,
            item['already_covered'],
            item['suggested_display'].lower(),
            item['normalized_key'],
        )
    )
    return suggestions


@transaction.atomic
def create_aliases_from_suggestions(
    definition: CharacteristicDefinition,
    *,
    selected_normalized_keys: list[str],
    display_overrides: dict[str, str] | None = None,
    safe_only: bool = False,
):
    display_overrides = display_overrides or {}
    suggestions = build_alias_suggestions(definition)
    created = 0
    skipped_existing = 0
    skipped_unsafe = 0

    for suggestion in suggestions:
        normalized_key = suggestion['normalized_key']
        if normalized_key not in selected_normalized_keys:
            continue
        if safe_only and not suggestion['safe_auto_applicable']:
            skipped_unsafe += 1
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
        'skipped_unsafe': skipped_unsafe,
    }


def build_source_alias_suggestions(definition: CharacteristicDefinition, *, product_ids=None, allowed_source_names=None):
    covered_source_names = set(get_definition_source_names(definition))
    definition_tokens = set(normalize_source_name_tokens(definition.source_name))
    definition_values = {
        normalize_characteristic_value(value).normalized_key
        for _product_id, _source_name, value in _definition_characteristic_rows(definition, product_ids=product_ids)
        if (value or '').strip()
    }
    source_queryset = ProductCharacteristic.objects.exclude(name__in=covered_source_names)
    if product_ids is not None:
        source_queryset = source_queryset.filter(product_id__in=product_ids)
    if allowed_source_names is not None:
        source_queryset = source_queryset.filter(name__in=allowed_source_names)
    source_rows = source_queryset.values_list('name', 'product_id', 'value').distinct()
    product_ids_by_source = defaultdict(set)
    value_keys_by_source = defaultdict(set)
    for raw_source_name, product_id, raw_value in source_rows:
        product_ids_by_source[raw_source_name].add(product_id)
        cleaned_value = (raw_value or '').strip()
        if cleaned_value:
            value_keys_by_source[raw_source_name].add(normalize_characteristic_value(cleaned_value).normalized_key)

    suggestions = []
    for raw_source_name, product_ids in product_ids_by_source.items():
        similarity_score = source_name_similarity_score(definition.source_name, raw_source_name)
        overlap_value_count = len(definition_values & value_keys_by_source[raw_source_name])
        tokens = tuple(sorted(set(normalize_source_name_tokens(raw_source_name)) | definition_tokens))
        if similarity_score <= 0 and overlap_value_count <= 0:
            continue
        suggestions.append(
            SourceAliasSuggestion(
                raw_source_name=raw_source_name,
                product_count=len(product_ids),
                similarity_score=similarity_score,
                overlap_value_count=overlap_value_count,
                tokens=tokens,
            )
        )

    suggestions.sort(
        key=lambda item: (-item.similarity_score, -item.overlap_value_count, -item.product_count, item.raw_source_name.lower())
    )
    return suggestions


@transaction.atomic
def create_source_aliases_from_suggestions(definition: CharacteristicDefinition, *, selected_source_names: list[str]):
    created = 0
    skipped_existing = 0
    for source_name in selected_source_names:
        alias, was_created = CharacteristicSourceAlias.objects.get_or_create(
            characteristic_definition=definition,
            raw_source_name=source_name,
            defaults={'sort_order': 0, 'is_active': True},
        )
        if was_created:
            created += 1
        else:
            skipped_existing += 1
    return {'created': created, 'skipped_existing': skipped_existing}


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
    source_names = set(
        ProductCharacteristic.objects
        .filter(product__category=category)
        .values_list('name', flat=True)
        .distinct()
    )
    definitions = (
        CharacteristicDefinition.objects
        .filter(is_filterable=True)
        .prefetch_related('source_aliases')
        .order_by('sort_order', 'name', 'code')
    )
    return [definition for definition in definitions if source_names & set(get_definition_source_names(definition))]


def _collect_definition_candidates_for_section(section: CatalogSection):
    source_names = set(
        ProductCharacteristic.objects
        .filter(product__category__section=section)
        .values_list('name', flat=True)
        .distinct()
    )
    definitions = (
        CharacteristicDefinition.objects
        .filter(is_filterable=True)
        .prefetch_related('source_aliases')
        .order_by('sort_order', 'name', 'code')
    )
    return [definition for definition in definitions if source_names & set(get_definition_source_names(definition))]


def bootstrap_filter_configs(scope_type: str, scope_obj, *, apply: bool = False, skip_existing: bool = True):
    """Создаёт FilterConfig для категории или раздела по реально встречающимся характеристикам.

    scope_type: 'category' или 'section'
    scope_obj: объект Category или CatalogSection
    """
    if scope_type == 'category':
        definitions = _collect_definition_candidates_for_category(scope_obj)
        existing_definition_ids = set(
            FilterConfig.objects.filter(category=scope_obj).values_list('characteristic_definition_id', flat=True)
        )
        create_kwargs = lambda definition: {'category': scope_obj, 'section': None}
    else:
        definitions = _collect_definition_candidates_for_section(scope_obj)
        existing_definition_ids = set(
            FilterConfig.objects.filter(section=scope_obj).values_list('characteristic_definition_id', flat=True)
        )
        create_kwargs = lambda definition: {'category': None, 'section': scope_obj}

    results = []
    for definition in definitions:
        if definition.pk in existing_definition_ids and skip_existing:
            results.append({'definition': definition, 'action': 'existing'})
            continue
        results.append({'definition': definition, 'action': 'would_create' if not apply else 'created'})
        if apply and definition.pk not in existing_definition_ids:
            FilterConfig.objects.create(
                **create_kwargs(definition),
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


# Обратная совместимость для management commands
def bootstrap_category_filter_configs(category: Category, *, apply: bool = False, skip_existing: bool = True):
    return bootstrap_filter_configs('category', category, apply=apply, skip_existing=skip_existing)


def bootstrap_section_filter_configs(section: CatalogSection, *, apply: bool = False, skip_existing: bool = True):
    return bootstrap_filter_configs('section', section, apply=apply, skip_existing=skip_existing)
