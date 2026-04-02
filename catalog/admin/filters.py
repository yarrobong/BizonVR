from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from ..cache_utils import invalidate_catalog_cache
from ..filter_bootstrap import (
    SAFE_AUTO_APPLICABLE,
    build_alias_suggestions,
    build_source_alias_suggestions,
    create_aliases_from_suggestions,
    create_source_aliases_from_suggestions,
    get_distinct_characteristic_source_names,
)
from ..models import (
    CharacteristicDefinition,
    CharacteristicSourceAlias,
    CharacteristicValueAlias,
    FilterConfig,
)


STATUS_LABELS = {
    SAFE_AUTO_APPLICABLE: 'Safe auto-apply',
    'blocked_by_existing_alias': 'Конфликт с существующими алиасами',
    'conflicting_group': 'Конфликтующие алиасы в группе',
    'manual_review_required': 'Нужна ручная проверка',
}


class CharacteristicDefinitionAdminForm(forms.ModelForm):
    source_name = forms.ChoiceField(label='Исходное имя характеристики')

    class Meta:
        model = CharacteristicDefinition
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_value = (getattr(self.instance, 'source_name', '') or '').strip()
        choice_values = get_distinct_characteristic_source_names()
        if current_value and current_value not in choice_values:
            choice_values.insert(0, current_value)
        self.fields['source_name'].choices = [(value, value) for value in choice_values]
        self.fields['source_name'].help_text = 'Выберите одно из существующих значений ProductCharacteristic.name.'
        self.fields['code'].required = False


class CharacteristicSourceAliasAdminForm(forms.ModelForm):
    raw_source_name = forms.ChoiceField(label='Сырое имя характеристики')

    class Meta:
        model = CharacteristicSourceAlias
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_value = (getattr(self.instance, 'raw_source_name', '') or '').strip()
        choice_values = get_distinct_characteristic_source_names()
        if current_value and current_value not in choice_values:
            choice_values.insert(0, current_value)
        self.fields['raw_source_name'].choices = [(value, value) for value in choice_values]


class FilterConfigInline(admin.TabularInline):
    model = FilterConfig
    extra = 0
    fields = ('characteristic_definition', 'is_visible', 'is_quick_filter', 'sort_order',
              'is_expanded_by_default', 'show_top_n', 'hide_single_value')
    autocomplete_fields = ('characteristic_definition',)
    ordering = ('sort_order', 'characteristic_definition__sort_order')
    verbose_name = 'Фильтр'
    verbose_name_plural = 'Фильтры'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('characteristic_definition')


class CategoryFilterConfigInline(FilterConfigInline):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(section__isnull=True)


class SectionFilterConfigInline(FilterConfigInline):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(category__isnull=True)


@admin.register(CharacteristicDefinition)
class CharacteristicDefinitionAdmin(admin.ModelAdmin):
    form = CharacteristicDefinitionAdminForm
    list_display = ('code', 'name', 'source_name', 'sorting_mode', 'is_filterable', 'sort_order', 'is_active')
    list_filter = ('sorting_mode', 'is_filterable', 'is_active')
    list_editable = ('sort_order', 'is_filterable', 'is_active')
    search_fields = ('code', 'name', 'source_name')
    ordering = ('sort_order', 'name', 'code')
    change_form_template = 'admin/catalog/characteristic_definition/change_form.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:object_id>/alias-suggestions/',
                self.admin_site.admin_view(self.alias_suggestions_view),
                name='catalog_characteristicdefinition_alias_suggestions',
            ),
            path(
                '<int:object_id>/source-alias-suggestions/',
                self.admin_site.admin_view(self.source_alias_suggestions_view),
                name='catalog_characteristicdefinition_source_alias_suggestions',
            ),
        ]
        return custom_urls + urls

    @admin.action(description='Открыть предложения алиасов значений')
    def open_alias_suggestions(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Выберите ровно одну характеристику.', messages.WARNING)
            return None
        return HttpResponseRedirect(
            reverse('admin:catalog_characteristicdefinition_alias_suggestions', args=[queryset.first().pk])
        )

    @admin.action(description='Открыть предложения source aliases')
    def open_source_alias_suggestions(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Выберите ровно одну характеристику.', messages.WARNING)
            return None
        return HttpResponseRedirect(
            reverse('admin:catalog_characteristicdefinition_source_alias_suggestions', args=[queryset.first().pk])
        )

    actions = ('open_alias_suggestions', 'open_source_alias_suggestions')

    def _get_definition_or_redirect(self, request, object_id):
        definition = self.get_object(request, object_id)
        if definition is None:
            self.message_user(request, 'Характеристика не найдена.', messages.ERROR)
            return None, HttpResponseRedirect(reverse('admin:catalog_characteristicdefinition_changelist'))
        if not self.has_change_permission(request, definition):
            self.message_user(request, 'Недостаточно прав.', messages.ERROR)
            return None, HttpResponseRedirect(reverse('admin:catalog_characteristicdefinition_changelist'))
        return definition, None

    def alias_suggestions_view(self, request, object_id):
        definition, redirect = self._get_definition_or_redirect(request, object_id)
        if redirect is not None:
            return redirect

        suggestions = build_alias_suggestions(definition)
        if request.method == 'POST':
            display_overrides = {
                suggestion['normalized_key']: (request.POST.get(f"display__{index}", '') or '').strip()
                for index, suggestion in enumerate(suggestions)
            }
            if 'auto_apply_safe' in request.POST:
                selected_keys = [item['normalized_key'] for item in suggestions if item['safe_auto_applicable']]
                result = create_aliases_from_suggestions(
                    definition,
                    selected_normalized_keys=selected_keys,
                    display_overrides=display_overrides,
                    safe_only=True,
                )
                self.message_user(
                    request,
                    f"Safe auto-apply: создано {result['created']}, существующих {result['skipped_existing']}, "
                    f"пропущено unsafe {result['skipped_unsafe']}.",
                    messages.SUCCESS if result['created'] else messages.INFO,
                )
            else:
                result = create_aliases_from_suggestions(
                    definition,
                    selected_normalized_keys=request.POST.getlist('selected_groups'),
                    display_overrides=display_overrides,
                )
                self.message_user(
                    request,
                    f"Создано алиасов: {result['created']}. Пропущено существующих: {result['skipped_existing']}.",
                    messages.SUCCESS if result['created'] else messages.INFO,
                )
            invalidate_catalog_cache()
            return HttpResponseRedirect(request.path)

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'original': definition,
            'definition': definition,
            'title': f'Предложения алиасов значений: {definition.name}',
            'suggestions': [
                {
                    **suggestion,
                    'status_label': STATUS_LABELS.get(suggestion['status'], suggestion['status']),
                    'display_field_name': f"display__{index}",
                }
                for index, suggestion in enumerate(suggestions)
            ],
        }
        return TemplateResponse(request, 'admin/catalog/characteristic_definition/alias_suggestions.html', context)

    def source_alias_suggestions_view(self, request, object_id):
        definition, redirect = self._get_definition_or_redirect(request, object_id)
        if redirect is not None:
            return redirect

        suggestions = build_source_alias_suggestions(definition)
        if request.method == 'POST':
            result = create_source_aliases_from_suggestions(
                definition,
                selected_source_names=request.POST.getlist('selected_source_names'),
            )
            invalidate_catalog_cache()
            self.message_user(
                request,
                f"Создано source alias-ов: {result['created']}. Пропущено существующих: {result['skipped_existing']}.",
                messages.SUCCESS if result['created'] else messages.INFO,
            )
            return HttpResponseRedirect(request.path)

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'original': definition,
            'definition': definition,
            'title': f'Предложения source aliases: {definition.name}',
            'suggestions': suggestions,
        }
        return TemplateResponse(
            request, 'admin/catalog/characteristic_definition/source_alias_suggestions.html', context
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


@admin.register(CharacteristicSourceAlias)
class CharacteristicSourceAliasAdmin(admin.ModelAdmin):
    form = CharacteristicSourceAliasAdminForm
    list_display = ('characteristic_definition', 'raw_source_name', 'sort_order', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('raw_source_name', 'characteristic_definition__code', 'characteristic_definition__name')
    autocomplete_fields = ('characteristic_definition',)
    ordering = ('characteristic_definition', 'sort_order', 'raw_source_name')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


@admin.register(CharacteristicValueAlias)
class CharacteristicValueAliasAdmin(admin.ModelAdmin):
    list_display = (
        'characteristic_definition', 'raw_value', 'normalized_value', 'display_value', 'sort_order', 'is_active',
    )
    list_filter = ('is_active',)
    search_fields = ('raw_value', 'normalized_value', 'display_value', 'characteristic_definition__name')
    autocomplete_fields = ('characteristic_definition',)
    ordering = ('characteristic_definition', 'sort_order', 'raw_value')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


@admin.register(FilterConfig)
class FilterConfigAdmin(admin.ModelAdmin):
    list_display = (
        'scope_label', 'characteristic_definition', 'is_visible', 'is_quick_filter', 'sort_order',
    )
    list_filter = ('is_visible', 'is_quick_filter', 'category', 'section')
    list_editable = ('is_visible', 'is_quick_filter', 'sort_order')
    search_fields = (
        'category__name', 'section__name',
        'characteristic_definition__code', 'characteristic_definition__name',
    )
    autocomplete_fields = ('category', 'section', 'characteristic_definition')
    ordering = ('category__name', 'section__name', 'sort_order', 'characteristic_definition__name')

    def scope_label(self, obj):
        if obj.category_id:
            return f'Категория: {obj.category.name}'
        return f'Раздел: {obj.section.name}'
    scope_label.short_description = 'Скоуп'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()
