from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from ..cache_utils import invalidate_catalog_cache
from ..filter_bootstrap import (
    build_alias_suggestions,
    create_aliases_from_suggestions,
    get_distinct_characteristic_source_names,
)
from ..models import (
    CategoryFilterConfig,
    CharacteristicDefinition,
    CharacteristicValueAlias,
    SectionFilterConfig,
)


class CharacteristicDefinitionAdminForm(forms.ModelForm):
    source_name = forms.ChoiceField(label='Исходное имя характеристики')

    class Meta:
        model = CharacteristicDefinition
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_value = (getattr(self.instance, 'source_name', '') or '').strip()
        choices = [(value, value) for value in get_distinct_characteristic_source_names()]
        if current_value and current_value not in {value for value, _ in choices}:
            choices.insert(0, (current_value, current_value))
        self.fields['source_name'].choices = choices
        self.fields['source_name'].help_text = (
            'Выберите одно из существующих значений ProductCharacteristic.name.'
        )
        self.fields['code'].required = False


@admin.register(CharacteristicDefinition)
class CharacteristicDefinitionAdmin(admin.ModelAdmin):
    form = CharacteristicDefinitionAdminForm
    list_display = ('code', 'name', 'source_name', 'is_filterable', 'sort_order', 'is_active')
    list_filter = ('is_filterable', 'is_active')
    search_fields = ('code', 'name', 'source_name')
    ordering = ('sort_order', 'name', 'code')
    actions = ('open_alias_suggestions',)
    change_form_template = 'admin/catalog/characteristic_definition/change_form.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:object_id>/alias-suggestions/',
                self.admin_site.admin_view(self.alias_suggestions_view),
                name='catalog_characteristicdefinition_alias_suggestions',
            ),
        ]
        return custom_urls + urls

    @admin.action(description='Открыть предложения алиасов')
    def open_alias_suggestions(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                'Для просмотра предложений алиасов выберите ровно одну характеристику.',
                messages.WARNING,
            )
            return None
        definition = queryset.first()
        return HttpResponseRedirect(
            reverse('admin:catalog_characteristicdefinition_alias_suggestions', args=[definition.pk])
        )

    def alias_suggestions_view(self, request, object_id):
        definition = self.get_object(request, object_id)
        if definition is None:
            self.message_user(request, 'Характеристика не найдена.', messages.ERROR)
            return HttpResponseRedirect(reverse('admin:catalog_characteristicdefinition_changelist'))

        if not self.has_change_permission(request, definition):
            self.message_user(request, 'Недостаточно прав для изменения характеристики.', messages.ERROR)
            return HttpResponseRedirect(reverse('admin:catalog_characteristicdefinition_changelist'))

        suggestions = build_alias_suggestions(definition)
        if request.method == 'POST':
            selected_keys = request.POST.getlist('selected_groups')
            display_overrides = {
                suggestion['normalized_key']: (request.POST.get(f"display__{index}", '') or '').strip()
                for index, suggestion in enumerate(suggestions)
            }
            result = create_aliases_from_suggestions(
                definition,
                selected_normalized_keys=selected_keys,
                display_overrides=display_overrides,
            )
            if result['created']:
                invalidate_catalog_cache()
                self.message_user(
                    request,
                    f"Создано алиасов: {result['created']}. Пропущено существующих: {result['skipped_existing']}.",
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"Новых алиасов не создано. Уже существующих записей: {result['skipped_existing']}.",
                    messages.INFO,
                )
            return HttpResponseRedirect(request.path)

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'original': definition,
            'definition': definition,
            'title': f'Предложения алиасов: {definition.name}',
            'suggestions': [
                {
                    **suggestion,
                    'display_field_name': f"display__{index}",
                }
                for index, suggestion in enumerate(suggestions)
            ],
        }
        return TemplateResponse(
            request,
            'admin/catalog/characteristic_definition/alias_suggestions.html',
            context,
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


@admin.register(CharacteristicValueAlias)
class CharacteristicValueAliasAdmin(admin.ModelAdmin):
    list_display = (
        'characteristic_definition',
        'raw_value',
        'normalized_value',
        'display_value',
        'sort_order',
        'is_active',
    )
    list_filter = ('characteristic_definition', 'is_active')
    search_fields = ('raw_value', 'normalized_value', 'display_value')
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


@admin.register(CategoryFilterConfig)
class CategoryFilterConfigAdmin(admin.ModelAdmin):
    list_display = ('category', 'characteristic_definition', 'is_visible', 'is_quick_filter', 'sort_order')
    list_filter = ('category', 'is_visible', 'is_quick_filter')
    autocomplete_fields = ('category', 'characteristic_definition')
    search_fields = (
        'category__name',
        'characteristic_definition__code',
        'characteristic_definition__name',
    )
    ordering = ('category__name', 'sort_order', 'characteristic_definition__name')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()


@admin.register(SectionFilterConfig)
class SectionFilterConfigAdmin(admin.ModelAdmin):
    list_display = ('section', 'characteristic_definition', 'is_visible', 'is_quick_filter', 'sort_order')
    list_filter = ('section', 'is_visible', 'is_quick_filter')
    autocomplete_fields = ('section', 'characteristic_definition')
    search_fields = (
        'section__name',
        'characteristic_definition__code',
        'characteristic_definition__name',
    )
    ordering = ('section__name', 'sort_order', 'characteristic_definition__name')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_catalog_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        invalidate_catalog_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        invalidate_catalog_cache()
