from django import forms
from django.contrib import admin

from config.formatting import format_currency_amount

from ..game_pack_mirrors import sync_game_pack_mirror
from ..pricing import resolve_in_stock_price
from ..models import GamePack, GamePackEntry, GamePackServiceEntry, ProductGameMetadata
from .shared import _admin_image_preview


class GamePackEntryInlineForm(forms.ModelForm):
    class Meta:
        model = GamePackEntry
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].help_text = 'Основной сценарий: выберите игру из каталога.'
        self.fields['unresolved_title'].label = 'Временное название'
        self.fields['unresolved_title'].help_text = (
            'Заполняйте только для legacy или временной позиции, '
            'если подходящего товара ещё нет в каталоге.'
        )
        self.fields['platform'].help_text = 'Необязательное уточнение платформы для карточки пака.'
        self.fields['note'].help_text = 'Служебная пометка для редактора.'


class GamePackServiceEntryInlineForm(forms.ModelForm):
    class Meta:
        model = GamePackServiceEntry
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service'].help_text = 'Основной сценарий: выберите услугу из каталога.'
        self.fields['title'].label = 'Временное название'
        self.fields['title'].help_text = (
            'Заполняйте только для legacy или временной услуги, '
            'если её ещё нет в каталоге.'
        )
        self.fields['platform'].help_text = 'Необязательное уточнение платформы или сценария.'
        self.fields['note'].help_text = 'Служебная пометка для редактора.'


class GamePackEntryInline(admin.TabularInline):
    model = GamePackEntry
    form = GamePackEntryInlineForm
    extra = 1
    fields = ('product', 'quantity', 'price_preview', 'unresolved_title', 'platform', 'note', 'sort_order')
    readonly_fields = ('price_preview',)
    ordering = ('sort_order', 'id')
    autocomplete_fields = ('product',)
    verbose_name = 'Игра в паке'
    verbose_name_plural = 'Состав игрового пака'

    def price_preview(self, obj):
        if obj and obj.product_id:
            price = resolve_in_stock_price(obj.product)
            if price is not None:
                return format_currency_amount(price)
        return '—'
    price_preview.short_description = 'Цена в паке'


class GamePackServiceEntryInline(admin.TabularInline):
    model = GamePackServiceEntry
    form = GamePackServiceEntryInlineForm
    extra = 1
    fields = ('service', 'quantity', 'price', 'title', 'platform', 'note', 'sort_order')
    ordering = ('sort_order', 'id')
    autocomplete_fields = ('service',)
    verbose_name = 'Услуга в паке'
    verbose_name_plural = 'Услуги игрового пака'


@admin.register(GamePack)
class GamePackAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'category',
        'package_format',
        'vr_club_tariff',
        'show_on_vr_club_page',
        'calculated_price_display',
        'items_count',
        'price_on_request',
        'sort_order',
        'is_active',
        'views_count',
    )
    list_filter = (
        'category__section',
        'category',
        'package_format',
        'vr_club_tariff',
        'show_on_vr_club_page',
        'is_active',
        'tags',
    )
    search_fields = (
        'name',
        'description',
        'devices',
        'genres',
        'commercial_pitch',
        'entries__product__name',
        'entries__unresolved_title',
        'service_entries__service__name',
        'service_entries__title',
    )
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('tags',)
    list_editable = ('sort_order', 'is_active', 'show_on_vr_club_page')
    readonly_fields = ('image_preview',)
    inlines = [GamePackEntryInline, GamePackServiceEntryInline]
    fieldsets = (
        (None, {
            'fields': (
                'category',
                'name',
                'slug',
                'description',
                'image_preview',
                'image',
                'price',
                'discount_percent',
                'price_on_request',
                'allow_order_on_request',
                'is_active',
                'sort_order',
                'tags',
            ),
            'description': (
                'Собирайте пак в первую очередь через товары каталога ниже. '
                'Цена из наличия используется как fallback, если в составе пака нет позиций с ценой.'
            ),
        }),
        ('VR-клубы и сценарии', {
            'fields': (
                'show_on_vr_club_page',
                'vr_club_tariff',
                'package_format',
                'club_format',
                'devices',
                'genres',
                'age_rating',
                'players_count',
                'play_places_count',
                'commercial_pitch',
                'included_summary',
            ),
        }),
    )

    @admin.display(description='Цена пака')
    def calculated_price_display(self, obj):
        return obj.in_stock_price

    def image_preview(self, obj):
        return _admin_image_preview(obj, width=120, height=120)
    image_preview.short_description = 'Превью'

    @admin.display(description='Игр')
    def items_count(self, obj):
        return obj.entries.count() if obj.pk else 0

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        game_pack = form.instance
        if game_pack.mirror_product_id:
            sync_game_pack_mirror(
                game_pack,
                mirror_image_name=getattr(game_pack.image, 'name', ''),
            )


@admin.register(GamePackEntry)
class GamePackEntryAdmin(admin.ModelAdmin):
    list_display = ('game_pack', 'product', 'unresolved_title', 'quantity', 'sort_order')
    list_filter = ('game_pack__category',)
    search_fields = ('game_pack__name', 'product__name', 'unresolved_title', 'note')
    autocomplete_fields = ('game_pack', 'product')


@admin.register(GamePackServiceEntry)
class GamePackServiceEntryAdmin(admin.ModelAdmin):
    list_display = ('game_pack', 'service', 'title', 'quantity', 'price', 'sort_order')
    list_filter = ('game_pack__category', 'service__service_kind')
    search_fields = ('game_pack__name', 'service__name', 'title', 'note')
    autocomplete_fields = ('game_pack', 'service')


@admin.register(ProductGameMetadata)
class ProductGameMetadataAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'devices',
        'genres',
        'min_players',
        'max_players',
        'age_rating',
        'club_format',
        'is_multiplayer',
        'is_active',
        'sort_order',
    )
    list_filter = ('club_format', 'is_pcvr', 'is_standalone', 'is_multiplayer', 'is_active')
    search_fields = ('product__name', 'devices', 'genres', 'b2b_note')
    autocomplete_fields = ('product',)
    list_editable = ('is_active', 'sort_order')
    fieldsets = (
        (None, {'fields': ('product', 'is_active', 'sort_order')}),
        ('Совместимость и сценарий', {
            'fields': (
                'devices',
                'genres',
                'min_players',
                'max_players',
                'age_rating',
                'club_format',
                'is_pcvr',
                'is_standalone',
                'is_multiplayer',
                'b2b_note',
            ),
        }),
    )
