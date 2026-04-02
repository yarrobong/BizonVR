from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count

from .characteristic_codes import generate_unique_characteristic_code
from .characteristic_normalization import normalize_characteristic_value
from .characteristic_sources import get_definition_source_names
from .filter_bootstrap import (
    SAFE_AUTO_APPLICABLE,
    bootstrap_filter_configs,
    build_alias_suggestions,
    build_source_alias_suggestions,
    create_aliases_from_suggestions,
    create_source_aliases_from_suggestions,
    get_covered_definition_sources,
)
from .models import (
    CatalogSection,
    Category,
    CharacteristicDefinition,
    CharacteristicValueAlias,
    FilterConfig,
    ProductCharacteristic,
)


def encode_source_alias_selection(definition_id: int, raw_source_name: str) -> str:
    return f'{definition_id}::{raw_source_name}'


def decode_source_alias_selection(selection: str) -> tuple[int | None, str]:
    left, separator, right = (selection or '').partition('::')
    if not separator or not left.isdigit():
        return None, ''
    return int(left), right.strip()


def encode_value_alias_selection(definition_id: int, normalized_key: str) -> str:
    return f'{definition_id}::{normalized_key}'


def decode_value_alias_selection(selection: str) -> tuple[int | None, str]:
    left, separator, right = (selection or '').partition('::')
    if not separator or not left.isdigit():
        return None, ''
    return int(left), right.strip()


def _build_filter_config_defaults(definition: CharacteristicDefinition) -> dict:
    return {
        'sort_order': definition.sort_order,
        'hide_single_value': True,
        'is_quick_filter': False,
        'is_visible': definition.is_filterable and definition.is_active,
        'is_expanded_by_default': False,
        'show_top_n': None,
    }


@dataclass
class CatalogFilterSetupWizard:
    scope_type: str
    scope_obj: Category | CatalogSection

    def __post_init__(self):
        if self.scope_type not in {'category', 'section'}:
            raise ValueError('scope_type must be "category" or "section".')

    @property
    def scope_label(self) -> str:
        if self.scope_type == 'category':
            return f'Категория: {self.scope_obj.name}'
        return f'Раздел: {self.scope_obj.name}'

    def _scope_characteristics(self):
        queryset = ProductCharacteristic.objects.all()
        if self.scope_type == 'category':
            return queryset.filter(product__category=self.scope_obj)
        return queryset.filter(product__category__section=self.scope_obj)

    def _scope_product_ids(self) -> list[int]:
        if self.scope_type == 'category':
            return list(self.scope_obj.products.values_list('id', flat=True).distinct())
        return list(
            self.scope_obj.categories.values_list('products__id', flat=True).exclude(products__id__isnull=True).distinct()
        )

    def _scope_source_name_counts(self) -> dict[str, int]:
        rows = (
            self._scope_characteristics()
            .values('name')
            .annotate(product_count=Count('product_id', distinct=True))
            .order_by('name')
        )
        return {row['name']: row['product_count'] for row in rows}

    def _scope_definitions(self) -> list[CharacteristicDefinition]:
        source_names = set(self._scope_source_name_counts())
        definitions = list(
            CharacteristicDefinition.objects
            .filter(is_filterable=True)
            .prefetch_related('source_aliases')
            .order_by('sort_order', 'name', 'code')
        )
        return [
            definition
            for definition in definitions
            if source_names & set(get_definition_source_names(definition))
        ]

    def _best_source_alias_matches(self, *, product_ids: list[int], uncovered_source_names: set[str]) -> dict[str, dict]:
        suggestions_by_source_name: dict[str, dict] = {}
        for definition in self._scope_definitions():
            for suggestion in build_source_alias_suggestions(
                definition,
                product_ids=product_ids,
                allowed_source_names=uncovered_source_names,
            ):
                current = suggestions_by_source_name.get(suggestion.raw_source_name)
                candidate_rank = (
                    suggestion.similarity_score,
                    suggestion.overlap_value_count,
                    suggestion.product_count,
                    -definition.sort_order,
                )
                if current is not None and current['rank'] >= candidate_rank:
                    continue
                suggestions_by_source_name[suggestion.raw_source_name] = {
                    'definition': definition,
                    'suggestion': suggestion,
                    'rank': candidate_rank,
                }
        return suggestions_by_source_name

    def _definition_value_metrics(self, definition: CharacteristicDefinition, *, product_ids: list[int], total_products: int):
        active_aliases = {
            alias.raw_value: alias
            for alias in CharacteristicValueAlias.objects.filter(
                characteristic_definition=definition,
                is_active=True,
            )
        }
        buckets: dict[str, set[int]] = defaultdict(set)
        rows = (
            ProductCharacteristic.objects
            .filter(product_id__in=product_ids, name__in=get_definition_source_names(definition))
            .values_list('product_id', 'value')
            .distinct()
        )
        for product_id, raw_value in rows:
            cleaned_value = (raw_value or '').strip()
            if not cleaned_value:
                continue
            alias = active_aliases.get(cleaned_value)
            if alias is not None and alias.normalized_value:
                normalized_key = alias.normalized_value.strip()
            else:
                normalized_key = normalize_characteristic_value(cleaned_value).normalized_key
            buckets[normalized_key].add(product_id)

        covered_products = len({product_id for product_ids_for_value in buckets.values() for product_id in product_ids_for_value})
        distinct_value_count = len(buckets)
        singleton_count = sum(1 for product_ids_for_value in buckets.values() if len(product_ids_for_value) == 1)
        coverage_ratio = (covered_products / total_products) if total_products else 0.0
        singleton_ratio = (singleton_count / distinct_value_count) if distinct_value_count else 1.0
        return {
            'distinct_value_count': distinct_value_count,
            'covered_products': covered_products,
            'coverage_ratio': coverage_ratio,
            'singleton_ratio': singleton_ratio,
        }

    def build_preview(self) -> dict:
        product_ids = self._scope_product_ids()
        source_name_counts = self._scope_source_name_counts()
        covered_by_source = get_covered_definition_sources()
        uncovered_source_names = {
            source_name for source_name in source_name_counts
            if source_name not in covered_by_source
        }
        best_alias_matches = self._best_source_alias_matches(
            product_ids=product_ids,
            uncovered_source_names=uncovered_source_names,
        )
        alias_source_names = set(best_alias_matches)

        missing_definitions = [
            {
                'source_name': source_name,
                'product_count': source_name_counts[source_name],
                'suggested_code': generate_unique_characteristic_code(source_name),
            }
            for source_name in sorted(
                uncovered_source_names - alias_source_names,
                key=lambda value: (-source_name_counts[value], value.lower()),
            )
        ]

        source_alias_groups_map: dict[int, dict] = {}
        for raw_source_name, match in best_alias_matches.items():
            definition = match['definition']
            suggestion = match['suggestion']
            group = source_alias_groups_map.setdefault(
                definition.pk,
                {
                    'definition': definition,
                    'items': [],
                },
            )
            group['items'].append(
                {
                    'selection_value': encode_source_alias_selection(definition.pk, raw_source_name),
                    'raw_source_name': raw_source_name,
                    'product_count': suggestion.product_count,
                    'similarity_score': suggestion.similarity_score,
                    'overlap_value_count': suggestion.overlap_value_count,
                }
            )
        source_alias_suggestions = []
        for group in source_alias_groups_map.values():
            group['items'].sort(
                key=lambda item: (-item['similarity_score'], -item['overlap_value_count'], -item['product_count'], item['raw_source_name'].lower())
            )
            source_alias_suggestions.append(group)
        source_alias_suggestions.sort(key=lambda item: (item['definition'].sort_order, item['definition'].name.lower()))

        safe_value_alias_suggestions = []
        for definition in self._scope_definitions():
            safe_items = []
            for suggestion in build_alias_suggestions(definition, product_ids=product_ids):
                if suggestion['status'] != SAFE_AUTO_APPLICABLE or not suggestion['missing_count']:
                    continue
                safe_items.append(
                    {
                        'selection_value': encode_value_alias_selection(definition.pk, suggestion['normalized_key']),
                        'normalized_key': suggestion['normalized_key'],
                        'suggested_display': suggestion['suggested_display'],
                        'product_count': suggestion['product_count'],
                        'missing_count': suggestion['missing_count'],
                        'raw_values': [item.raw_value for item in suggestion['raw_values'] if not item.alias_exists],
                    }
                )
            if safe_items:
                safe_items.sort(key=lambda item: (-item['product_count'], item['suggested_display'].lower()))
                safe_value_alias_suggestions.append({'definition': definition, 'items': safe_items})

        missing_configs = [
            {
                'definition': result['definition'],
                'defaults': _build_filter_config_defaults(result['definition']),
            }
            for result in bootstrap_filter_configs(self.scope_type, self.scope_obj, apply=False, skip_existing=True)
            if result['action'] == 'would_create'
        ]

        config_lookup = {}
        filter_config_queryset = FilterConfig.objects.select_related('characteristic_definition')
        if self.scope_type == 'category':
            filter_config_queryset = filter_config_queryset.filter(category=self.scope_obj)
        else:
            filter_config_queryset = filter_config_queryset.filter(section=self.scope_obj)
        for config in filter_config_queryset:
            config_lookup[config.characteristic_definition_id] = config

        quick_filter_recommendations = []
        total_products = len(product_ids)
        for definition in self._scope_definitions():
            config = config_lookup.get(definition.pk)
            if config is not None and config.is_quick_filter:
                continue
            metrics = self._definition_value_metrics(definition, product_ids=product_ids, total_products=total_products)
            distinct_value_count = metrics['distinct_value_count']
            coverage_ratio = metrics['coverage_ratio']
            singleton_ratio = metrics['singleton_ratio']
            is_recommended = (
                definition.is_active
                and definition.is_filterable
                and 2 <= distinct_value_count <= 6
                and coverage_ratio >= 0.6
                and singleton_ratio <= 0.5
            )
            if not is_recommended:
                continue
            quick_filter_recommendations.append(
                {
                    'definition': definition,
                    'selection_value': str(definition.pk),
                    'distinct_value_count': distinct_value_count,
                    'coverage_ratio_percent': round(coverage_ratio * 100),
                    'singleton_ratio_percent': round(singleton_ratio * 100),
                    'has_config': config is not None,
                    'reason': (
                        f'{distinct_value_count} значений, покрытие {round(coverage_ratio * 100)}%, '
                        f'единичных значений {round(singleton_ratio * 100)}%.'
                    ),
                }
            )
        quick_filter_recommendations.sort(key=lambda item: (item['definition'].sort_order, item['definition'].name.lower()))

        return {
            'scope_label': self.scope_label,
            'scope_type': self.scope_type,
            'product_count': len(product_ids),
            'source_name_count': len(source_name_counts),
            'missing_definitions': missing_definitions,
            'source_alias_suggestions': source_alias_suggestions,
            'safe_value_alias_suggestions': safe_value_alias_suggestions,
            'missing_configs': missing_configs,
            'quick_filter_recommendations': quick_filter_recommendations,
        }

    def _ensure_scope_filter_config(self, definition: CharacteristicDefinition):
        scope_kwargs = {'category': self.scope_obj, 'section': None} if self.scope_type == 'category' else {
            'category': None,
            'section': self.scope_obj,
        }
        config, created = FilterConfig.objects.get_or_create(
            characteristic_definition=definition,
            **scope_kwargs,
            defaults=_build_filter_config_defaults(definition),
        )
        return config, created

    @transaction.atomic
    def apply(
        self,
        *,
        selected_missing_definitions: list[str] | None = None,
        selected_source_aliases: list[str] | None = None,
        selected_value_aliases: list[str] | None = None,
        apply_missing_configs: bool = False,
        selected_quick_filters: list[str] | None = None,
    ) -> dict:
        selected_missing_definitions = selected_missing_definitions or []
        selected_source_aliases = selected_source_aliases or []
        selected_value_aliases = selected_value_aliases or []
        selected_quick_filters = selected_quick_filters or []

        result = {
            'created_definitions': 0,
            'created_source_aliases': 0,
            'created_value_aliases': 0,
            'created_filter_configs': 0,
            'enabled_quick_filters': 0,
        }

        scope_source_names = set(self._scope_source_name_counts())
        definitions = list(
            CharacteristicDefinition.objects
            .prefetch_related('source_aliases')
            .order_by('sort_order', 'name', 'code')
        )
        covered_by_source = get_covered_definition_sources(definitions)
        for source_name in selected_missing_definitions:
            cleaned_source_name = (source_name or '').strip()
            if not cleaned_source_name or cleaned_source_name not in scope_source_names:
                continue
            if cleaned_source_name in covered_by_source:
                continue
            definition = CharacteristicDefinition.objects.create(
                code=generate_unique_characteristic_code(cleaned_source_name),
                name=cleaned_source_name,
                source_name=cleaned_source_name,
                is_filterable=True,
                is_active=True,
                sort_order=0,
            )
            covered_by_source[cleaned_source_name] = definition
            result['created_definitions'] += 1

        source_aliases_by_definition: dict[int, list[str]] = defaultdict(list)
        for selection in selected_source_aliases:
            definition_id, raw_source_name = decode_source_alias_selection(selection)
            if definition_id is None or not raw_source_name:
                continue
            if raw_source_name not in scope_source_names:
                continue
            owner = covered_by_source.get(raw_source_name)
            if owner is not None and owner.pk != definition_id:
                continue
            source_aliases_by_definition[definition_id].append(raw_source_name)

        for definition_id, raw_source_names in source_aliases_by_definition.items():
            try:
                definition = CharacteristicDefinition.objects.get(pk=definition_id)
            except CharacteristicDefinition.DoesNotExist:
                continue
            alias_result = create_source_aliases_from_suggestions(
                definition,
                selected_source_names=raw_source_names,
            )
            result['created_source_aliases'] += alias_result['created']

        value_aliases_by_definition: dict[int, list[str]] = defaultdict(list)
        for selection in selected_value_aliases:
            definition_id, normalized_key = decode_value_alias_selection(selection)
            if definition_id is None or not normalized_key:
                continue
            value_aliases_by_definition[definition_id].append(normalized_key)

        for definition_id, normalized_keys in value_aliases_by_definition.items():
            try:
                definition = CharacteristicDefinition.objects.get(pk=definition_id)
            except CharacteristicDefinition.DoesNotExist:
                continue
            alias_result = create_aliases_from_suggestions(
                definition,
                selected_normalized_keys=normalized_keys,
                safe_only=True,
            )
            result['created_value_aliases'] += alias_result['created']

        if apply_missing_configs:
            config_results = bootstrap_filter_configs(self.scope_type, self.scope_obj, apply=True, skip_existing=True)
            result['created_filter_configs'] = sum(1 for item in config_results if item['action'] == 'created')

        for definition_id in selected_quick_filters:
            if not str(definition_id).isdigit():
                continue
            try:
                definition = CharacteristicDefinition.objects.get(pk=int(definition_id))
            except CharacteristicDefinition.DoesNotExist:
                continue
            config, _created = self._ensure_scope_filter_config(definition)
            if config.is_quick_filter:
                continue
            config.is_quick_filter = True
            config.save(update_fields=['is_quick_filter'])
            result['enabled_quick_filters'] += 1

        return result
