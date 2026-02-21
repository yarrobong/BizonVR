import csv
import io
import os
import zipfile
from datetime import datetime

from django.conf import settings
import json

from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import escape, format_html
from django.utils import timezone
from decimal import Decimal

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
        extra_context['commercial_proposal_url'] = 'admin:catalog_product_commercial_proposal'
        extra_context['can_export_commercial_proposal'] = request.user.has_perm('catalog.view_product')
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
            path('commercial-proposal/', self.admin_site.admin_view(self.commercial_proposal_export_view), name='catalog_product_commercial_proposal'),
            path('product-search/', self.admin_site.admin_view(self.product_search_api_view), name='catalog_product_product_search'),
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
            html_content = self._build_commercial_proposal_html(
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

    def _build_commercial_proposal_html(
        self,
        rows,
        total,
        date_display,
        valid_until,
        manager_first_name,
        manager_last_name,
        manager_email,
        manager_phone,
        site_url,
        site_brand,
        logo_url,
        site_phone,
        site_email,
        site_address,
    ):
        """Собирает HTML-документ коммерческого предложения в стиле kp.html (тёмная тема, неоновые акценты)."""
        def _fmt(val):
            """Форматирование денег: 260000 -> 260 000; 12500.5 -> 12 500,50."""
            try:
                d = Decimal(str(val))
            except Exception:
                d = Decimal('0')
            d = d.quantize(Decimal('0.01'))
            if d == d.to_integral():
                return f'{int(d):,}'.replace(',', ' ')
            # RU-формат: пробелы в тысячах + запятая в дробной части
            return f'{d:,.2f}'.replace(',', ' ').replace('.', ',')

        def _truncate_for_desc(text: str, max_chars: int = 160) -> str:
            """Обрезка описания с добавлением троеточия (для HTML/PDF)."""
            t = (text or '').replace('\n', ' ').replace('\r', ' ').strip()
            t = ' '.join(t.split())
            if len(t) <= max_chars:
                return t
            cut = t[:max_chars].rstrip()
            if cut.endswith(('…', '.', ',', ';', ':')):
                cut = cut.rstrip('. ,;:')
            return cut + '…'

        css = '''
        @page { size: A4; margin: 0; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: #0b0d14;
            display: flex;
            justify-content: center;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            color: #e5e7eb;
            padding: 18px 0;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }
        .a4-page {
            width: 210mm;
            min-height: 297mm;
            background: linear-gradient(180deg, #0b0d14 0%, #151923 100%);
            padding: 14mm 14mm;
            border-radius: 25px;
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.12);
            box-shadow:
              0 25px 50px -12px rgba(0,0,0,0.35),
              0 0 0 1px rgba(255,255,255,0.06),
              0 0 40px rgba(0,212,255,0.10);
        }
        .a4-page::before {
            content: '';
            position: absolute;
            top: 0; left: 0; width: 100%; height: 3px;
            background: linear-gradient(90deg, #00D4FF, rgba(188, 19, 254, 0.55), rgba(0,0,0,0));
            box-shadow: 0 0 14px rgba(0, 212, 255, 0.55);
        }
        
        .header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 26px;
            border-bottom: 1px solid rgba(255,255,255,0.10); padding-bottom: 18px; }
        .brand-logo {
            font-size: 34px;
            font-weight: 900;
            color: #ffffff;
            letter-spacing: 1px;
            font-family: "Orbitron", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
            text-shadow: 0 0 14px rgba(0, 212, 255, 0.35);
            margin-bottom: 4px;
        }
        .brand-logo img { max-height: 52px; max-width: 220px; display: block;
            filter: drop-shadow(0 0 10px rgba(0, 212, 255, 0.28)); }
        .brand-subtitle { font-size: 12px; color: rgba(0, 212, 255, 0.92); text-transform: uppercase; letter-spacing: 3px; }
        .contacts { text-align: right; font-size: 12px; line-height: 1.6; color: rgba(229,231,235,0.70); }
        .contacts span { color: rgba(0, 212, 255, 0.95); font-weight: 700; }
        .title-block { text-align: center; margin-bottom: 22px; }
        .title-block h1 { font-size: 26px; text-transform: uppercase; color: #ffffff; margin-bottom: 10px;
            letter-spacing: 2.5px; text-shadow: 0 0 14px rgba(0, 212, 255, 0.35); }
        .title-block p { font-size: 13px; color: rgba(0, 212, 255, 0.85); }
        .info-panel { display: flex; justify-content: space-between;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.10);
            border-left: 3px solid rgba(0, 212, 255, 0.95);
            padding: 14px 16px; margin-bottom: 22px; font-size: 13px;
            border-radius: 25px; }
        .info-panel strong { color: #fff; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 30px; table-layout: fixed; }
        th { background: rgba(255,255,255,0.06); color: #ffffff; text-transform: uppercase; font-size: 11px;
            letter-spacing: 1px; padding: 10px 8px; text-align: left;
            border-bottom: 2px solid rgba(0, 212, 255, 0.55); }
        td { padding: 12px 8px; font-size: 13px; border-bottom: 1px solid rgba(255, 255, 255, 0.05); vertical-align: middle; word-break: break-word; }
        tr:hover td { background: rgba(0, 243, 255, 0.03); }
        .item-photo { width: 60px; height: 60px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
        .item-photo img { width: 60px; height: 60px; object-fit: contain; }
        .col-num { width: 5%; text-align: center; }
        .col-photo { width: 10%; }
        .col-name { width: 15%; font-weight: bold; color: #fff; }
        .col-desc { width: 20%; color: #888; font-size: 10px; line-height: 1.35; }
        .col-desc .desc-clamp {
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
            max-height: calc(1.35em * 3);
        }
        .col-qty { width: 10%; text-align: center; }
        .col-price { width: 10%; white-space: nowrap; text-align: right; }
        .col-sum { width: 10%; font-weight: bold; color: rgba(0, 212, 255, 0.95); white-space: nowrap; text-align: right; }
        .footer-block { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 40px; }
        .total-box { background: rgba(0, 212, 255, 0.08); padding: 14px 22px; border-radius: 25px;
            border: 1px solid rgba(0, 212, 255, 0.24); box-shadow: 0 0 20px rgba(0, 212, 255, 0.12); }
        .total-box .total-label { font-size: 13px; color: rgba(229,231,235,0.72); margin-right: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
        .total-box .total-amount { font-size: 22px; font-weight: 900; color: #ffffff; text-shadow: 0 0 14px rgba(0, 212, 255, 0.28); }
        .date-signature { display: flex; justify-content: space-between; font-size: 12px; color: #666;
            border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px; }
        .legal-note { margin-top: 14px; font-size: 11px; line-height: 1.45; color: rgba(229,231,235,0.65); }
        @media print {
            body { padding: 0; background-color: #0b0d14; }
            .a4-page { box-shadow: none; margin: 0; border: none; border-radius: 0; }
            tr:hover td { background: transparent; }
        }
        '''
        lines = [
            '<!DOCTYPE html>',
            '<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f'<title>Коммерческое предложение - {escape(site_brand)}</title>',
            '<style>', css.strip(), '</style></head><body>',
            '<div class="a4-page">',
            '<div class="header">',
            '<div>',
        ]
        if logo_url:
            lines.append(f'<div class="brand-logo"><img src="{escape(logo_url)}" alt="" style="max-height: 48px;"></div>')
        else:
            lines.append(f'<div class="brand-logo">{escape(site_brand)}</div>')
        lines.append('<div class="brand-subtitle">Виртуальная реальность</div>')
        lines.append('</div>')
        lines.append('<div class="contacts">')
        if site_phone:
            lines.append(f'<p><span>Тел:</span> {escape(site_phone)}</p>')
        if site_email:
            lines.append(f'<p><span>Email:</span> {escape(site_email)}</p>')
        if site_url:
            lines.append(f'<p><span>Сайт:</span> {escape(site_url)}</p>')
        lines.append('</div></div>')
        lines.append('<div class="title-block">')
        lines.append('<h1>Коммерческое предложение</h1>')
        # Строку про «Официальный документ / Действительно до ...» убрали — срок указан внизу (7 дней).
        lines.append('</div>')
        lines.append('<div class="info-panel">')
        lines.append('<div>')
        manager_full_name = f'{(manager_last_name or "").strip()} {(manager_first_name or "").strip()}'.strip() or '—'
        lines.append(f'Менеджер: <strong>{escape(manager_full_name)}</strong><br>')
        lines.append(f'Телефон для связи: <strong>{escape(manager_phone) or "—"}</strong>')
        lines.append('</div></div>')
        lines.append('<table>')
        lines.append(
            '<thead><tr><th class="col-num">№</th><th class="col-photo">Фото</th><th class="col-name">Название</th>'
            '<th class="col-desc">Описание</th><th class="col-qty">Кол-во</th><th class="col-price">Цена (₽)</th>'
            '<th class="col-sum">Итого (₽)</th></tr></thead><tbody>'
        )
        for r in rows:
            if r.get('image_url'):
                photo_cell = f'<div class="item-photo"><img src="{escape(r["image_url"])}" alt=""></div>'
            else:
                photo_cell = '<div class="item-photo">—</div>'
            desc = escape(_truncate_for_desc(r.get('description') or '', max_chars=160))
            price_fmt = _fmt(r['price'])
            sum_fmt = _fmt(r['row_total'])
            lines.append(
                f'<tr><td class="col-num" style="text-align: center;">{r["num"]}</td>'
                f'<td class="col-photo">{photo_cell}</td>'
                f'<td class="col-name">{escape(r["name"])}</td><td class="col-desc"><div class="desc-clamp">{desc}</div></td>'
                f'<td class="col-qty">{r["qty"]}</td><td class="col-price">{price_fmt} ₽</td>'
                f'<td class="col-sum">{sum_fmt} ₽</td></tr>'
            )
        lines.append('</tbody></table>')
        total_fmt = _fmt(total)
        lines.append(
            '<div class="footer-block">'
            '<div class="total-box">'
            '<span class="total-label">Итого к оплате:</span>'
            f'<span class="total-amount">{total_fmt} ₽</span>'
            '</div></div>'
        )
        lines.append(
            '<div class="date-signature">'
            f'<div>Дата составления: <strong>{escape(date_display)}</strong></div>'
            '</div>'
        )
        lines.append(
            '<div class="legal-note">'
            'Данное коммерческое предложение является официальным и действует в течение 7 дней с даты составления.<br>'
            'Цена не включает в себя доставку. Доставка оплачивается покупателем при получении.'
            '</div>'
        )
        lines.append('</div></body></html>')
        return '\n'.join(lines)

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
