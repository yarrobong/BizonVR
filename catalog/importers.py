from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    CatalogSection,
    Category,
    City,
    PickupPoint,
    Product,
    ProductBundle,
    ProductBundleItem,
    ProductCharacteristic,
    ProductContentBlock,
    ProductImage,
    ProductStock,
    ProductTag,
    ProductVariant,
    ProductVariantCharacteristic,
    ProductVideo,
    _parse_rutube_video_url,
)


MediaResolver = Callable[[str, dict[str, Any], str, str], str | None]
DIRECT_TARGET_PK_KEY = 'target_pk'


def is_direct_target_reference(value: Any) -> bool:
    return isinstance(value, dict) and DIRECT_TARGET_PK_KEY in value


class CatalogImportError(Exception):
    """Raised when the incoming catalog payload is invalid or ambiguous."""


@dataclass
class CatalogImportReport:
    created: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)

    def bump(self, bucket: str, name: str) -> None:
        getattr(self, bucket)[name] += 1

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def sections(self) -> list[tuple[str, dict[str, int]]]:
        return [
            ('Создано', dict(sorted(self.created.items()))),
            ('Обновлено', dict(sorted(self.updated.items()))),
            ('Без изменений', dict(sorted(self.skipped.items()))),
        ]


class CatalogDataImporter:
    MEDIA_COLLECTION_FIELDS = {
        'products': ('image',),
        'product_variants': ('image',),
        'product_images': ('image',),
        'product_content_blocks': ('image',),
    }
    SAVE_BASE_MODELS = (ProductVideo, ProductContentBlock)

    def __init__(self, payload: dict[str, Any], *, media_resolver: MediaResolver | None = None):
        self.payload = payload
        self.models_payload = self._extract_models_payload(payload)
        self.media_resolver = media_resolver
        self.report = CatalogImportReport()
        self.sections_by_source_id: dict[Any, CatalogSection] = {}
        self.categories_by_source_id: dict[Any, Category] = {}
        self.tags_by_source_id: dict[Any, ProductTag] = {}
        self.products_by_source_id: dict[Any, Product] = {}
        self.variants_by_source_id: dict[Any, ProductVariant] = {}
        self.bundles_by_source_id: dict[Any, ProductBundle] = {}
        self.cities_by_source_id: dict[Any, City] = {}
        self.pickup_points_by_source_id: dict[Any, PickupPoint] = {}

    def import_data(self, *, dry_run: bool = False) -> CatalogImportReport:
        self._validate_payload_duplicates()

        with transaction.atomic():
            self._import_sections()
            self._import_categories()
            self._import_tags()
            self._import_products()
            self._import_variants()
            self._import_product_characteristics()
            self._import_variant_characteristics()
            self._import_product_images()
            self._import_product_videos()
            self._import_product_content_blocks()
            self._import_bundles()
            self._import_bundle_items()
            self._import_cities()
            self._import_pickup_points()
            self._import_product_stocks()

            if dry_run:
                transaction.set_rollback(True)

        return self.report

    def _extract_models_payload(self, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        if not isinstance(payload, dict):
            raise CatalogImportError('JSON должен содержать объект верхнего уровня.')

        models_payload = payload.get('models')
        if not isinstance(models_payload, dict):
            raise CatalogImportError('JSON должен содержать ключ "models" с объектом коллекций.')

        normalized: dict[str, list[dict[str, Any]]] = {}
        for collection_name, items in models_payload.items():
            if not isinstance(items, list):
                raise CatalogImportError(f'Коллекция "{collection_name}" должна быть массивом.')
            for item in items:
                if not isinstance(item, dict):
                    raise CatalogImportError(f'Элементы коллекции "{collection_name}" должны быть объектами.')
            normalized[collection_name] = items
        return normalized

    def _collection(self, name: str) -> list[dict[str, Any]]:
        return self.models_payload.get(name, [])

    def _validate_payload_duplicates(self) -> None:
        self._assert_unique(
            self._collection('catalog_sections'),
            lambda item: ('slug', self._require_key(item, 'slug', 'catalog_sections')),
            'catalog_sections',
        )
        self._assert_unique(
            self._collection('categories'),
            lambda item: ('slug', self._require_key(item, 'slug', 'categories')),
            'categories',
        )
        self._assert_unique(
            self._collection('product_tags'),
            lambda item: ('slug', self._require_key(item, 'slug', 'product_tags')),
            'product_tags',
        )
        self._assert_unique(
            self._collection('products'),
            lambda item: ('slug', self._require_key(item, 'slug', 'products')),
            'products',
        )
        self._assert_unique(
            self._collection('product_variants'),
            self._variant_duplicate_key,
            'product_variants',
        )
        self._assert_unique(
            self._collection('product_characteristics'),
            lambda item: (
                self._require_key(item, 'product_id', 'product_characteristics'),
                self._require_key(item, 'name', 'product_characteristics'),
            ),
            'product_characteristics',
        )
        self._assert_unique(
            self._collection('product_variant_characteristics'),
            lambda item: (
                self._require_key(item, 'variant_id', 'product_variant_characteristics'),
                self._require_key(item, 'name', 'product_variant_characteristics'),
            ),
            'product_variant_characteristics',
        )
        self._assert_unique(
            self._collection('product_images'),
            lambda item: (
                self._require_key(item, 'product_id', 'product_images'),
                int(item.get('order') or 0),
            ),
            'product_images',
        )
        self._assert_unique(
            self._collection('product_videos'),
            lambda item: (
                self._require_key(item, 'product_id', 'product_videos'),
                (item.get('rutube_url') or '').strip(),
            ),
            'product_videos',
        )
        self._assert_unique(
            self._collection('product_content_blocks'),
            lambda item: (
                self._require_key(item, 'product_id', 'product_content_blocks'),
                self._require_key(item, 'block_type', 'product_content_blocks'),
                int(item.get('sort_order') or 0),
                (item.get('title') or '').strip(),
            ),
            'product_content_blocks',
        )
        self._assert_unique(
            self._collection('product_bundles'),
            lambda item: ('slug', (item.get('slug') or '').strip()) if (item.get('slug') or '').strip() else ('name', self._require_key(item, 'name', 'product_bundles')),
            'product_bundles',
        )
        self._assert_unique(
            self._collection('product_bundle_items'),
            lambda item: (
                self._require_key(item, 'bundle_id', 'product_bundle_items'),
                self._require_key(item, 'product_id', 'product_bundle_items'),
            ),
            'product_bundle_items',
        )
        self._assert_unique(
            self._collection('cities'),
            lambda item: ('slug', self._require_key(item, 'slug', 'cities')),
            'cities',
        )
        self._assert_unique(
            self._collection('pickup_points'),
            lambda item: (
                self._require_key(item, 'city_id', 'pickup_points'),
                self._require_key(item, 'name', 'pickup_points'),
            ),
            'pickup_points',
        )
        self._assert_unique(
            self._collection('product_stocks'),
            lambda item: (
                self._require_key(item, 'product_id', 'product_stocks'),
                self._require_key(item, 'pickup_point_id', 'product_stocks'),
                item.get('variant_id'),
            ),
            'product_stocks',
        )

    def _variant_duplicate_key(self, item: dict[str, Any]) -> tuple[Any, ...]:
        product_id = self._require_key(item, 'product_id', 'product_variants')
        sku = (item.get('sku') or '').strip()
        if sku:
            return product_id, 'sku', sku
        return product_id, 'name', self._require_key(item, 'name', 'product_variants')

    def _assert_unique(self, items: list[dict[str, Any]], key_builder: Callable[[dict[str, Any]], tuple[Any, ...]], label: str) -> None:
        seen: dict[tuple[Any, ...], int] = {}
        for index, item in enumerate(items):
            key = key_builder(item)
            if key in seen:
                previous_index = seen[key]
                raise CatalogImportError(
                    f'В коллекции "{label}" найдены дублирующиеся элементы '
                    f'с ключом {key!r} (индексы {previous_index} и {index}).'
                )
            seen[key] = index

    def _require_key(self, item: dict[str, Any], key: str, collection: str) -> Any:
        value = item.get(key)
        if value in (None, ''):
            raise CatalogImportError(f'В коллекции "{collection}" обязательно поле "{key}".')
        return value

    def _remember(self, mapping: dict[Any, Any], item: dict[str, Any], obj: Any) -> None:
        if 'id' in item and item['id'] is not None:
            mapping[item['id']] = obj

    def _resolve_reference(
        self,
        mapping: dict[Any, Any],
        raw_value: Any,
        *,
        model_class: type,
        field_name: str,
    ) -> Any | None:
        if raw_value in (None, ''):
            return None
        if is_direct_target_reference(raw_value):
            target_pk = raw_value.get(DIRECT_TARGET_PK_KEY)
            obj = model_class.objects.filter(pk=target_pk).first()
            if obj is None:
                raise CatalogImportError(f'Не найдена целевая запись для "{field_name}" (pk={target_pk!r}).')
            return obj
        return mapping.get(raw_value)

    def _decimal_or_none(self, value: Any, *, field_name: str) -> Decimal | None:
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise CatalogImportError(f'Некорректное число в поле "{field_name}": {value!r}') from exc

    def _bool_or_default(self, item: dict[str, Any], key: str, default: bool) -> bool:
        return bool(item[key]) if key in item else default

    def _set_media_value(
        self,
        collection_name: str,
        item: dict[str, Any],
        field_name: str,
        payload_value: Any,
    ) -> str | None:
        if payload_value in (None, ''):
            return None
        if self.media_resolver is None:
            self.report.warn(
                f'Поле {collection_name}.{field_name} для элемента '
                f'{item.get("slug") or item.get("id") or item.get("name")!r} проигнорировано: импорт медиа отключён.'
            )
            return None

        resolved = self.media_resolver(collection_name, item, field_name, str(payload_value))
        if not resolved:
            self.report.warn(
                f'Не удалось сопоставить медиа для {collection_name}.{field_name} '
                f'({item.get("slug") or item.get("id") or item.get("name")!r}).'
            )
            return None
        return resolved

    def _values_equal(self, current: Any, new: Any) -> bool:
        if hasattr(current, 'pk'):
            current = current.pk
        if hasattr(new, 'pk'):
            new = new.pk
        return current == new

    def _persist(self, instance: Any, *, changed_fields: list[str] | None = None) -> None:
        if isinstance(instance, self.SAVE_BASE_MODELS):
            if changed_fields:
                instance.save_base(update_fields=changed_fields)
            else:
                instance.save_base()
            return

        if changed_fields:
            instance.save(update_fields=changed_fields)
        else:
            instance.save()

    def _upsert_instance(
        self,
        *,
        collection_name: str,
        queryset,
        create_kwargs: dict[str, Any],
        update_values: dict[str, Any],
        validate_before_save: bool = False,
    ):
        matches = list(queryset[:2])
        if len(matches) > 1:
            raise CatalogImportError(f'В БД найдено несколько записей для коллекции "{collection_name}" по одному natural key.')

        if not matches:
            obj = queryset.model(**{**create_kwargs, **update_values})
            if validate_before_save:
                obj.full_clean()
            self._persist(obj)
            self.report.bump('created', collection_name)
            return obj

        obj = matches[0]
        changed_fields: list[str] = []
        for field_name, new_value in update_values.items():
            current_value = getattr(obj, field_name)
            if not self._values_equal(current_value, new_value):
                setattr(obj, field_name, new_value)
                changed_fields.append(field_name)

        if changed_fields:
            if validate_before_save:
                obj.full_clean()
            self._persist(obj, changed_fields=changed_fields)
            self.report.bump('updated', collection_name)
        else:
            self.report.bump('skipped', collection_name)
        return obj

    def _import_sections(self) -> None:
        for item in self._collection('catalog_sections'):
            slug = self._require_key(item, 'slug', 'catalog_sections')
            obj = self._upsert_instance(
                collection_name='catalog_sections',
                queryset=CatalogSection.objects.filter(slug=slug),
                create_kwargs={'slug': slug},
                update_values={
                    'name': self._require_key(item, 'name', 'catalog_sections'),
                    'order': int(item.get('order') or 0),
                    **({'icon': item.get('icon') or ''} if 'icon' in item else {}),
                },
            )
            self._remember(self.sections_by_source_id, item, obj)

    def _import_categories(self) -> None:
        for item in self._collection('categories'):
            slug = self._require_key(item, 'slug', 'categories')
            section = None
            if 'section_id' in item and item.get('section_id') is not None:
                section = self._resolve_reference(
                    self.sections_by_source_id,
                    item['section_id'],
                    model_class=CatalogSection,
                    field_name='categories.section_id',
                )
                if not section:
                    raise CatalogImportError(f'Категория {slug!r} ссылается на неизвестный section_id={item["section_id"]!r}.')

            update_values = {
                'name': self._require_key(item, 'name', 'categories'),
                'section': section,
            }
            if 'icon' in item:
                update_values['icon'] = item.get('icon') or ''
            if 'tile_size' in item:
                update_values['tile_size'] = item.get('tile_size') or 'small'
            if 'is_bundles_category' in item:
                update_values['is_bundles_category'] = bool(item.get('is_bundles_category'))

            obj = self._upsert_instance(
                collection_name='categories',
                queryset=Category.objects.filter(slug=slug),
                create_kwargs={'slug': slug},
                update_values=update_values,
            )
            self._remember(self.categories_by_source_id, item, obj)

    def _import_tags(self) -> None:
        for item in self._collection('product_tags'):
            slug = self._require_key(item, 'slug', 'product_tags')
            obj = self._upsert_instance(
                collection_name='product_tags',
                queryset=ProductTag.objects.filter(slug=slug),
                create_kwargs={'slug': slug},
                update_values={
                    'name': self._require_key(item, 'name', 'product_tags'),
                    'order': int(item.get('order') or 0),
                },
            )
            self._remember(self.tags_by_source_id, item, obj)

    def _import_products(self) -> None:
        for item in self._collection('products'):
            slug = self._require_key(item, 'slug', 'products')
            category = self._resolve_reference(
                self.categories_by_source_id,
                self._require_key(item, 'category_id', 'products'),
                model_class=Category,
                field_name='products.category_id',
            )
            if not category:
                raise CatalogImportError(f'Товар {slug!r} ссылается на неизвестную категорию.')

            update_values: dict[str, Any] = {
                'name': self._require_key(item, 'name', 'products'),
                'category': category,
                'description': item.get('description', ''),
                'is_active': self._bool_or_default(item, 'is_active', True),
                'allow_order_on_request': self._bool_or_default(item, 'allow_order_on_request', True),
                'option_label': item.get('option_label', ''),
            }
            if 'price' in item:
                update_values['price'] = self._decimal_or_none(item.get('price'), field_name='products.price')
            if 'sku' in item:
                update_values['sku'] = item.get('sku') or ''
            if 'price_on_request' in item:
                update_values['price_on_request'] = self._decimal_or_none(
                    item.get('price_on_request'),
                    field_name='products.price_on_request',
                )
            if 'avito_url' in item:
                update_values['avito_url'] = item.get('avito_url') or ''
            if 'ozon_url' in item:
                update_values['ozon_url'] = item.get('ozon_url') or ''
            if 'wildberries_url' in item:
                update_values['wildberries_url'] = item.get('wildberries_url') or ''
            if 'views_count' in item:
                update_values['views_count'] = int(item.get('views_count') or 0)
            if 'image' in item:
                resolved_image = self._set_media_value('products', item, 'image', item.get('image'))
                if resolved_image:
                    update_values['image'] = resolved_image

            obj = self._upsert_instance(
                collection_name='products',
                queryset=Product.objects.filter(slug=slug),
                create_kwargs={'slug': slug},
                update_values=update_values,
            )

            if 'tag_ids' in item:
                desired_tags = []
                for raw_tag in item.get('tag_ids', []):
                    tag = self._resolve_reference(
                        self.tags_by_source_id,
                        raw_tag,
                        model_class=ProductTag,
                        field_name='products.tag_ids',
                    )
                    if not tag:
                        raise CatalogImportError(f'Товар {slug!r} ссылается на неизвестный тег.')
                    desired_tags.append(tag)
                current_tag_ids = list(obj.tags.order_by('id').values_list('id', flat=True))
                desired_tag_ids = [tag.id for tag in desired_tags]
                if current_tag_ids != desired_tag_ids:
                    obj.tags.set(desired_tags)
                    self.report.bump('updated', 'product_tags_relations')
                else:
                    self.report.bump('skipped', 'product_tags_relations')

            self._remember(self.products_by_source_id, item, obj)

    def _import_variants(self) -> None:
        for item in self._collection('product_variants'):
            product = self._resolve_reference(
                self.products_by_source_id,
                self._require_key(item, 'product_id', 'product_variants'),
                model_class=Product,
                field_name='product_variants.product_id',
            )
            if not product:
                raise CatalogImportError('Вариант товара ссылается на неизвестный товар.')

            sku = (item.get('sku') or '').strip()
            if sku:
                queryset = ProductVariant.objects.filter(product=product, sku=sku)
                create_kwargs = {'product': product, 'sku': sku}
            else:
                name = self._require_key(item, 'name', 'product_variants')
                queryset = ProductVariant.objects.filter(product=product, sku='', name=name)
                create_kwargs = {'product': product, 'name': name, 'sku': ''}

            update_values: dict[str, Any] = {
                'name': self._require_key(item, 'name', 'product_variants'),
                'order': int(item.get('order') or 0),
            }
            if 'price_override' in item:
                update_values['price_override'] = self._decimal_or_none(
                    item.get('price_override'),
                    field_name='product_variants.price_override',
                )
            if 'price_on_request_override' in item:
                update_values['price_on_request_override'] = self._decimal_or_none(
                    item.get('price_on_request_override'),
                    field_name='product_variants.price_on_request_override',
                )
            if 'sku' in item:
                update_values['sku'] = item.get('sku') or ''
            if 'image' in item:
                resolved_image = self._set_media_value('product_variants', item, 'image', item.get('image'))
                if resolved_image:
                    update_values['image'] = resolved_image

            obj = self._upsert_instance(
                collection_name='product_variants',
                queryset=queryset,
                create_kwargs=create_kwargs,
                update_values=update_values,
            )
            self._remember(self.variants_by_source_id, item, obj)

    def _import_product_characteristics(self) -> None:
        for item in self._collection('product_characteristics'):
            product = self._resolve_reference(
                self.products_by_source_id,
                self._require_key(item, 'product_id', 'product_characteristics'),
                model_class=Product,
                field_name='product_characteristics.product_id',
            )
            if not product:
                raise CatalogImportError('Характеристика товара ссылается на неизвестный товар.')
            name = self._require_key(item, 'name', 'product_characteristics')
            self._upsert_instance(
                collection_name='product_characteristics',
                queryset=ProductCharacteristic.objects.filter(product=product, name=name),
                create_kwargs={'product': product, 'name': name},
                update_values={'value': self._require_key(item, 'value', 'product_characteristics')},
            )

    def _import_variant_characteristics(self) -> None:
        for item in self._collection('product_variant_characteristics'):
            variant = self._resolve_reference(
                self.variants_by_source_id,
                self._require_key(item, 'variant_id', 'product_variant_characteristics'),
                model_class=ProductVariant,
                field_name='product_variant_characteristics.variant_id',
            )
            if not variant:
                raise CatalogImportError('Характеристика варианта ссылается на неизвестный вариант.')
            name = self._require_key(item, 'name', 'product_variant_characteristics')
            self._upsert_instance(
                collection_name='product_variant_characteristics',
                queryset=ProductVariantCharacteristic.objects.filter(variant=variant, name=name),
                create_kwargs={'variant': variant, 'name': name},
                update_values={'value': self._require_key(item, 'value', 'product_variant_characteristics')},
            )

    def _import_product_images(self) -> None:
        for item in self._collection('product_images'):
            product = self._resolve_reference(
                self.products_by_source_id,
                self._require_key(item, 'product_id', 'product_images'),
                model_class=Product,
                field_name='product_images.product_id',
            )
            if not product:
                raise CatalogImportError('Дополнительное изображение ссылается на неизвестный товар.')
            resolved_image = self._set_media_value('product_images', item, 'image', item.get('image'))
            if not resolved_image:
                self.report.bump('skipped', 'product_images')
                continue
            order = int(item.get('order') or 0)
            self._upsert_instance(
                collection_name='product_images',
                queryset=ProductImage.objects.filter(product=product, order=order),
                create_kwargs={'product': product, 'order': order},
                update_values={'image': resolved_image},
            )

    def _import_product_videos(self) -> None:
        for item in self._collection('product_videos'):
            product = self._resolve_reference(
                self.products_by_source_id,
                self._require_key(item, 'product_id', 'product_videos'),
                model_class=Product,
                field_name='product_videos.product_id',
            )
            if not product:
                raise CatalogImportError('Видео товара ссылается на неизвестный товар.')
            rutube_url = self._require_key(item, 'rutube_url', 'product_videos')
            try:
                normalized_url, video_id, embed_url = _parse_rutube_video_url(rutube_url)
            except ValidationError as exc:
                raise CatalogImportError(f'Некорректная ссылка RUTUBE в product_videos: {exc.messages[0]}') from exc

            update_values = {
                'rutube_url': normalized_url,
                'rutube_video_id': item.get('rutube_video_id') or video_id,
                'embed_url': item.get('embed_url') or embed_url,
                'thumbnail_url': item.get('thumbnail_url') or '',
                'title': item.get('title') or '',
                'order': int(item.get('order') or 0),
            }
            self._upsert_instance(
                collection_name='product_videos',
                queryset=ProductVideo.objects.filter(product=product, rutube_url=normalized_url),
                create_kwargs={'product': product, 'rutube_url': normalized_url},
                update_values=update_values,
                validate_before_save=True,
            )

    def _import_product_content_blocks(self) -> None:
        for item in self._collection('product_content_blocks'):
            product = self._resolve_reference(
                self.products_by_source_id,
                self._require_key(item, 'product_id', 'product_content_blocks'),
                model_class=Product,
                field_name='product_content_blocks.product_id',
            )
            if not product:
                raise CatalogImportError('Блок контента товара ссылается на неизвестный товар.')

            block_type = self._require_key(item, 'block_type', 'product_content_blocks')
            sort_order = int(item.get('sort_order') or 0)
            title = item.get('title') or ''
            queryset = ProductContentBlock.objects.filter(
                product=product,
                block_type=block_type,
                sort_order=sort_order,
                title=title,
            )
            update_values = {
                'text': item.get('text') or '',
                'image_position': item.get('image_position') or ProductContentBlock.ImagePosition.LEFT,
                'caption': item.get('caption') or '',
                'rutube_url': item.get('rutube_url') or '',
                'rutube_video_id': item.get('rutube_video_id') or '',
                'embed_url': item.get('embed_url') or '',
                'sort_order': sort_order,
                'is_active': self._bool_or_default(item, 'is_active', True),
            }
            resolved_image = None
            if 'image' in item:
                resolved_image = self._set_media_value('product_content_blocks', item, 'image', item.get('image'))
                if resolved_image:
                    update_values['image'] = resolved_image
            if block_type in (
                ProductContentBlock.BlockType.IMAGE_TEXT,
                ProductContentBlock.BlockType.FULL_IMAGE,
            ) and not queryset.exists() and not resolved_image:
                self.report.warn(
                    f'Блок контента {title or sort_order!r} пропущен: для этого типа требуется изображение.'
                )
                self.report.bump('skipped', 'product_content_blocks')
                continue

            self._upsert_instance(
                collection_name='product_content_blocks',
                queryset=queryset,
                create_kwargs={
                    'product': product,
                    'block_type': block_type,
                    'sort_order': sort_order,
                    'title': title,
                },
                update_values=update_values,
                validate_before_save=True,
            )

    def _import_bundles(self) -> None:
        for item in self._collection('product_bundles'):
            slug = (item.get('slug') or '').strip()
            if slug:
                queryset = ProductBundle.objects.filter(slug=slug)
                create_kwargs = {'slug': slug}
            else:
                name = self._require_key(item, 'name', 'product_bundles')
                queryset = ProductBundle.objects.filter(name=name)
                create_kwargs = {'name': name}

            update_values = {}
            for field_name in ('name', 'description'):
                if field_name in item:
                    update_values[field_name] = item.get(field_name) or ''
            if slug:
                update_values['slug'] = slug
            if 'image' in item:
                resolved_image = self._set_media_value('product_bundles', item, 'image', item.get('image'))
                if resolved_image:
                    update_values['image'] = resolved_image

            obj = self._upsert_instance(
                collection_name='product_bundles',
                queryset=queryset,
                create_kwargs=create_kwargs,
                update_values=update_values,
            )
            self._remember(self.bundles_by_source_id, item, obj)

    def _import_bundle_items(self) -> None:
        for item in self._collection('product_bundle_items'):
            bundle = self._resolve_reference(
                self.bundles_by_source_id,
                self._require_key(item, 'bundle_id', 'product_bundle_items'),
                model_class=ProductBundle,
                field_name='product_bundle_items.bundle_id',
            )
            product = self._resolve_reference(
                self.products_by_source_id,
                self._require_key(item, 'product_id', 'product_bundle_items'),
                model_class=Product,
                field_name='product_bundle_items.product_id',
            )
            if not bundle or not product:
                raise CatalogImportError('Позиция набора ссылается на неизвестный набор или товар.')

            update_values: dict[str, Any] = {'quantity': int(item.get('quantity') or 1)}
            if 'price' in item:
                update_values['price'] = self._decimal_or_none(item.get('price'), field_name='product_bundle_items.price')
            self._upsert_instance(
                collection_name='product_bundle_items',
                queryset=ProductBundleItem.objects.filter(bundle=bundle, product=product),
                create_kwargs={'bundle': bundle, 'product': product},
                update_values=update_values,
            )

    def _import_cities(self) -> None:
        for item in self._collection('cities'):
            slug = self._require_key(item, 'slug', 'cities')
            obj = self._upsert_instance(
                collection_name='cities',
                queryset=City.objects.filter(slug=slug),
                create_kwargs={'slug': slug},
                update_values={
                    'name': self._require_key(item, 'name', 'cities'),
                    'order': int(item.get('order') or 0),
                },
            )
            self._remember(self.cities_by_source_id, item, obj)

    def _import_pickup_points(self) -> None:
        for item in self._collection('pickup_points'):
            city = self._resolve_reference(
                self.cities_by_source_id,
                self._require_key(item, 'city_id', 'pickup_points'),
                model_class=City,
                field_name='pickup_points.city_id',
            )
            if not city:
                raise CatalogImportError('Точка выдачи ссылается на неизвестный город.')
            name = self._require_key(item, 'name', 'pickup_points')
            obj = self._upsert_instance(
                collection_name='pickup_points',
                queryset=PickupPoint.objects.filter(city=city, name=name),
                create_kwargs={'city': city, 'name': name},
                update_values={
                    'address': item.get('address') or '',
                    'order': int(item.get('order') or 0),
                },
            )
            self._remember(self.pickup_points_by_source_id, item, obj)

    def _import_product_stocks(self) -> None:
        for item in self._collection('product_stocks'):
            product = self._resolve_reference(
                self.products_by_source_id,
                self._require_key(item, 'product_id', 'product_stocks'),
                model_class=Product,
                field_name='product_stocks.product_id',
            )
            pickup_point = self._resolve_reference(
                self.pickup_points_by_source_id,
                self._require_key(item, 'pickup_point_id', 'product_stocks'),
                model_class=PickupPoint,
                field_name='product_stocks.pickup_point_id',
            )
            variant = self._resolve_reference(
                self.variants_by_source_id,
                item.get('variant_id'),
                model_class=ProductVariant,
                field_name='product_stocks.variant_id',
            ) if item.get('variant_id') is not None else None
            if not product or not pickup_point:
                raise CatalogImportError('Остаток товара ссылается на неизвестный товар или точку выдачи.')
            if item.get('variant_id') is not None and not variant:
                raise CatalogImportError('Остаток товара ссылается на неизвестный вариант.')

            self._upsert_instance(
                collection_name='product_stocks',
                queryset=ProductStock.objects.filter(product=product, pickup_point=pickup_point, variant=variant),
                create_kwargs={'product': product, 'pickup_point': pickup_point, 'variant': variant},
                update_values={'quantity': int(item.get('quantity') or 0)},
            )
