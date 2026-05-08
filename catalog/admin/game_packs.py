from django.contrib import admin

from ..models import GamePack, GamePackEntry, GamePackServiceEntry, ProductGameMetadata


class GamePackEntryInline(admin.TabularInline):
    model = GamePackEntry
    extra = 0
    fields = ('product', 'unresolved_title', 'quantity', 'note', 'sort_order')
    ordering = ('sort_order', 'id')


class GamePackServiceEntryInline(admin.TabularInline):
    model = GamePackServiceEntry
    extra = 0
    fields = ('service', 'title', 'quantity', 'price', 'note', 'sort_order')
    ordering = ('sort_order', 'id')


@admin.register(GamePack)
class GamePackAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'vr_club_tariff', 'show_on_vr_club_page', 'calculated_price_display', 'price_on_request', 'is_active', 'views_count')
    list_filter = ('category__section', 'category', 'vr_club_tariff', 'show_on_vr_club_page', 'is_active', 'tags')
    search_fields = ('name', 'description', 'entries__product__name', 'entries__unresolved_title', 'service_entries__service__name', 'service_entries__title')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('tags',)
    inlines = [GamePackEntryInline, GamePackServiceEntryInline]
    fieldsets = (
        (None, {
            'fields': ('category', 'name', 'slug', 'description', 'image', 'price', 'discount_percent', 'price_on_request', 'allow_order_on_request', 'is_active', 'tags'),
            'description': 'Цена из наличия используется как fallback, если у состава пака нет ни одной позиции с ценой.',
        }),
        ('VR-клубы', {'fields': ('show_on_vr_club_page', 'vr_club_tariff', 'club_format', 'devices', 'genres', 'age_rating', 'players_count', 'play_places_count', 'commercial_pitch', 'included_summary')}),
    )

    @admin.display(description='Цена пака')
    def calculated_price_display(self, obj):
        return obj.in_stock_price


@admin.register(GamePackEntry)
class GamePackEntryAdmin(admin.ModelAdmin):
    list_display = ('game_pack', 'product', 'unresolved_title', 'quantity', 'sort_order')
    list_filter = ('game_pack__category',)
    search_fields = ('game_pack__name', 'product__name', 'unresolved_title', 'note')


@admin.register(GamePackServiceEntry)
class GamePackServiceEntryAdmin(admin.ModelAdmin):
    list_display = ('game_pack', 'service', 'title', 'quantity', 'price', 'sort_order')
    list_filter = ('game_pack__category', 'service__service_kind')
    search_fields = ('game_pack__name', 'service__name', 'title', 'note')


@admin.register(ProductGameMetadata)
class ProductGameMetadataAdmin(admin.ModelAdmin):
    list_display = ('product', 'devices', 'genres', 'min_players', 'max_players', 'age_rating', 'club_format', 'is_multiplayer', 'is_active', 'sort_order')
    list_filter = ('club_format', 'is_pcvr', 'is_standalone', 'is_multiplayer', 'is_active')
    search_fields = ('product__name', 'devices', 'genres', 'b2b_note')
    raw_id_fields = ('product',)
    list_editable = ('is_active', 'sort_order')
