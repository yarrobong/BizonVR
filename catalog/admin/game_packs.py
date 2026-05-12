from django.contrib import admin

from ..game_pack_mirrors import sync_game_pack_mirror
from ..models import GamePack, GamePackEntry, GamePackServiceEntry, ProductGameMetadata


class GamePackEntryInline(admin.TabularInline):
    model = GamePackEntry
    extra = 0
    fields = ('product', 'unresolved_title', 'platform', 'quantity', 'note', 'sort_order')
    ordering = ('sort_order', 'id')
    autocomplete_fields = ('product',)


class GamePackServiceEntryInline(admin.TabularInline):
    model = GamePackServiceEntry
    extra = 0
    fields = ('service', 'title', 'platform', 'quantity', 'price', 'note', 'sort_order')
    ordering = ('sort_order', 'id')
    autocomplete_fields = ('service',)


@admin.register(GamePack)
class GamePackAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'category',
        'package_format',
        'vr_club_tariff',
        'show_on_vr_club_page',
        'calculated_price_display',
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
    inlines = [GamePackEntryInline, GamePackServiceEntryInline]
    fieldsets = (
        (None, {
            'fields': (
                'category',
                'name',
                'slug',
                'description',
                'image',
                'price',
                'discount_percent',
                'price_on_request',
                'allow_order_on_request',
                'is_active',
                'sort_order',
                'tags',
            ),
            'description': 'Цена из наличия используется как fallback, если в составе пака нет позиций с ценой.',
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
