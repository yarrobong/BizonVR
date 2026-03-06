from django.contrib import admin

from ..cache_utils import invalidate_catalog_cache
from ..models import CatalogSection, Category, ProductTag


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
