from decimal import Decimal

from django.contrib import admin
from django import forms
from django.utils.html import format_html

from catalog.models import Product
from config.formatting import format_currency_amount

from .models import Order, OrderItem, OrderNotificationLog, PromoCode, PurchaseRequest, resolve_order_item_image_url
from .services import sync_order_state_side_effects


def _recalculate_order_total(order):
    total = sum((item.subtotal for item in order.items.all()), Decimal('0'))
    if order.total != total:
        order.total = total
        order.save(update_fields=['total', 'updated_at'])


class OrderItemAdminForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        product_name = (cleaned.get('product_name') or '').strip()
        product = cleaned.get('product')
        if product is None and product_name:
            matches = list(Product.objects.filter(name__iexact=product_name).order_by('name')[:2])
            if len(matches) == 1:
                product = matches[0]
                cleaned['product'] = product
        if product is not None:
            cleaned['product_name'] = product.name
            if cleaned.get('price') in (None, ''):
                cleaned['price'] = product.price
            if not (cleaned.get('product_image_url') or '').strip():
                cleaned['product_image_url'] = resolve_order_item_image_url(product=product, variant=cleaned.get('variant'))
        elif not product_name:
            self.add_error('product_name', 'Укажите название позиции.')
        return cleaned


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
    search_fields = ('id', 'phone', 'email', 'first_name', 'last_name', 'business_company_name', 'business_inn')
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
            'fields': (
                'first_name',
                'last_name',
                'phone',
                'email',
                'contact_channel',
                'contact_handle',
                'recipient_is_customer',
                'recipient_name',
                'recipient_phone',
            ),
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
            ),
        }),
        ('Реквизиты юр. лица', {
            'fields': (
                'business_company_name',
                'business_inn',
                'business_kpp',
                'business_checking_account',
                'business_bank_name',
                'business_bik',
                'business_correspondent_account',
                'business_phone',
                'business_telegram',
                'business_whatsapp',
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
    form = OrderItemAdminForm
    list_display = ('order', 'display_name', 'quantity', 'price', 'is_on_request', 'subtotal_display')
    list_filter = ('order',)
    autocomplete_fields = ('order', 'product', 'variant')
    search_fields = ('product_name', 'product__name', 'order__id', 'comment')
    readonly_fields = ('catalog_preview',)
    fieldsets = (
        (None, {
            'fields': (
                'order',
                'product_name',
                'product',
                'catalog_preview',
                'product_image_url',
                'variant',
                'variant_name',
                'quantity',
                'price',
                'discount_amount',
                'purchase_price',
                'condition',
                'is_on_request',
                'comment',
            ),
        }),
    )

    def display_name(self, obj):
        return obj.display_name
    display_name.short_description = 'Позиция'

    def subtotal_display(self, obj):
        return format_currency_amount(obj.subtotal)
    subtotal_display.short_description = 'Сумма'

    def catalog_preview(self, obj):
        if obj is None:
            return 'Сохраните позицию, чтобы увидеть превью.'
        image_url = obj.display_image_url
        catalog_price = obj.product.price if obj.product_id else None
        if not image_url and catalog_price is None:
            return 'Нет связанного товара из каталога.'
        preview_parts = []
        if image_url:
            preview_parts.append(f'<img src="{image_url}" alt="{obj.resolved_product_name}" style="max-height:72px;border-radius:12px;" />')
        if catalog_price is not None:
            preview_parts.append(f'<div style="margin-top:8px;">Цена в каталоге: {format_currency_amount(catalog_price)}</div>')
        return format_html(''.join(preview_parts))
    catalog_preview.short_description = 'Превью каталога'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        _recalculate_order_total(obj.order)

    def delete_model(self, request, obj):
        order = obj.order
        super().delete_model(request, obj)
        _recalculate_order_total(order)


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
