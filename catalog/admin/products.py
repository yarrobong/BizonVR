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
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
from django.utils import timezone

from ..cache_utils import invalidate_catalog_cache
from ..models import (
    Product,
    ProductCharacteristic,
    ProductContentBlock,
    ProductImage,
    ProductVideo,
    ProductVariant,
    ProductVariantCharacteristic,
)
from .bundles import ProductBundleItemInlineForProduct
from .location import ProductStockInlineForProduct
from .proposal_html import build_commercial_proposal_html
from .shared import _admin_image_preview


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

@admin.register(Product)
class ProductAdmin(SortableAdminBase, admin.ModelAdmin):
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
    readonly_fields = ('created_at', 'updated_at')
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
            'description': 'Минимум для публикации: название, категория и цена.',
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
            'fields': ('description',),
            'description': 'Краткое описание для карточки товара в каталоге. Рекомендуем 300–1200 символов.',
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
                    'description': 'Сначала заполните название, категорию и цену. Описание можно добавить здесь же или на вкладке «Описание».',
                    'classes': ('product-fieldset', 'product-fieldset--primary'),
                }),
                ('Описание', {
                    'fields': ('description',),
                    'description': 'Краткое описание для карточки товара в каталоге. Рекомендуем 300–1200 символов.',
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
            formfield.help_text = 'Текущая цена из наличия. Именно она используется в каталоге для сортировки и фильтрации.'

        if db_field.name == 'price_on_request':
            formfield.help_text = 'Более низкая цена для покупки под заказ. Если не заполнена, товар продаётся только по цене из наличия.'

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
        js = ('admin/js/product_image_paste.js', 'admin/js/product_admin.js')
        css = {'all': ('admin/css/product_admin.css',)}

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=80, height=80)

    image_preview.short_description = 'Превью'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category').prefetch_related(
            'tags',
            'variants',
            'characteristics',
            'content_blocks',
            'images',
            'videos',
        )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['restore_backup_url'] = 'admin:catalog_product_restore_backup'
        extra_context['commercial_proposal_url'] = 'admin:catalog_product_commercial_proposal'
        extra_context['can_export_commercial_proposal'] = request.user.has_perm('catalog.view_product')
        extra_context['can_restore_backup'] = self.has_restore_backup_permission(request)
        return super().changelist_view(request, extra_context=extra_context)

    def has_restore_backup_permission(self, request):
        return request.user.has_perm('catalog.can_restore_backup')

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
                    str(product.price),
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
            path('commercial-proposal/', self.admin_site.admin_view(self.commercial_proposal_export_view), name='catalog_product_commercial_proposal'),
            path('product-search/', self.admin_site.admin_view(self.product_search_api_view), name='catalog_product_product_search'),
            path('product-content-blocks/<int:product_id>/', self.admin_site.admin_view(self.product_content_blocks_api_view), name='catalog_product_content_blocks'),
        ]
        return custom_urls + urls

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
                'price': str(p.price),
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
                if price_str:
                    try:
                        price = Decimal(price_str.replace(',', '.'))
                        if price < 0:
                            price = product.price
                    except Exception:
                        price = product.price
                else:
                    price = product.price
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


@admin.register(ProductContentBlock)
class ProductContentBlockAdmin(admin.ModelAdmin):
    list_display = ('product', 'block_type', 'title', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('block_type', 'is_active', 'product__category')
    search_fields = ('product__name', 'title', 'text', 'caption')
    autocomplete_fields = ('product',)
    ordering = ('product', 'sort_order', 'id')
