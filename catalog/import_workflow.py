from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from .importers import CatalogDataImporter, CatalogImportError
from .models import (
    CatalogImportBatch,
    CatalogImportConflict,
    CatalogSection,
    Category,
    City,
    PickupPoint,
    Product,
    ProductBundle,
    ProductBundleItem,
    ProductCharacteristic,
    ProductContentBlock,
    ProductStock,
    ProductTag,
    ProductVariant,
    ProductVariantCharacteristic,
    ProductVideo,
    _parse_rutube_video_url,
)


DIRECT_TARGET_PK_KEY = 'target_pk'


def is_direct_target_reference(value: Any) -> bool:
    return isinstance(value, dict) and DIRECT_TARGET_PK_KEY in value


def make_direct_target_reference(pk: int) -> dict[str, int]:
    return {DIRECT_TARGET_PK_KEY: int(pk)}


def serialize_for_json(value: Any) -> Any:
    if hasattr(value, 'pk'):
        return value.pk
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [serialize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [serialize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize_for_json(item) for key, item in value.items()}
    return value


@dataclass
class AnalysisBinding:
    collection_name: str
    source_index: int
    source_id: Any
    model_class: type
    item_label: str
    existing_obj: Any | None = None
    item_status: str = ''
    planned_create: bool = False
    stable: bool = False

    @property
    def source_key(self) -> str:
        return f'{self.collection_name}:{self.source_index}'


@dataclass
class AnalysisDependency:
    field_name: str
    source_value: Any
    binding: AnalysisBinding | None = None
    direct_target_obj: Any | None = None
    available_model: type | None = None
    message: str = ''


@dataclass
class AnalysisItem:
    collection_name: str
    source_index: int
    source_id: str
    item_label: str
    status: str
    operation: str
    source_snapshot: dict[str, Any]
    target_snapshot: dict[str, Any]
    field_conflicts: dict[str, Any]
    resolutions: dict[str, Any]
    target_model: str = ''
    target_pk: int | None = None
    update_values: dict[str, Any] = field(default_factory=dict)
    create_kwargs: dict[str, Any] = field(default_factory=dict)
    dependency_fields: dict[str, AnalysisDependency] = field(default_factory=dict)
    has_conflict_history: bool = False
    conflict_kind: str = ''
    messages: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f'{self.collection_name}:{self.source_index}'

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            'key': self.key,
            'collection_name': self.collection_name,
            'source_index': self.source_index,
            'source_id': self.source_id,
            'item_label': self.item_label,
            'status': self.status,
            'operation': self.operation,
            'target_model': self.target_model,
            'target_pk': self.target_pk,
            'messages': self.messages,
            'has_conflict_history': self.has_conflict_history,
        }


@dataclass
class AnalysisResult:
    items: list[AnalysisItem]
    warnings: list[str]
    duplicate_conflicts: dict[str, dict[str, Any]]
    bindings: dict[str, dict[Any, AnalysisBinding]]

    @property
    def item_map(self) -> dict[str, AnalysisItem]:
        return {item.key: item for item in self.items}

    def summary(self) -> dict[str, Any]:
        groups = {
            'ready': [],
            'noop': [],
            'pending_conflicts': [],
            'blocking_issues': [],
        }
        for item in self.items:
            if item.status in {'ready_create', 'ready_update'}:
                groups['ready'].append(item.to_summary_dict())
            elif item.status == 'noop':
                groups['noop'].append(item.to_summary_dict())
            elif item.status == 'pending_conflict':
                groups['pending_conflicts'].append(item.to_summary_dict())
            elif item.status == 'blocking':
                groups['blocking_issues'].append(item.to_summary_dict())
        return {
            'counts': {key: len(value) for key, value in groups.items()},
            **groups,
            'warnings': self.warnings,
        }


class CatalogImportAnalyzer:
    STATUS_READY_CREATE = 'ready_create'
    STATUS_READY_UPDATE = 'ready_update'
    STATUS_NOOP = 'noop'
    STATUS_PENDING_CONFLICT = 'pending_conflict'
    STATUS_BLOCKING = 'blocking'

    def __init__(self, payload: dict[str, Any], *, conflict_rows: list[CatalogImportConflict] | None = None):
        self.payload = payload if isinstance(payload, dict) else {}
        self.models_payload = self._extract_models_payload(self.payload)
        self.conflict_rows = conflict_rows or []
        self.warnings: list[str] = []
        self.items: list[AnalysisItem] = []
        self.conflict_map = {
            f'{conflict.collection_name}:{conflict.source_index}': conflict
            for conflict in self.conflict_rows
        }
        self.bindings: dict[str, dict[Any, AnalysisBinding]] = {
            'catalog_sections': {},
            'categories': {},
            'product_tags': {},
            'products': {},
            'product_variants': {},
            'product_bundles': {},
            'cities': {},
            'pickup_points': {},
        }
        self.duplicate_conflicts = self._build_duplicate_conflicts()

    def analyze(self) -> AnalysisResult:
        self._analyze_sections()
        self._analyze_categories()
        self._analyze_tags()
        self._analyze_products()
        self._analyze_variants()
        self._analyze_product_characteristics()
        self._analyze_variant_characteristics()
        self._analyze_product_images()
        self._analyze_product_videos()
        self._analyze_content_blocks()
        self._analyze_bundles()
        self._analyze_bundle_items()
        self._analyze_cities()
        self._analyze_pickup_points()
        self._analyze_stocks()
        return AnalysisResult(
            items=self.items,
            warnings=self.warnings,
            duplicate_conflicts=self.duplicate_conflicts,
            bindings=self.bindings,
        )

    def _extract_models_payload(self, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        models_payload = payload.get('models')
        if not isinstance(models_payload, dict):
            raise CatalogImportError('JSON должен содержать ключ "models" с объектом коллекций.')

        normalized: dict[str, list[dict[str, Any]]] = {}
        for collection_name, items in models_payload.items():
            if not isinstance(items, list):
                raise CatalogImportError(f'Коллекция "{collection_name}" должна быть массивом.')
            normalized[collection_name] = items
        return normalized

    def _collection(self, name: str) -> list[dict[str, Any]]:
        return self.models_payload.get(name, [])

    def _build_duplicate_conflicts(self) -> dict[str, dict[str, Any]]:
        duplicates: dict[str, dict[str, Any]] = {}
        configs = (
            ('catalog_sections', lambda item: ('slug', (item.get('slug') or '').strip())),
            ('categories', lambda item: ('slug', (item.get('slug') or '').strip())),
            ('product_tags', lambda item: ('slug', (item.get('slug') or '').strip())),
            ('products', lambda item: ('slug', (item.get('slug') or '').strip())),
            ('cities', lambda item: ('slug', (item.get('slug') or '').strip())),
            (
                'product_variants',
                lambda item: (
                    self._normalize_reference_key(item.get('product_id')),
                    'sku' if (item.get('sku') or '').strip() else 'name',
                    (item.get('sku') or item.get('name') or '').strip(),
                ),
            ),
            (
                'pickup_points',
                lambda item: (
                    self._normalize_reference_key(item.get('city_id')),
                    (item.get('name') or '').strip(),
                ),
            ),
        )
        for collection_name, key_builder in configs:
            seen: dict[tuple[Any, ...], str] = {}
            for index, item in enumerate(self._collection(collection_name)):
                key = key_builder(item)
                item_key = f'{collection_name}:{index}'
                if any(part in ('', None) for part in key):
                    continue
                if key in seen:
                    previous_key = seen[key]
                    message = f'Внутри файла есть дубликат natural key {key!r}.'
                    duplicates[item_key] = {
                        'field_conflicts': {
                            '__duplicate__': {
                                'label': 'Дубликат внутри файла',
                                'field_type': 'info',
                                'current_value': '',
                                'incoming_value': message,
                                'options': [],
                            },
                        },
                        'message': message,
                    }
                    duplicates[previous_key] = {
                        'field_conflicts': {
                            '__duplicate__': {
                                'label': 'Дубликат внутри файла',
                                'field_type': 'info',
                                'current_value': '',
                                'incoming_value': message,
                                'options': [],
                            },
                        },
                        'message': message,
                    }
                else:
                    seen[key] = item_key
        return duplicates

    def _normalize_reference_key(self, value: Any) -> Any:
        if is_direct_target_reference(value):
            return f'pk:{value[DIRECT_TARGET_PK_KEY]}'
        return value

    def _string_source_id(self, item: dict[str, Any], index: int) -> str:
        if item.get('id') is not None:
            return str(item.get('id'))
        return str(index)

    def _existing_conflict(self, collection_name: str, index: int) -> CatalogImportConflict | None:
        return self.conflict_map.get(f'{collection_name}:{index}')

    def _register_item(
        self,
        *,
        collection_name: str,
        index: int,
        item: dict[str, Any],
        status: str,
        operation: str,
        source_snapshot: dict[str, Any],
        target_snapshot: dict[str, Any],
        field_conflicts: dict[str, Any],
        resolutions: dict[str, Any],
        target_obj: Any | None = None,
        update_values: dict[str, Any] | None = None,
        create_kwargs: dict[str, Any] | None = None,
        dependency_fields: dict[str, AnalysisDependency] | None = None,
        conflict_kind: str = '',
        messages: list[str] | None = None,
    ) -> AnalysisItem:
        existing_conflict = self._existing_conflict(collection_name, index)
        item_obj = AnalysisItem(
            collection_name=collection_name,
            source_index=index,
            source_id=self._string_source_id(item, index),
            item_label=self._item_label(collection_name, item, source_snapshot),
            status=status,
            operation=operation,
            source_snapshot=source_snapshot,
            target_snapshot=target_snapshot,
            field_conflicts=field_conflicts,
            resolutions=resolutions,
            target_model=getattr(getattr(target_obj, '_meta', None), 'label_lower', ''),
            target_pk=getattr(target_obj, 'pk', None),
            update_values=update_values or {},
            create_kwargs=create_kwargs or {},
            dependency_fields=dependency_fields or {},
            has_conflict_history=bool(existing_conflict or field_conflicts),
            conflict_kind=conflict_kind,
            messages=messages or [],
        )
        self.items.append(item_obj)
        return item_obj

    def _item_label(self, collection_name: str, item: dict[str, Any], source_snapshot: dict[str, Any]) -> str:
        for candidate in ('name', 'slug', 'title', 'rutube_url'):
            value = source_snapshot.get(candidate) or item.get(candidate)
            if value not in (None, ''):
                return str(value)
        return f'{collection_name}[{item.get("id", "?")}]'

    def _sync_binding(
        self,
        collection_name: str,
        item: dict[str, Any],
        index: int,
        model_class: type,
        item_label: str,
        *,
        existing_obj: Any | None,
        status: str,
        planned_create: bool,
        stable: bool,
    ) -> None:
        source_id = item.get('id')
        if source_id is None:
            return
        self.bindings[collection_name][source_id] = AnalysisBinding(
            collection_name=collection_name,
            source_index=index,
            source_id=source_id,
            model_class=model_class,
            item_label=item_label,
            existing_obj=existing_obj,
            item_status=status,
            planned_create=planned_create,
            stable=stable,
        )

    def _manual_value_for_field(self, resolutions: dict[str, Any], field_name: str) -> Any:
        resolution = resolutions.get(field_name) or {}
        if resolution.get('mode') == 'manual':
            return resolution.get('value')
        return None

    def _field_resolution_mode(self, resolutions: dict[str, Any], field_name: str) -> str:
        resolution = resolutions.get(field_name) or {}
        return resolution.get('mode') or ''

    def _field_equal(self, current: Any, incoming: Any, *, field_type: str) -> bool:
        current_normalized = serialize_for_json(current)
        incoming_normalized = serialize_for_json(incoming)
        if field_type == 'multiselect':
            current_items = [serialize_for_json(item) for item in (current_normalized or [])]
            incoming_items = [serialize_for_json(item) for item in (incoming_normalized or [])]
            current_values = sorted(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in current_items)
            incoming_values = sorted(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in incoming_items)
            return current_values == incoming_values
        return current_normalized == incoming_normalized

    def _parse_manual_value(self, field_meta: dict[str, Any], value: Any) -> Any:
        field_type = field_meta.get('field_type')
        if field_type in {'text', 'slug', 'choice', 'url', 'rutube'}:
            return '' if value is None else str(value)
        if field_type == 'textarea':
            return '' if value is None else str(value)
        if field_type == 'int':
            if value in (None, ''):
                return 0
            return int(value)
        if field_type == 'decimal':
            if value in (None, ''):
                return None
            Decimal(str(value))
            return str(value)
        if field_type == 'bool':
            if isinstance(value, bool):
                return value
            return str(value).lower() in {'1', 'true', 'on', 'yes'}
        if field_type == 'fk':
            if value in (None, ''):
                return None
            return make_direct_target_reference(int(value))
        if field_type == 'multiselect':
            raw_values = value if isinstance(value, list) else []
            return [make_direct_target_reference(int(item)) for item in raw_values if item not in (None, '')]
        return value

    def _resolve_field_conflicts(
        self,
        *,
        current_values: dict[str, Any],
        incoming_values: dict[str, Any],
        field_meta: dict[str, dict[str, Any]],
        resolutions: dict[str, Any],
        default_resolution_mode: str = '',
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        effective_updates: dict[str, Any] = {}
        field_conflicts: dict[str, Any] = {}
        unresolved_fields: list[str] = []

        for field_name, incoming_value in incoming_values.items():
            meta = field_meta.get(field_name, {'label': field_name, 'field_type': 'text', 'options': []})
            current_value = current_values.get(field_name)
            if default_resolution_mode and field_name not in current_values:
                effective_updates[field_name] = incoming_value
                continue
            if self._field_equal(current_value, incoming_value, field_type=meta.get('field_type', 'text')):
                effective_updates[field_name] = incoming_value
                continue

            resolution_mode = self._field_resolution_mode(resolutions, field_name) or default_resolution_mode
            chosen_value = incoming_value
            if resolution_mode == 'keep_current':
                chosen_value = current_value
            elif resolution_mode == 'manual':
                try:
                    chosen_value = self._parse_manual_value(meta, self._manual_value_for_field(resolutions, field_name))
                except (TypeError, ValueError, InvalidOperation) as exc:
                    unresolved_fields.append(field_name)
                    field_conflicts[field_name] = {
                        **meta,
                        'current_value': serialize_for_json(current_value),
                        'incoming_value': serialize_for_json(incoming_value),
                        'resolution_mode': resolution_mode,
                        'resolution_error': str(exc),
                    }
                    continue
            elif resolution_mode == 'take_incoming':
                chosen_value = incoming_value
            else:
                unresolved_fields.append(field_name)

            field_conflicts[field_name] = {
                **meta,
                'current_value': serialize_for_json(current_value),
                'incoming_value': serialize_for_json(incoming_value),
                'chosen_value': serialize_for_json(chosen_value),
                'resolution_mode': resolution_mode,
            }
            effective_updates[field_name] = chosen_value

        return effective_updates, field_conflicts, unresolved_fields

    def _inject_identifier_conflict(
        self,
        *,
        field_name: str,
        field_type: str,
        label: str,
        current_value: Any,
        incoming_value: Any,
        resolutions: dict[str, Any],
        effective_updates: dict[str, Any],
        field_conflicts: dict[str, Any],
        unresolved_fields: list[str],
    ) -> None:
        resolution_mode = self._field_resolution_mode(resolutions, field_name) or 'take_incoming'
        chosen_value = incoming_value
        if resolution_mode == 'keep_current':
            chosen_value = current_value
        elif resolution_mode == 'manual':
            try:
                chosen_value = self._parse_manual_value(
                    self._metadata(label, field_type),
                    self._manual_value_for_field(resolutions, field_name),
                )
            except (TypeError, ValueError, InvalidOperation) as exc:
                unresolved_fields.append(field_name)
                field_conflicts[field_name] = {
                    **self._metadata(label, field_type),
                    'current_value': serialize_for_json(current_value),
                    'incoming_value': serialize_for_json(incoming_value),
                    'resolution_mode': resolution_mode,
                    'resolution_error': str(exc),
                }
                return

        effective_updates[field_name] = chosen_value
        field_conflicts[field_name] = {
            **self._metadata(label, field_type),
            'current_value': serialize_for_json(current_value),
            'incoming_value': serialize_for_json(incoming_value),
            'chosen_value': serialize_for_json(chosen_value),
            'resolution_mode': resolution_mode,
        }

    def _direct_or_bound_object(
        self,
        *,
        raw_value: Any,
        source_map: dict[Any, AnalysisBinding],
        model_class: type,
        field_name: str,
        conflict_meta: dict[str, Any],
    ) -> tuple[Any | AnalysisBinding | None, AnalysisDependency | None]:
        if raw_value in (None, ''):
            return None, None
        if is_direct_target_reference(raw_value):
            target_pk = raw_value.get(DIRECT_TARGET_PK_KEY)
            target_obj = model_class.objects.filter(pk=target_pk).first()
            if target_obj:
                return target_obj, AnalysisDependency(
                    field_name=field_name,
                    source_value=raw_value,
                    direct_target_obj=target_obj,
                )
            return None, AnalysisDependency(
                field_name=field_name,
                source_value=raw_value,
                available_model=model_class,
                message=f'Целевая запись для поля {field_name!r} не найдена.',
            )
        binding = source_map.get(raw_value)
        if binding is None:
            return None, AnalysisDependency(
                field_name=field_name,
                source_value=raw_value,
                available_model=model_class,
                message=f'Источник для поля {field_name!r} не найден в payload.',
            )
        if binding.existing_obj is not None:
            return binding.existing_obj, AnalysisDependency(
                field_name=field_name,
                source_value=raw_value,
                binding=binding,
                direct_target_obj=binding.existing_obj,
            )
        if binding.stable and binding.planned_create:
            return binding, AnalysisDependency(
                field_name=field_name,
                source_value=raw_value,
                binding=binding,
            )
        return None, AnalysisDependency(
            field_name=field_name,
            source_value=raw_value,
            binding=binding,
            available_model=model_class,
            message=f'Зависимость {binding.item_label!r} ещё не готова к применению.',
        )

    def _model_choices(self, model_class, *, include_blank: bool = False) -> list[dict[str, Any]]:
        queryset = model_class.objects.order_by('pk')
        options = [{'value': str(obj.pk), 'label': str(obj)} for obj in queryset]
        if include_blank:
            options = [{'value': '', 'label': 'Пусто'}] + options
        return options

    def _metadata(self, label: str, field_type: str, *, options: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            'label': label,
            'field_type': field_type,
            'options': options or [],
        }

    def _conflict_from_dependencies(
        self,
        *,
        label: str,
        dependencies: dict[str, AnalysisDependency],
        resolutions: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        field_conflicts: dict[str, Any] = {}
        unresolved_fields: list[str] = []
        for field_name, dependency in dependencies.items():
            if dependency is None or not dependency.message:
                continue
            field_type = 'multiselect' if field_name == 'tag_ids' else 'fk'
            field_conflicts[field_name] = {
                'label': label,
                'field_type': field_type,
                'options': self._model_choices(dependency.available_model, include_blank=True) if dependency.available_model else [],
                'current_value': '',
                'incoming_value': serialize_for_json(dependency.source_value),
                'resolution_mode': self._field_resolution_mode(resolutions, field_name),
                'resolution_error': dependency.message,
            }
            unresolved_fields.append(field_name)
        return field_conflicts, unresolved_fields

    def _status_from_conflicts(
        self,
        *,
        existing_obj: Any | None,
        unresolved_fields: list[str],
        field_conflicts: dict[str, Any],
        effective_updates: dict[str, Any],
        current_values: dict[str, Any],
    ) -> tuple[str, str]:
        if unresolved_fields:
            return self.STATUS_PENDING_CONFLICT, 'conflict'
        if existing_obj is None:
            return self.STATUS_READY_CREATE, 'create'
        if any(
            not self._field_equal(current_values.get(field_name), value, field_type=field_conflicts.get(field_name, {}).get('field_type', 'text'))
            for field_name, value in effective_updates.items()
        ):
            return self.STATUS_READY_UPDATE, 'update'
        if field_conflicts:
            return self.STATUS_NOOP, 'noop'
        return self.STATUS_NOOP, 'noop'

    def _add_duplicate_item(self, collection_name: str, index: int, item: dict[str, Any]) -> bool:
        duplicate = self.duplicate_conflicts.get(f'{collection_name}:{index}')
        if not duplicate:
            return False
        resolutions = self._existing_conflict(collection_name, index).resolutions if self._existing_conflict(collection_name, index) else {}
        self._register_item(
            collection_name=collection_name,
            index=index,
            item=item,
            status=self.STATUS_PENDING_CONFLICT,
            operation='conflict',
            source_snapshot=item,
            target_snapshot={},
            field_conflicts=duplicate['field_conflicts'],
            resolutions=resolutions,
            conflict_kind='duplicate_in_payload',
            messages=[duplicate['message']],
        )
        return True

    def _analyze_simple_collection(
        self,
        *,
        collection_name: str,
        model_class: type,
        identity_field: str,
        incoming_fields_builder,
        field_meta_builder,
        existing_lookup_builder,
        binding_collection_name: str | None = None,
    ) -> None:
        for index, item in enumerate(self._collection(collection_name)):
            if self._add_duplicate_item(collection_name, index, item):
                self._sync_binding(
                    binding_collection_name or collection_name,
                    item,
                    index,
                    model_class,
                    self._item_label(collection_name, item, item),
                    existing_obj=None,
                    status=self.STATUS_PENDING_CONFLICT,
                    planned_create=False,
                    stable=False,
                )
                continue

            resolutions = deepcopy(self._existing_conflict(collection_name, index).resolutions) if self._existing_conflict(collection_name, index) else {}
            source_snapshot = deepcopy(item)
            identity_value = source_snapshot.get(identity_field)
            if identity_value in (None, ''):
                self._register_item(
                    collection_name=collection_name,
                    index=index,
                    item=item,
                    status=self.STATUS_PENDING_CONFLICT,
                    operation='conflict',
                    source_snapshot=source_snapshot,
                    target_snapshot={},
                    field_conflicts={
                        identity_field: {
                            **self._metadata(identity_field, 'text'),
                            'current_value': '',
                            'incoming_value': '',
                            'resolution_error': f'Обязательно поле {identity_field!r}.',
                        },
                    },
                    resolutions=resolutions,
                    conflict_kind='missing_identity',
                    messages=[f'Не заполнено поле {identity_field!r}.'],
                )
                self._sync_binding(
                    binding_collection_name or collection_name,
                    item,
                    index,
                    model_class,
                    self._item_label(collection_name, item, source_snapshot),
                    existing_obj=None,
                    status=self.STATUS_PENDING_CONFLICT,
                    planned_create=False,
                    stable=False,
                )
                continue

            existing_obj = existing_lookup_builder(source_snapshot)
            current_values = incoming_fields_builder(existing_obj) if existing_obj else {}
            incoming_values = incoming_fields_builder(source_snapshot)
            field_meta = field_meta_builder()
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            if existing_obj is not None and field_conflicts:
                self._inject_identifier_conflict(
                    field_name=identity_field,
                    field_type='slug' if identity_field in {'slug', 'sku'} else 'text',
                    label=identity_field.upper() if identity_field == 'sku' else identity_field,
                    current_value=getattr(existing_obj, identity_field),
                    incoming_value=identity_value,
                    resolutions=resolutions,
                    effective_updates=effective_updates,
                    field_conflicts=field_conflicts,
                    unresolved_fields=unresolved,
                )
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            item_obj = self._register_item(
                collection_name=collection_name,
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={identity_field: identity_value},
                conflict_kind='field_mismatch' if field_conflicts else '',
            )
            self._sync_binding(
                binding_collection_name or collection_name,
                item,
                index,
                model_class,
                item_obj.item_label,
                existing_obj=existing_obj,
                status=status,
                planned_create=existing_obj is None and status == self.STATUS_READY_CREATE,
                stable=existing_obj is not None or status == self.STATUS_READY_CREATE,
            )

    def _analyze_sections(self) -> None:
        self._analyze_simple_collection(
            collection_name='catalog_sections',
            model_class=CatalogSection,
            identity_field='slug',
            incoming_fields_builder=lambda source: {
                'name': source.get('name', '') if isinstance(source, dict) else source.name,
                'order': int(source.get('order') or 0) if isinstance(source, dict) else source.order,
                'icon': source.get('icon', '') if isinstance(source, dict) else source.icon,
            },
            field_meta_builder=lambda: {
                'name': self._metadata('Название', 'text'),
                'order': self._metadata('Порядок', 'int'),
                'icon': self._metadata('Иконка', 'textarea'),
            },
            existing_lookup_builder=lambda source: CatalogSection.objects.filter(slug=source.get('slug')).first(),
        )

    def _analyze_categories(self) -> None:
        for index, item in enumerate(self._collection('categories')):
            if self._add_duplicate_item('categories', index, item):
                self._sync_binding('categories', item, index, Category, self._item_label('categories', item, item), existing_obj=None, status=self.STATUS_PENDING_CONFLICT, planned_create=False, stable=False)
                continue

            resolutions = deepcopy(self._existing_conflict('categories', index).resolutions) if self._existing_conflict('categories', index) else {}
            source_snapshot = deepcopy(item)
            existing_obj = Category.objects.filter(slug=source_snapshot.get('slug')).first() if source_snapshot.get('slug') else None
            section_obj, dependency = self._direct_or_bound_object(
                raw_value=source_snapshot.get('section_id'),
                source_map=self.bindings['catalog_sections'],
                model_class=CatalogSection,
                field_name='section_id',
                conflict_meta={},
            )
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Раздел',
                dependencies={'section_id': dependency} if dependency else {},
                resolutions=resolutions,
            )
            incoming_values = {
                'name': source_snapshot.get('name', ''),
                'section': section_obj,
                'icon': source_snapshot.get('icon', ''),
                'tile_size': source_snapshot.get('tile_size') or 'small',
                'is_bundles_category': bool(source_snapshot.get('is_bundles_category')) if 'is_bundles_category' in source_snapshot else False,
            }
            current_values = {
                'name': existing_obj.name,
                'section': existing_obj.section,
                'icon': existing_obj.icon,
                'tile_size': existing_obj.tile_size,
                'is_bundles_category': existing_obj.is_bundles_category,
            } if existing_obj else {}
            field_meta = {
                'name': self._metadata('Название', 'text'),
                'section': self._metadata('Раздел', 'fk', options=self._model_choices(CatalogSection, include_blank=True)),
                'icon': self._metadata('Иконка', 'textarea'),
                'tile_size': self._metadata('Размер плитки', 'choice', options=[
                    {'value': 'small', 'label': 'small'},
                    {'value': 'medium', 'label': 'medium'},
                    {'value': 'large', 'label': 'large'},
                    {'value': 'tall', 'label': 'tall'},
                ]),
                'is_bundles_category': self._metadata('Категория наборов', 'bool'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            item_obj = self._register_item(
                collection_name='categories',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={'slug': source_snapshot.get('slug')},
                dependency_fields={'section_id': dependency} if dependency else {},
                conflict_kind='field_mismatch' if field_conflicts else '',
            )
            self._sync_binding(
                'categories',
                item,
                index,
                Category,
                item_obj.item_label,
                existing_obj=existing_obj,
                status=status,
                planned_create=existing_obj is None and status == self.STATUS_READY_CREATE,
                stable=existing_obj is not None or status == self.STATUS_READY_CREATE,
            )

    def _analyze_tags(self) -> None:
        self._analyze_simple_collection(
            collection_name='product_tags',
            model_class=ProductTag,
            identity_field='slug',
            incoming_fields_builder=lambda source: {
                'name': source.get('name', '') if isinstance(source, dict) else source.name,
                'order': int(source.get('order') or 0) if isinstance(source, dict) else source.order,
            },
            field_meta_builder=lambda: {
                'name': self._metadata('Название', 'text'),
                'order': self._metadata('Порядок', 'int'),
            },
            existing_lookup_builder=lambda source: ProductTag.objects.filter(slug=source.get('slug')).first(),
        )

    def _resolve_tag_list(self, raw_values: list[Any]) -> tuple[list[Any], AnalysisDependency | None]:
        resolved_tags: list[Any] = []
        for raw_value in raw_values:
            if is_direct_target_reference(raw_value):
                target_obj = ProductTag.objects.filter(pk=raw_value.get(DIRECT_TARGET_PK_KEY)).first()
                if not target_obj:
                    return [], AnalysisDependency(
                        field_name='tag_ids',
                        source_value=raw_values,
                        available_model=ProductTag,
                        message='Один из выбранных тегов не найден.',
                    )
                resolved_tags.append(target_obj)
            else:
                binding = self.bindings['product_tags'].get(raw_value)
                if binding is None:
                    return [], AnalysisDependency(
                        field_name='tag_ids',
                        source_value=raw_values,
                        available_model=ProductTag,
                        message='Один из тегов не найден в payload.',
                    )
                if binding.existing_obj is not None:
                    resolved_tags.append(binding.existing_obj)
                elif binding.stable and binding.planned_create:
                    resolved_tags.append(binding)
                else:
                    return [], AnalysisDependency(
                        field_name='tag_ids',
                        source_value=raw_values,
                        available_model=ProductTag,
                        message='Один из тегов ещё не готов к применению.',
                    )
        return resolved_tags, None

    def _analyze_products(self) -> None:
        for index, item in enumerate(self._collection('products')):
            if self._add_duplicate_item('products', index, item):
                self._sync_binding('products', item, index, Product, self._item_label('products', item, item), existing_obj=None, status=self.STATUS_PENDING_CONFLICT, planned_create=False, stable=False)
                continue

            resolutions = deepcopy(self._existing_conflict('products', index).resolutions) if self._existing_conflict('products', index) else {}
            source_snapshot = deepcopy(item)
            existing_obj = Product.objects.filter(slug=source_snapshot.get('slug')).first() if source_snapshot.get('slug') else None
            category_obj, category_dependency = self._direct_or_bound_object(
                raw_value=source_snapshot.get('category_id'),
                source_map=self.bindings['categories'],
                model_class=Category,
                field_name='category_id',
                conflict_meta={},
            )
            tag_values, tag_dependency = self._resolve_tag_list(source_snapshot.get('tag_ids', []))
            incoming_values = {
                'name': source_snapshot.get('name', ''),
                'sku': source_snapshot.get('sku', ''),
                'description': source_snapshot.get('description', ''),
                'price': source_snapshot.get('price', ''),
                'discount_percent': source_snapshot.get('discount_percent', '0.00'),
                'price_on_request': source_snapshot.get('price_on_request', ''),
                'is_active': bool(source_snapshot.get('is_active')) if 'is_active' in source_snapshot else True,
                'allow_order_on_request': bool(source_snapshot.get('allow_order_on_request')) if 'allow_order_on_request' in source_snapshot else True,
                'avito_url': source_snapshot.get('avito_url', ''),
                'ozon_url': source_snapshot.get('ozon_url', ''),
                'wildberries_url': source_snapshot.get('wildberries_url', ''),
                'option_label': source_snapshot.get('option_label', ''),
                'views_count': int(source_snapshot.get('views_count') or 0),
                'category': category_obj,
                'tag_ids': [
                    make_direct_target_reference(tag.pk) if hasattr(tag, 'pk') else {'source_key': tag.source_key}
                    for tag in tag_values
                ],
            }
            current_values = {
                'name': existing_obj.name,
                'sku': existing_obj.sku,
                'description': existing_obj.description,
                'price': serialize_for_json(existing_obj.price),
                'discount_percent': serialize_for_json(existing_obj.discount_percent),
                'price_on_request': serialize_for_json(existing_obj.price_on_request),
                'is_active': existing_obj.is_active,
                'allow_order_on_request': existing_obj.allow_order_on_request,
                'avito_url': existing_obj.avito_url,
                'ozon_url': existing_obj.ozon_url,
                'wildberries_url': existing_obj.wildberries_url,
                'option_label': existing_obj.option_label,
                'views_count': existing_obj.views_count,
                'category': existing_obj.category,
                'tag_ids': list(existing_obj.tags.order_by('id').values_list('id', flat=True)),
            } if existing_obj else {}
            field_meta = {
                'name': self._metadata('Название', 'text'),
                'sku': self._metadata('SKU', 'slug'),
                'description': self._metadata('Описание', 'textarea'),
                'price': self._metadata('Цена из наличия', 'decimal'),
                'discount_percent': self._metadata('Скидка, %', 'decimal'),
                'price_on_request': self._metadata('Цена под заказ', 'decimal'),
                'is_active': self._metadata('Активен', 'bool'),
                'allow_order_on_request': self._metadata('Под заказ', 'bool'),
                'avito_url': self._metadata('Avito URL', 'url'),
                'ozon_url': self._metadata('Ozon URL', 'url'),
                'wildberries_url': self._metadata('Wildberries URL', 'url'),
                'option_label': self._metadata('Подпись вариантов', 'text'),
                'views_count': self._metadata('Просмотры', 'int'),
                'category': self._metadata('Категория', 'fk', options=self._model_choices(Category)),
                'tag_ids': self._metadata('Теги', 'multiselect', options=self._model_choices(ProductTag)),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            dependencies = {}
            if category_dependency:
                dependencies['category'] = category_dependency
            if tag_dependency:
                dependencies['tag_ids'] = tag_dependency
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Связь',
                dependencies=dependencies,
                resolutions=resolutions,
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            if existing_obj is not None and field_conflicts:
                self._inject_identifier_conflict(
                    field_name='slug',
                    field_type='slug',
                    label='Slug',
                    current_value=existing_obj.slug,
                    incoming_value=source_snapshot.get('slug', ''),
                    resolutions=resolutions,
                    effective_updates=effective_updates,
                    field_conflicts=field_conflicts,
                    unresolved_fields=unresolved,
                )
            if 'image' in source_snapshot and source_snapshot.get('image'):
                self.warnings.append(
                    f'Поле products.image для элемента {source_snapshot.get("slug")!r} проигнорировано: импорт медиа отключён.'
                )
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            item_obj = self._register_item(
                collection_name='products',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={'slug': source_snapshot.get('slug')},
                dependency_fields=dependencies,
                conflict_kind='field_mismatch' if field_conflicts else '',
            )
            stable = bool(existing_obj) or status == self.STATUS_READY_CREATE
            self._sync_binding(
                'products',
                item,
                index,
                Product,
                item_obj.item_label,
                existing_obj=existing_obj,
                status=status,
                planned_create=existing_obj is None and status == self.STATUS_READY_CREATE,
                stable=stable,
            )

    def _resolve_product_binding(self, raw_value: Any, field_name: str):
        return self._direct_or_bound_object(
            raw_value=raw_value,
            source_map=self.bindings['products'],
            model_class=Product,
            field_name=field_name,
            conflict_meta={},
        )

    def _resolve_variant_binding(self, raw_value: Any, field_name: str):
        return self._direct_or_bound_object(
            raw_value=raw_value,
            source_map=self.bindings['product_variants'],
            model_class=ProductVariant,
            field_name=field_name,
            conflict_meta={},
        )

    def _resolve_bundle_binding(self, raw_value: Any, field_name: str):
        return self._direct_or_bound_object(
            raw_value=raw_value,
            source_map=self.bindings['product_bundles'],
            model_class=ProductBundle,
            field_name=field_name,
            conflict_meta={},
        )

    def _resolve_city_binding(self, raw_value: Any, field_name: str):
        return self._direct_or_bound_object(
            raw_value=raw_value,
            source_map=self.bindings['cities'],
            model_class=City,
            field_name=field_name,
            conflict_meta={},
        )

    def _resolve_pickup_binding(self, raw_value: Any, field_name: str):
        return self._direct_or_bound_object(
            raw_value=raw_value,
            source_map=self.bindings['pickup_points'],
            model_class=PickupPoint,
            field_name=field_name,
            conflict_meta={},
        )

    def _analyze_variants(self) -> None:
        for index, item in enumerate(self._collection('product_variants')):
            if self._add_duplicate_item('product_variants', index, item):
                self._sync_binding('product_variants', item, index, ProductVariant, self._item_label('product_variants', item, item), existing_obj=None, status=self.STATUS_PENDING_CONFLICT, planned_create=False, stable=False)
                continue

            resolutions = deepcopy(self._existing_conflict('product_variants', index).resolutions) if self._existing_conflict('product_variants', index) else {}
            source_snapshot = deepcopy(item)
            product_obj, product_dependency = self._resolve_product_binding(source_snapshot.get('product_id'), 'product_id')
            dependency_fields = {'product': product_dependency} if product_dependency else {}
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Товар',
                dependencies={'product_id': product_dependency} if product_dependency else {},
                resolutions=resolutions,
            )
            existing_obj = None
            if isinstance(product_obj, Product):
                sku = (source_snapshot.get('sku') or '').strip()
                if sku:
                    existing_obj = ProductVariant.objects.filter(product=product_obj, sku=sku).first()
                else:
                    existing_obj = ProductVariant.objects.filter(
                        product=product_obj,
                        sku='',
                        name=source_snapshot.get('name', ''),
                    ).first()
            incoming_values = {
                'name': source_snapshot.get('name', ''),
                'sku': source_snapshot.get('sku', ''),
                'order': int(source_snapshot.get('order') or 0),
                'price_override': source_snapshot.get('price_override', ''),
                'price_on_request_override': source_snapshot.get('price_on_request_override', ''),
            }
            current_values = {
                'name': existing_obj.name,
                'sku': existing_obj.sku,
                'order': existing_obj.order,
                'price_override': serialize_for_json(existing_obj.price_override),
                'price_on_request_override': serialize_for_json(existing_obj.price_on_request_override),
            } if existing_obj else {}
            field_meta = {
                'name': self._metadata('Название', 'text'),
                'sku': self._metadata('SKU', 'slug'),
                'order': self._metadata('Порядок', 'int'),
                'price_override': self._metadata('Цена из наличия', 'decimal'),
                'price_on_request_override': self._metadata('Цена под заказ', 'decimal'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            create_kwargs = {'product': product_obj}
            if (source_snapshot.get('sku') or '').strip():
                create_kwargs['sku'] = source_snapshot.get('sku') or ''
            item_obj = self._register_item(
                collection_name='product_variants',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs=create_kwargs,
                dependency_fields=dependency_fields,
                conflict_kind='field_mismatch' if field_conflicts else '',
            )
            stable = isinstance(product_obj, Product) or status == self.STATUS_READY_CREATE
            self._sync_binding(
                'product_variants',
                item,
                index,
                ProductVariant,
                item_obj.item_label,
                existing_obj=existing_obj,
                status=status,
                planned_create=existing_obj is None and status == self.STATUS_READY_CREATE,
                stable=stable,
            )

    def _analyze_product_characteristics(self) -> None:
        self._analyze_name_value_child(
            collection_name='product_characteristics',
            model_class=ProductCharacteristic,
            parent_resolver=self._resolve_product_binding,
            parent_label='Товар',
            existing_queryset=lambda parent, name: ProductCharacteristic.objects.filter(product=parent, name=name),
            create_parent_field='product',
        )

    def _analyze_variant_characteristics(self) -> None:
        self._analyze_name_value_child(
            collection_name='product_variant_characteristics',
            model_class=ProductVariantCharacteristic,
            parent_resolver=self._resolve_variant_binding,
            parent_label='Вариант',
            existing_queryset=lambda parent, name: ProductVariantCharacteristic.objects.filter(variant=parent, name=name),
            create_parent_field='variant',
        )

    def _analyze_name_value_child(self, *, collection_name: str, model_class: type, parent_resolver, parent_label: str, existing_queryset, create_parent_field: str) -> None:
        for index, item in enumerate(self._collection(collection_name)):
            resolutions = deepcopy(self._existing_conflict(collection_name, index).resolutions) if self._existing_conflict(collection_name, index) else {}
            source_snapshot = deepcopy(item)
            parent_obj, dependency = parent_resolver(source_snapshot.get('product_id') if 'product_id' in source_snapshot else source_snapshot.get('variant_id'), create_parent_field + '_id')
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label=parent_label,
                dependencies={create_parent_field + '_id': dependency} if dependency else {},
                resolutions=resolutions,
            )
            existing_obj = None
            if hasattr(parent_obj, 'pk'):
                existing_obj = existing_queryset(parent_obj, source_snapshot.get('name', '')).first()
            incoming_values = {
                'name': source_snapshot.get('name', ''),
                'value': source_snapshot.get('value', ''),
            }
            current_values = {
                'name': existing_obj.name,
                'value': existing_obj.value,
            } if existing_obj else {}
            field_meta = {
                'name': self._metadata('Название', 'text'),
                'value': self._metadata('Значение', 'text'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            self._register_item(
                collection_name=collection_name,
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={create_parent_field: parent_obj, 'name': source_snapshot.get('name', '')},
                dependency_fields={create_parent_field: dependency} if dependency else {},
                conflict_kind='field_mismatch' if field_conflicts else '',
            )

    def _analyze_product_images(self) -> None:
        for index, item in enumerate(self._collection('product_images')):
            source_snapshot = deepcopy(item)
            if source_snapshot.get('image'):
                self.warnings.append(
                    f'Поле product_images.image для элемента #{source_snapshot.get("id", index)} проигнорировано: импорт медиа отключён.'
                )
            self._register_item(
                collection_name='product_images',
                index=index,
                item=item,
                status=self.STATUS_NOOP,
                operation='skip',
                source_snapshot=source_snapshot,
                target_snapshot={},
                field_conflicts={},
                resolutions={},
                messages=['Медиа остаются вне интерактивного импорта.'],
            )

    def _analyze_product_videos(self) -> None:
        for index, item in enumerate(self._collection('product_videos')):
            resolutions = deepcopy(self._existing_conflict('product_videos', index).resolutions) if self._existing_conflict('product_videos', index) else {}
            source_snapshot = deepcopy(item)
            product_obj, dependency = self._resolve_product_binding(source_snapshot.get('product_id'), 'product_id')
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Товар',
                dependencies={'product_id': dependency} if dependency else {},
                resolutions=resolutions,
            )
            rutube_url = source_snapshot.get('rutube_url') or ''
            try:
                normalized_url, video_id, embed_url = _parse_rutube_video_url(rutube_url)
            except ValidationError as exc:
                source_snapshot['rutube_url'] = rutube_url
                field_conflicts = {
                    'rutube_url': {
                        **self._metadata('Ссылка RUTUBE', 'rutube'),
                        'current_value': '',
                        'incoming_value': rutube_url,
                        'resolution_error': exc.messages[0],
                    },
                }
                field_conflicts.update(dependency_conflicts)
                self._register_item(
                    collection_name='product_videos',
                    index=index,
                    item=item,
                    status=self.STATUS_PENDING_CONFLICT,
                    operation='conflict',
                    source_snapshot=source_snapshot,
                    target_snapshot={},
                    field_conflicts=field_conflicts,
                    resolutions=resolutions,
                    dependency_fields={'product': dependency} if dependency else {},
                    conflict_kind='validation',
                )
                continue
            existing_obj = None
            if isinstance(product_obj, Product):
                existing_obj = ProductVideo.objects.filter(product=product_obj, rutube_url=normalized_url).first()
            incoming_values = {
                'rutube_url': normalized_url,
                'rutube_video_id': source_snapshot.get('rutube_video_id') or video_id,
                'embed_url': source_snapshot.get('embed_url') or embed_url,
                'thumbnail_url': source_snapshot.get('thumbnail_url', ''),
                'title': source_snapshot.get('title', ''),
                'order': int(source_snapshot.get('order') or 0),
            }
            current_values = {
                'rutube_url': existing_obj.rutube_url,
                'rutube_video_id': existing_obj.rutube_video_id,
                'embed_url': existing_obj.embed_url,
                'thumbnail_url': existing_obj.thumbnail_url,
                'title': existing_obj.title,
                'order': existing_obj.order,
            } if existing_obj else {}
            field_meta = {
                'rutube_url': self._metadata('Ссылка RUTUBE', 'rutube'),
                'rutube_video_id': self._metadata('ID видео', 'text'),
                'embed_url': self._metadata('Embed URL', 'url'),
                'thumbnail_url': self._metadata('Постер', 'url'),
                'title': self._metadata('Заголовок', 'text'),
                'order': self._metadata('Порядок', 'int'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            self._register_item(
                collection_name='product_videos',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={'product': product_obj, 'rutube_url': normalized_url},
                dependency_fields={'product': dependency} if dependency else {},
                conflict_kind='field_mismatch' if field_conflicts else '',
            )

    def _analyze_content_blocks(self) -> None:
        for index, item in enumerate(self._collection('product_content_blocks')):
            resolutions = deepcopy(self._existing_conflict('product_content_blocks', index).resolutions) if self._existing_conflict('product_content_blocks', index) else {}
            source_snapshot = deepcopy(item)
            product_obj, dependency = self._resolve_product_binding(source_snapshot.get('product_id'), 'product_id')
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Товар',
                dependencies={'product_id': dependency} if dependency else {},
                resolutions=resolutions,
            )
            if source_snapshot.get('image'):
                self.warnings.append(
                    f'Поле product_content_blocks.image для элемента #{source_snapshot.get("id", index)} проигнорировано: импорт медиа отключён.'
                )
            existing_obj = None
            if isinstance(product_obj, Product):
                existing_obj = ProductContentBlock.objects.filter(
                    product=product_obj,
                    block_type=source_snapshot.get('block_type'),
                    sort_order=int(source_snapshot.get('sort_order') or 0),
                    title=source_snapshot.get('title', ''),
                ).first()
            incoming_values = {
                'block_type': source_snapshot.get('block_type', ''),
                'title': source_snapshot.get('title', ''),
                'text': source_snapshot.get('text', ''),
                'image_position': source_snapshot.get('image_position') or ProductContentBlock.ImagePosition.LEFT,
                'caption': source_snapshot.get('caption', ''),
                'rutube_url': source_snapshot.get('rutube_url', ''),
                'rutube_video_id': source_snapshot.get('rutube_video_id', ''),
                'embed_url': source_snapshot.get('embed_url', ''),
                'sort_order': int(source_snapshot.get('sort_order') or 0),
                'is_active': bool(source_snapshot.get('is_active')) if 'is_active' in source_snapshot else True,
            }
            current_values = {
                'block_type': existing_obj.block_type,
                'title': existing_obj.title,
                'text': existing_obj.text,
                'image_position': existing_obj.image_position,
                'caption': existing_obj.caption,
                'rutube_url': existing_obj.rutube_url,
                'rutube_video_id': existing_obj.rutube_video_id,
                'embed_url': existing_obj.embed_url,
                'sort_order': existing_obj.sort_order,
                'is_active': existing_obj.is_active,
            } if existing_obj else {}
            field_meta = {
                'block_type': self._metadata('Тип блока', 'choice', options=[{'value': choice[0], 'label': choice[1]} for choice in ProductContentBlock.BlockType.choices]),
                'title': self._metadata('Заголовок', 'text'),
                'text': self._metadata('Текст', 'textarea'),
                'image_position': self._metadata('Положение изображения', 'choice', options=[{'value': choice[0], 'label': choice[1]} for choice in ProductContentBlock.ImagePosition.choices]),
                'caption': self._metadata('Подпись', 'text'),
                'rutube_url': self._metadata('Ссылка RUTUBE', 'rutube'),
                'rutube_video_id': self._metadata('ID видео', 'text'),
                'embed_url': self._metadata('Embed URL', 'url'),
                'sort_order': self._metadata('Порядок', 'int'),
                'is_active': self._metadata('Активен', 'bool'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            self._register_item(
                collection_name='product_content_blocks',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={'product': product_obj, 'block_type': source_snapshot.get('block_type', ''), 'sort_order': int(source_snapshot.get('sort_order') or 0), 'title': source_snapshot.get('title', '')},
                dependency_fields={'product': dependency} if dependency else {},
                conflict_kind='field_mismatch' if field_conflicts else '',
            )

    def _analyze_bundles(self) -> None:
        for index, item in enumerate(self._collection('product_bundles')):
            resolutions = deepcopy(self._existing_conflict('product_bundles', index).resolutions) if self._existing_conflict('product_bundles', index) else {}
            source_snapshot = deepcopy(item)
            slug = (source_snapshot.get('slug') or '').strip()
            if slug:
                existing_obj = ProductBundle.objects.filter(slug=slug).first()
            else:
                existing_obj = ProductBundle.objects.filter(name=source_snapshot.get('name', '')).first() if source_snapshot.get('name') else None
            category_obj, category_dependency = self._direct_or_bound_object(
                raw_value=source_snapshot.get('category_id'),
                source_map=self.bindings['categories'],
                model_class=Category,
                field_name='category_id',
                conflict_meta={},
            )
            incoming_values = {
                'category': category_obj,
                'name': source_snapshot.get('name', ''),
                'slug': slug,
                'description': source_snapshot.get('description', ''),
            }
            current_values = {
                'category': make_direct_target_reference(existing_obj.category_id) if existing_obj and existing_obj.category_id else None,
                'name': existing_obj.name,
                'slug': existing_obj.slug,
                'description': existing_obj.description,
            } if existing_obj else {}
            field_meta = {
                'category': self._metadata('Категория набора', 'relation'),
                'name': self._metadata('Название', 'text'),
                'slug': self._metadata('Slug', 'slug'),
                'description': self._metadata('Описание', 'textarea'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            if existing_obj is not None and field_conflicts:
                self._inject_identifier_conflict(
                    field_name='slug',
                    field_type='slug',
                    label='Slug',
                    current_value=existing_obj.slug,
                    incoming_value=slug,
                    resolutions=resolutions,
                    effective_updates=effective_updates,
                    field_conflicts=field_conflicts,
                    unresolved_fields=unresolved,
                )
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            item_obj = self._register_item(
                collection_name='product_bundles',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={'category': category_obj, 'slug': slug} if slug else {'category': category_obj, 'name': source_snapshot.get('name', '')},
                dependency_fields={'category': category_dependency} if category_dependency else {},
                conflict_kind='field_mismatch' if field_conflicts else '',
            )
            self._sync_binding(
                'product_bundles',
                item,
                index,
                ProductBundle,
                item_obj.item_label,
                existing_obj=existing_obj,
                status=status,
                planned_create=existing_obj is None and status == self.STATUS_READY_CREATE,
                stable=existing_obj is not None or status == self.STATUS_READY_CREATE,
            )

    def _analyze_bundle_items(self) -> None:
        for index, item in enumerate(self._collection('product_bundle_items')):
            resolutions = deepcopy(self._existing_conflict('product_bundle_items', index).resolutions) if self._existing_conflict('product_bundle_items', index) else {}
            source_snapshot = deepcopy(item)
            bundle_obj, bundle_dependency = self._resolve_bundle_binding(source_snapshot.get('bundle_id'), 'bundle_id')
            product_obj, product_dependency = self._resolve_product_binding(source_snapshot.get('product_id'), 'product_id')
            dependencies = {}
            if bundle_dependency:
                dependencies['bundle_id'] = bundle_dependency
            if product_dependency:
                dependencies['product_id'] = product_dependency
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Связь',
                dependencies=dependencies,
                resolutions=resolutions,
            )
            existing_obj = None
            if isinstance(bundle_obj, ProductBundle) and isinstance(product_obj, Product):
                existing_obj = ProductBundleItem.objects.filter(bundle=bundle_obj, product=product_obj).first()
            incoming_values = {
                'quantity': int(source_snapshot.get('quantity') or 1),
                'price': source_snapshot.get('price', ''),
            }
            current_values = {
                'quantity': existing_obj.quantity,
                'price': serialize_for_json(existing_obj.price),
            } if existing_obj else {}
            field_meta = {
                'quantity': self._metadata('Количество', 'int'),
                'price': self._metadata('Цена', 'decimal'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            self._register_item(
                collection_name='product_bundle_items',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={'bundle': bundle_obj, 'product': product_obj},
                dependency_fields=dependencies,
                conflict_kind='field_mismatch' if field_conflicts else '',
            )

    def _analyze_cities(self) -> None:
        self._analyze_simple_collection(
            collection_name='cities',
            model_class=City,
            identity_field='slug',
            incoming_fields_builder=lambda source: {
                'name': source.get('name', '') if isinstance(source, dict) else source.name,
                'order': int(source.get('order') or 0) if isinstance(source, dict) else source.order,
            },
            field_meta_builder=lambda: {
                'name': self._metadata('Название', 'text'),
                'order': self._metadata('Порядок', 'int'),
            },
            existing_lookup_builder=lambda source: City.objects.filter(slug=source.get('slug')).first(),
        )

    def _analyze_pickup_points(self) -> None:
        for index, item in enumerate(self._collection('pickup_points')):
            if self._add_duplicate_item('pickup_points', index, item):
                self._sync_binding('pickup_points', item, index, PickupPoint, self._item_label('pickup_points', item, item), existing_obj=None, status=self.STATUS_PENDING_CONFLICT, planned_create=False, stable=False)
                continue
            resolutions = deepcopy(self._existing_conflict('pickup_points', index).resolutions) if self._existing_conflict('pickup_points', index) else {}
            source_snapshot = deepcopy(item)
            city_obj, city_dependency = self._resolve_city_binding(source_snapshot.get('city_id'), 'city_id')
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Город',
                dependencies={'city_id': city_dependency} if city_dependency else {},
                resolutions=resolutions,
            )
            existing_obj = None
            if isinstance(city_obj, City):
                existing_obj = PickupPoint.objects.filter(city=city_obj, name=source_snapshot.get('name', '')).first()
            incoming_values = {
                'name': source_snapshot.get('name', ''),
                'address': source_snapshot.get('address', ''),
                'order': int(source_snapshot.get('order') or 0),
            }
            current_values = {
                'name': existing_obj.name,
                'address': existing_obj.address,
                'order': existing_obj.order,
            } if existing_obj else {}
            field_meta = {
                'name': self._metadata('Название', 'text'),
                'address': self._metadata('Адрес', 'textarea'),
                'order': self._metadata('Порядок', 'int'),
            }
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            item_obj = self._register_item(
                collection_name='pickup_points',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={'city': city_obj, 'name': source_snapshot.get('name', '')},
                dependency_fields={'city_id': city_dependency} if city_dependency else {},
                conflict_kind='field_mismatch' if field_conflicts else '',
            )
            self._sync_binding(
                'pickup_points',
                item,
                index,
                PickupPoint,
                item_obj.item_label,
                existing_obj=existing_obj,
                status=status,
                planned_create=existing_obj is None and status == self.STATUS_READY_CREATE,
                stable=existing_obj is not None or status == self.STATUS_READY_CREATE,
            )

    def _analyze_stocks(self) -> None:
        for index, item in enumerate(self._collection('product_stocks')):
            resolutions = deepcopy(self._existing_conflict('product_stocks', index).resolutions) if self._existing_conflict('product_stocks', index) else {}
            source_snapshot = deepcopy(item)
            product_obj, product_dependency = self._resolve_product_binding(source_snapshot.get('product_id'), 'product_id')
            pickup_point_obj, pickup_dependency = self._resolve_pickup_binding(source_snapshot.get('pickup_point_id'), 'pickup_point_id')
            variant_obj, variant_dependency = self._resolve_variant_binding(source_snapshot.get('variant_id'), 'variant_id') if source_snapshot.get('variant_id') not in (None, '') else (None, None)
            dependencies = {}
            if product_dependency:
                dependencies['product_id'] = product_dependency
            if pickup_dependency:
                dependencies['pickup_point_id'] = pickup_dependency
            if variant_dependency:
                dependencies['variant_id'] = variant_dependency
            dependency_conflicts, unresolved_dependencies = self._conflict_from_dependencies(
                label='Связь',
                dependencies=dependencies,
                resolutions=resolutions,
            )
            existing_obj = None
            if isinstance(product_obj, Product) and isinstance(pickup_point_obj, PickupPoint):
                existing_obj = ProductStock.objects.filter(
                    product=product_obj,
                    pickup_point=pickup_point_obj,
                    variant=variant_obj if isinstance(variant_obj, ProductVariant) else None,
                ).first()
            incoming_values = {
                'quantity': int(source_snapshot.get('quantity') or 0),
            }
            current_values = {'quantity': existing_obj.quantity} if existing_obj else {}
            field_meta = {'quantity': self._metadata('Количество', 'int')}
            effective_updates, field_conflicts, unresolved = self._resolve_field_conflicts(
                current_values=current_values,
                incoming_values=incoming_values,
                field_meta=field_meta,
                resolutions=resolutions,
                default_resolution_mode='take_incoming' if existing_obj is None else '',
            )
            field_conflicts.update(dependency_conflicts)
            unresolved.extend(unresolved_dependencies)
            status, operation = self._status_from_conflicts(
                existing_obj=existing_obj,
                unresolved_fields=unresolved,
                field_conflicts=field_conflicts,
                effective_updates=effective_updates,
                current_values=current_values,
            )
            self._register_item(
                collection_name='product_stocks',
                index=index,
                item=item,
                status=status,
                operation=operation,
                source_snapshot=source_snapshot,
                target_snapshot=current_values,
                field_conflicts=field_conflicts,
                resolutions=resolutions,
                target_obj=existing_obj,
                update_values=effective_updates,
                create_kwargs={
                    'product': product_obj,
                    'pickup_point': pickup_point_obj,
                    'variant': variant_obj if isinstance(variant_obj, ProductVariant) else None,
                },
                dependency_fields=dependencies,
                conflict_kind='field_mismatch' if field_conflicts else '',
            )


class CatalogImportWorkflowService:
    def __init__(self, batch: CatalogImportBatch):
        self.batch = batch

    @classmethod
    def create_batch(cls, *, payload: dict[str, Any], source_filename: str) -> CatalogImportBatch:
        batch = CatalogImportBatch.objects.create(
            source_filename=source_filename,
            raw_payload=deepcopy(payload),
            editable_payload=deepcopy(payload),
            status=CatalogImportBatch.Status.REVIEW,
        )
        cls(batch).analyze_and_persist()
        return batch

    def analyze_and_persist(self) -> AnalysisResult:
        analyzer = CatalogImportAnalyzer(
            self.batch.editable_payload or self.batch.raw_payload or {},
            conflict_rows=list(self.batch.conflicts.all()),
        )
        result = analyzer.analyze()
        summary = result.summary()
        self._sync_conflicts(result)
        self.batch.summary = summary
        if self.batch.status == CatalogImportBatch.Status.FAILED:
            self.batch.status = CatalogImportBatch.Status.REVIEW
        self.batch.error_text = ''
        self.batch.save(update_fields=['summary', 'status', 'error_text', 'updated_at'])
        return result

    def _sync_conflicts(self, result: AnalysisResult) -> None:
        active_keys: set[tuple[str, int]] = set()
        for item in result.items:
            if not item.field_conflicts and not item.has_conflict_history:
                continue
            active_keys.add((item.collection_name, item.source_index))
            existing_conflict = self.batch.conflicts.filter(
                collection_name=item.collection_name,
                source_index=item.source_index,
            ).first()
            status = (
                CatalogImportConflict.Status.RESOLVED
                if item.status in {CatalogImportAnalyzer.STATUS_READY_UPDATE, CatalogImportAnalyzer.STATUS_READY_CREATE, CatalogImportAnalyzer.STATUS_NOOP}
                else CatalogImportConflict.Status.PENDING
            )
            if existing_conflict and existing_conflict.status == CatalogImportConflict.Status.APPLIED:
                status = CatalogImportConflict.Status.APPLIED
            CatalogImportConflict.objects.update_or_create(
                batch=self.batch,
                collection_name=item.collection_name,
                source_index=item.source_index,
                defaults={
                    'source_id': item.source_id,
                    'item_label': item.item_label,
                    'target_model': item.target_model,
                    'target_pk': item.target_pk,
                    'conflict_kind': item.conflict_kind or 'field_mismatch',
                    'source_snapshot': serialize_for_json(item.source_snapshot),
                    'target_snapshot': serialize_for_json(item.target_snapshot),
                    'field_conflicts': serialize_for_json(item.field_conflicts or {}),
                    'resolutions': serialize_for_json(item.resolutions),
                    'status': status,
                },
            )
        stale_conflicts = self.batch.conflicts.exclude(
            collection_name__in=[key[0] for key in active_keys],
        )
        for conflict in self.batch.conflicts.all():
            if (conflict.collection_name, conflict.source_index) not in active_keys and conflict.status != CatalogImportConflict.Status.APPLIED:
                conflict.status = CatalogImportConflict.Status.CLEARED
                conflict.save(update_fields=['status', 'updated_at'])

    def _result(self) -> AnalysisResult:
        return CatalogImportAnalyzer(
            self.batch.editable_payload or self.batch.raw_payload or {},
            conflict_rows=list(self.batch.conflicts.all()),
        ).analyze()

    def _editable_item(self, collection_name: str, source_index: int) -> dict[str, Any]:
        models_payload = (self.batch.editable_payload or {}).setdefault('models', {})
        collection = models_payload.setdefault(collection_name, [])
        return collection[source_index]

    def save_conflict_resolution(self, conflict: CatalogImportConflict, post_data) -> None:
        item = self._editable_item(conflict.collection_name, conflict.source_index)
        original_item = ((self.batch.raw_payload or {}).get('models') or {}).get(conflict.collection_name, [])[conflict.source_index]
        updated_resolutions = deepcopy(conflict.resolutions or {})

        for field_name, meta in (conflict.field_conflicts or {}).items():
            if field_name.startswith('__'):
                continue
            mode = post_data.get(f'mode__{field_name}', '')
            if not mode:
                updated_resolutions.pop(field_name, None)
                continue

            if mode == 'manual':
                if meta.get('field_type') == 'multiselect':
                    raw_value = post_data.getlist(f'manual__{field_name}')
                else:
                    raw_value = post_data.get(f'manual__{field_name}')
            else:
                raw_value = None

            value = raw_value
            payload_field_name = field_name
            if meta.get('field_type') == 'fk' and not field_name.endswith('_id'):
                payload_field_name = f'{field_name}_id'
            if mode == 'manual':
                if meta.get('field_type') == 'fk':
                    value = make_direct_target_reference(int(raw_value)) if raw_value not in (None, '') else None
                    item[payload_field_name] = value
                    if payload_field_name != field_name:
                        item.pop(field_name, None)
                elif meta.get('field_type') == 'multiselect':
                    item[field_name] = [make_direct_target_reference(int(entry)) for entry in raw_value if entry not in (None, '')]
                    value = item[field_name]
                elif meta.get('field_type') == 'bool':
                    bool_value = str(raw_value).lower() in {'1', 'true', 'on', 'yes'}
                    item[field_name] = bool_value
                    value = bool_value
                elif meta.get('field_type') in {'int'}:
                    item[field_name] = int(raw_value or 0)
                    value = item[field_name]
                else:
                    item[field_name] = raw_value or ''
                    value = item[field_name]
            elif mode == 'take_incoming':
                if isinstance(original_item, dict):
                    if payload_field_name in original_item:
                        item[payload_field_name] = deepcopy(original_item[payload_field_name])
                    elif field_name in original_item:
                        item[payload_field_name] = deepcopy(original_item[field_name])
            updated_resolutions[field_name] = {'mode': mode, 'value': serialize_for_json(value)}

        conflict.resolutions = updated_resolutions
        conflict.save(update_fields=['resolutions', 'updated_at'])
        self.batch.editable_payload = self.batch.editable_payload
        self.batch.save(update_fields=['editable_payload', 'updated_at'])
        self.analyze_and_persist()

    def _conflict_status_by_key(self) -> dict[str, str]:
        return {
            f'{conflict.collection_name}:{conflict.source_index}': conflict.status
            for conflict in self.batch.conflicts.all()
            if conflict.status in {CatalogImportConflict.Status.PENDING, CatalogImportConflict.Status.RESOLVED}
        }

    def _selected_keys(self, *, resolved_only: bool) -> set[str]:
        result = self._result()
        conflict_status = self._conflict_status_by_key()
        selected = set()
        for item in result.items:
            if item.status not in {CatalogImportAnalyzer.STATUS_READY_CREATE, CatalogImportAnalyzer.STATUS_READY_UPDATE}:
                continue
            conflict_status_value = conflict_status.get(item.key)
            if resolved_only:
                if conflict_status_value == CatalogImportConflict.Status.RESOLVED:
                    selected.add(item.key)
            else:
                if item.key not in conflict_status:
                    selected.add(item.key)
        return selected

    def _collect_dependency_keys(self, result: AnalysisResult, selected_keys: set[str]) -> set[str]:
        final_keys = set(selected_keys)
        changed = True
        while changed:
            changed = False
            for item in result.items:
                if item.key not in list(final_keys):
                    continue
                for dependency in item.dependency_fields.values():
                    binding = dependency.binding if dependency else None
                    if binding and binding.planned_create:
                        if binding.source_key not in final_keys:
                            final_keys.add(binding.source_key)
                            changed = True
        return final_keys

    def _prepare_payload_for_apply(self, selected_keys: set[str]) -> dict[str, Any]:
        result = self._result()
        final_keys = self._collect_dependency_keys(result, selected_keys)
        models_payload = deepcopy((self.batch.editable_payload or {}).get('models') or {})
        item_map = result.item_map

        filtered_models: dict[str, list[dict[str, Any]]] = {name: [] for name in models_payload.keys()}
        for collection_name, items in models_payload.items():
            for index, item in enumerate(items):
                key = f'{collection_name}:{index}'
                if key not in final_keys and key not in selected_keys:
                    continue
                cloned = deepcopy(item)
                item_result = item_map.get(key)
                if item_result:
                    for field_name, value in item_result.update_values.items():
                        if field_name == 'tag_ids':
                            normalized_tags = []
                            for tag_value in value:
                                if isinstance(tag_value, dict) and 'source_key' in tag_value:
                                    source_key = tag_value['source_key']
                                    _, source_index = source_key.split(':', 1)
                                    source_item = models_payload.get('product_tags', [])[int(source_index)]
                                    normalized_tags.append(source_item.get('id'))
                                elif hasattr(tag_value, 'pk'):
                                    normalized_tags.append(make_direct_target_reference(tag_value.pk))
                                else:
                                    normalized_tags.append(tag_value)
                            cloned['tag_ids'] = normalized_tags
                            continue
                        if hasattr(value, 'pk'):
                            cloned[f'{field_name}_id'] = make_direct_target_reference(value.pk)
                            cloned.pop(field_name, None)
                            continue
                        cloned[field_name] = serialize_for_json(value)
                    for field_name, dependency in item_result.dependency_fields.items():
                        binding = dependency.binding if dependency else None
                        if not binding:
                            continue
                        if binding.existing_obj is not None and binding.source_key not in final_keys:
                            source_field = field_name if field_name.endswith('_id') else f'{field_name}_id'
                            if source_field in cloned:
                                cloned[source_field] = make_direct_target_reference(binding.existing_obj.pk)
                    if collection_name == 'products' and 'tag_ids' in cloned:
                        resolved_tags = []
                        for raw_tag in cloned.get('tag_ids', []):
                            if is_direct_target_reference(raw_tag):
                                resolved_tags.append(raw_tag)
                                continue
                            binding = result.bindings['product_tags'].get(raw_tag)
                            if binding and binding.existing_obj is not None and binding.source_key not in final_keys:
                                resolved_tags.append(make_direct_target_reference(binding.existing_obj.pk))
                            else:
                                resolved_tags.append(raw_tag)
                        cloned['tag_ids'] = resolved_tags
                filtered_models[collection_name].append(cloned)

        return {
            'version': (self.batch.editable_payload or {}).get('version') or (self.batch.raw_payload or {}).get('version') or '1.0',
            'models': filtered_models,
        }

    def apply_clean_rows(self) -> CatalogImportError | None:
        return self._apply_selected(self._selected_keys(resolved_only=False), mark_resolved=False)

    def apply_resolved_rows(self) -> CatalogImportError | None:
        return self._apply_selected(self._selected_keys(resolved_only=True), mark_resolved=True)

    def _apply_selected(self, selected_keys: set[str], *, mark_resolved: bool) -> CatalogImportError | None:
        if not selected_keys:
            return None
        payload = self._prepare_payload_for_apply(selected_keys)
        importer = CatalogDataImporter(payload)
        try:
            importer.import_data()
        except CatalogImportError as exc:
            self.batch.status = CatalogImportBatch.Status.FAILED
            self.batch.error_text = str(exc)
            self.batch.save(update_fields=['status', 'error_text', 'updated_at'])
            return exc

        if mark_resolved:
            for conflict in self.batch.conflicts.filter(status=CatalogImportConflict.Status.RESOLVED):
                if f'{conflict.collection_name}:{conflict.source_index}' in selected_keys:
                    conflict.status = CatalogImportConflict.Status.APPLIED
                    conflict.save(update_fields=['status', 'updated_at'])

        self.batch.status = CatalogImportBatch.Status.PARTIAL if self.batch.conflicts.filter(status=CatalogImportConflict.Status.PENDING).exists() else CatalogImportBatch.Status.COMPLETED
        self.batch.save(update_fields=['status', 'updated_at'])
        self.analyze_and_persist()
        return None


def admin_change_url(model_label: str, pk: int | None) -> str:
    if not model_label or not pk:
        return ''
    app_label, model_name = model_label.split('.', 1)
    return reverse(f'admin:{app_label}_{model_name}_change', args=[pk])
