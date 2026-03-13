from django.contrib import admin
from django.utils.html import format_html

from config.formatting import format_currency_amount

from .models import Order, OrderItem, OrderNotificationLog, PromoCode, PurchaseRequest
from .services import sync_order_state_side_effects


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
    list_display = (
        'id',
        'user',
        'phone',
        'email',
        'delivery_type',
        'payment_method',
        'payment_status_badge',
        'status_badge',
        'city',
        'pickup_point',
        'total',
        'delivery_cost',
        'promo_discount_display',
        'total_to_pay_display',
        'promo_code',
        'partner_bonus_applied',
        'stock_decreased',
        'created_at',
    )
    list_filter = ('status', 'payment_status', 'payment_method', 'promo_code', 'partner_bonus_applied', 'city', 'stock_decreased')
    search_fields = ('id', 'phone', 'email', 'first_name', 'last_name')
    readonly_fields = (
        'created_at',
        'updated_at',
        'total',
        'promo_discount',
        'partner_bonus_applied',
        'stock_decreased',
        'guest_access_token',
        'guest_access_expires_at',
    )
    raw_id_fields = ('user', 'promo_code', 'city', 'pickup_point')
    actions = (
        'mark_confirmed',
        'mark_shipping',
        'mark_ready_for_pickup',
        'mark_cancelled',
        'mark_paid',
    )
    fieldsets = (
        ('Клиент и заказ', {
            'fields': ('user', 'status', 'payment_status', 'payment_method', 'promo_code'),
            'description': 'Статус заказа отвечает за lifecycle, статус оплаты — только за деньги.',
        }),
        ('Контакты', {
            'fields': ('first_name', 'last_name', 'phone', 'email', 'recipient_is_customer', 'recipient_name', 'recipient_phone'),
        }),
        ('Доставка', {
            'fields': (
                'delivery_type',
                'country',
                'city',
                'city_text',
                'postal_code',
                'pickup_point',
                'address_line',
                'address',
                'delivery_comment',
                'delivery_cost',
                'shipping_weight_kg',
                'shipping_volume_cm3',
                'cdek_fallback_to_nearest',
            ),
        }),
        ('Суммы и служебные поля', {
            'fields': (
                'total',
                'promo_discount',
                'partner_bonus_applied',
                'stock_decreased',
                'guest_access_token',
                'guest_access_expires_at',
                'legal_accepted_at',
                'legal_docs_version',
                'created_at',
                'updated_at',
            ),
        }),
    )

    def status_badge(self, obj):
        return obj.get_status_display()
    status_badge.short_description = 'Статус заказа'

    def payment_status_badge(self, obj):
        return obj.get_payment_status_display()
    payment_status_badge.short_description = 'Статус оплаты'

    def promo_discount_display(self, obj):
        if obj.promo_discount and obj.promo_discount > 0:
            return format_html('<span style="color: green;">−{}</span>', format_currency_amount(obj.promo_discount))
        return '—'
    promo_discount_display.short_description = 'Скидка'

    def total_to_pay_display(self, obj):
        return format_currency_amount(obj.total_to_pay)
    total_to_pay_display.short_description = 'К оплате'

    def save_model(self, request, obj, form, change):
        previous_status = ''
        previous_payment_status = ''
        if change:
            previous = Order.objects.get(pk=obj.pk)
            previous_status = previous.status
            previous_payment_status = previous.payment_status
        super().save_model(request, obj, form, change)
        sync_order_state_side_effects(
            obj,
            previous_status=previous_status,
            previous_payment_status=previous_payment_status,
            request=request,
        )

    @admin.action(description='Отметить как подтверждённые')
    def mark_confirmed(self, request, queryset):
        self._bulk_transition(queryset, status=Order.STATUS_CONFIRMED)

    @admin.action(description='Отметить как в доставке')
    def mark_shipping(self, request, queryset):
        self._bulk_transition(queryset, status=Order.STATUS_SHIPPING)

    @admin.action(description='Отметить как готовые к выдаче')
    def mark_ready_for_pickup(self, request, queryset):
        self._bulk_transition(queryset, status=Order.STATUS_READY_FOR_PICKUP)

    @admin.action(description='Отметить как отменённые')
    def mark_cancelled(self, request, queryset):
        self._bulk_transition(queryset, status=Order.STATUS_CANCELLED)

    @admin.action(description='Отметить оплату полученной')
    def mark_paid(self, request, queryset):
        self._bulk_transition(queryset, payment_status=Order.PAYMENT_STATUS_PAID)

    def _bulk_transition(self, queryset, *, status=None, payment_status=None):
        for order in queryset:
            previous_status = order.status
            previous_payment_status = order.payment_status
            update_fields = []
            if status and order.status != status:
                order.status = status
                update_fields.append('status')
            if payment_status and order.payment_status != payment_status:
                order.payment_status = payment_status
                update_fields.append('payment_status')
            if not update_fields:
                continue
            update_fields.append('updated_at')
            order.save(update_fields=update_fields)
            sync_order_state_side_effects(
                order,
                previous_status=previous_status,
                previous_payment_status=previous_payment_status,
            )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'variant_name', 'quantity', 'price', 'is_on_request', 'subtotal_display')
    list_filter = ('order',)
    raw_id_fields = ('order', 'product')

    def subtotal_display(self, obj):
        return format_currency_amount(obj.subtotal)
    subtotal_display.short_description = 'Сумма'


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'phone', 'telegram', 'total', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('phone', 'telegram')
    readonly_fields = ('created_at',)


@admin.register(OrderNotificationLog)
class OrderNotificationLogAdmin(admin.ModelAdmin):
    list_display = ('order', 'event', 'channel', 'created_at')
    list_filter = ('event', 'channel')
    search_fields = ('order__id', 'order__email', 'order__phone')
    readonly_fields = ('order', 'event', 'channel', 'created_at')
