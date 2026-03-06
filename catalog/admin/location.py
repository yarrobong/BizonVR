from django.contrib import admin

from ..cache_utils import invalidate_catalog_cache
from ..models import City, PickupPoint, ProductStock


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
