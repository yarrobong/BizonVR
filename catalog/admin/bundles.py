from django.contrib import admin

from ..models import ProductBundle, ProductBundleItem
from .shared import _admin_image_preview


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
    classes = ('collapse',)
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
