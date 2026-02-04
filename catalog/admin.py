from django.contrib import admin
from django.utils.html import format_html

from .models import CatalogSection, Category, City, Favorite, PickupPoint, Product, ProductCharacteristic, ProductStock


@admin.register(CatalogSection)
class CatalogSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


class ProductCharacteristicInline(admin.TabularInline):
    model = ProductCharacteristic
    extra = 1


class ProductStockInlineForProduct(admin.TabularInline):
    model = ProductStock
    fk_name = 'product'
    extra = 0
    autocomplete_fields = ('pickup_point',)


class ProductStockInlineForPickupPoint(admin.TabularInline):
    model = ProductStock
    fk_name = 'pickup_point'
    extra = 0
    autocomplete_fields = ('product',)


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(PickupPoint)
class PickupPointAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'address', 'order')
    list_filter = ('city',)
    search_fields = ('name', 'address')
    inlines = (ProductStockInlineForPickupPoint,)
    ordering = ('city', 'order', 'name')


@admin.register(ProductStock)
class ProductStockAdmin(admin.ModelAdmin):
    list_display = ('product', 'pickup_point', 'quantity')
    list_filter = ('pickup_point__city', 'pickup_point')
    search_fields = ('product__name',)
    raw_id_fields = ('product', 'pickup_point')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'section')
    list_filter = ('section',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'is_active', 'allow_order_on_request', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (ProductCharacteristicInline, ProductStockInlineForProduct)
    readonly_fields = ('created_at', 'updated_at')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category')


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('product__name',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('user', 'product')
