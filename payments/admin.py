from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'external_id', 'price_amount', 'price_currency', 'status', 'created_at')
    list_filter = ('status', 'price_currency')
    search_fields = ('external_id', 'order__id')
    readonly_fields = ('created_at', 'updated_at', 'ipn_data')
