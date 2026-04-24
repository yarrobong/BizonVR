import csv
import io
import json
import os
import tempfile
import zipfile
from datetime import datetime
from decimal import Decimal

from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin
from django.conf import settings
from django.contrib import admin, messages
from django import forms
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils import timezone

from ..cache_utils import invalidate_catalog_cache
from ..importers import CatalogImportError
from ..import_workflow import CatalogImportWorkflowService, admin_change_url
from ..models import (
    CatalogImportBatch,
    CatalogImportConflict,
    DescriptionBlockType,
    DescriptionTemplate,
    DescriptionTemplateSlot,
    Product,
    ProductCharacteristic,
    ProductContentBlock,
    ProductDescription,
    ProductDescriptionAsset,
    ProductDescriptionBlock,
    ProductImage,
    ProductVideo,
    ProductVariant,
    ProductVariantCharacteristic,
)
from ..product_descriptions import (
    build_admin_constructor_state,
    render_description_preview,
    save_product_description_from_payload,
    serialize_template,
    template_to_constructor_payload,
)
from .bundles import ProductBundleItemInlineForProduct
from .location import ProductStockInlineForProduct
from .proposal_html import build_commercial_proposal_html
from .shared import _admin_image_preview


def _decimal_to_str_or_empty(value):
    return '' if value is None else str(value)


def _product_default_price(product):
    return product.price if product.price is not None else product.price_on_request


def _parse_decimal_or_fallback(raw_value, fallback):
    if raw_value:
        try:
            value = Decimal(raw_value.replace(',', '.'))
            if value >= 0:
                return value
        except Exception:
            pass
    return fallback


def _load_uploaded_json(uploaded_file):
    try:
        raw_bytes = uploaded_file.read()
        if not raw_bytes:
            raise ValueError('Файл пустой.')
        return json.loads(raw_bytes.decode('utf-8'))
    except UnicodeDecodeError as exc:
        raise ValueError('JSON-файл должен быть в UTF-8.') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'Некорректный JSON: {exc.msg}.') from exc


COLLECTION_LABELS = {
    'catalog_sections': 'Разделы каталога',
    'categories': 'Категории',
    'product_tags': 'Теги',
    'products': 'Товары',
    'product_variants': 'Варианты',
    'product_characteristics': 'Характеристики товаров',
    'product_variant_characteristics': 'Характеристики вариантов',
    'product_images': 'Изображения',
    'product_videos': 'Видео',
    'product_content_blocks': 'Контентные блоки',
    'product_bundles': 'Наборы',
    'product_bundle_items': 'Позиции наборов',
    'cities': 'Города',
    'pickup_points': 'Точки выдачи',
    'product_stocks': 'Остатки',
}


def _collection_label(name):
    return COLLECTION_LABELS.get(name, name.replace('_', ' ').title())


def _status_badge(status):
    labels = {
        'ready_create': 'Готово к созданию',
        'ready_update': 'Готово к обновлению',
        'noop': 'Без изменений',
        'pending_conflict': 'Нужна проверка',
        'blocking': 'Блокирующая ошибка',
        'pending': 'Ожидает решения',
        'resolved': 'Разрешён',
        'applied': 'Применён',
        'cleared': 'Устарел',
    }
    return labels.get(status, status)


def _display_import_value(value):
    if value in (None, '', []):
        return '—'
    if value is True:
        return 'Да'
    if value is False:
        return 'Нет'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


class ProductCharacteristicInline(admin.TabularInline):
    model = ProductCharacteristic
    extra = 1


class ProductVariantCharacteristicInline(admin.TabularInline):
    model = ProductVariantCharacteristic
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ('image_preview', 'name', 'sku', 'image', 'price_override', 'price_on_request_override', 'order')
    readonly_fields = ('image_preview',)
    show_change_link = True
    verbose_name = 'Вариант товара'
    verbose_name_plural = 'Варианты товара (если вариантов нет, используется базовая цена товара)'

    def image_preview(self, obj):
        return _admin_image_preview(obj)

    image_preview.short_description = 'Превью'


class ProductImageInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProductImage
    extra = 1
    sortable_field_name = 'order'
    template = 'admin/catalog/product/edit_inline/tabular_with_help.html'
    fields = ('image_preview', 'image', 'order')
    readonly_fields = ('image_preview',)
    verbose_name = 'Фото товара'
    verbose_name_plural = 'Фото товара'
    help_text = 'Первое фото станет главным. Порядок можно менять перетаскиванием, изображения можно вставлять через Ctrl+V.'

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=140, height=104)

    image_preview.short_description = 'Превью'


class ProductVideoInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProductVideo
    extra = 1
    sortable_field_name = 'order'
    fields = ('thumbnail_preview', 'rutube_url', 'title', 'order')
    readonly_fields = ('thumbnail_preview', 'title')
    verbose_name = 'Видео товара'
    verbose_name_plural = 'Видео товара (публичные ссылки RUTUBE, после фото на витрине)'

    def thumbnail_preview(self, obj):
        if not getattr(obj, 'thumbnail_url', ''):
            return 'Превью появится после сохранения'
        return format_html(
            '<img src="{}" alt="{}" style="width: 92px; height: 52px; object-fit: cover; border-radius: 8px;" />',
            obj.thumbnail_url,
            obj.title or 'Видео товара',
        )

    thumbnail_preview.short_description = 'Превью'


class ProductContentBlockInline(SortableInlineAdminMixin, admin.StackedInline):
    model = ProductContentBlock
    extra = 0
    sortable_field_name = 'sort_order'
    fields = (
        'block_type',
        'title',
        'text',
        'image_preview',
        'image',
        'rutube_preview',
        'rutube_url',
        'image_position',
        'caption',
        'sort_order',
        'is_active',
    )
    readonly_fields = ('image_preview', 'rutube_preview')
    verbose_name = 'Блок подробного описания'
    verbose_name_plural = 'Блоки подробного описания (порядок можно менять перетаскиванием)'

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=120, height=80)

    image_preview.short_description = 'Превью'

    def rutube_preview(self, obj):
        if obj and getattr(obj, 'rutube_url', ''):
            return format_html(
                '<a href="{}" target="_blank" rel="noreferrer">Открыть видео на RUTUBE</a>',
                obj.rutube_url,
            )
        return '—'

    rutube_preview.short_description = 'Видео'


class DescriptionTemplateSlotInline(SortableInlineAdminMixin, admin.StackedInline):
    model = DescriptionTemplateSlot
    extra = 0
    sortable_field_name = 'sort_order'
    fields = ('slot_key', 'block_type', 'label', 'help_text', 'default_data', 'settings', 'sort_order', 'is_required')
    autocomplete_fields = ('block_type',)
    verbose_name = 'Блок шаблона'
    verbose_name_plural = 'Блоки шаблона'


def _next_copy_identity(*, base_name, base_slug):
    counter = 1
    while True:
        suffix = '' if counter == 1 else f'-{counter}'
        name_suffix = '' if counter == 1 else f' {counter}'
        candidate_slug = f'{base_slug}{suffix}'
        if not DescriptionTemplate.objects.filter(slug=candidate_slug).exists():
            return f'{base_name}{name_suffix}', candidate_slug
        counter += 1


def _duplicate_description_template(template, *, name=None, slug=None):
    source_name = (name or '').strip() or f'{template.name} копия'
    source_slug = (slug or '').strip() or f'{template.slug}-copy'
    normalized_slug = slugify(source_slug) or f'template-{template.pk}-copy'
    duplicate_name, duplicate_slug = _next_copy_identity(base_name=source_name, base_slug=normalized_slug)

    duplicated = DescriptionTemplate.objects.create(
        name=duplicate_name,
        slug=duplicate_slug,
        description=template.description,
        preview_image=template.preview_image,
        preview_data=template.preview_data,
        category=template.category,
        is_active=template.is_active,
        version=template.version,
    )
    slot_copies = [
        DescriptionTemplateSlot(
            template=duplicated,
            slot_key=slot.slot_key,
            block_type=slot.block_type,
            label=slot.label,
            help_text=slot.help_text,
            sort_order=slot.sort_order,
            is_required=slot.is_required,
            default_data=slot.default_data,
            settings=slot.settings,
        )
        for slot in template.slots.select_related('block_type').order_by('sort_order', 'id')
    ]
    DescriptionTemplateSlot.objects.bulk_create(slot_copies)
    return duplicated


@admin.register(DescriptionBlockType)
class DescriptionBlockTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'category', 'sort_order', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'slug', 'description')
    ordering = ('sort_order', 'name')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(DescriptionTemplate)
class DescriptionTemplateAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ('name', 'slug', 'category', 'slots_count', 'version', 'is_active', 'updated_at', 'duplicate_link')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (DescriptionTemplateSlotInline,)
    ordering = ('category', 'name')
    readonly_fields = ('template_actions',)
    actions = ('duplicate_templates',)
    save_as = True
    save_as_continue = False
    fieldsets = (
        ('Шаблон', {
            'fields': ('name', 'slug', 'category', 'description', 'preview_image', 'preview_data', 'version', 'is_active'),
            'description': 'Шаблон — это только заготовка. При применении в товар структура копируется, а не связывается с товаром “вживую”.',
        }),
        ('Действия', {
            'fields': ('template_actions',),
            'description': 'Можно редактировать текущий шаблон, дублировать его или сохранить как новый через стандартную кнопку Django admin.',
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:template_id>/duplicate/',
                self.admin_site.admin_view(self.duplicate_template_view),
                name='catalog_descriptiontemplate_duplicate',
            ),
        ]
        return custom_urls + urls

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('slots')

    @admin.display(description='Блоки')
    def slots_count(self, obj):
        return obj.slots.count()

    @admin.display(description='Дублировать')
    def duplicate_link(self, obj):
        url = reverse('admin:catalog_descriptiontemplate_duplicate', args=[obj.pk])
        return format_html('<a class="button" href="{}">Дублировать</a>', url)

    def template_actions(self, obj):
        if not obj or not obj.pk:
            return 'После первого сохранения станут доступны действия для дублирования.'
        duplicate_url = reverse('admin:catalog_descriptiontemplate_duplicate', args=[obj.pk])
        return format_html(
            '<div style="display:grid; gap:8px;">'
            '<p style="margin:0;">Изменения шаблона не меняют уже созданные описания товаров: в товар копируется структура блоков.</p>'
            '<a class="button" href="{}">Дублировать шаблон</a>'
            '</div>',
            duplicate_url,
        )

    template_actions.short_description = 'Действия'

    def duplicate_template_view(self, request, template_id):
        template = get_object_or_404(
            DescriptionTemplate.objects.prefetch_related('slots__block_type'),
            pk=template_id,
        )
        duplicated = _duplicate_description_template(template)
        self.message_user(
            request,
            f'Шаблон «{template.name}» продублирован как «{duplicated.name}».',
            messages.SUCCESS,
        )
        return HttpResponseRedirect(reverse('admin:catalog_descriptiontemplate_change', args=[duplicated.pk]))

    @admin.action(description='Дублировать выбранные шаблоны')
    def duplicate_templates(self, request, queryset):
        duplicated = []
        for template in queryset.prefetch_related('slots__block_type'):
            duplicated.append(_duplicate_description_template(template))
        if duplicated:
            self.message_user(
                request,
                f'Продублировано шаблонов: {len(duplicated)}.',
                messages.SUCCESS,
            )
        else:
            self.message_user(request, 'Нет шаблонов для дублирования.', messages.WARNING)


class ProductDescriptionBlockInline(SortableInlineAdminMixin, admin.StackedInline):
    model = ProductDescriptionBlock
    extra = 0
    sortable_field_name = 'sort_order'
    fields = ('slot_key', 'block_type', 'data', 'sort_order', 'is_active')
    autocomplete_fields = ('block_type',)
    verbose_name = 'Блок описания'
    verbose_name_plural = 'Блоки описания'


class ProductDescriptionAssetInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ProductDescriptionAsset
    extra = 0
    sortable_field_name = 'sort_order'
    fields = ('image_preview', 'image', 'block', 'alt', 'caption', 'role', 'sort_order')
    readonly_fields = ('image_preview',)
    verbose_name = 'Медиа описания'
    verbose_name_plural = 'Медиа описания'

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=120, height=80)

    image_preview.short_description = 'Превью'


@admin.register(ProductDescription)
class ProductDescriptionAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ('product', 'template', 'status', 'is_active', 'source', 'updated_at')
    list_filter = ('status', 'is_active', 'source', 'template')
    search_fields = ('product__name', 'title', 'intro')
    autocomplete_fields = ('product', 'template')
    inlines = (ProductDescriptionBlockInline, ProductDescriptionAssetInline)
    readonly_fields = ('published_at',)
    fieldsets = (
        ('Товар и шаблон', {
            'fields': ('product', 'template', 'source'),
        }),
        ('Публикация', {
            'fields': ('title', 'intro', 'status', 'is_active', 'published_at'),
        }),
    )

    def get_model_perms(self, request):
        if request.user.is_superuser:
            return super().get_model_perms(request)
        return {}

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'product', 'price_override', 'price_on_request_override', 'order')
    list_filter = ('product__category',)
    search_fields = ('name', 'sku', 'product__name', 'product__sku')
    autocomplete_fields = ('product',)
    inlines = (ProductVariantCharacteristicInline,)
    actions = ('copy_characteristics_from_product',)

    @admin.action(description='Скопировать характеристики из товара')
    def copy_characteristics_from_product(self, request, queryset):
        count = 0
        for variant in queryset.select_related('product').prefetch_related('characteristics'):
            if variant.characteristics.exists():
                continue
            for ch in variant.product.characteristics.all():
                ProductVariantCharacteristic.objects.create(
                    variant=variant,
                    name=ch.name,
                    value=ch.value,
                )
                count += 1
        if count:
            self.message_user(request, f'Скопировано характеристик: {count}', messages.SUCCESS)
        else:
            self.message_user(request, 'Нечего копировать (у вариантов уже есть хар-ки или у товара их нет)', messages.WARNING)


class ProductAdminForm(forms.ModelForm):
    description_constructor_payload = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )

    class Meta:
        model = Product
        fields = '__all__'


@admin.register(Product)
class ProductAdmin(SortableAdminBase, admin.ModelAdmin):
    form = ProductAdminForm
    list_display = (
        'name',
        'sku',
        'image_preview',
        'category',
        'price',
        'price_on_request',
        'option_label',
        'is_active',
        'allow_order_on_request',
        'created_at',
    )
    list_filter = ('category', 'is_active', 'tags')
    search_fields = ('name', 'sku', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (
        ProductImageInline,
        ProductVideoInline,
        ProductCharacteristicInline,
        ProductContentBlockInline,
        ProductVariantInline,
        ProductStockInlineForProduct,
        ProductBundleItemInlineForProduct,
    )
    readonly_fields = ('created_at', 'updated_at', 'description_constructor')
    actions = ('export_catalog_with_images', 'backup_full_catalog',)
    change_form_template = 'admin/catalog/product/change_form.html'
    save_on_top = False
    fieldsets = (
        ('База карточки', {
            'fields': (
                'name',
                'sku',
                'category',
                'price',
                'price_on_request',
                'is_active',
                'allow_order_on_request',
                'avito_url',
                'ozon_url',
                'wildberries_url',
            ),
            'description': 'Минимум для публикации: название и категория. Можно заполнить цену из наличия, цену под заказ, обе сразу или оставить обе пустыми.',
            'classes': ('product-fieldset', 'product-fieldset--primary'),
        }),
        ('Публикация и структура', {
            'fields': ('slug', 'option_label', 'tags'),
            'description': 'Slug заполняется автоматически из названия. Подпись к вариантам и теги можно добавить позже.',
            'classes': ('product-fieldset', 'product-fieldset--secondary'),
        }),
        ('Служебное', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('product-fieldset', 'product-fieldset--meta', 'collapse'),
        }),
        ('Описание', {
            'fields': ('description', 'description_constructor'),
            'description': 'Краткое описание для карточки товара и конструктор подробного описания для витрины.',
            'classes': ('product-fieldset', 'product-fieldset--description'),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                ('База карточки', {
                    'fields': (
                        'name',
                        'sku',
                        'category',
                        'price',
                        'price_on_request',
                        'is_active',
                        'allow_order_on_request',
                        'avito_url',
                        'ozon_url',
                        'wildberries_url',
                    ),
                    'description': 'Сначала заполните название и категорию. Цену из наличия и цену под заказ можно указать сразу, по отдельности или позже.',
                    'classes': ('product-fieldset', 'product-fieldset--primary'),
                }),
                ('Описание', {
                    'fields': ('description', 'description_constructor'),
                    'description': 'Краткое описание для карточки товара и конструктор подробного описания для витрины.',
                    'classes': ('product-fieldset', 'product-fieldset--description'),
                }),
                ('Дополнительно', {
                    'fields': (
                        'slug',
                        'option_label',
                        'tags',
                    ),
                    'description': 'Slug сформируется автоматически. Здесь же задаются теги и подпись вариантов.',
                    'classes': ('product-fieldset', 'product-fieldset--secondary', 'collapse'),
                }),
            )
        return super().get_fieldsets(request, obj)

    def get_inline_instances(self, request, obj=None):
        inline_instances = super().get_inline_instances(request, obj)
        if not request.user.is_superuser:
            inline_instances = [
                inline for inline in inline_instances
                if not isinstance(inline, ProductContentBlockInline)
            ]
        for inline in inline_instances:
            if isinstance(inline, (ProductStockInlineForProduct, ProductBundleItemInlineForProduct)):
                inline.classes = ('collapse',) if obj is None else ()
        return inline_instances

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == 'tags':
            kwargs['widget'] = forms.CheckboxSelectMultiple(
                attrs={'data-product-admin-tags-widget': 'true'}
            )
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if not formfield:
            return formfield

        if db_field.name == 'sku':
            formfield.widget.attrs['data-product-admin-sku-field'] = 'true'

        if db_field.name == 'description':
            formfield.help_text = (
                'Рекомендуем 300-1200 символов: кратко опишите ключевые преимущества, '
                'комплектацию и для кого подходит товар.'
            )
            formfield.widget.attrs.update({
                'data-product-admin-description': 'true',
                'data-soft-min-length': '300',
                'data-soft-max-length': '1200',
                'rows': 10,
                'placeholder': 'Например: что входит в комплект, для кого подходит товар и чем он отличается от альтернатив.',
            })

        if db_field.name == 'option_label':
            formfield.help_text = (
                'Подпись над выбором вариантов на странице товара. '
                'Например: «Цвет», «Объём памяти» или «Комплектация».'
            )

        if db_field.name == 'price':
            formfield.help_text = 'Цена из наличия. Необязательна: можно оставить пустой и использовать только цену под заказ или сохранить товар без публичной цены.'

        if db_field.name == 'price_on_request':
            formfield.help_text = 'Цена под заказ. Необязательна: можно заполнить только её, заполнить обе цены или оставить поле пустым.'

        return formfield

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context['is_add_product'] = add
        context['product_admin_sections'] = (
            {'label': 'База', 'target': 'field-name', 'available_on_add': True},
            {'label': 'Описание', 'target': 'inline-description-group', 'available_on_add': True},
            {'label': 'Фото и видео', 'target': 'inline-images-group', 'available_on_add': True},
            {'label': 'Варианты', 'target': 'inline-variants-group', 'available_on_add': False},
            {'label': 'Остатки', 'target': 'inline-stocks-group', 'available_on_add': False},
            {'label': 'Комплекты', 'target': 'inline-bundle_items-group', 'available_on_add': False},
        )
        context['product_view_url'] = obj.get_absolute_url() if obj else ''
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    class Media:
        js = ('admin/js/product_image_paste.js', 'admin/js/product_admin.js', 'admin/js/product_description_constructor.js')
        css = {'all': ('admin/css/product_admin.css',)}

    def description_constructor(self, obj):
        state = build_admin_constructor_state(obj if obj and obj.pk else None)
        state_json = json.dumps(state, ensure_ascii=False)
        product_id = obj.pk if obj and obj.pk else 0

        return format_html(
            '''
            <div class="product-description-constructor"
                 data-product-description-constructor
                 data-templates-url="{}"
                 data-preview-url="{}">
              <textarea name="description_constructor_payload" data-pdc-payload hidden>{}</textarea>
              <div class="product-description-constructor__header">
                <div>
                  <strong>Подробное описание</strong>
                  <p>Все изменения сохраняются вместе с карточкой товара. Для показа на витрине включите публикацию и активность.</p>
                </div>
              </div>
              <section class="product-description-constructor__templates" aria-label="Шаблоны подробного описания">
                <div class="product-description-constructor__templates-head">
                  <div>
                    <strong>Выбор шаблона</strong>
                    <p>Выберите готовую структуру по карточкам ниже: у каждого шаблона сразу видно название, краткое описание и состав блоков. Применение только загружает заготовку в редактор ниже.</p>
                  </div>
                  <div class="product-description-constructor__template-selection" data-pdc-template-selection>
                    <strong>Сейчас в редакторе</strong>
                    <p>Загрузка...</p>
                  </div>
                </div>
                <div class="product-description-constructor__template-list" data-pdc-template-list></div>
              </section>
              <section class="product-description-constructor__settings" aria-label="Общие настройки подробного описания">
                <div class="product-description-constructor__panel-head">
                  <div>
                    <strong>1. Общие настройки</strong>
                    <p>Сначала задайте заголовок, вступление и статус публикации для всего подробного описания.</p>
                  </div>
                </div>
                <div class="product-description-constructor__meta">
                  <label>Заголовок <input type="text" data-pdc-title></label>
                  <label>Статус
                    <select data-pdc-status>
                      <option value="draft">Черновик</option>
                      <option value="published">Опубликовано</option>
                    </select>
                  </label>
                  <label class="product-description-constructor__checkbox"><input type="checkbox" data-pdc-active> Показывать на витрине</label>
                  <label>Вступление <textarea data-pdc-intro rows="4"></textarea></label>
                </div>
              </section>
              <div class="product-description-constructor__message" data-pdc-message></div>
              <section class="product-description-constructor__workspace" aria-label="Редактор блоков подробного описания">
                <div class="product-description-constructor__sidebar">
                  <div class="product-description-constructor__panel-head">
                    <div>
                      <strong>2. Блоки</strong>
                      <p>Добавляйте блоки, меняйте порядок, включайте и отключайте их прямо в списке.</p>
                    </div>
                  </div>
                  <div class="product-description-constructor__controls">
                    <label>Добавить блок <select data-pdc-block-type-select></select></label>
                    <button type="button" class="button" data-pdc-add-block>Добавить блок</button>
                  </div>
                  <div class="product-description-constructor__blocks" data-pdc-block-list></div>
                </div>
                <div class="product-description-constructor__main">
                  <div class="product-description-constructor__editor-panel">
                    <div class="product-description-constructor__panel-head">
                      <div>
                        <strong>3. Выбранный блок</strong>
                        <p>Сначала редактируйте быстрые поля. JSON нужен только для точечной ручной настройки.</p>
                      </div>
                    </div>
                    <div class="product-description-constructor__block-editor" data-pdc-block-editor>
                      <p>Выберите блок слева или добавьте новый.</p>
                    </div>
                  </div>
                  <div class="product-description-constructor__preview-panel">
                    <div class="product-description-constructor__panel-head">
                      <div>
                        <strong>4. Предпросмотр</strong>
                        <p data-pdc-preview-status>Обновляется автоматически при изменениях в настройках и блоках.</p>
                      </div>
                    </div>
                    <div class="product-description-constructor__preview" data-pdc-preview-target>
                      <p>Предпросмотр появится автоматически после первой синхронизации.</p>
                    </div>
                  </div>
                </div>
              </section>
            </div>
            ''',
            reverse('admin:catalog_product_description_templates'),
            reverse('admin:catalog_product_description_preview', args=[product_id]),
            state_json,
        )

    description_constructor.short_description = 'Конструктор'

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=80, height=80)

    image_preview.short_description = 'Превью'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category', 'product_description').prefetch_related(
            'tags',
            'variants',
            'characteristics',
            'content_blocks',
            'product_description__blocks__block_type',
            'images',
            'videos',
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        payload = request.POST.get('description_constructor_payload')
        if payload is not None:
            save_product_description_from_payload(obj, payload, user=request.user)
            invalidate_catalog_cache()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['restore_backup_url'] = 'admin:catalog_product_restore_backup'
        extra_context['import_catalog_json_url'] = 'admin:catalog_product_import_json'
        extra_context['commercial_proposal_url'] = 'admin:catalog_product_commercial_proposal'
        extra_context['can_export_commercial_proposal'] = request.user.has_perm('catalog.view_product')
        extra_context['can_restore_backup'] = self.has_restore_backup_permission(request)
        extra_context['can_import_catalog_json'] = self.has_import_catalog_json_permission(request)
        return super().changelist_view(request, extra_context=extra_context)

    def has_restore_backup_permission(self, request):
        return request.user.has_perm('catalog.can_restore_backup')

    def has_import_catalog_json_permission(self, request):
        return request.user.has_perm('catalog.can_import_catalog_json')

    @admin.action(description='Скачать каталог с картинками (ZIP)')
    def export_catalog_with_images(self, request, queryset):
        """
        Экспортирует выбранные товары (или все, если ничего не выбрано) в ZIP архив:
        - CSV файл с данными товаров
        - Папка images/ со всеми изображениями
        """
        # Если ничего не выбрано, экспортируем все активные товары
        if not queryset.exists():
            products = Product.objects.filter(is_active=True).select_related('category').prefetch_related(
                'characteristics', 'variants', 'images', 'tags'
            )
        else:
            products = queryset.select_related('category').prefetch_related(
                'characteristics', 'variants', 'images', 'tags'
            )

        # Создаём ZIP архив в памяти
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Создаём CSV файл
            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer, delimiter=';', quoting=csv.QUOTE_MINIMAL)

            # Заголовки CSV
            writer.writerow([
                'Название',
                'Цена продажи',
                'Артикул (slug)',
                'Категория',
                'Описание',
                'Характеристики',
            ])

            # Собираем изображения
            media_root = settings.MEDIA_ROOT
            images_added = set()  # Чтобы не дублировать одинаковые файлы

            for product in products.order_by('category__name', 'name'):
                # Собираем характеристики в строку
                characteristics = []
                for char in product.characteristics.all().order_by('name'):
                    characteristics.append(f'{char.name}: {char.value}')
                characteristics_str = '; '.join(characteristics)

                # Записываем строку товара в CSV
                writer.writerow([
                    product.name,
                    _decimal_to_str_or_empty(product.price),
                    product.slug,
                    product.category.name,
                    product.description or '',
                    characteristics_str,
                ])

                # Добавляем основное изображение товара
                if product.image:
                    image_path = product.image.path
                    if os.path.exists(image_path) and image_path not in images_added:
                        # Имя файла в архиве: images/product_slug_main.jpg
                        archive_name = f'images/{product.slug}_main{os.path.splitext(image_path)[1]}'
                        zip_file.write(image_path, archive_name)
                        images_added.add(image_path)

                # Добавляем изображения вариантов
                for variant in product.variants.all():
                    if variant.image:
                        variant_image_path = variant.image.path
                        if os.path.exists(variant_image_path) and variant_image_path not in images_added:
                            # Имя файла: images/product_slug_variant_variantname.jpg
                            safe_variant_name = variant.name.replace('/', '_').replace('\\', '_')
                            archive_name = f'images/{product.slug}_variant_{safe_variant_name}{os.path.splitext(variant_image_path)[1]}'
                            zip_file.write(variant_image_path, archive_name)
                            images_added.add(variant_image_path)

                # Добавляем дополнительные изображения товара
                for product_image in product.images.all().order_by('order', 'id'):
                    if product_image.image:
                        extra_image_path = product_image.image.path
                        if os.path.exists(extra_image_path) and extra_image_path not in images_added:
                            # Имя файла: images/product_slug_extra_N.jpg
                            archive_name = f'images/{product.slug}_extra_{product_image.order}{os.path.splitext(extra_image_path)[1]}'
                            zip_file.write(extra_image_path, archive_name)
                            images_added.add(extra_image_path)

            # Добавляем CSV файл в архив
            csv_content = csv_buffer.getvalue().encode('utf-8-sig')  # UTF-8 BOM для Excel
            zip_file.writestr('catalog_export.csv', csv_content)

        # Подготавливаем ответ
        zip_buffer.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'catalog_export_{timestamp}.zip'

        response = HttpResponse(zip_buffer.read(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(zip_buffer.getvalue())

        products_count = products.count()
        images_count = len(images_added)
        self.message_user(
            request,
            f'Экспорт завершён: {products_count} товаров, {images_count} изображений. Файл скачивается...',
            messages.SUCCESS
        )

        return response

    @admin.action(description='Создать полный бэкап каталога (ZIP)')
    def backup_full_catalog(self, request, queryset):
        """
        Создаёт полный бэкап всего каталога: все модели в JSON + изображения в ZIP архиве.
        Использует команду management backup_catalog.
        """
        from django.core.management import call_command
        from io import BytesIO
        
        # Создаём бэкап в памяти
        output_buffer = BytesIO()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_filename = f'/tmp/catalog_backup_{timestamp}.zip'
        
        try:
            # Вызываем команду бэкапа
            call_command('backup_catalog', output=temp_filename)
            
            # Читаем созданный файл
            with open(temp_filename, 'rb') as f:
                backup_data = f.read()
            
            # Удаляем временный файл
            os.remove(temp_filename)
            
            # Отправляем файл пользователю
            filename = f'catalog_backup_{timestamp}.zip'
            response = HttpResponse(backup_data, content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = len(backup_data)
            
            self.message_user(
                request,
                f'Полный бэкап каталога создан и скачивается: {filename}',
                messages.SUCCESS
            )
            
            return response
            
        except Exception as e:
            import traceback
            self.message_user(
                request,
                f'Ошибка при создании бэкапа: {str(e)}',
                messages.ERROR
            )
            return HttpResponseRedirect(request.path)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('restore-backup/', self.admin_site.admin_view(self.restore_backup_view), name='catalog_product_restore_backup'),
            path('import-json/', self.admin_site.admin_view(self.import_json_view), name='catalog_product_import_json'),
            path('import-json/<int:batch_id>/', self.admin_site.admin_view(self.import_json_review_view), name='catalog_product_import_json_review'),
            path(
                'import-json/<int:batch_id>/revalidate/',
                self.admin_site.admin_view(self.import_json_revalidate_view),
                name='catalog_product_import_json_revalidate',
            ),
            path(
                'import-json/<int:batch_id>/apply-clean/',
                self.admin_site.admin_view(self.import_json_apply_clean_view),
                name='catalog_product_import_json_apply_clean',
            ),
            path(
                'import-json/<int:batch_id>/apply-resolved/',
                self.admin_site.admin_view(self.import_json_apply_resolved_view),
                name='catalog_product_import_json_apply_resolved',
            ),
            path(
                'import-json/<int:batch_id>/conflicts/<int:conflict_id>/',
                self.admin_site.admin_view(self.import_json_save_conflict_view),
                name='catalog_product_import_json_conflict',
            ),
            path('commercial-proposal/', self.admin_site.admin_view(self.commercial_proposal_export_view), name='catalog_product_commercial_proposal'),
            path('product-search/', self.admin_site.admin_view(self.product_search_api_view), name='catalog_product_product_search'),
            path('product-content-blocks/<int:product_id>/', self.admin_site.admin_view(self.product_content_blocks_api_view), name='catalog_product_content_blocks'),
            path('description-templates/', self.admin_site.admin_view(self.description_templates_api_view), name='catalog_product_description_templates'),
            path('description-templates/<int:template_id>/', self.admin_site.admin_view(self.description_template_detail_api_view), name='catalog_product_description_template_detail'),
            path('<int:product_id>/description/preview/', self.admin_site.admin_view(self.product_description_preview_api_view), name='catalog_product_description_preview'),
            path('<int:product_id>/description/apply-template/', self.admin_site.admin_view(self.product_description_apply_template_api_view), name='catalog_product_description_apply_template'),
        ]
        return custom_urls + urls

    def _description_template_payload(self, template, *, include_slots=False):
        payload = serialize_template(template)
        if not include_slots:
            payload.pop('slots', None)
        return payload

    def description_templates_api_view(self, request):
        if not (
            request.user.has_perm('catalog.view_product')
            or request.user.has_perm('catalog.add_product')
            or request.user.has_perm('catalog.change_product')
        ):
            return HttpResponseForbidden('Недостаточно прав.')
        templates = DescriptionTemplate.objects.filter(is_active=True).prefetch_related('slots__block_type').order_by('category', 'name')
        return JsonResponse({
            'templates': [self._description_template_payload(template, include_slots=True) for template in templates],
        })

    def description_template_detail_api_view(self, request, template_id):
        if not (
            request.user.has_perm('catalog.view_product')
            or request.user.has_perm('catalog.add_product')
            or request.user.has_perm('catalog.change_product')
        ):
            return HttpResponseForbidden('Недостаточно прав.')
        template = get_object_or_404(
            DescriptionTemplate.objects.prefetch_related('slots__block_type'),
            pk=template_id,
            is_active=True,
        )
        return JsonResponse(self._description_template_payload(template, include_slots=True))

    def product_description_preview_api_view(self, request, product_id):
        if not (
            request.user.has_perm('catalog.view_product')
            or request.user.has_perm('catalog.add_product')
            or request.user.has_perm('catalog.change_product')
        ):
            return HttpResponseForbidden('Недостаточно прав.')
        if request.method != 'POST':
            return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
        product = get_object_or_404(Product, pk=product_id) if product_id else None
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Некорректный JSON.'}, status=400)
        html = render_description_preview(payload, product=product)
        return JsonResponse({'html': html})

    def product_description_apply_template_api_view(self, request, product_id):
        required_perm = 'catalog.change_product' if product_id else 'catalog.add_product'
        if not request.user.has_perm(required_perm):
            return HttpResponseForbidden('Недостаточно прав.')
        if request.method != 'POST':
            return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
        product = get_object_or_404(Product, pk=product_id) if product_id else None
        template_id = request.POST.get('template_id')
        if not template_id and request.body:
            try:
                template_id = (json.loads(request.body.decode('utf-8') or '{}') or {}).get('template_id')
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Некорректный JSON.'}, status=400)
        template = get_object_or_404(
            DescriptionTemplate.objects.prefetch_related('slots__block_type'),
            pk=template_id,
            is_active=True,
        )
        return JsonResponse({
            'ok': True,
            'payload': template_to_constructor_payload(template, product=product),
        })

    def product_search_api_view(self, request):
        """JSON API для поиска товаров по названию (автодополнение). Доступ при catalog.view_product."""
        if not request.user.has_perm('catalog.view_product'):
            return HttpResponseForbidden('Недостаточно прав.')
        q = (request.GET.get('q') or '').strip()
        if len(q) < 2:
            return HttpResponse(json.dumps([]), content_type='application/json')
        products = (
            Product.objects.filter(name__icontains=q)
            .select_related('category')
            .prefetch_related('variants', 'images')
            .order_by('category__name', 'name')[:15]
        )
        result = []
        for p in products:
            img = p.get_display_image()
            image_url = request.build_absolute_uri(img.url) if img else ''
            result.append({
                'id': p.pk,
                'name': p.name,
                'price': _decimal_to_str_or_empty(_product_default_price(p)),
                'category': p.category.name,
                'image_url': image_url,
            })
        return HttpResponse(json.dumps(result, ensure_ascii=False), content_type='application/json; charset=utf-8')

    def product_content_blocks_api_view(self, request, product_id):
        """JSON API: возвращает блоки подробного описания товара для копирования. Доступ при catalog.view_product."""
        if not request.user.has_perm('catalog.view_product'):
            return HttpResponseForbidden('Недостаточно прав.')
        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            from django.http import JsonResponse
            return JsonResponse({'error': 'Товар не найден.'}, status=404)
        blocks = (
            ProductContentBlock.objects
            .filter(product=product, is_active=True)
            .order_by('sort_order', 'id')
        )
        blocks_data = []
        for b in blocks:
            blocks_data.append({
                'id': b.pk,
                'block_type': b.block_type,
                'title': b.title or '',
                'text': b.text or '',
                'image_position': b.image_position or 'left',
                'caption': b.caption or '',
                'rutube_url': b.rutube_url or '',
                'sort_order': b.sort_order,
                'is_active': b.is_active,
            })
        result = {
            'product': {'id': product.pk, 'name': product.name},
            'blocks': blocks_data,
        }
        return HttpResponse(json.dumps(result, ensure_ascii=False), content_type='application/json; charset=utf-8')

    def commercial_proposal_export_view(self, request):
        """Формирование коммерческого предложения из выбранных товаров. Доступно при праве catalog.view_product (в т.ч. менеджерам)."""
        if not request.user.has_perm('catalog.view_product'):
            return HttpResponseForbidden('Недостаточно прав для формирования коммерческого предложения.')
        if request.method == 'POST':
            product_ids = request.POST.getlist('products')
            if not product_ids:
                messages.warning(request, 'Выберите хотя бы один товар.')
                return HttpResponseRedirect(request.path)
            products = (
                Product.objects.filter(pk__in=product_ids)
                .select_related('category')
                .prefetch_related('variants', 'images')
                .order_by('category__name', 'name')
            )
            rows = []
            total = Decimal('0')
            for idx, product in enumerate(products, 1):
                qty_str = request.POST.get(f'qty_{product.pk}', '1').strip() or '1'
                try:
                    qty = max(1, int(qty_str))
                except ValueError:
                    qty = 1
                price_str = request.POST.get(f'price_{product.pk}', '').strip()
                price = _parse_decimal_or_fallback(price_str, _product_default_price(product) or Decimal('0'))
                row_total = price * qty
                total += row_total
                img = product.get_display_image()
                image_url = request.build_absolute_uri(img.url) if img else ''
                rows.append({
                    'num': idx,
                    'name': product.name,
                    'category': product.category.name,
                    'description': product.description or '',
                    'image_url': image_url,
                    'price': price,
                    'qty': qty,
                    'row_total': row_total,
                })
            timestamp = timezone.now().strftime('%Y%m%d_%H%M')
            date_display = timezone.now().strftime('%d.%m.%Y')
            valid_until = (timezone.now() + timezone.timedelta(days=7)).strftime('%d.%m.%Y')
            work_terms = (request.POST.get('work_terms') or '').strip()
            delivery_terms = (request.POST.get('delivery_terms') or '').strip()
            manager_first_name = (request.user.first_name or '').strip()
            manager_last_name = (request.user.last_name or '').strip()
            manager_email = (getattr(request.user, 'email', '') or '').strip()
            manager_phone = ''
            # Приоритет: отдельные контакты для КП (не зависят от логина/профиля)
            try:
                cp_contact = request.user.cp_contact
                if getattr(cp_contact, 'email', ''):
                    manager_email = (cp_contact.email or '').strip()
                if getattr(cp_contact, 'phone', ''):
                    manager_phone = (cp_contact.phone or '').strip()
            except Exception:
                pass
            try:
                profile = request.user.profile
                if not manager_phone:
                    manager_phone = profile.phone or ''
            except Exception:
                pass
            if not manager_first_name and not manager_last_name:
                # fallback: хотя бы что-то показать
                fallback_name = request.user.get_full_name() or request.user.get_username() or ''
                manager_first_name = fallback_name
            if not manager_phone:
                manager_phone = getattr(settings, 'SITE_CONTACT_PHONE', '')
            site_url = getattr(settings, 'SITE_URL', '')
            site_brand = getattr(settings, 'SITE_BRAND', 'BizonVR')
            logo_path = getattr(settings, 'SITE_LOGO', '')
            logo_url = request.build_absolute_uri(settings.STATIC_URL + logo_path) if logo_path else ''
            site_phone = getattr(settings, 'SITE_CONTACT_PHONE', '')
            site_email = getattr(settings, 'SITE_CONTACT_EMAIL', '')
            site_address = getattr(settings, 'SITE_CONTACT_ADDRESS', '')
            html_content = build_commercial_proposal_html(
                rows=rows,
                total=total,
                date_display=date_display,
                valid_until=valid_until,
                manager_first_name=manager_first_name,
                manager_last_name=manager_last_name,
                manager_email=manager_email,
                manager_phone=manager_phone,
                site_url=site_url,
                site_brand=site_brand,
                logo_url=logo_url,
                site_phone=site_phone,
                site_email=site_email,
                site_address=site_address,
                work_terms=work_terms,
                delivery_terms=delivery_terms,
            )
            export_format = (request.POST.get('export_format') or 'pdf').lower()
            if export_format == 'pdf':
                try:
                    from weasyprint import HTML
                    pdf_bytes = HTML(
                        string=html_content,
                        base_url=request.build_absolute_uri('/'),
                    ).write_pdf()
                except Exception as e:
                    messages.error(request, f'Не удалось сформировать PDF: {e}. Скачайте HTML и сохраните в PDF через печать.')
                    export_format = 'html'
                else:
                    response = HttpResponse(pdf_bytes, content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="commercial_proposal_{timestamp}.pdf"'
                    return response
            response = HttpResponse(html_content, content_type='text/html; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="commercial_proposal_{timestamp}.html"'
            return response
        context = {
            **self.admin_site.each_context(request),
            'title': 'Коммерческое предложение',
            'opts': self.model._meta,
            'has_view_permission': True,
        }
        return TemplateResponse(request, 'admin/catalog/commercial_proposal_export.html', context)

    def restore_backup_view(self, request):
        """Представление для восстановления каталога из бэкапа."""
        if not self.has_restore_backup_permission(request):
            raise PermissionDenied

        if request.method == 'POST':
            backup_file = request.FILES.get('backup_file')
            clear = request.POST.get('clear') == 'on'
            
            if not backup_file:
                messages.error(request, 'Не выбран файл бэкапа')
                context = {
                    **self.admin_site.each_context(request),
                    'title': 'Восстановление каталога из бэкапа',
                    'opts': self.model._meta,
                    'has_view_permission': True,
                }
                return TemplateResponse(request, 'admin/catalog/restore_backup.html', context)
            
            temp_dir = tempfile.mkdtemp()
            temp_file_path = ''

            try:
                with tempfile.NamedTemporaryFile(dir=temp_dir, suffix='.zip', delete=False) as temp_file:
                    temp_file_path = temp_file.name
                    for chunk in backup_file.chunks():
                        temp_file.write(chunk)

                # Вызываем команду восстановления
                from django.core.management import call_command
                call_command('restore_catalog', temp_file_path, clear=clear)

                messages.success(request, 'Каталог успешно восстановлен из бэкапа!')
                invalidate_catalog_cache()

            except Exception as e:
                messages.error(request, f'Ошибка при восстановлении: {e}')
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)

            return HttpResponseRedirect('../../')

        context = {
            **self.admin_site.each_context(request),
            'title': 'Восстановление каталога из бэкапа',
            'opts': self.model._meta,
            'has_view_permission': True,
        }
        return TemplateResponse(request, 'admin/catalog/restore_backup.html', context)

    def import_json_view(self, request):
        if not self.has_import_catalog_json_permission(request):
            raise PermissionDenied

        context = self._import_json_upload_context(request)

        if request.method != 'POST':
            return TemplateResponse(request, 'admin/catalog/import_json.html', context)

        json_file = request.FILES.get('json_file')
        dry_run = request.POST.get('dry_run') == 'on'
        context['dry_run'] = dry_run

        if not json_file:
            messages.error(request, 'Не выбран JSON-файл.')
            return TemplateResponse(request, 'admin/catalog/import_json.html', context)

        try:
            payload = _load_uploaded_json(json_file)
            batch = CatalogImportWorkflowService.create_batch(
                payload=payload,
                source_filename=json_file.name or 'catalog.json',
            )
        except (ValueError, CatalogImportError) as exc:
            messages.error(request, f'Ошибка импорта: {exc}')
            return TemplateResponse(request, 'admin/catalog/import_json.html', context)

        if dry_run:
            messages.success(request, 'Проверка JSON завершена. Изменения в БД не применялись, пакет открыт в режиме review.')
        else:
            messages.success(request, 'Файл загружен. Проверьте конфликтующие записи и примените готовые изменения.')

        return HttpResponseRedirect(reverse('admin:catalog_product_import_json_review', args=[batch.pk]))

    def import_json_review_view(self, request, batch_id):
        batch = self._get_import_batch(request, batch_id)
        context = self._import_json_review_context(request, batch)
        return TemplateResponse(request, 'admin/catalog/import_json_review.html', context)

    def import_json_revalidate_view(self, request, batch_id):
        batch = self._get_import_batch(request, batch_id)
        if request.method != 'POST':
            raise Http404
        CatalogImportWorkflowService(batch).analyze_and_persist()
        messages.success(request, 'Пакет перепроверен с учётом текущих правок и состояния БД.')
        return HttpResponseRedirect(reverse('admin:catalog_product_import_json_review', args=[batch.pk]))

    def import_json_apply_clean_view(self, request, batch_id):
        batch = self._get_import_batch(request, batch_id)
        if request.method != 'POST':
            raise Http404
        workflow = CatalogImportWorkflowService(batch)
        error = workflow.apply_clean_rows()
        if error:
            messages.error(request, f'Не удалось применить готовые записи: {error}')
        else:
            invalidate_catalog_cache()
            messages.success(request, 'Готовые записи применены.')
        return HttpResponseRedirect(reverse('admin:catalog_product_import_json_review', args=[batch.pk]))

    def import_json_apply_resolved_view(self, request, batch_id):
        batch = self._get_import_batch(request, batch_id)
        if request.method != 'POST':
            raise Http404
        workflow = CatalogImportWorkflowService(batch)
        error = workflow.apply_resolved_rows()
        if error:
            messages.error(request, f'Не удалось применить разрешённые конфликты: {error}')
        else:
            invalidate_catalog_cache()
            messages.success(request, 'Разрешённые конфликты применены.')
        return HttpResponseRedirect(reverse('admin:catalog_product_import_json_review', args=[batch.pk]))

    def import_json_save_conflict_view(self, request, batch_id, conflict_id):
        batch = self._get_import_batch(request, batch_id)
        if request.method != 'POST':
            raise Http404
        conflict = get_object_or_404(CatalogImportConflict, batch=batch, pk=conflict_id)
        CatalogImportWorkflowService(batch).save_conflict_resolution(conflict, request.POST)
        messages.success(request, f'Конфликт для "{conflict.item_label or conflict.collection_name}" обновлён и перепроверен.')
        return HttpResponseRedirect(reverse('admin:catalog_product_import_json_review', args=[batch.pk]))

    def _get_import_batch(self, request, batch_id):
        if not self.has_import_catalog_json_permission(request):
            raise PermissionDenied
        return get_object_or_404(CatalogImportBatch, pk=batch_id)

    def _import_json_upload_context(self, request):
        return {
            **self.admin_site.each_context(request),
            'title': 'Импорт каталога из JSON',
            'opts': self.model._meta,
            'has_view_permission': True,
            'dry_run': False,
        }

    def _import_json_review_context(self, request, batch):
        summary = batch.summary or {}
        active_conflicts = batch.conflicts.exclude(status=CatalogImportConflict.Status.CLEARED).order_by(
            'status',
            'collection_name',
            'source_index',
        )
        pending_conflicts = []
        resolved_conflicts = []
        applied_conflicts = []
        for conflict in active_conflicts:
            card = self._build_import_conflict_card(conflict)
            if conflict.status == CatalogImportConflict.Status.PENDING:
                pending_conflicts.append(card)
            elif conflict.status == CatalogImportConflict.Status.RESOLVED:
                resolved_conflicts.append(card)
            elif conflict.status == CatalogImportConflict.Status.APPLIED:
                applied_conflicts.append(card)

        return {
            **self.admin_site.each_context(request),
            'title': f'Проверка импорта JSON #{batch.pk}',
            'opts': self.model._meta,
            'has_view_permission': True,
            'batch': batch,
            'summary_counts': summary.get('counts', {}),
            'ready_items': summary.get('ready', []),
            'noop_items': summary.get('noop', []),
            'blocking_items': summary.get('blocking_issues', []),
            'warnings': summary.get('warnings', []),
            'pending_conflicts': pending_conflicts,
            'resolved_conflicts': resolved_conflicts,
            'applied_conflicts': applied_conflicts,
            'review_url': reverse('admin:catalog_product_import_json_review', args=[batch.pk]),
            'upload_url': reverse('admin:catalog_product_import_json'),
            'revalidate_url': reverse('admin:catalog_product_import_json_revalidate', args=[batch.pk]),
            'apply_clean_url': reverse('admin:catalog_product_import_json_apply_clean', args=[batch.pk]),
            'apply_resolved_url': reverse('admin:catalog_product_import_json_apply_resolved', args=[batch.pk]),
        }

    def _build_import_conflict_card(self, conflict):
        fields = []
        for field_name, meta in (conflict.field_conflicts or {}).items():
            resolution = (conflict.resolutions or {}).get(field_name, {})
            field_type = meta.get('field_type') or 'text'
            manual_value = resolution.get('value')
            if field_type == 'fk' and isinstance(manual_value, dict):
                manual_value = manual_value.get('target_pk', '')
            elif field_type == 'multiselect':
                manual_value = [
                    str(item.get('target_pk') if isinstance(item, dict) else item)
                    for item in (manual_value or [])
                ]
            elif field_type == 'bool':
                manual_value = '1' if manual_value in (True, '1', 1, 'true', 'True') else '0'
            elif manual_value is None:
                manual_value = ''
            else:
                manual_value = str(manual_value)

            options = meta.get('options') or []
            if field_type == 'bool' and not options:
                options = [
                    {'value': '1', 'label': 'Да'},
                    {'value': '0', 'label': 'Нет'},
                ]

            fields.append(
                {
                    'name': field_name,
                    'label': meta.get('label') or field_name,
                    'field_type': field_type,
                    'options': options,
                    'current_display': _display_import_value(meta.get('current_value')),
                    'incoming_display': _display_import_value(meta.get('incoming_value')),
                    'chosen_display': _display_import_value(meta.get('chosen_value')),
                    'resolution_mode': resolution.get('mode', ''),
                    'manual_value': manual_value,
                    'resolution_error': meta.get('resolution_error', ''),
                }
            )

        return {
            'id': conflict.pk,
            'item_label': conflict.item_label or f'{_collection_label(conflict.collection_name)} #{conflict.source_index}',
            'collection_label': _collection_label(conflict.collection_name),
            'status_label': _status_badge(conflict.status),
            'conflict_kind': conflict.conflict_kind,
            'source_id': conflict.source_id,
            'admin_change_url': admin_change_url(conflict.target_model, conflict.target_pk),
            'save_url': reverse('admin:catalog_product_import_json_conflict', args=[conflict.batch_id, conflict.pk]),
            'fields': fields,
        }


@admin.register(ProductContentBlock)
class ProductContentBlockAdmin(admin.ModelAdmin):
    list_display = ('product', 'block_type', 'title', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('block_type', 'is_active', 'product__category')
    search_fields = ('product__name', 'title', 'text', 'caption')
    autocomplete_fields = ('product',)
    ordering = ('product', 'sort_order', 'id')

    def get_model_perms(self, request):
        if request.user.is_superuser:
            return super().get_model_perms(request)
        return {}

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
