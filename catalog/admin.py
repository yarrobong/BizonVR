from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html

from .cache_utils import invalidate_catalog_cache
from .models import (
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
)


@admin.register(CatalogSection)
class CatalogSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

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
    model = ProductStock
    fk_name = 'product'
    extra = 0
    autocomplete_fields = ('pickup_point', 'variant')

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


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


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
    list_display = ('name', 'slug', 'section')
    list_filter = ('section',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

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


@admin.register(ProductBundle)
class ProductBundleAdmin(admin.ModelAdmin):
    list_display = ('name', 'items_count', 'bundle_total')
    inlines = (ProductBundleItemInline,)
    search_fields = ('name',)

    def items_count(self, obj):
        return obj.items.count() if obj.pk else 0

    items_count.short_description = 'Позиций'

    def bundle_total(self, obj):
        if obj.pk:
            total = sum(float(i.price) * i.quantity for i in obj.items.all())
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
    inlines = (ProductVariantInline, ProductImageInline, ProductCharacteristicInline, ProductStockInlineForProduct)
    readonly_fields = ('created_at', 'updated_at', 'image_preview')
    filter_horizontal = ('tags',)
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'category', 'price', 'description', 'image_preview', 'image', 'is_active', 'allow_order_on_request', 'option_label', 'tags', 'created_at', 'updated_at'),
        }),
    )

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=80, height=80)

    image_preview.short_description = 'Превью'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category').prefetch_related('tags', 'variants')


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


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('product__name',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('user', 'product')
