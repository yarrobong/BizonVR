from django.contrib import admin

from .models import (
    Cargo,
    CargoItem,
    CargoPhoto,
    DealActivity,
    DealSavedView,
    ContractCompanyProfile,
    ContractDocument,
    ContractTemplate,
    Expense,
    FinanceDeal,
    FinanceDealType,
    FinanceExpense,
    FinanceExpenseCategory,
    FinancePayout,
    InventoryBalance,
    InventoryMovement,
    ManagerDeal,
    ManagerClient,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    TradeInItem,
    TransportLeg,
    Warehouse,
)


@admin.register(ManagerClient)
class ManagerClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'status', 'user', 'created_at')
    search_fields = ('name', 'phone', 'email')
    filter_horizontal = ('orders',)


@admin.register(ManagerDeal)
class ManagerDealAdmin(admin.ModelAdmin):
    list_display = (
        'order',
        'deal_type',
        'case_status',
        'next_step_code',
        'payment_state',
        'fulfillment_status',
        'responsible_manager',
        'deal_created_at',
    )
    list_filter = (
        'deal_type',
        'case_status',
        'deal_status',
        'payment_state',
        'fulfillment_status',
        'delivery_status',
        'documents_status',
        'buyer_type',
        'customer_source',
        'shipment_status',
        'delivery_method',
    )
    search_fields = (
        'order__id',
        'individual_full_name',
        'individual_phone',
        'business_company_name',
        'business_contact_person',
        'business_phone',
        'next_step_code',
    )
    raw_id_fields = ('order', 'responsible_manager')


@admin.register(DealActivity)
class DealActivityAdmin(admin.ModelAdmin):
    list_display = ('manager_deal', 'event_type', 'source', 'actor', 'created_at')
    list_filter = ('source', 'event_type')
    search_fields = ('manager_deal__order__id', 'event_type')
    raw_id_fields = ('manager_deal', 'actor')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DealSavedView)
class DealSavedViewAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at', 'updated_at')
    search_fields = ('name', 'owner__username')
    raw_id_fields = ('owner',)


@admin.register(TradeInItem)
class TradeInItemAdmin(admin.ModelAdmin):
    list_display = ('deal', 'device_type', 'model_name', 'condition', 'preliminary_estimate', 'final_estimate')
    search_fields = ('deal__order__id', 'model_name', 'device_type', 'condition')


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'pickup_point', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'address')


@admin.register(InventoryBalance)
class InventoryBalanceAdmin(admin.ModelAdmin):
    list_display = ('warehouse', 'product', 'variant', 'quantity', 'min_stock', 'updated_at')
    list_filter = ('warehouse',)
    search_fields = ('product__name', 'warehouse__name')


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ('warehouse', 'product', 'variant', 'movement_type', 'quantity', 'reference_type', 'reference_id', 'created_at')
    list_filter = ('warehouse', 'movement_type')
    search_fields = ('product__name', 'warehouse__name', 'reference_type')


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'supplier_name', 'status', 'currency', 'total_amount')
    list_filter = ('status', 'currency')
    search_fields = ('supplier_name', 'agent')
    inlines = [PurchaseItemInline]


class CargoItemInline(admin.TabularInline):
    model = CargoItem
    extra = 0


class CargoPhotoInline(admin.TabularInline):
    model = CargoPhoto
    extra = 0


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ('cargo_number', 'status', 'destination_warehouse', 'eta', 'purchase')
    list_filter = ('status', 'destination_warehouse')
    search_fields = ('cargo_number',)
    inlines = [CargoItemInline, CargoPhotoInline]


@admin.register(TransportLeg)
class TransportLegAdmin(admin.ModelAdmin):
    list_display = ('cargo', 'from_location', 'to_warehouse', 'method', 'status', 'cost')
    list_filter = ('status',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'amount', 'date', 'cargo', 'leg')
    list_filter = ('category', 'date')


@admin.register(FinanceDealType)
class FinanceDealTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'partner_share', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(FinanceExpenseCategory)
class FinanceExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'expense_side', 'is_active', 'updated_at')
    list_filter = ('expense_side', 'is_active')
    search_fields = ('name',)


@admin.register(FinanceDeal)
class FinanceDealAdmin(admin.ModelAdmin):
    list_display = ('date', 'contract_number', 'manager_deal', 'deal_type', 'revenue', 'margin', 'partner_share_amount')
    list_filter = ('deal_type', 'date')
    search_fields = ('contract_number', 'comment', 'manager_deal__order__id')


@admin.register(FinanceExpense)
class FinanceExpenseAdmin(admin.ModelAdmin):
    list_display = ('date', 'expense_side', 'category', 'amount', 'deal', 'manager_deal')
    list_filter = ('expense_side', 'category')
    search_fields = ('comment', 'who_paid', 'deal__contract_number', 'manager_deal__order__id')


@admin.register(FinancePayout)
class FinancePayoutAdmin(admin.ModelAdmin):
    list_display = ('date', 'amount', 'manager_deal', 'created_by')
    search_fields = ('comment',)


@admin.register(ContractCompanyProfile)
class ContractCompanyProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'legal_type', 'company_name', 'is_active', 'updated_at')
    list_filter = ('legal_type', 'is_active')
    search_fields = ('name', 'company_name', 'inn', 'email', 'phone')


@admin.register(ContractTemplate)
class ContractTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'document_type', 'version', 'is_active', 'updated_at')
    list_filter = ('document_type', 'is_active')
    search_fields = ('name', 'slug', 'description')


@admin.register(ContractDocument)
class ContractDocumentAdmin(admin.ModelAdmin):
    list_display = ('number', 'title', 'manager_deal', 'document_type', 'status', 'counterparty_display', 'issue_date', 'amount')
    list_filter = ('document_type', 'status', 'currency', 'issue_date')
    search_fields = ('number', 'title', 'counterparty_name', 'manager_client__name', 'manager_deal__order__id')
    raw_id_fields = ('manager_deal', 'manager_client', 'linked_order', 'responsible_manager', 'created_by', 'template', 'company_profile')


class ReservationItemInline(admin.TabularInline):
    model = ReservationItem
    extra = 0


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'manager_deal', 'client', 'status', 'source_type', 'source_warehouse', 'source_cargo', 'target_warehouse')
    list_filter = ('status', 'source_type')
    search_fields = ('client__name', 'manager_deal__order__id')
    inlines = [ReservationItemInline]
