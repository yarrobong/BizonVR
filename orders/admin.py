from django.contrib import admin
from django.utils.html import format_html

from .models import Order, OrderItem, PromoCode, PurchaseRequest


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'discount_amount', 'partner_bonus', 'partner_user', 'is_active', 'orders_count', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('code', 'label')
    readonly_fields = ('created_at', 'updated_at')

    def orders_count(self, obj):
        return obj.orders.count()
    orders_count.short_description = 'Заказов по коду'


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'phone', 'city', 'pickup_point', 'total', 'promo_discount_display', 'total_to_pay_display', 'promo_code', 'status', 'partner_bonus_applied', 'stock_decreased', 'created_at')
    list_filter = ('status', 'promo_code', 'partner_bonus_applied', 'city', 'stock_decreased')
    search_fields = ('id', 'phone', 'email', 'first_name', 'last_name')
    readonly_fields = ('created_at', 'updated_at', 'total', 'promo_discount', 'partner_bonus_applied', 'stock_decreased')
    raw_id_fields = ('user', 'promo_code', 'city', 'pickup_point')

    def promo_discount_display(self, obj):
        if obj.promo_discount and obj.promo_discount > 0:
            return format_html('<span style="color: green;">−{} ₽</span>', obj.promo_discount)
        return '—'
    promo_discount_display.short_description = 'Скидка'

    def total_to_pay_display(self, obj):
        return f'{obj.total_to_pay} ₽'
    total_to_pay_display.short_description = 'К оплате'


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'price', 'is_on_request', 'subtotal_display')
    list_filter = ('order',)
    raw_id_fields = ('order', 'product')

    def subtotal_display(self, obj):
        return f'{obj.subtotal} ₽'
    subtotal_display.short_description = 'Сумма'


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'phone', 'telegram', 'total', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('phone', 'telegram')
    readonly_fields = ('created_at',)
