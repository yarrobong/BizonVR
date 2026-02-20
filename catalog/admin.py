import csv
import io
import os
import zipfile
from datetime import datetime

from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path
from django.utils.html import format_html

from .cache_utils import invalidate_catalog_cache
from .models import (
    CallbackRequest,
    CartItem,
    CatalogSection,
    Category,
    City,
    ContactRequest,
    Favorite,
    PickupPoint,
    Product,
    ProductBundle,
    ProductBundleItem,
    ProductCharacteristic,
    ProductImage,
    ProductStock,
    ProductTag,
    ProductVariant,
    ProductVariantCharacteristic,
    Service,
)


@admin.register(CatalogSection)
class CatalogSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'has_icon')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    fields = ('name', 'slug', 'order', 'icon')
    
    def has_icon(self, obj):
        return bool(obj.icon)
    has_icon.boolean = True
    has_icon.short_description = 'Есть иконка'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


class ProductCharacteristicInline(admin.TabularInline):
    model = ProductCharacteristic
    extra = 1


def _admin_image_preview(obj, width=60, height=60):
    """Превью изображения для админки."""
    if obj and getattr(obj, 'image', None) and obj.image:
        return format_html(
            '<img src="{}" width="{}" height="{}" style="object-fit: cover; border-radius: 4px;" />',
            obj.image.url, width, height
        )
    return '—'


class ProductVariantCharacteristicInline(admin.TabularInline):
    model = ProductVariantCharacteristic
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ('image_preview', 'name', 'image', 'price_override', 'order')
    readonly_fields = ('image_preview',)
    show_change_link = True

    def image_preview(self, obj):
        return _admin_image_preview(obj)

    image_preview.short_description = 'Превью'


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ('image_preview', 'image', 'order')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        return _admin_image_preview(obj)

    image_preview.short_description = 'Превью'


class ProductStockInlineForProduct(admin.TabularInline):
    """Остатки товара по точкам выдачи. Наличие в городе = сумма остатков по точкам этого города."""
    model = ProductStock
    fk_name = 'product'
    extra = 0
    autocomplete_fields = ('pickup_point', 'variant')
    readonly_fields = ('stock_city',)
    fields = ('pickup_point', 'stock_city', 'variant', 'quantity')

    def stock_city(self, obj):
        if obj and obj.pickup_point_id:
            return obj.pickup_point.city.name
        return '—'
    stock_city.short_description = 'Город'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'variant':
            parent_obj = getattr(request, '_product_stock_parent_obj', None)
            if parent_obj and hasattr(parent_obj, 'variants'):
                kwargs['queryset'] = parent_obj.variants.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_formset(self, request, obj=None, **kwargs):
        if obj:
            request._product_stock_parent_obj = obj
        return super().get_formset(request, obj, **kwargs)


class ProductStockInlineForPickupPoint(admin.TabularInline):
    model = ProductStock
    fk_name = 'pickup_point'
    extra = 0
    autocomplete_fields = ('product', 'variant')


class PickupPointInline(admin.TabularInline):
    """Точки выдачи в городе — наличие товаров в городе задаётся остатками в этих точках."""
    model = PickupPoint
    extra = 1
    ordering = ('order', 'name')
    fields = ('name', 'address', 'order')


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'pickup_points_count')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    inlines = (PickupPointInline,)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()

    def pickup_points_count(self, obj):
        if obj is None:
            return '—'
        return obj.pickup_points.count()
    pickup_points_count.short_description = 'Точек выдачи'


@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'address', 'order')
    list_filter = ('city',)
    search_fields = ('name', 'address')
    inlines = (ProductStockInlineForPickupPoint,)
    ordering = ('city', 'order', 'name')


@admin.register(ProductStock)
class ProductStockAdmin(admin.ModelAdmin):
    list_display = ('product', 'variant', 'pickup_point', 'quantity')
    list_filter = ('pickup_point__city', 'pickup_point')
    search_fields = ('product__name',)
    autocomplete_fields = ('product', 'variant', 'pickup_point')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'section', 'tile_size', 'is_bundles_category', 'has_icon')
    list_editable = ('tile_size',)
    list_filter = ('section', 'is_bundles_category')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    fields = ('name', 'slug', 'section', 'icon', 'tile_size', 'is_bundles_category')
    
    def has_icon(self, obj):
        return bool(obj.icon)
    has_icon.boolean = True
    has_icon.short_description = 'Есть иконка'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


class ProductBundleItemInline(admin.TabularInline):
    model = ProductBundleItem
    extra = 1
    autocomplete_fields = ('product',)
    fields = ('product', 'quantity', 'price_preview')
    readonly_fields = ('price_preview',)

    def price_preview(self, obj):
        if obj and obj.product_id:
            return f'{obj.effective_price} ₽ (−5%)'
        return '—'
    price_preview.short_description = 'Цена в комплекте'


class ProductBundleItemInlineForProduct(admin.TabularInline):
    """Участие товара в комплектах — редактируется при редактировании товара."""
    model = ProductBundleItem
    fk_name = 'product'
    extra = 1
    autocomplete_fields = ('bundle',)
    fields = ('bundle', 'quantity', 'price_preview')
    readonly_fields = ('price_preview',)
    verbose_name = 'Позиция в комплекте'
    verbose_name_plural = 'Участие в комплектах'

    def price_preview(self, obj):
        if obj and obj.product_id:
            return f'{obj.effective_price} ₽ (−5%)'
        return '—'
    price_preview.short_description = 'Цена в комплекте'


@admin.register(ProductBundle)
class ProductBundleAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'items_count', 'bundle_total')
    inlines = (ProductBundleItemInline,)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('image_preview',)
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'image_preview', 'image'),
        }),
    )

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=120, height=120)
    image_preview.short_description = 'Превью'

    def items_count(self, obj):
        return obj.items.count() if obj.pk else 0

    items_count.short_description = 'Позиций'

    def bundle_total(self, obj):
        if obj.pk:
            total = sum(float(i.effective_price) * i.quantity for i in obj.items.all())
            return f'{total:,.0f} ₽'.replace(',', ' ')
        return '—'

    bundle_total.short_description = 'Сумма набора'


@admin.register(ProductTag)
class ProductTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('name', 'product', 'price_override', 'order')
    list_filter = ('product__category',)
    search_fields = ('name', 'product__name')
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
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'image_preview', 'category', 'price', 'option_label', 'is_active', 'allow_order_on_request', 'created_at')
    list_filter = ('category', 'is_active', 'tags')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (ProductVariantInline, ProductImageInline, ProductCharacteristicInline, ProductStockInlineForProduct, ProductBundleItemInlineForProduct)
    readonly_fields = ('created_at', 'updated_at', 'image_preview')
    filter_horizontal = ('tags',)
    actions = ('export_catalog_with_images', 'backup_full_catalog',)
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'category', 'price', 'description', 'image_preview', 'image', 'is_active', 'allow_order_on_request', 'option_label', 'tags', 'created_at', 'updated_at'),
        }),
    )

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=80, height=80)

    image_preview.short_description = 'Превью'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category').prefetch_related('tags', 'variants', 'characteristics', 'images')

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['restore_backup_url'] = 'admin:catalog_product_restore_backup'
        return super().changelist_view(request, extra_context=extra_context)

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
        ]
        return custom_urls + urls

    def restore_backup_view(self, request):
        """Представление для восстановления каталога из бэкапа."""
        from django.contrib.admin.views.decorators import staff_member_required
        from django.template.response import TemplateResponse
        
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
            
            # Сохраняем загруженный файл во временную директорию
            import tempfile
            temp_dir = tempfile.mkdtemp()
            temp_file_path = os.path.join(temp_dir, backup_file.name)
            
            try:
                with open(temp_file_path, 'wb') as f:
                    for chunk in backup_file.chunks():
                        f.write(chunk)
                
                # Вызываем команду восстановления
                from django.core.management import call_command
                call_command('restore_catalog', temp_file_path, clear=clear)
                
                messages.success(request, 'Каталог успешно восстановлен из бэкапа!')
                invalidate_catalog_cache()
                
            except Exception as e:
                import traceback
                error_msg = str(e)
                self.stdout.write(traceback.format_exc())
                messages.error(request, f'Ошибка при восстановлении: {error_msg}')
            finally:
                # Удаляем временный файл
                if os.path.exists(temp_file_path):
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


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'variant', 'quantity')
    list_filter = ('user',)
    search_fields = ('product__name',)
    raw_id_fields = ('user', 'product', 'variant')


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'email', 'message')
    readonly_fields = ('name', 'email', 'phone', 'message', 'created_at')


@admin.register(CallbackRequest)
class CallbackRequestAdmin(admin.ModelAdmin):
    list_display = ('phone', 'name', 'source', 'created_at')
    list_filter = ('source', 'created_at')
    search_fields = ('phone', 'name')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'price_from', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'short_description', 'description')
    fields = ('name', 'short_description', 'description', 'icon', 'price_from', 'order', 'is_active')


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('product__name',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('user', 'product')
