from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from ..cache_utils import invalidate_catalog_cache
from ..filter_bootstrap import bootstrap_filter_configs
from ..filter_setup_wizard import CatalogFilterSetupWizard
from ..models import CatalogSection, Category, ProductTag
from .shared import _admin_image_preview
from .filters import CategoryFilterConfigInline, SectionFilterConfigInline


class FilterSetupWizardAdminMixin:
    filter_setup_scope_type = ''
    filter_setup_template = 'admin/catalog/filter_setup_wizard.html'

    def get_urls(self):
        urls = super().get_urls()
        info = self.model._meta
        custom_urls = [
            path(
                '<int:object_id>/filter-setup-wizard/',
                self.admin_site.admin_view(self.filter_setup_wizard_view),
                name=f'{info.app_label}_{info.model_name}_filter_setup_wizard',
            ),
        ]
        return custom_urls + urls

    def get_filter_setup_wizard_url(self, obj):
        return reverse(f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_filter_setup_wizard', args=[obj.pk])

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj is not None and obj.pk:
            context['filter_setup_wizard_url'] = self.get_filter_setup_wizard_url(obj)
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def filter_setup_wizard_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(request, 'Объект не найден.', messages.ERROR)
            return HttpResponseRedirect(reverse(f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist'))
        if not self.has_change_permission(request, obj):
            self.message_user(request, 'Недостаточно прав.', messages.ERROR)
            return HttpResponseRedirect(reverse(f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change', args=[obj.pk]))

        wizard = CatalogFilterSetupWizard(self.filter_setup_scope_type, obj)
        if request.method == 'POST':
            result = wizard.apply(
                selected_missing_definitions=request.POST.getlist('missing_definitions'),
                selected_source_aliases=request.POST.getlist('source_aliases'),
                selected_value_aliases=request.POST.getlist('value_aliases'),
                apply_missing_configs=bool(request.POST.get('apply_missing_configs')),
                selected_quick_filters=request.POST.getlist('quick_filters'),
            )
            invalidate_catalog_cache()
            changes = [
                f"definitions: {result['created_definitions']}",
                f"source aliases: {result['created_source_aliases']}",
                f"value aliases: {result['created_value_aliases']}",
                f"configs: {result['created_filter_configs']}",
                f"quick filters: {result['enabled_quick_filters']}",
            ]
            level = messages.SUCCESS if sum(result.values()) else messages.INFO
            self.message_user(request, 'Wizard применён, изменений: ' + ', '.join(changes) + '.', level)
            return HttpResponseRedirect(request.path)

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'original': obj,
            'title': f'Мастер настройки фильтров: {obj}',
            'wizard': wizard.build_preview(),
        }
        return TemplateResponse(request, self.filter_setup_template, context)


@admin.register(CatalogSection)
class CatalogSectionAdmin(FilterSetupWizardAdminMixin, admin.ModelAdmin):
    filter_setup_scope_type = 'section'
    list_display = ('name', 'slug', 'order', 'has_icon')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    fields = ('name', 'slug', 'order', 'icon')
    inlines = (SectionFilterConfigInline,)
    actions = ('bootstrap_filter_configs_action',)
    change_form_template = 'admin/catalog/catalogsection/change_form.html'

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

    @admin.action(description='Автозаполнить фильтры для выбранных разделов')
    def bootstrap_filter_configs_action(self, request, queryset):
        created_total = 0
        existing_total = 0
        for section in queryset:
            results = bootstrap_filter_configs('section', section, apply=True, skip_existing=True)
            created_total += sum(1 for r in results if r['action'] == 'created')
            existing_total += sum(1 for r in results if r['action'] == 'existing')
        invalidate_catalog_cache()
        self.message_user(
            request,
            f'Для разделов создано конфигов: {created_total}. Уже существовало: {existing_total}.',
            messages.SUCCESS,
        )


@admin.register(Category)
class CategoryAdmin(FilterSetupWizardAdminMixin, admin.ModelAdmin):
    filter_setup_scope_type = 'category'
    list_display = ('name', 'slug', 'section', 'tile_size', 'is_bundles_category', 'has_image', 'has_icon')
    list_editable = ('tile_size',)
    list_filter = ('section', 'is_bundles_category')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    fields = ('name', 'slug', 'section', 'image', 'image_preview', 'icon', 'tile_size', 'is_bundles_category')
    readonly_fields = ('image_preview',)
    inlines = (CategoryFilterConfigInline,)
    actions = ('bootstrap_filter_configs_action',)
    change_form_template = 'admin/catalog/category/change_form.html'

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=140, height=104)

    image_preview.short_description = 'Превью'

    def has_image(self, obj):
        return bool(obj.image)

    has_image.boolean = True
    has_image.short_description = 'Есть фото'

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

    @admin.action(description='Автозаполнить фильтры для выбранных категорий')
    def bootstrap_filter_configs_action(self, request, queryset):
        created_total = 0
        existing_total = 0
        for category in queryset.select_related('section'):
            results = bootstrap_filter_configs('category', category, apply=True, skip_existing=True)
            created_total += sum(1 for r in results if r['action'] == 'created')
            existing_total += sum(1 for r in results if r['action'] == 'existing')
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
