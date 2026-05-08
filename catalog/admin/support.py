from django.contrib import admin

from ..models import CallbackRequest, CartItem, ContactRequest, Favorite, Service, VRClubQuizRequest


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'line_type', 'product', 'variant', 'game_pack', 'service', 'quantity')
    list_filter = ('user', 'line_type')
    search_fields = ('product__name', 'game_pack__name', 'service__name')
    raw_id_fields = ('user', 'product', 'variant', 'game_pack', 'service')


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'email', 'message')
    readonly_fields = ('name', 'email', 'phone', 'message', 'created_at')


@admin.register(CallbackRequest)
class CallbackRequestAdmin(admin.ModelAdmin):
    list_display = ('phone', 'name', 'source', 'created_at')
    list_filter = ('source', 'created_at')
    search_fields = ('phone', 'name')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'service_kind', 'price', 'price_from', 'is_vr_club_service', 'order', 'is_active')
    list_editable = ('order', 'is_active', 'is_vr_club_service')
    list_filter = ('is_active', 'is_vr_club_service', 'service_kind')
    search_fields = ('name', 'short_description', 'description')
    fields = ('name', 'short_description', 'description', 'icon', 'price', 'price_from', 'service_kind', 'is_vr_club_service', 'order', 'is_active')


@admin.register(VRClubQuizRequest)
class VRClubQuizRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'club_format', 'devices', 'headsets_count', 'budget', 'created_at')
    list_filter = ('club_format', 'created_at')
    search_fields = ('name', 'phone', 'email', 'devices', 'comment')
    readonly_fields = ('created_at', 'legal_accepted_at', 'legal_docs_version', 'legal_acceptance_ip', 'legal_acceptance_user_agent')


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('product__name',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('user', 'product')
