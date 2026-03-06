from django.contrib import admin

from ..models import CallbackRequest, CartItem, ContactRequest, Favorite, Service


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'variant', 'quantity')
    list_filter = ('user',)
    search_fields = ('product__name',)
    raw_id_fields = ('user', 'product', 'variant')


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
    list_display = ('name', 'price_from', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'short_description', 'description')
    fields = ('name', 'short_description', 'description', 'icon', 'price_from', 'order', 'is_active')


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('product__name',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('user', 'product')
