from django.contrib import admin, messages

from ..cache_utils import invalidate_catalog_cache
from ..filter_bootstrap import bootstrap_category_filter_configs, bootstrap_section_filter_configs
from ..models import CatalogSection, Category, ProductTag


@admin.register(CatalogSection)
class CatalogSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'has_icon')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    fields = ('name', 'slug', 'order', 'icon')
    actions = ('bootstrap_filter_configs',)

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

    @admin.action(description='Создать конфиги фильтров для выбранных разделов')
    def bootstrap_filter_configs(self, request, queryset):
        created_total = 0
        existing_total = 0
        for section in queryset:
            results = bootstrap_section_filter_configs(section, apply=True, skip_existing=True)
            created_total += sum(1 for result in results if result['action'] == 'created')
            existing_total += sum(1 for result in results if result['action'] == 'existing')
        invalidate_catalog_cache()
        self.message_user(
            request,
            f'Для разделов создано конфигов: {created_total}. Уже существовало: {existing_total}.',
            messages.SUCCESS,
        )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'section', 'tile_size', 'is_bundles_category', 'has_icon')
    list_editable = ('tile_size',)
    list_filter = ('section', 'is_bundles_category')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    fields = ('name', 'slug', 'section', 'icon', 'tile_size', 'is_bundles_category')
    actions = ('bootstrap_filter_configs',)

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

    @admin.action(description='Создать конфиги фильтров для выбранных категорий')
    def bootstrap_filter_configs(self, request, queryset):
        created_total = 0
        existing_total = 0
        for category in queryset.select_related('section'):
            results = bootstrap_category_filter_configs(category, apply=True, skip_existing=True)
            created_total += sum(1 for result in results if result['action'] == 'created')
            existing_total += sum(1 for result in results if result['action'] == 'existing')
        invalidate_catalog_cache()
        self.message_user(
            request,
            f'Для категорий создано конфигов: {created_total}. Уже существовало: {existing_total}.',
            messages.SUCCESS,
        )


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
