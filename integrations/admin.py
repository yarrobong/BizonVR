from django.contrib import admin

from .models import SiteLeadRequest


@admin.register(SiteLeadRequest)
class SiteLeadRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'source_type',
        'name',
        'phone',
        'spam_status',
        'sync_status',
        'bitrix_deal_id',
        'created_at',
    )
    list_filter = ('source_type', 'spam_status', 'sync_status', 'created_at')
    search_fields = ('name', 'phone', 'email', 'bitrix_deal_id', 'bitrix_contact_id', 'message')
    readonly_fields = (
        'created_at',
        'updated_at',
        'bitrix_synced_at',
    )
