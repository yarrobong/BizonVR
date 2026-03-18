import csv
from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, DateTimeField, F, Max, OuterRef, Prefetch, Q, Subquery, Sum
from django.db.models.functions import Coalesce, Greatest
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from catalog.admin.proposal_html import build_commercial_proposal_html
from catalog.models import Product, ProductStock
from catalog.stock import public_stock_status
from config.formatting import format_currency_amount
from orders.models import Order, OrderItem, resolve_order_item_image_url
from payments.models import Payment

from .access import (
    finance_admin_required,
    finance_required,
    has_any_manager_portal_access,
    has_finance_admin_access,
    has_finance_portal_access,
    has_manager_portal_access,
    staff_required,
)
from .forms import (
    CargoForm,
    CargoFilterForm,
    CargoItemForm,
    CargoPhotoForm,
    CargoReceiveForm,
    CargoSplitForm,
    ClientFilterForm,
    ContractCompanyProfileForm,
    ContractDocumentFilterForm,
    ContractDocumentForm,
    ContractTemplateForm,
    DealBulkAssignForm,
    DealBulkCaseStatusForm,
    DealCommentForm,
    DealFilterForm,
    DealManagementForm,
    DealSavedViewForm,
    ExpenseForm,
    FinanceDealForm,
    FinanceDealTypeForm,
    FinanceExpenseCategoryForm,
    FinanceExpenseForm,
    FinancePayoutForm,
    FinancePeriodForm,
    GlobalSearchForm,
    InventoryReceiptForm,
    ManagerClientForm,
    ManagerDealStateForm,
    ManualOrderForm,
    ManualOrderItemFormSet,
    OrderFilterForm,
    OrderStateForm,
    PurchaseForm,
    PurchaseFilterForm,
    PurchaseItemForm,
    QuickDealForm,
    QuickOrderItemFormSet,
    ReservationForm,
    ReservationFilterForm,
    ReservationItemForm,
    ReservationStatusForm,
    ShipmentFilterForm,
    TradeInItemFormSet,
    TransportLegForm,
    WarehouseFilterForm,
    WarehouseForm,
)
from .models import (
    Cargo,
    CargoItem,
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
    ManagerClient,
    ManagerDeal,
    ManagerDealParticipant,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    Shipment,
    TradeInItem,
    Warehouse,
)
from .services import (
    ACTIVE_RESERVATION_STATUSES,
    INVENTORY_PROBLEM_FILTERS,
    apply_deal_assignment,
    apply_deal_case_status_change,
    apply_deal_next_step_override,
    autofill_reservation_items_from_deal,
    build_finance_report_zip,
    clear_deal_next_step_override,
    contract_document_missing_fields,
    deal_manager_client,
    deal_search_groups,
    ensure_current_document_for_manager_deal,
    ensure_finance_deal_for_manager_deal,
    ensure_primary_reservation_for_manager_deal,
    ensure_reservations_for_manager_deal,
    ensure_shipment_for_manager_deal,
    enrich_inventory_rows,
    finance_case_missing_fields,
    finance_dashboard_data,
    finance_report_archive,
    inventory_snapshot,
    inventory_snapshot_for_warehouse,
    inventory_summary,
    manager_portal_now,
    manager_portal_stale_after,
    prefill_contract_document_from_manager_deal,
    prefill_finance_deal_from_manager_deal,
    create_or_update_shipment_for_order,
    ensure_order_reservations,
    fulfill_reservation,
    receive_cargo_item,
    reservation_effective_warehouse,
    reservation_coverage_snapshot,
    reservation_prefill_lines_for_deal,
    receipt_inventory,
    resolve_manager_client,
    restore_avito_return_to_stock,
    shipment_checklist,
    shipment_missing_fields,
    shipments_grouped_by_reservation,
    shipments_rows,
    split_cargo,
    sync_public_stock_for_warehouse,
    record_deal_activity,
    recompute_deal_workflow,
    update_order_state,
    validate_reservation_availability,
    create_or_update_reservation_movements,
    ensure_manager_client_for_order,
)
from .status_system import deal_primary_status, deal_risk_summary, deal_secondary_status


CREATE_MODE_QUICK = 'quick'
CREATE_MODE_FULL = 'full'
CLIENT_LOOKUP_RESULT_LIMIT = 8

DEAL_PROBLEM_VIEW_SLA_OVERDUE = 'sla_overdue'
DEAL_PROBLEM_VIEW_STALE_UPDATES = 'stale_updates'
DEAL_PROBLEM_VIEW_ETA_OVERDUE = 'eta_overdue'
DEAL_PROBLEM_VIEW_STOCK_CONFLICT = 'stock_conflict'
DEAL_PROBLEM_VIEW_MISSING_CONTACTS = 'missing_contacts'
DEAL_PROBLEM_VIEW_NO_ASSIGNEE = 'no_assignee'
DEAL_PROBLEM_VIEW_RESERVATIONS_EXPIRING = 'reservations_expiring'
DEAL_PROBLEM_VIEW_MISSING_B2B_DOCUMENTS = 'missing_b2b_documents'
DEAL_PROBLEM_VIEW_RESERVED_UNPAID = 'reserved_unpaid'
DEAL_SIGNAL_RESERVATION_AGE = timezone.timedelta(hours=48)
DEAL_LIST_PAGE_SIZE = 50
DEAL_VIEW_LIST = 'list'
DEAL_VIEW_KANBAN = 'kanban'
DEAL_VIEW_CHOICES = {DEAL_VIEW_LIST, DEAL_VIEW_KANBAN}
DEAL_SCOPE_CORE = 'core'
DEAL_SCOPE_AVITO = 'avito'
DEAL_SCOPE_CHOICES = {DEAL_SCOPE_CORE, DEAL_SCOPE_AVITO}
INVENTORY_BUSINESS_VIEW_DEAL_RISK = 'deal_risk'
INVENTORY_BUSINESS_VIEW_REPLENISHMENT = 'replenishment'
INVENTORY_BUSINESS_VIEW_OVERSOLD = 'oversold'
INVENTORY_BUSINESS_VIEW_SITE_MISMATCH = 'site_mismatch'

INVENTORY_BUSINESS_VIEW_DEFINITIONS = (
    {
        'code': INVENTORY_BUSINESS_VIEW_DEAL_RISK,
        'label': 'Горят сделки',
        'description': 'Проблемные SKU уже мешают активным сделкам.',
    },
    {
        'code': INVENTORY_BUSINESS_VIEW_REPLENISHMENT,
        'label': 'Нужно пополнить',
        'description': 'Остаток ниже минимума и быстрый приход не спасает.',
    },
    {
        'code': INVENTORY_BUSINESS_VIEW_OVERSOLD,
        'label': 'Обещано больше, чем есть',
        'description': 'Доступный остаток ушел в минус или резерв съел весь on-hand.',
    },
    {
        'code': INVENTORY_BUSINESS_VIEW_SITE_MISMATCH,
        'label': 'Сайт показывает неверно',
        'description': 'Публичный остаток расходится с ожидаемым.',
    },
)

DEAL_PROBLEM_VIEW_DEFINITIONS = (
    {
        'code': DEAL_PROBLEM_VIEW_SLA_OVERDUE,
        'label': 'SLA просрочен',
        'description': 'Заказы с просроченным операционным сроком.',
    },
    {
        'code': DEAL_PROBLEM_VIEW_STALE_UPDATES,
        'label': 'Нет обновлений 48 ч',
        'description': 'По сделке давно не было активности менеджера.',
    },
    {
        'code': DEAL_PROBLEM_VIEW_ETA_OVERDUE,
        'label': 'ETA просрочен',
        'description': 'Ожидаемая поставка или отправка уже сорвана.',
    },
    {
        'code': DEAL_PROBLEM_VIEW_STOCK_CONFLICT,
        'label': 'Конфликт по остаткам',
        'description': 'Текущий остаток не покрывает заказ без закупки.',
    },
    {
        'code': DEAL_PROBLEM_VIEW_MISSING_CONTACTS,
        'label': 'Нет контактов',
        'description': 'У сделки нет рабочего канала связи с клиентом.',
    },
    {
        'code': DEAL_PROBLEM_VIEW_RESERVATIONS_EXPIRING,
        'label': 'Истекают брони',
        'description': 'Активный резерв держится больше 48 часов.',
    },
    {
        'code': DEAL_PROBLEM_VIEW_MISSING_B2B_DOCUMENTS,
        'label': 'Нет документов для B2B',
        'description': 'Юрлица без подписанного пакета документов.',
    },
    {
        'code': DEAL_PROBLEM_VIEW_RESERVED_UNPAID,
        'label': 'Не оплачен, но зарезервирован',
        'description': 'Товар уже держится в резерве без полной оплаты.',
    },
)


def _nav_groups(user):
    if not has_any_manager_portal_access(user):
        return [
            {
                'key': 'entry',
                'label': 'Модули',
                'url_name': 'manager_portal:entry',
                'children': [],
            },
        ]

    groups = []
    if has_manager_portal_access(user):
        groups.append(
            {
                'key': 'deals',
                'label': 'Заказы',
                'url_name': 'manager_portal:deal_list',
                'children': [
                    ('deals', 'Очереди', 'manager_portal:deal_list'),
                    ('clients', 'Клиенты', 'manager_portal:client_list'),
                    ('warehouses', 'Склады', 'manager_portal:warehouse_list'),
                    ('inventory', 'Остатки', 'manager_portal:inventory'),
                    ('purchases', 'Закупки', 'manager_portal:purchase_list'),
                    ('cargos', 'Грузы', 'manager_portal:cargo_list'),
                    ('reservations', 'Брони', 'manager_portal:reservation_list'),
                    ('shipments', 'Отгрузки', 'manager_portal:shipments'),
                ],
            }
        )
    if has_finance_portal_access(user):
        finance_children = [
            ('finance_dashboard', 'Обзор', 'manager_portal:finance'),
            ('finance_deals', 'Сделки', 'manager_portal:finance_deal_list'),
            ('finance_expenses', 'Расходы', 'manager_portal:finance_expense_list'),
            ('finance_payouts', 'Выплаты', 'manager_portal:finance_payout_list'),
            ('finance_report', 'Отчет', 'manager_portal:finance_report'),
            ('finance_archive', 'Архив', 'manager_portal:finance_archive'),
        ]
        if has_finance_admin_access(user):
            finance_children.append(('finance_settings', 'Настройки', 'manager_portal:finance_settings'))
        groups.append(
            {
                'key': 'finance',
                'label': 'Финансы',
                'url_name': 'manager_portal:finance',
                'children': finance_children,
            }
        )
    if _can_use_commercial_proposals(user):
        groups.append(
            {
                'key': 'proposals',
                'label': 'Генератор КП',
                'url_name': 'manager_portal:commercial_proposals',
                'children': [],
            }
        )
    if has_manager_portal_access(user):
        groups.append(
            {
                'key': 'contracts',
                'label': 'Документы',
                'url_name': 'manager_portal:contracts',
                'children': [
                    ('contracts_dashboard', 'Обзор', 'manager_portal:contracts'),
                    ('contracts_documents', 'Реестр', 'manager_portal:contracts_documents'),
                    ('contracts_create', 'Создать новый', 'manager_portal:contracts_create'),
                    ('contracts_templates', 'Шаблоны', 'manager_portal:contracts_templates'),
                    ('contracts_settings', 'Настройки', 'manager_portal:contracts_settings'),
                ],
            }
        )
    return groups


def _tab_module_key(active_tab):
    if active_tab in {'deals', 'dashboard', 'orders', 'clients', 'warehouses', 'inventory', 'purchases', 'cargos', 'reservations', 'shipments'}:
        return 'deals'
    if active_tab in {'finance_dashboard', 'finance_deals', 'finance_expenses', 'finance_payouts', 'finance_report', 'finance_archive', 'finance_settings'}:
        return 'finance'
    if active_tab in {'contracts_dashboard', 'contracts_documents', 'contracts_create', 'contracts_templates', 'contracts_settings'}:
        return 'contracts'
    return active_tab


def _nav_items(user):
    items = []
    for group in _nav_groups(user):
        items.append((group['key'], group['label'], group['url_name']))
        items.extend(group['children'])
    return items


def _nav_groups_with_state(user, active_tab):
    active_module_key = _tab_module_key(active_tab)
    groups = []
    for group in _nav_groups(user):
        group_active = group['key'] == active_module_key
        children = [
            {
                'key': key,
                'label': label,
                'url_name': url_name,
                'active': key == active_tab,
            }
            for key, label, url_name in group['children']
        ]
        groups.append(
            {
                'key': group['key'],
                'label': group['label'],
                'url_name': group['url_name'],
                'active': group_active,
                'expanded': group_active and bool(children),
                'children': children,
            }
        )
    return groups


def _sidebar_item(*, key, label, url_name, icon, active, enabled=True):
    return {
        'key': key,
        'label': label,
        'url_name': url_name,
        'icon': icon,
        'active': active,
        'enabled': enabled,
    }


def _sidebar_groups_with_state(user, active_tab):
    active_module_key = _tab_module_key(active_tab)

    if not has_any_manager_portal_access(user):
        items = [
            _sidebar_item(
                key='entry',
                label='Модули',
                url_name='manager_portal:entry',
                icon='profile',
                active=active_tab == 'entry',
            )
        ]
        return [
            {
                'key': 'entry',
                'label': 'Навигация',
                'items': items,
                'has_enabled_items': True,
            }
        ]

    groups = []

    sales_items = []
    if has_manager_portal_access(user):
        sales_items.extend(
            [
                _sidebar_item(
                    key='deals',
                    label='Сделки',
                    url_name='manager_portal:deal_list',
                    icon='deals',
                    active=active_module_key == 'deals',
                ),
                _sidebar_item(
                    key='clients',
                    label='Клиенты',
                    url_name='manager_portal:client_list',
                    icon='clients',
                    active=active_tab == 'clients',
                ),
            ]
        )
        if _can_use_commercial_proposals(user):
            sales_items.append(
                _sidebar_item(
                    key='proposals',
                    label='Коммерческие предложения',
                    url_name='manager_portal:commercial_proposals',
                    icon='commercial_proposals',
                    active=active_module_key == 'proposals',
                )
            )
    if sales_items:
        groups.append(
            {
                'key': 'sales',
                'label': 'Продажи',
                'items': sales_items,
                'has_enabled_items': any(item['enabled'] for item in sales_items),
            }
        )

    logistics_items = []
    if has_manager_portal_access(user):
        logistics_items.extend(
            [
                _sidebar_item(
                    key='warehouses',
                    label='Склады',
                    url_name='manager_portal:warehouse_list',
                    icon='warehouses',
                    active=active_tab == 'warehouses',
                ),
                _sidebar_item(
                    key='inventory',
                    label='Остатки',
                    url_name='manager_portal:inventory',
                    icon='inventory',
                    active=active_tab == 'inventory',
                ),
                _sidebar_item(
                    key='reservations',
                    label='Бронирования',
                    url_name='manager_portal:reservation_list',
                    icon='reservations',
                    active=active_tab == 'reservations',
                ),
                _sidebar_item(
                    key='cargos',
                    label='Грузы',
                    url_name='manager_portal:cargo_list',
                    icon='cargos',
                    active=active_tab == 'cargos',
                ),
                _sidebar_item(
                    key='shipments',
                    label='Отгрузки',
                    url_name='manager_portal:shipments',
                    icon='shipments',
                    active=active_tab == 'shipments',
                ),
            ]
        )
    if logistics_items:
        groups.append(
            {
                'key': 'logistics',
                'label': 'Склад и логистика',
                'items': logistics_items,
                'has_enabled_items': any(item['enabled'] for item in logistics_items),
            }
        )

    finance_docs_items = []
    if has_finance_portal_access(user):
        finance_docs_items.append(
            _sidebar_item(
                key='finance',
                label='Финансы',
                url_name='manager_portal:finance',
                icon='finance',
                active=active_module_key == 'finance',
            )
        )
    if has_manager_portal_access(user):
        finance_docs_items.extend(
            [
                _sidebar_item(
                    key='contracts',
                    label='Договоры',
                    url_name='manager_portal:contracts',
                    icon='contracts',
                    active=active_module_key == 'contracts',
                ),
                _sidebar_item(
                    key='purchases',
                    label='Закупки',
                    url_name='manager_portal:purchase_list',
                    icon='purchases',
                    active=active_tab == 'purchases',
                ),
            ]
        )
    if finance_docs_items:
        groups.append(
            {
                'key': 'finance_docs',
                'label': 'Финансы и документы',
                'items': finance_docs_items,
                'has_enabled_items': any(item['enabled'] for item in finance_docs_items),
            }
        )

    return groups


def _can_use_commercial_proposals(user):
    return bool(has_manager_portal_access(user) and user.has_perm('catalog.view_product'))


def _selected_deal_ids(raw_value):
    return [int(value) for value in (raw_value or '').split(',') if value.strip().isdigit()]


def _staff_topbar_context():
    active_deals = ManagerDeal.objects.exclude(
        case_status__in=[ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED]
    )
    problem_count = active_deals.exclude(problem_flags=[]).count()
    overdue_count = active_deals.filter(problem_flags__contains=[ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE]).count()
    unassigned_count = active_deals.filter(responsible_manager__isnull=True).count()
    latest_sync_at = (
        DealActivity.objects.filter(event_type='order.synced')
        .order_by('-created_at')
        .values_list('created_at', flat=True)
        .first()
    )
    return {
        'problem_count': problem_count,
        'overdue_count': overdue_count,
        'unassigned_count': unassigned_count,
        'latest_sync_at': latest_sync_at,
        'problem_url': f'{reverse("manager_portal:deal_list")}?{urlencode({"only_problematic": "1"})}',
        'overdue_url': f'{reverse("manager_portal:deal_list")}?{urlencode({"overlay": ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE})}',
        'unassigned_url': f'{reverse("manager_portal:deal_list")}?{urlencode({"only_unassigned": "1"})}',
        'quick_create_url': reverse('manager_portal:deal_create'),
    }


def _deal_activity_title(activity):
    payload = activity.payload or {}
    if activity.event_type == 'comment.added':
        return 'Комментарий'
    if activity.event_type == 'deal.created':
        return 'Заказ создан'
    if activity.event_type == 'order.synced':
        return 'Заказ синхронизирован'
    if activity.event_type == 'assignment.changed':
        return 'Ответственный обновлен'
    if activity.event_type == 'case_status.changed':
        return f'Этап: {dict(ManagerDeal.CASE_STATUS_CHOICES).get(payload.get("case_status"), "обновлен")}'
    if activity.event_type == 'deadline.changed':
        return 'Дедлайн клиента обновлен'
    if activity.event_type == 'next_step.overridden':
        return f'Ручной next step: {ManagerDeal.next_step_label_for(payload.get("next_step_code"))}'
    if activity.event_type == 'next_step.override_cleared':
        return 'Ручное переопределение снято'
    if activity.event_type == 'reservation.created':
        return f'Бронь #{payload.get("reservation_id")} создана'
    if activity.event_type == 'shipment.created':
        return f'Отгрузка #{payload.get("shipment_id")} создана'
    if activity.event_type == 'finance.created':
        return f'Финансовая сделка #{payload.get("finance_deal_id")} создана'
    if activity.event_type == 'document.created':
        document_type = payload.get('document_type') or 'document'
        document_label = dict(ContractTemplate.DOCUMENT_TYPE_CHOICES).get(document_type, document_type)
        return f'{document_label} создан'
    if activity.event_type == 'inventory.returned_to_stock':
        return 'Возврат принят на склад'
    if activity.event_type == 'workflow.recomputed':
        return 'Workflow пересчитан'
    return activity.event_type


def _deal_activity_body(activity):
    payload = activity.payload or {}
    if activity.event_type == 'comment.added':
        return (payload.get('comment') or '').strip()
    if activity.event_type == 'assignment.changed':
        if activity.actor:
            return f'Назначил: {activity.actor.get_username()}'
        return 'Ответственный по заказу обновлен.'
    if activity.event_type == 'deadline.changed':
        deadline = payload.get('customer_deadline') or 'без даты'
        return f'Новый дедлайн клиента: {deadline}.'
    if activity.event_type == 'next_step.overridden':
        reason = (payload.get('reason') or '').strip()
        return reason or 'Следующий шаг зафиксирован вручную.'
    if activity.event_type == 'next_step.override_cleared':
        return 'Карточка снова использует системный workflow.'
    if activity.event_type == 'workflow.recomputed':
        updates = []
        if payload.get('next_step_code'):
            updates.append(f'Следующий шаг: {ManagerDeal.next_step_label_for(payload["next_step_code"].get("new"))}')
        if payload.get('payment_state'):
            updates.append(
                f'Оплата: {dict(ManagerDeal.PAYMENT_STATE_CHOICES).get(payload["payment_state"].get("new"), payload["payment_state"].get("new"))}'
            )
        if payload.get('fulfillment_status'):
            updates.append(
                f'Обеспечение: {dict(ManagerDeal.FULFILLMENT_STATUS_CHOICES).get(payload["fulfillment_status"].get("new"), payload["fulfillment_status"].get("new"))}'
            )
        if payload.get('documents_status'):
            updates.append(
                f'Документы: {dict(ManagerDeal.DOCUMENTS_STATUS_CHOICES).get(payload["documents_status"].get("new"), payload["documents_status"].get("new"))}'
            )
        if payload.get('delivery_status'):
            updates.append(
                f'Доставка: {dict(ManagerDeal.DELIVERY_STATUS_CHOICES).get(payload["delivery_status"].get("new"), payload["delivery_status"].get("new"))}'
            )
        if payload.get('problem_flags'):
            updates.append('Сигналы обновлены')
        if payload.get('sla_due_at'):
            updates.append('SLA обновлен')
        return ' · '.join(updates) or 'Система обновила расчет заказа.'
    if activity.event_type == 'inventory.returned_to_stock':
        receipt_total = payload.get('receipts_total') or 0
        if receipt_total:
            return f'На склад возвращено {receipt_total} шт.'
        if payload.get('released_reservation_ids'):
            return 'Резерв снят, товар снова доступен на складе.'
        return 'Складской возврат подтвержден.'
    if activity.event_type in {'reservation.created', 'shipment.created', 'finance.created', 'document.created'}:
        return 'Связанная сущность создана из карточки заказа.'
    if activity.event_type == 'order.synced':
        return 'Связи заказа, клиента и текущих сущностей синхронизированы.'
    if activity.event_type == 'deal.created':
        return 'Заказ добавлен в рабочий контур.'
    return ''


def _deal_timeline_entries(activities):
    entries = []
    for activity in activities:
        entries.append(
            {
                'title': _deal_activity_title(activity),
                'body': _deal_activity_body(activity),
                'meta': activity.actor.get_username() if activity.actor else activity.get_source_display(),
                'timestamp': activity.created_at,
                'is_system': activity.source == DealActivity.SOURCE_SYSTEM,
            }
        )
    return entries


def _deal_latest_event_summary(activities):
    if not activities:
        return None
    primary_activity = next(
        (activity for activity in activities if activity.event_type != 'workflow.recomputed'),
        activities[0],
    )
    return {
        'title': _deal_activity_title(primary_activity),
        'body': _deal_activity_body(primary_activity),
        'meta': primary_activity.actor.get_username() if primary_activity.actor else primary_activity.get_source_display(),
        'timestamp': primary_activity.created_at,
    }


def _deal_participant_summary(participants):
    answered = []
    shipped = []
    planned_allocations = []
    for participant in participants:
        name = participant.person_alias.display_name
        if participant.role == ManagerDealParticipant.ROLE_ANSWERED:
            answered.append(name)
        elif participant.role == ManagerDealParticipant.ROLE_SHIPPED:
            shipped.append(name)
        elif participant.role == ManagerDealParticipant.ROLE_PLANNED_PROFIT_SHARE:
            planned_allocations.append(
                {
                    'name': name,
                    'amount': participant.amount,
                    'quantity_basis': participant.quantity_basis,
                }
            )
    return {
        'answered': answered,
        'shipped': shipped,
        'planned_allocations': planned_allocations,
        'has_any': bool(answered or shipped or planned_allocations),
    }


def _deal_participant_name(person_alias):
    return person_alias.display_name if person_alias is not None else ''


def _sync_deal_participants(*, deal, answered_person_alias=None, shipped_person_alias=None, actor=None):
    role_map = {
        ManagerDealParticipant.ROLE_ANSWERED: answered_person_alias,
        ManagerDealParticipant.ROLE_SHIPPED: shipped_person_alias,
    }
    payload = {}
    changed = False
    for role, person_alias in role_map.items():
        queryset = deal.participants.filter(role=role, order_item__isnull=True)
        current_ids = list(queryset.values_list('person_alias_id', flat=True))
        next_ids = [person_alias.pk] if person_alias is not None else []
        if current_ids == next_ids:
            payload[role] = _deal_participant_name(person_alias)
            continue
        queryset.delete()
        if person_alias is not None:
            ManagerDealParticipant.objects.create(
                manager_deal=deal,
                person_alias=person_alias,
                role=role,
            )
        payload[role] = _deal_participant_name(person_alias)
        changed = True
    if changed:
        record_deal_activity(
            deal,
            event_type='participants.updated',
            source='user',
            actor=actor,
            payload=payload,
        )
    return changed


def _deal_request_target(request, *, query_param='createFromDeal'):
    raw_value = (request.POST.get(query_param) or request.GET.get(query_param) or '').strip()
    if not raw_value.isdigit():
        return None
    return ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse').filter(pk=int(raw_value)).first()


def _deal_reservation_prefill_url(deal):
    return f"{reverse('manager_portal:reservation_list')}?{urlencode({'createFromDeal': deal.pk, 'openDrawer': 'reservation-create-drawer'})}"


def _deal_document_prefill_url(deal, *, document_type='contract'):
    return f"{reverse('manager_portal:contracts_create')}?{urlencode({'createFromDeal': deal.pk, 'document_type': document_type})}"


def _deal_finance_prefill_url(deal):
    return f"{reverse('manager_portal:finance_deal_list')}?{urlencode({'createFromDeal': deal.pk})}"


def _deal_confirm_action(deal, *, scope, return_query=''):
    fields = {'action': 'confirm_case'}
    if scope == 'list':
        fields['deal_id'] = deal.pk
        fields['return_query'] = return_query
        url = reverse('manager_portal:deal_list')
    else:
        url = reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk})
    return {
        'label': 'Подтвердить',
        'kind': 'form',
        'url': url,
        'fields': fields,
    }


def _deal_assign_self_action(deal, *, scope, return_query=''):
    fields = {'action': 'assign_self'}
    if scope == 'list':
        fields['deal_id'] = deal.pk
        fields['return_query'] = return_query
        url = reverse('manager_portal:deal_list')
    else:
        url = reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk})
    return {
        'label': 'Назначить себя',
        'kind': 'form',
        'url': url,
        'fields': fields,
    }


def _deal_next_step_action(deal, *, scope, return_query='', finance_deal=None):
    if deal.avito_return_pending:
        return {
            'label': 'Вернуть на склад',
            'kind': 'form',
            'url': reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}),
            'fields': {'action': 'return_to_stock'},
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION:
        return _deal_confirm_action(deal, scope=scope, return_query=return_query)
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION:
        return {
            'label': 'Подтвердить наличие',
            'kind': 'link',
            'url': f'{reverse("manager_portal:deal_detail", kwargs={"pk": deal.pk})}?tab=supply#goods',
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT:
        if finance_deal is not None:
            return {
                'label': 'Зафиксировать оплату',
                'kind': 'link',
                'url': reverse('manager_portal:finance_deal_detail', kwargs={'pk': finance_deal.pk}),
            }
        return {
            'label': 'Запросить оплату',
            'kind': 'link',
            'url': _deal_finance_prefill_url(deal),
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_RESERVATION:
        return {
            'label': 'Создать резерв',
            'kind': 'link',
            'url': _deal_reservation_prefill_url(deal),
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS:
        return {
            'label': 'Подготовить договор',
            'kind': 'link',
            'url': _deal_document_prefill_url(deal, document_type='contract'),
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_DOCUMENT_DISPATCH:
        return {
            'label': 'Отправить документы',
            'kind': 'link',
            'url': _deal_document_prefill_url(deal, document_type='contract'),
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_READY_TO_SHIP:
        return {
            'label': 'Подготовить отправление',
            'kind': 'link',
            'url': reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk}),
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT:
        return {
            'label': 'Открыть снабжение',
            'kind': 'link',
            'url': reverse('manager_portal:purchase_list'),
        }
    if deal.next_step_code == ManagerDeal.NEXT_STEP_SHIPPED:
        return {
            'label': 'Открыть отправление',
            'kind': 'link',
            'url': reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk}),
        }
    return {
        'label': 'Открыть сделку',
        'kind': 'link',
        'url': reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}),
    }


def _deal_primary_cta(deal, *, scope, return_query='', finance_deal=None):
    if deal.responsible_manager_id is None:
        return _deal_assign_self_action(deal, scope=scope, return_query=return_query)
    return _deal_next_step_action(deal, scope=scope, return_query=return_query, finance_deal=finance_deal)


def _deal_secondary_ctas(deal, *, deal_client=None):
    actions = []
    if deal.avito_return_pending:
        actions.append({'label': 'Остатки', 'url': reverse('manager_portal:inventory')})
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION:
        actions.append({'label': 'Склад', 'url': '#goods'})
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT:
        actions.append({'label': 'Счёт', 'url': _deal_document_prefill_url(deal, document_type='invoice')})
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_RESERVATION:
        actions.append({'label': 'Остатки', 'url': reverse('manager_portal:inventory')})
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS:
        actions.append({'label': 'Условия', 'url': '#deal-workflow'})
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_DOCUMENT_DISPATCH:
        actions.append({'label': 'Документы', 'url': '#process-documents'})
    elif deal.next_step_code in {ManagerDeal.NEXT_STEP_READY_TO_SHIP, ManagerDeal.NEXT_STEP_SHIPPED}:
        actions.append({'label': 'Бронь', 'url': '#reservation'})
    else:
        actions.append({'label': 'Управление', 'url': '#deal-workflow'})
    actions.append({'label': 'История', 'url': '#deal-history'})
    return actions[:2]


def _format_duration_compact(delta):
    total_seconds = max(int(delta.total_seconds()), 0)
    total_hours = total_seconds // 3600
    days, hours = divmod(total_hours, 24)
    if days and hours:
        return f'{days} дн {hours} ч'
    if days:
        return f'{days} дн'
    return f'{max(total_hours, 0)} ч'


def _format_duration_tight(delta):
    total_seconds = max(int(delta.total_seconds()), 0)
    total_hours = total_seconds // 3600
    days, hours = divmod(total_hours, 24)
    if days and hours:
        return f'{days}д {hours}ч'
    if days:
        return f'{days}д'
    return f'{max(total_hours, 0)}ч'


def _truncate_single_line(value, *, max_length=64):
    normalized = ' '.join((value or '').split()).strip()
    if len(normalized) <= max_length:
        return normalized
    return f'{normalized[: max_length - 1].rstrip(" ,;:.-")}…'


def _deal_list_action_reason(deal):
    compact_reasons = {
        ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION: 'Новый заказ без подтверждения',
        ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION: 'Нужно проверить склад и наличие',
        ManagerDeal.NEXT_STEP_NEEDS_PAYMENT: 'Оплата ещё не закрыта',
        ManagerDeal.NEXT_STEP_NEEDS_RESERVATION: 'Резерв по позициям не создан',
        ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT: 'Требуется закупка',
        ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS: 'Нужен договорный пакет',
        ManagerDeal.NEXT_STEP_NEEDS_DOCUMENT_DISPATCH: 'Документы готовы к отправке',
        ManagerDeal.NEXT_STEP_READY_TO_SHIP: 'Можно готовить отправление',
        ManagerDeal.NEXT_STEP_SHIPPED: 'Заказ уже в доставке',
        ManagerDeal.NEXT_STEP_RETURN_TO_STOCK: 'Нужно вернуть товар на склад',
        ManagerDeal.NEXT_STEP_COMPLETED: 'Сделка закрыта',
    }
    if deal.next_step_source != ManagerDeal.NEXT_STEP_SOURCE_MANUAL:
        compact_reason = compact_reasons.get(deal.next_step_code)
        if compact_reason:
            return compact_reason
    reason = deal.next_step_reason_snapshot or 'Нужно уточнить следующий шаг'
    compact_reason = ' '.join(reason.split()).strip()
    sentence, _, _ = compact_reason.partition('. ')
    compact_reason = sentence.rstrip('.').strip() or compact_reason
    return _truncate_single_line(compact_reason, max_length=58)


def _deal_list_action_urgency_text(deal):
    if not deal.sla_due_at:
        return 'Без дедлайна'
    if deal.sla_breached_at or deal.sla_due_at <= timezone.now():
        overdue_for = timezone.now() - deal.sla_due_at
        return f'Просрочено на {_format_duration_tight(overdue_for)}'
    remaining = deal.sla_due_at - timezone.now()
    return f'До дедлайна {_format_duration_tight(remaining)}'


def _deal_sla_health_block(deal):
    if not deal.sla_due_at:
        return {
            'text': 'SLA не задан',
            'detail': 'Для следующего шага пока нет дедлайна.',
            'tone': 'neutral',
            'is_overdue': False,
        }
    due_at = timezone.localtime(deal.sla_due_at)
    if deal.sla_breached_at or deal.sla_due_at <= timezone.now():
        overdue_for = timezone.now() - deal.sla_due_at
        return {
            'text': f'следующий шаг просрочен на {_format_duration_compact(overdue_for)}',
            'detail': f'Дедлайн был {due_at:%d.%m %H:%M}.',
            'tone': 'danger',
            'is_overdue': True,
        }
    return {
        'text': f'следующий шаг до {due_at:%d.%m %H:%M}',
        'detail': 'Дедлайн следующего шага ещё не нарушен.',
        'tone': 'neutral',
        'is_overdue': False,
    }


def _deal_activity_health_block(deal):
    last_activity_at = deal.last_activity_at or deal.deal_created_at or deal.created_at
    if not last_activity_at:
        return {
            'text': 'Активность не зафиксирована',
            'detail': 'Сделка пока без событий.',
            'tone': 'neutral',
            'is_stale': False,
        }
    age = timezone.now() - last_activity_at
    local_activity = timezone.localtime(last_activity_at)
    if age >= manager_portal_stale_after():
        return {
            'text': f'нет обновлений {_format_duration_compact(age)}',
            'detail': f'Последняя активность {local_activity:%d.%m %H:%M}.',
            'tone': 'danger',
            'is_stale': True,
        }
    return {
        'text': f'обновлено {local_activity:%d.%m %H:%M}',
        'detail': 'Активность в допустимом окне.',
        'tone': 'positive',
        'is_stale': False,
    }


def _deal_list_owner_sla_summary(deal):
    if deal.responsible_manager_id is None:
        return {
            'label': 'SLA не задан',
            'detail': 'Сначала назначьте владельца сделки.',
            'tone': 'quiet',
            'is_overdue': False,
        }
    if not deal.sla_due_at:
        return {
            'label': 'SLA не задан',
            'detail': 'Для следующего шага дедлайн пока не задан.',
            'tone': 'quiet',
            'is_overdue': False,
        }
    due_at = timezone.localtime(deal.sla_due_at)
    if deal.sla_breached_at or deal.sla_due_at <= timezone.now():
        overdue_for = timezone.now() - deal.sla_due_at
        return {
            'label': f'SLA: просрочено на {_format_duration_compact(overdue_for)}',
            'detail': f'Дедлайн был {due_at:%d.%m %H:%M}.',
            'tone': 'danger',
            'is_overdue': True,
        }
    remaining = deal.sla_due_at - timezone.now()
    return {
        'label': f'SLA: через {_format_duration_compact(remaining)}',
        'detail': f'Дедлайн {due_at:%d.%m %H:%M}.',
        'tone': 'active',
        'is_overdue': False,
    }


def _deal_list_owner_update_text(deal):
    if deal.responsible_manager_id is None:
        return ''
    activity_at = deal.last_activity_at or deal.deal_created_at or deal.created_at
    if not activity_at:
        return 'Обновлений нет'
    activity_at = timezone.localtime(activity_at)
    if activity_at.date() == timezone.localdate():
        return f'Обновлено {activity_at:%H:%M}'
    return f'Обновлено {activity_at:%d.%m %H:%M}'


def _deal_action_block(deal, *, scope, finance_deal=None, deal_client=None, return_query=''):
    return {
        'title': 'Следующее действие',
        'label': deal.next_step_label,
        'reason': deal.next_step_reason_snapshot or 'Система пока не дала пояснение для следующего шага.',
        'source_label': 'Ручной сценарий' if deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL else 'Системный сценарий',
        'primary_action': _deal_primary_cta(
            deal,
            scope=scope,
            return_query=return_query,
            finance_deal=finance_deal,
        ),
        'secondary_actions': _deal_secondary_ctas(deal, deal_client=deal_client),
    }


def _deal_blocker_block(blockers):
    return {
        'title': 'Блокеры',
        'items': blockers[:2],
        'extra_count': max(len(blockers) - 2, 0),
        'is_blocked': bool(blockers),
        'summary': blockers[0]['text'] if blockers else 'Без блокеров',
    }


def _deal_health_block(deal):
    sla = _deal_sla_health_block(deal)
    activity = _deal_activity_health_block(deal)
    return {
        'title': 'SLA / активность',
        'sla': sla,
        'activity': activity,
        'has_attention': sla['is_overdue'] or activity['is_stale'],
    }


def _deal_next_step_panel(deal, *, finance_deal=None, deal_client=None):
    panel = {
        'label': deal.next_step_label,
        'reason': deal.next_step_reason_snapshot or 'Система пока не дала пояснение для следующего шага.',
        'sla_due_at': deal.sla_due_at,
        'source_label': 'Ручной сценарий' if deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL else 'Системный сценарий',
        'primary_action': _deal_primary_cta(deal, scope='detail', finance_deal=finance_deal),
        'secondary_actions': _deal_secondary_ctas(deal),
        'health': _deal_health_block(deal),
    }
    return panel


def _action_identity(action):
    if not action:
        return None
    if action.get('kind') == 'form':
        fields = tuple(sorted((action.get('fields') or {}).items()))
        return ('form', action.get('label'), action.get('url'), fields)
    return ('link', action.get('label'), action.get('url'))


def _unique_actions(actions):
    unique = []
    seen = set()
    for action in actions:
        identity = _action_identity(action)
        if identity is None or identity in seen:
            continue
        seen.add(identity)
        unique.append(action)
    return unique


def _deal_operation_actions(deal, *, finance_deal=None):
    actions = []
    if deal.responsible_manager_id is None:
        actions.append(_deal_assign_self_action(deal, scope='detail'))
    actions.append(_deal_next_step_action(deal, scope='detail', finance_deal=finance_deal))
    return _unique_actions(actions)


def _deal_header_primary_actions(deal, *, reservations, shipments):
    document_type = (
        'invoice'
        if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT
        else 'contract'
    )
    prefer_shipment = (
        deal.delivery_status != ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED
        and (
            bool(shipments)
            or bool(reservations)
            or deal.next_step_code in {
                ManagerDeal.NEXT_STEP_READY_TO_SHIP,
                ManagerDeal.NEXT_STEP_SHIPPED,
            }
            or deal.delivery_status in {
                ManagerDeal.DELIVERY_STATUS_PREPARING,
                ManagerDeal.DELIVERY_STATUS_READY,
                ManagerDeal.DELIVERY_STATUS_SHIPPED,
                ManagerDeal.DELIVERY_STATUS_DELIVERED,
            }
        )
    )
    return [
        {
            'label': 'Изменить статус',
            'kind': 'drawer',
            'target': '#deal-management-drawer',
        },
        {
            'label': 'Добавить оплату',
            'kind': 'link',
            'url': reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk}),
        },
        {
            'label': 'Создать документ',
            'kind': 'link',
            'url': reverse(
                'manager_portal:deal_document_action',
                kwargs={'pk': deal.pk, 'document_type': document_type},
            ),
        },
        {
            'label': 'Создать отгрузку' if prefer_shipment else 'Создать бронь',
            'kind': 'link',
            'url': reverse(
                'manager_portal:deal_shipment_action' if prefer_shipment else 'manager_portal:deal_reservation_action',
                kwargs={'pk': deal.pk},
            ),
        },
    ]


def _deal_header_summary(
    deal,
    *,
    deal_client,
    blockers,
    next_step_panel,
    order_item_rows,
    reservations,
    shipments,
    finance_deal=None,
):
    customer_name = getattr(deal_client, 'name', '') or _deal_customer_label(deal)
    main_product_label = deal.main_product_label() or (
        order_item_rows[0]['item'].resolved_product_name
        if order_item_rows
        else 'Позиции не добавлены'
    )
    return {
        'identity': deal.code or deal.order_id,
        'customer_name': customer_name or 'Клиент не указан',
        'customer_type': deal.get_buyer_type_display(),
        'current_stage': deal.get_case_status_display(),
        'current_status': deal.get_deal_status_display(),
        'amount': deal.grand_total,
        'created_at': deal.deal_created_at,
        'responsible_manager': str(deal.responsible_manager) if deal.responsible_manager else 'Не назначен',
        'source': deal.get_customer_source_display(),
        'next_step_deadline': next_step_panel['sla_due_at'],
        'next_step_label': next_step_panel['label'],
        'next_step_reason': next_step_panel['reason'],
        'action_block': _deal_action_block(deal, scope='detail', finance_deal=finance_deal, deal_client=deal_client),
        'product_label': main_product_label,
        'positions_count': len(order_item_rows),
        'total_quantity': sum(row['item'].quantity for row in order_item_rows),
        'blockers': blockers[:2],
        'blockers_count': len(blockers),
        'blocker_block': _deal_blocker_block(blockers),
        'health_block': _deal_health_block(deal),
        'primary_actions': _deal_header_primary_actions(
            deal,
            reservations=reservations,
            shipments=shipments,
        ),
    }


def _deal_detail_url(deal, *, created=False, tab=''):
    url = reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk})
    params = {}
    if created:
        params['created'] = '1'
    if tab:
        params['tab'] = tab
    if params:
        url = f'{url}?{urlencode(params)}'
    return url


def _deal_remote_action_urls(deal):
    return {
        reverse('manager_portal:deal_reservation_action', kwargs={'pk': deal.pk}),
        reverse('manager_portal:deal_document_action', kwargs={'pk': deal.pk, 'document_type': 'contract'}),
        reverse('manager_portal:deal_document_action', kwargs={'pk': deal.pk, 'document_type': 'invoice'}),
        reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk}),
        reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk}),
    }


def _normalize_guided_action(action, *, detail_url, remote_urls):
    if not action:
        return None
    resolved = dict(action)
    kind = resolved.get('kind') or 'link'
    resolved['kind'] = kind
    if kind == 'link':
        url = resolved.get('url') or detail_url
        if url.startswith('#'):
            url = f'{detail_url}{url}'
        resolved['url'] = url
        resolved['is_remote'] = url in remote_urls
    else:
        resolved['is_remote'] = False
    return resolved


def _guided_check(title, *, status, detail, tone, action=None):
    return {
        'title': title,
        'status': status,
        'detail': detail,
        'tone': tone,
        'action': action,
    }


def _guided_support_action(title, *, status, detail, action, tone):
    return {
        'title': title,
        'status': status,
        'detail': detail,
        'action': action,
        'tone': tone,
    }


def _deal_guided_flow(
    deal,
    *,
    next_step_panel,
    workflow_strip,
    blockers,
    activities,
    reservations,
    shipments,
    documents,
    finance_deal,
    supply_summary,
):
    detail_url = _deal_detail_url(deal)
    supply_url = _deal_detail_url(deal, tab='supply')
    documents_url = _deal_detail_url(deal, tab='documents')
    finance_url = _deal_detail_url(deal, tab='finance')
    history_url = f'{detail_url}#deal-history'
    remote_urls = _deal_remote_action_urls(deal)
    latest_event = _deal_latest_event_summary(activities)
    strip_by_label = {item['label']: item for item in workflow_strip}

    created = False
    next_step_action = _normalize_guided_action(next_step_panel['primary_action'], detail_url=detail_url, remote_urls=remote_urls)
    primary_step = {
        'title': 'Что делать сейчас',
        'label': next_step_panel['label'],
        'reason': next_step_panel['reason'],
        'deadline': next_step_panel['sla_due_at'],
        'source_label': next_step_panel['source_label'],
        'action': next_step_action,
    }

    if deal.responsible_manager_id is None:
        assignment_status = 'Назначить ответственного'
        assignment_detail = 'Сделка ещё не взята в работу. Сначала закрепите менеджера, чтобы маршрут не потерялся.'
        assignment_tone = 'blocked'
        assignment_action = _deal_assign_self_action(deal, scope='detail')
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION:
        assignment_status = 'Подтвердить сделку'
        assignment_detail = (
            f'Ответственный уже назначен: {deal.responsible_manager}. '
            'Следующий шаг пока не начнётся, пока заказ не подтверждён.'
        )
        assignment_tone = 'working'
        assignment_action = _deal_confirm_action(deal, scope='detail')
    else:
        assignment_status = 'Под контролем'
        assignment_detail = (
            f'Сделку ведёт {deal.responsible_manager}. '
            f'Текущий этап: {deal.get_case_status_display()}.'
        )
        assignment_tone = 'ready'
        assignment_action = {
            'label': 'Изменить статус',
            'kind': 'drawer',
            'target': '#deal-management-drawer',
        }

    if deal.fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED:
        supply_status = 'Нужна закупка'
        supply_detail = (
            'Текущего покрытия по позициям недостаточно. '
            f'{supply_summary["risk_label"]}.'
        )
        supply_tone = 'working'
        supply_action = {'label': 'Открыть снабжение', 'url': f'{supply_url}#supply'}
    elif deal.fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_NOT_RESERVED:
        supply_status = 'Собрать покрытие'
        supply_detail = 'Резерв под сделку ещё не создан. Проверьте остатки и зафиксируйте бронь.'
        supply_tone = 'blocked'
        supply_action = {'label': 'Создать бронь', 'url': reverse('manager_portal:deal_reservation_action', kwargs={'pk': deal.pk})}
    elif supply_summary['risk_tone'] == 'working':
        supply_status = supply_summary['risk_label']
        supply_detail = (
            f'Резервов: {supply_summary["reservation_count"]}. '
            f'Закупок: {supply_summary["purchase_count"]}. '
            f'Грузов: {supply_summary["cargo_count"]}.'
        )
        supply_tone = 'working'
        supply_action = supply_summary['primary_cta']
    else:
        reserve_source = supply_summary['reserve_source_label'] or 'источник покрытия уже определён'
        supply_status = deal.get_fulfillment_status_display()
        supply_detail = f'Обеспечение собрано: {reserve_source}.'
        supply_tone = 'ready'
        supply_action = {'label': 'Проверить обеспечение', 'url': f'{supply_url}#reservation'}

    downstream_parts = []
    downstream_tone = 'ready'
    downstream_action = {'label': 'Открыть историю', 'url': history_url}
    if deal.balance_due > 0:
        downstream_parts.append(f'оплата: {deal.get_payment_state_display().lower()}')
        downstream_tone = 'working'
        downstream_action = next_step_panel['primary_action'] if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT else {
            'label': 'Открыть оплату',
            'url': reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk}),
        }
    if deal.documents_status not in {
        ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED,
        ManagerDeal.DOCUMENTS_STATUS_SIGNED,
    }:
        downstream_parts.append(f'документы: {deal.get_documents_status_display().lower()}')
        if downstream_tone == 'ready':
            downstream_tone = 'working'
            downstream_action = {
                'label': 'Подготовить документы',
                'url': reverse('manager_portal:deal_document_action', kwargs={'pk': deal.pk, 'document_type': 'contract'}),
            }
    shipment_needed = deal.delivery_status != ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED
    if shipment_needed and deal.delivery_status not in {
        ManagerDeal.DELIVERY_STATUS_READY,
        ManagerDeal.DELIVERY_STATUS_SHIPPED,
        ManagerDeal.DELIVERY_STATUS_DELIVERED,
    }:
        downstream_parts.append(f'отгрузка: {deal.get_delivery_status_display().lower()}')
        if downstream_tone == 'ready':
            downstream_tone = 'working'
            downstream_action = {
                'label': 'Подготовить отправление',
                'url': reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk}),
            }
    if downstream_parts:
        downstream_status = 'Следующий контур ждёт подготовки'
        downstream_detail = 'Дальше по сделке: ' + '; '.join(downstream_parts) + '.'
    else:
        downstream_status = 'Контур готов'
        downstream_detail = 'Оплата, документы и отгрузка не блокируют дальнейшее движение сделки.'

    payment_action = next_step_panel['primary_action'] if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT else (
        {
            'label': 'Открыть оплату',
            'url': reverse('manager_portal:finance_deal_detail', kwargs={'pk': finance_deal.pk}),
        }
        if finance_deal is not None
        else {
            'label': 'Открыть финансы',
            'url': reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk}),
        }
    )
    payment_detail = (
        f'Оплачено {format_currency_amount(deal.amount_paid)}'
        f' · Остаток {format_currency_amount(deal.balance_due)}'
    )

    if deal.fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED:
        supply_support_action = {'label': 'Открыть снабжение', 'url': f'{supply_url}#supply'}
    elif deal.fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_NOT_RESERVED:
        supply_support_action = {'label': 'Создать бронь', 'url': reverse('manager_portal:deal_reservation_action', kwargs={'pk': deal.pk})}
    else:
        supply_support_action = {'label': 'Проверить обеспечение', 'url': f'{supply_url}#reservation'}

    document_action = {
        'label': 'Подготовить документы',
        'url': reverse(
            'manager_portal:deal_document_action',
            kwargs={
                'pk': deal.pk,
                'document_type': 'invoice' if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT else 'contract',
            },
        ),
    }

    shipment_action = (
        {'label': 'Подготовить отправление', 'url': reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk})}
        if shipment_needed
        else {'label': 'Проверить доставку', 'url': f'{supply_url}#process-shipment'}
    )

    support_actions = [
        _guided_support_action(
            'Оплата',
            status=strip_by_label['Оплата']['status'],
            detail=payment_detail,
            action=_normalize_guided_action(payment_action, detail_url=detail_url, remote_urls=remote_urls),
            tone=strip_by_label['Оплата']['tone'],
        ),
        _guided_support_action(
            'Обеспечение',
            status=strip_by_label['Снабжение']['status'],
            detail=supply_detail,
            action=_normalize_guided_action(supply_support_action, detail_url=detail_url, remote_urls=remote_urls),
            tone=strip_by_label['Снабжение']['tone'],
        ),
        _guided_support_action(
            'Документы',
            status=strip_by_label['Документы']['status'],
            detail='Документов в работе: '
            + (
                str(len(documents))
                if documents
                else '0'
            ),
            action=_normalize_guided_action(document_action, detail_url=detail_url, remote_urls=remote_urls),
            tone=strip_by_label['Документы']['tone'],
        ),
        _guided_support_action(
            'Отгрузка',
            status=strip_by_label['Отгрузка']['status'],
            detail=(
                'Доставка не требуется.'
                if not shipment_needed
                else f'Создано отправлений: {len(shipments)}.'
            ),
            action=_normalize_guided_action(shipment_action, detail_url=detail_url, remote_urls=remote_urls),
            tone=strip_by_label['Отгрузка']['tone'],
        ),
        _guided_support_action(
            'История',
            status=latest_event['title'] if latest_event else 'Событий пока нет',
            detail=(
                f'{latest_event["timestamp"]:%d.%m.%Y %H:%M} · {latest_event["meta"]}'
                if latest_event
                else 'Откройте таймлайн, чтобы добавить комментарий или сверить последние действия.'
            ),
            action=_normalize_guided_action({'label': 'Открыть историю', 'url': history_url}, detail_url=detail_url, remote_urls=remote_urls),
            tone='neutral',
        ),
    ]

    return {
        'is_just_created': created,
        'headline': 'Сделка создана' if created else 'Сделка в работе',
        'summary': (
            'Система уже собрала ближайший маршрут: начните с главного шага, затем проверьте обеспечение и смежные процессы.'
            if created
            else 'Карточка продолжает вести менеджера по следующему шагу и смежным процессам без лишних переключений.'
        ),
        'primary_step': primary_step,
        'checks': [
            _guided_check(
                'Назначь следующий шаг',
                status=assignment_status,
                detail=assignment_detail,
                tone=assignment_tone,
                action=_normalize_guided_action(assignment_action, detail_url=detail_url, remote_urls=remote_urls),
            ),
            _guided_check(
                'Проверь наличие',
                status=supply_status,
                detail=supply_detail,
                tone=supply_tone,
                action=_normalize_guided_action(supply_action, detail_url=detail_url, remote_urls=remote_urls),
            ),
            _guided_check(
                'Подготовь следующее',
                status=downstream_status,
                detail=downstream_detail,
                tone=downstream_tone,
                action=_normalize_guided_action(downstream_action, detail_url=detail_url, remote_urls=remote_urls),
            ),
        ],
        'support_actions': support_actions,
        'blockers': blockers[:3],
    }


def _deal_list_actions(deal, *, current_user):
    detail_url = reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk})
    return {
        'primary_action': _deal_primary_cta(deal, scope='list'),
        'detail_url': detail_url,
    }


def _deal_contact_action(deal, *, deal_client=None):
    email = (
        getattr(deal_client, 'email', '')
        or deal.business_email
        or deal.order.email
    ).strip()
    if email:
        return {
            'label': 'Написать клиенту',
            'kind': 'link',
            'url': f'mailto:{email}',
        }
    phone = (
        getattr(deal_client, 'phone', '')
        or deal.customer_phone
        or deal.order.phone
    ).strip()
    if phone:
        normalized_phone = ''.join(ch for ch in phone if ch.isdigit() or ch == '+')
        return {
            'label': 'Связаться с клиентом',
            'kind': 'link',
            'url': f'tel:{normalized_phone or phone}',
        }
    return None


def _deal_list_more_actions(deal, *, deal_client=None, return_query=''):
    detail_url = reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk})
    primary_action = _deal_primary_cta(deal, scope='list', return_query=return_query)
    actions = []
    assign_self_action = _deal_assign_self_action(deal, scope='list', return_query=return_query)
    if deal.responsible_manager_id is None and _action_identity(primary_action) != _action_identity(assign_self_action):
        actions.append(assign_self_action)
    contact_action = _deal_contact_action(deal, deal_client=deal_client)
    if contact_action is not None:
        actions.append(contact_action)
    actions.extend(
        [
            {'label': 'Добавить комментарий', 'kind': 'link', 'url': f'{detail_url}?tab=history#deal-history'},
            {'label': 'Изменить статус', 'kind': 'link', 'url': f'{detail_url}#deal-workflow'},
            {
                'label': 'Создать документ',
                'kind': 'link',
                'url': reverse(
                    'manager_portal:deal_document_action',
                    kwargs={'pk': deal.pk, 'document_type': ContractTemplate.DOC_TYPE_CONTRACT},
                ),
            },
        ]
    )
    actions.extend(
        _resolve_deal_scoped_actions(
            _deal_secondary_ctas(deal, deal_client=deal_client),
            detail_url=detail_url,
        )
    )
    return _unique_actions(actions)


def _deal_list_readiness(deal):
    return (
        {
            'label': 'Оплата',
            'value': deal.get_payment_state_display(),
            'tone': 'positive' if deal.payment_state == ManagerDeal.PAYMENT_STATE_PAID else 'neutral',
        },
        {
            'label': 'Обеспечение',
            'value': deal.get_fulfillment_status_display(),
            'tone': 'positive' if deal.fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_FULFILLED else 'neutral',
        },
        {
            'label': 'Документы',
            'value': deal.get_documents_status_display(),
            'tone': 'positive' if deal.documents_status in {
                ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED,
                ManagerDeal.DOCUMENTS_STATUS_SIGNED,
            } else 'neutral',
        },
    )


def _resolve_deal_scoped_actions(actions, *, detail_url):
    resolved = []
    for action in actions:
        url = action['url']
        if url.startswith('#'):
            url = f'{detail_url}{url}'
        resolved.append({**action, 'url': url})
    return resolved


def _deal_list_commentaries(deal, *, deal_client=None):
    comments = []
    comment_candidates = (
        ('Комментарий клиента', deal.customer_request_comment),
        (
            'Комментарий по клиенту',
            deal.business_comment if deal.buyer_type == ManagerDeal.BUYER_BUSINESS else deal.individual_comment,
        ),
        ('Комментарий по доставке', deal.shipping_comment),
        ('Комментарий CRM', getattr(deal_client, 'comments', '')),
    )
    for label, value in comment_candidates:
        value = (value or '').strip()
        if not value:
            continue
        comments.append({'label': label, 'value': value})
    return comments[:3]


def _deal_list_delivery_summary(deal):
    parts = [deal.get_delivery_method_display(), deal.get_delivery_status_display()]
    route_points = [point for point in [deal.delivery_from_city, deal.delivery_to_city or deal.customer_city] if point]
    if len(route_points) > 1:
        parts.append(f'{route_points[0]} -> {route_points[-1]}')
    elif route_points:
        parts.append(route_points[0])
    if deal.delivery_provider_name:
        parts.append(deal.delivery_provider_name)
    if deal.tracking_number:
        parts.append(f'Трек {deal.tracking_number}')
    return ' · '.join(part for part in parts if part)


def _deal_list_fulfillment_detail(deal):
    if deal.primary_reservation_id:
        return f'Резерв #{deal.primary_reservation_id}'
    if deal.stock_warehouse_id and deal.stock_warehouse:
        return deal.stock_warehouse.name
    if deal.expected_arrival_date:
        return f'ETA {deal.expected_arrival_date:%d.%m.%Y}'
    return 'Покрытие не собрано'


def _deal_list_documents_detail(deal):
    document_count = len(deal.contract_documents.all())
    if document_count:
        return f'{document_count} док.'
    if deal.documents_status == ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED:
        return 'Не требуются'
    return 'Документов нет'


def _deal_list_channel_summary(deal):
    parts = [deal.get_customer_source_display()]
    if deal.avito_contact_channel:
        parts.append(deal.avito_contact_channel)
    return ' · '.join(part for part in parts if part)


def _deal_list_customer_label(deal):
    return deal.customer_name or deal.order.first_name or deal.order.phone or ('Клиент Avito' if deal.is_avito else 'Клиент')


def _deal_list_primary_product_label(deal):
    order_items = list(deal.order.items.all())
    if not order_items:
        return ''
    primary_item = order_items[0]
    parts = [primary_item.resolved_product_name, primary_item.resolved_variant_name]
    return ' · '.join(part for part in parts if part)


def _deal_list_product_summary(deal):
    summary = _deal_list_primary_product_label(deal)
    order_items = list(deal.order.items.all())
    if not order_items:
        return deal.short_label or deal.get_deal_type_display()
    if len(order_items) > 1:
        summary = f'{summary} +{len(order_items) - 1}'
    return summary


def _deal_list_identity_summary(deal):
    customer_label = _deal_list_customer_label(deal)
    if deal.is_avito:
        product_label = deal.avito_listing_title or _deal_list_primary_product_label(deal) or deal.short_label
    else:
        product_label = _deal_list_primary_product_label(deal) or deal.short_label or deal.get_case_status_display()
    parts = [part for part in [customer_label, product_label] if part]
    return ' · '.join(parts) if parts else 'Без описания'


def _deal_list_context_summary(deal):
    primary_status = getattr(deal, 'primary_status', None) or {}
    delivery_label = deal.get_delivery_method_display() or deal.delivery_provider_name
    parts = [deal.get_buyer_type_display(), delivery_label, primary_status.get('label') or deal.get_case_status_display()]
    compact_parts = []
    for part in parts:
        normalized = (part or '').strip()
        if not normalized or normalized == '—' or normalized == 'Не требуется' or normalized in compact_parts:
            continue
        compact_parts.append(normalized)
    return ' · '.join(compact_parts)


def _decorate_deal_list_rows(deals, *, finance_map, current_user, return_query):
    for deal in deals:
        deal.work_queue_client = deal_manager_client(deal)
        finance_deal = finance_map.get(deal.pk)
        deal.list_actions = _deal_list_actions(deal, current_user=current_user)
        deal.list_actions['primary_action'] = _deal_primary_cta(
            deal,
            scope='list',
            return_query=return_query,
            finance_deal=finance_deal,
        )
        deal.list_actions['secondary_actions'] = _resolve_deal_scoped_actions(
            _deal_secondary_ctas(deal, deal_client=deal.work_queue_client),
            detail_url=deal.list_actions['detail_url'],
        )
        deal.list_actions['more_actions'] = _deal_list_more_actions(
            deal,
            deal_client=deal.work_queue_client,
            return_query=return_query,
        )
        assign_self_action = _deal_assign_self_action(deal, scope='list', return_query=return_query)
        deal.list_owner_sla = _deal_list_owner_sla_summary(deal)
        deal.list_owner_update_text = _deal_list_owner_update_text(deal)
        deal.list_owner_action = None
        if deal.responsible_manager_id is None and _action_identity(deal.list_actions['primary_action']) != _action_identity(assign_self_action):
            deal.list_owner_action = assign_self_action
        deal.list_readiness = _deal_list_readiness(deal)
        deal.list_problem_labels = list(deal.problem_flag_labels[:3])
        deal.list_row_key = f'deal-{deal.pk}'
        deal.list_product_summary = _deal_list_product_summary(deal)
        deal.list_channel_summary = _deal_list_channel_summary(deal)
        deal.list_delivery_summary = _deal_list_delivery_summary(deal)
        deal.list_comments = _deal_list_commentaries(deal, deal_client=deal.work_queue_client)
        deal.list_fulfillment_detail = _deal_list_fulfillment_detail(deal)
        deal.list_documents_detail = _deal_list_documents_detail(deal)
        deal.list_action_reason = _deal_list_action_reason(deal)
        deal.list_action_urgency = _deal_list_action_urgency_text(deal)
        deal.list_sla_is_overdue = bool(
            deal.sla_due_at and (deal.sla_breached_at or deal.sla_due_at <= timezone.now())
        )
        deal.action_block = _deal_action_block(
            deal,
            scope='list',
            finance_deal=finance_deal,
            deal_client=deal.work_queue_client,
            return_query=return_query,
        )
        blockers = _deal_blockers(
            deal,
            documents=list(getattr(deal, 'contract_documents').all()),
            reservations=list(getattr(deal, 'reservations').all()),
            shipments=list(getattr(deal, 'shipments').all()),
            finance_deal=finance_deal,
            purchase_items=[],
            cargo_items=[],
        )
        deal.blocker_block = _deal_blocker_block(blockers)
        deal.health_block = _deal_health_block(deal)
        deal.primary_status = deal_primary_status(deal)
        deal.secondary_status = deal_secondary_status(deal)
        deal.risk_summary = deal_risk_summary(deal, blockers=blockers)
        deal.list_identity_summary = _deal_list_identity_summary(deal)
        deal.list_context_summary = _deal_list_context_summary(deal)
    return deals


def _decorate_deal_kanban_rows(deals):
    for deal in deals:
        deal.list_readiness = _deal_list_readiness(deal)
        deal.list_problem_labels = list(deal.problem_flag_labels[:3])
        deal.list_product_summary = _deal_list_product_summary(deal)
        deal.list_delivery_summary = _deal_list_delivery_summary(deal)
        deal.list_sla_is_overdue = bool(
            deal.sla_due_at and (deal.sla_breached_at or deal.sla_due_at <= timezone.now())
        )
        deal.action_block = _deal_action_block(deal, scope='detail')
        deal.blocker_block = _deal_blocker_block(_deal_blockers(
            deal,
            documents=list(getattr(deal, 'contract_documents').all()),
            reservations=[],
            shipments=[],
            finance_deal=None,
            purchase_items=[],
            cargo_items=[],
        ))
        deal.health_block = _deal_health_block(deal)
    return deals


def _sidebar_module_map():
    return {
        'entry': {
            'eyebrow': 'Навигатор',
            'title': 'Каталог модулей',
            'description': 'Единая точка входа в сайт, админку и внутренние рабочие модули по доступам аккаунта.',
            'status': 'Маршрутизация',
            'chips': ['Сайт', 'Admin', 'Модули'],
        },
        'deals': {
            'eyebrow': 'Рабочий центр',
            'title': 'Заказы',
            'description': 'Ежедневная работа менеджера: очереди заказов по следующему шагу, SLA, контекстные действия и единая карточка исполнения.',
            'status': 'Основной поток',
            'chips': ['Очереди', 'Следующий шаг', 'SLA'],
        },
        'dashboard': {
            'eyebrow': 'Сигналы',
            'title': 'Операционный обзор',
            'description': 'Просроченные SLA, проблемные заказы, ETA и операционные риски, собранные поверх рабочих очередей.',
            'status': 'Вторичный контур',
            'chips': ['Сигналы', 'SLA', 'Риск'],
        },
        'finance': {
            'eyebrow': 'Модуль',
            'title': 'Финансы',
            'description': 'Управленческий учет по сделкам, расходам, выплатам и расчетам с партнером.',
            'status': 'Готово',
            'chips': ['Платежи', 'P&L', 'Отчеты'],
        },
        'finance_dashboard': {
            'eyebrow': 'Раздел',
            'title': 'Финансовый обзор',
            'description': 'Сводка периода: выручка, маржа, OPEX, доля партнера и остаток к выплате.',
            'status': 'Рабочий',
            'chips': ['KPI', 'OPEX', 'Payout'],
        },
        'finance_deals': {
            'eyebrow': 'Раздел',
            'title': 'Сделки',
            'description': 'Реестр сделок с расчетом маржи, партнерской доли и расходами по сделке.',
            'status': 'Рабочий',
            'chips': ['Revenue', 'Margin', 'Deals'],
        },
        'finance_expenses': {
            'eyebrow': 'Раздел',
            'title': 'Расходы',
            'description': 'Операционные расходы компании и партнера вне привязки к отдельной сделке.',
            'status': 'Рабочий',
            'chips': ['OPEX', 'Costs', 'Categories'],
        },
        'finance_payouts': {
            'eyebrow': 'Раздел',
            'title': 'Выплаты',
            'description': 'Фиксация выплаченных сумм партнеру для управленческого расчета периода.',
            'status': 'Рабочий',
            'chips': ['Cashflow', 'Settlements', 'Ledger'],
        },
        'finance_report': {
            'eyebrow': 'Раздел',
            'title': 'Отчет',
            'description': 'Выгрузка сводки периода и реестров по сделкам, расходам и выплатам.',
            'status': 'Рабочий',
            'chips': ['Export', 'CSV', 'Archive'],
        },
        'finance_archive': {
            'eyebrow': 'Раздел',
            'title': 'Архив',
            'description': 'Полная история сделок, расходов и выплат финансового модуля.',
            'status': 'Рабочий',
            'chips': ['History', 'Deals', 'Payouts'],
        },
        'finance_settings': {
            'eyebrow': 'Раздел',
            'title': 'Настройки',
            'description': 'Справочники типов сделок и категорий расходов для новых операций.',
            'status': 'Рабочий',
            'chips': ['Setup', 'Types', 'Categories'],
        },
        'contracts': {
            'eyebrow': 'Модуль',
            'title': 'Договоры',
            'description': 'Внутренний кабинет менеджеров для договоров, счетов, шаблонов и реквизитов на общей базе сайта.',
            'status': 'Внутренний кабинет',
            'chips': ['Shared DB', 'Docs', 'B2B'],
        },
        'contracts_dashboard': {
            'eyebrow': 'Подмодуль',
            'title': 'Дашборд документов',
            'description': 'Сводка по внутреннему кабинету договоров: статусы, суммы, связанные заказы и активность менеджеров.',
            'status': 'Рабочий',
            'chips': ['Dashboard', 'Contracts', 'Invoices'],
        },
        'contracts_documents': {
            'eyebrow': 'Подмодуль',
            'title': 'Документы',
            'description': 'Реестр договоров и счетов с привязкой к клиентам, менеджерам и заказам сайта.',
            'status': 'Рабочий',
            'chips': ['Documents', 'Invoices', 'Counterparties'],
        },
        'contracts_create': {
            'eyebrow': 'Подмодуль',
            'title': 'Создать новый',
            'description': 'Запуск мастера создания нового договора и связанных документов.',
            'status': 'Рабочий',
            'chips': ['Wizard', 'Create', 'Flow'],
        },
        'contracts_templates': {
            'eyebrow': 'Подмодуль',
            'title': 'Шаблоны',
            'description': 'Редактирование HTML-шаблонов документов для внутреннего кабинета менеджеров.',
            'status': 'Рабочий',
            'chips': ['Templates', 'Editor', 'Variables'],
        },
        'contracts_settings': {
            'eyebrow': 'Подмодуль',
            'title': 'Настройки',
            'description': 'Профили компании и реквизиты, которые используются при генерации документов внутри сайта.',
            'status': 'Рабочий',
            'chips': ['Settings', 'Company', 'Profiles'],
        },
        'proposals': {
            'eyebrow': 'Модуль',
            'title': 'Генератор КП',
            'description': 'Подбор товаров и выпуск коммерческого предложения в PDF или HTML без admin-flow.',
            'status': 'Готово',
            'chips': ['Products', 'PDF', 'HTML'],
        },
        'orders': {
            'eyebrow': 'Раздел',
            'title': 'Legacy alias',
            'description': 'Старый URL-алиас, ведущий в процессный центр заказов.',
            'status': 'Compatibility',
            'chips': ['Legacy', 'Redirect'],
        },
        'clients': {
            'eyebrow': 'Раздел',
            'title': 'Клиенты',
            'description': 'Внутренняя CRM-база клиентов, контактов, заказов и броней.',
            'status': 'Рабочий',
            'chips': ['CRM', 'Contacts', 'Reservations'],
        },
        'warehouses': {
            'eyebrow': 'Раздел',
            'title': 'Склады',
            'description': 'Состояние складов и их связь с публичными точками выдачи сайта.',
            'status': 'Рабочий',
            'chips': ['Stock', 'Pickup', 'Sync'],
        },
        'inventory': {
            'eyebrow': 'Раздел',
            'title': 'Остатки',
            'description': 'Матрица on-hand, reserve и incoming по складам и товарным позициям.',
            'status': 'Рабочий',
            'chips': ['On-hand', 'Reserve', 'Incoming'],
        },
        'purchases': {
            'eyebrow': 'Раздел',
            'title': 'Закупки',
            'description': 'Закупочные документы, поставщики и состав будущих поставок.',
            'status': 'Рабочий',
            'chips': ['Suppliers', 'Items', 'Cargo'],
        },
        'cargos': {
            'eyebrow': 'Раздел',
            'title': 'Грузы',
            'description': 'ETA, приемка, split, транспортные этапы и связанные расходы.',
            'status': 'Рабочий',
            'chips': ['ETA', 'Receipt', 'Split'],
        },
        'reservations': {
            'eyebrow': 'Раздел',
            'title': 'Бронирования',
            'description': 'Резерв товара со склада или incoming под клиента и заказ.',
            'status': 'Рабочий',
            'chips': ['Reserve', 'Warehouse', 'Incoming'],
        },
        'shipments': {
            'eyebrow': 'Раздел',
            'title': 'Отгрузки',
            'description': 'Диспетчерский экран по активным броням, готовым к выдаче и отправке.',
            'status': 'Рабочий',
            'chips': ['Queue', 'Dispatch', 'Reserve'],
        },
    }


def _entry_sections(request):
    sections = [
        {
            'title': 'Системные переходы',
            'description': 'Базовые точки входа в публичный сайт и служебные интерфейсы.',
            'items': [
                {
                    'title': 'Зайти на сайт',
                    'description': 'Открыть главную страницу магазина и перейти в публичный интерфейс.',
                    'url': reverse('home'),
                    'badge': 'Система',
                    'status': 'Готово',
                    'accent': 'primary',
                },
                {
                    'title': 'Админ-панель' if request.user.is_staff else 'Профиль',
                    'description': (
                        'Открыть Django admin для управления моделями, каталогом и системными объектами.'
                        if request.user.is_staff
                        else 'Открыть личный кабинет, контакты и историю аккаунта.'
                    ),
                    'url': reverse('admin:index') if request.user.is_staff else reverse('accounts:profile'),
                    'badge': 'Система',
                    'status': 'Готово',
                },
            ],
        },
    ]
    if has_any_manager_portal_access(request.user):
        modules = [
        ]
        if has_manager_portal_access(request.user):
            modules.extend(
                [
                    {
                        'title': 'Логистика',
                        'description': 'Основной рабочий модуль: заказы, клиенты, остатки, склады, грузы, брони и отгрузки.',
                        'url': reverse('manager_portal:deal_list'),
                        'badge': 'Модуль',
                        'status': 'Готово',
                        'accent': 'primary',
                    },
                    {
                        'title': 'Договоры',
                        'description': 'Внутренний кабинет менеджеров для работы с договорами и счетами на общей базе с сайтом.',
                        'url': reverse('manager_portal:contracts'),
                        'badge': 'Модуль',
                        'status': 'Готово',
                    },
                ]
            )
        if has_finance_portal_access(request.user):
            modules.append(
                {
                    'title': 'Финансы',
                    'description': 'Управленческий учет: сделки, расходы, выплаты, аналитика периода и выгрузка отчетов.',
                    'url': reverse('manager_portal:finance'),
                    'badge': 'Модуль',
                    'status': 'Готово',
                }
            )
        if _can_use_commercial_proposals(request.user):
            modules.append(
                {
                    'title': 'Генератор КП',
                    'description': 'Формирование коммерческих предложений как отдельный модуль, без захода в общий admin-flow.',
                    'url': reverse('manager_portal:commercial_proposals'),
                    'badge': 'Модуль',
                    'status': 'Готово',
                }
            )
        sections.insert(
            0,
            {
                'title': 'Рабочие модули',
                'description': 'Верхнеуровневые внутренние модули, через которые менеджер заходит в нужный контур.',
                'items': modules,
            }
        )
    return sections


def _base_context(request, *, active_tab, **extra):
    nav_items = _nav_items(request.user)
    active_label = next((label for key, label, _ in nav_items if key == active_tab), active_tab)
    nav_groups = _nav_groups_with_state(request.user, active_tab)
    sidebar_groups = _sidebar_groups_with_state(request.user, active_tab)
    sidebar_module = _sidebar_module_map().get(
        active_tab,
        {
            'eyebrow': 'Раздел',
            'title': active_label,
            'description': 'Рабочий раздел manager-портала.',
            'status': 'Активен',
            'chips': [],
        },
    )
    context = {
        'manager_nav_items': nav_items,
        'manager_nav_groups': nav_groups,
        'manager_sidebar_groups': sidebar_groups,
        'manager_active_tab': active_tab,
        'manager_active_label': active_label,
        'manager_has_staff_access': has_manager_portal_access(request.user),
        'manager_has_finance_access': has_finance_portal_access(request.user),
        'manager_has_internal_access': has_any_manager_portal_access(request.user),
        'manager_can_access_admin': bool(request.user.is_authenticated and request.user.is_staff),
        'manager_sidebar_module': sidebar_module,
        'manager_global_search_url': reverse('manager_portal:global_search_results') if has_manager_portal_access(request.user) else '',
        'manager_topbar': _staff_topbar_context() if has_manager_portal_access(request.user) else None,
    }
    context.update(extra)
    return context


def _render(request, template_name, *, active_tab, **context):
    return render(request, template_name, _base_context(request, active_tab=active_tab, **context))


def _is_htmx_request(request):
    return request.headers.get('HX-Request') == 'true'


def _reservation_effective_warehouse(reservation):
    return reservation_effective_warehouse(reservation)


def _redirect_back_to_deal(request, *, fallback, anchor=''):
    deal_id = (
        request.GET.get('deal')
        or request.POST.get('deal')
        or request.GET.get('createFromDeal')
        or request.POST.get('createFromDeal')
    )
    if deal_id and str(deal_id).isdigit():
        deal = ManagerDeal.objects.filter(pk=int(deal_id)).first()
        if deal is not None:
            target = reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk})
            target_anchor = request.GET.get('return_anchor') or request.POST.get('return_anchor') or anchor
            if target_anchor:
                target = f'{target}#{target_anchor}'
            return redirect(target)
    return fallback


@login_required
def entry_view(request):
    has_staff_access = has_manager_portal_access(request.user)
    has_finance_access = has_finance_portal_access(request.user)
    if has_staff_access:
        return redirect('manager_portal:deal_list')
    role_pills = [
        ('Аккаунт', 'Авторизован'),
    ]
    if has_staff_access:
        role_pills.append(('Staff', 'Внутренний доступ'))
    elif has_finance_access:
        role_pills.append(('Finance', 'Доступ только к финансовому контуру'))
    if request.user.is_superuser:
        role_pills.append(('Superuser', 'Полный контроль'))
    return _render(
        request,
        'manager_portal/entry.html',
        active_tab='entry',
        entry_sections=_entry_sections(request),
        entry_role_pills=role_pills,
        entry_has_staff_access=has_staff_access,
        entry_has_finance_access=has_finance_access,
    )


@finance_required
def finance_view(request):
    initial = {'year': timezone.localdate().year, 'month': timezone.localdate().month}
    finance_period_form = FinancePeriodForm(request.GET or None, initial=initial)
    if finance_period_form.is_valid():
        period = finance_period_form.cleaned_data
    else:
        period = initial
    finance_data = finance_dashboard_data(year=period['year'], month=period['month'])
    return _render(
        request,
        'manager_portal/finance_dashboard.html',
        active_tab='finance_dashboard',
        finance_period_form=finance_period_form,
        finance_data=finance_data,
        finance_recent_daily_rows=finance_data['daily_rows'][-14:],
        finance_has_setup=FinanceDealType.objects.exists() and FinanceExpenseCategory.objects.exists(),
    )


@finance_required
def finance_deal_list_view(request):
    create_from_deal = _deal_request_target(request)
    prefilled_finance_deal = FinanceDeal()
    finance_prefill_note = ''
    finance_prefill_hints = []
    finance_prefill_missing_fields = []
    if create_from_deal is not None:
        prefilled_finance_deal = prefill_finance_deal_from_manager_deal(
            FinanceDeal(
                manager_deal=create_from_deal,
                created_by=request.user,
                responsible_manager=create_from_deal.responsible_manager or request.user,
            ),
            create_from_deal,
            actor=request.user,
        )
        finance_prefill_note = f'Новая запись будет привязана к сделке #{create_from_deal.order_id}.'
        finance_prefill_hints = prefilled_finance_deal.snapshot_data.get('expense_hints', [])
        finance_prefill_missing_fields = finance_case_missing_fields(prefilled_finance_deal)
    finance_deal_form = FinanceDealForm(prefix='deal', instance=prefilled_finance_deal)
    if request.method == 'POST':
        finance_deal_form = FinanceDealForm(request.POST, prefix='deal', instance=prefilled_finance_deal)
        if finance_deal_form.is_valid():
            finance_deal = finance_deal_form.save(commit=False)
            finance_deal.created_by = request.user
            if create_from_deal is not None:
                finance_deal.manager_deal = create_from_deal
                finance_deal.responsible_manager = create_from_deal.responsible_manager or request.user
                finance_deal.expected_margin_snapshot = create_from_deal.expected_margin
            finance_deal.save()
            if create_from_deal is not None:
                record_deal_activity(
                    create_from_deal,
                    event_type='finance.created',
                    source=DealActivity.SOURCE_USER,
                    actor=request.user,
                    payload={'finance_deal_id': finance_deal.id},
                )
                recompute_deal_workflow(create_from_deal, actor=request.user)
                messages.success(request, f'Финансовый кейс по сделке #{create_from_deal.order_id} создан.')
                return _redirect_back_to_deal(
                    request,
                    fallback=redirect('manager_portal:finance_deal_detail', pk=finance_deal.pk),
                    anchor='finance',
                )
            messages.success(request, 'Сделка сохранена.')
            return redirect('manager_portal:finance_deal_detail', pk=finance_deal.pk)
        messages.error(request, 'Не удалось сохранить сделку. Проверьте поля формы.')
    finance_deals = FinanceDeal.objects.select_related('deal_type', 'created_by').prefetch_related('expenses').order_by('-date', '-id')
    return _render(
        request,
        'manager_portal/finance_deals.html',
        active_tab='finance_deals',
        finance_deal_form=finance_deal_form,
        finance_deals=finance_deals,
        finance_prefill_deal=create_from_deal,
        finance_prefill_note=finance_prefill_note,
        finance_prefill_hints=finance_prefill_hints,
        finance_prefill_missing_fields=finance_prefill_missing_fields,
    )


@finance_required
def finance_deal_detail_view(request, pk):
    finance_deal = get_object_or_404(
        FinanceDeal.objects.select_related('deal_type', 'created_by', 'responsible_manager', 'linked_document', 'manager_deal'),
        pk=pk,
    )
    deal_form = FinanceDealForm(instance=finance_deal, prefix='deal')
    expense_form = FinanceExpenseForm(
        prefix='expense',
        deal=finance_deal,
        initial={
            'expense_side': FinanceExpense.SIDE_OURS,
            'date': timezone.localdate(),
        },
    )
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_deal':
            deal_form = FinanceDealForm(request.POST, instance=finance_deal, prefix='deal')
            if deal_form.is_valid():
                deal_form.save()
                messages.success(request, 'Сделка обновлена.')
                finance_deal_manager = finance_deal.manager_deal
                if finance_deal_manager is not None:
                    recompute_deal_workflow(finance_deal_manager, actor=request.user)
                return _redirect_back_to_deal(
                    request,
                    fallback=redirect('manager_portal:finance_deal_detail', pk=finance_deal.pk),
                    anchor='finance',
                )
            messages.error(request, 'Не удалось обновить сделку.')
        elif action == 'add_expense':
            expense_form = FinanceExpenseForm(request.POST, prefix='expense', deal=finance_deal)
            if expense_form.is_valid():
                finance_expense = expense_form.save(commit=False)
                finance_expense.deal = finance_deal
                finance_expense.created_by = request.user
                finance_expense.save()
                messages.success(request, 'Расход по сделке добавлен.')
                if finance_deal.manager_deal_id:
                    recompute_deal_workflow(finance_deal.manager_deal, actor=request.user)
                return _redirect_back_to_deal(
                    request,
                    fallback=redirect('manager_portal:finance_deal_detail', pk=finance_deal.pk),
                    anchor='finance',
                )
            messages.error(request, 'Не удалось добавить расход по сделке.')
    return _render(
        request,
        'manager_portal/finance_deal_detail.html',
        active_tab='finance_deals',
        finance_deal=finance_deal,
        finance_deal_form=deal_form,
        finance_expense_form=expense_form,
        finance_deal_expenses=finance_deal.expenses.select_related('category', 'created_by').order_by('-date', '-id'),
        finance_missing_fields=finance_case_missing_fields(finance_deal),
        finance_snapshot=finance_deal.snapshot_data or {},
    )


@finance_required
def finance_expense_list_view(request):
    finance_expense_form = FinanceExpenseForm(
        prefix='expense',
        initial={
            'expense_side': FinanceExpense.SIDE_OURS,
            'date': timezone.localdate(),
        },
    )
    if request.method == 'POST':
        finance_expense_form = FinanceExpenseForm(request.POST, prefix='expense')
        if finance_expense_form.is_valid():
            finance_expense = finance_expense_form.save(commit=False)
            finance_expense.created_by = request.user
            finance_expense.save()
            messages.success(request, 'Операционный расход сохранен.')
            return redirect('manager_portal:finance_expense_list')
        messages.error(request, 'Не удалось сохранить расход.')
    operational_expenses = FinanceExpense.objects.filter(deal__isnull=True).select_related('category', 'created_by').order_by('-date', '-id')
    return _render(
        request,
        'manager_portal/finance_expenses.html',
        active_tab='finance_expenses',
        finance_expense_form=finance_expense_form,
        finance_our_expenses=operational_expenses.filter(expense_side=FinanceExpense.SIDE_OURS),
        finance_partner_expenses=operational_expenses.filter(expense_side=FinanceExpense.SIDE_PARTNER),
    )


@finance_required
def finance_payout_list_view(request):
    finance_payout_form = FinancePayoutForm(prefix='payout', initial={'date': timezone.localdate()})
    if request.method == 'POST':
        finance_payout_form = FinancePayoutForm(request.POST, prefix='payout')
        if finance_payout_form.is_valid():
            finance_payout = finance_payout_form.save(commit=False)
            finance_payout.created_by = request.user
            finance_payout.save()
            messages.success(request, 'Выплата сохранена.')
            return redirect('manager_portal:finance_payout_list')
        messages.error(request, 'Не удалось сохранить выплату.')
    finance_payouts = FinancePayout.objects.select_related('created_by').order_by('-date', '-id')
    return _render(
        request,
        'manager_portal/finance_payouts.html',
        active_tab='finance_payouts',
        finance_payout_form=finance_payout_form,
        finance_payouts=finance_payouts,
    )


@finance_required
def finance_archive_view(request):
    return _render(
        request,
        'manager_portal/finance_archive.html',
        active_tab='finance_archive',
        finance_archive=finance_report_archive(),
    )


@finance_required
def finance_report_view(request):
    initial = {'year': timezone.localdate().year, 'month': timezone.localdate().month}
    finance_period_form = FinancePeriodForm(request.GET or None, initial=initial)
    if finance_period_form.is_valid():
        period = finance_period_form.cleaned_data
    else:
        period = initial
    if request.GET.get('download') == '1':
        content = build_finance_report_zip(year=period['year'], month=period['month'])
        filename = f'finance-report-{period["year"]}-{int(period["month"]):02d}.zip'
        response = HttpResponse(content, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    return _render(
        request,
        'manager_portal/finance_report.html',
        active_tab='finance_report',
        finance_period_form=finance_period_form,
        finance_data=finance_dashboard_data(year=period['year'], month=period['month']),
    )


@finance_required
def finance_settings_view(request):
    finance_settings_readonly = not has_finance_admin_access(request.user)
    finance_deal_type_form = FinanceDealTypeForm(prefix='deal-type')
    finance_expense_category_form = FinanceExpenseCategoryForm(prefix='expense-category')
    if request.method == 'POST':
        if finance_settings_readonly:
            raise PermissionDenied
        action = request.POST.get('action')
        if action == 'create_deal_type':
            finance_deal_type_form = FinanceDealTypeForm(request.POST, prefix='deal-type')
            if finance_deal_type_form.is_valid():
                finance_deal_type_form.save()
                messages.success(request, 'Тип сделки добавлен.')
                return redirect('manager_portal:finance_settings')
            messages.error(request, 'Не удалось добавить тип сделки.')
        elif action == 'update_deal_type':
            deal_type = get_object_or_404(FinanceDealType, pk=request.POST.get('deal_type_id'))
            form = FinanceDealTypeForm(request.POST, instance=deal_type)
            if form.is_valid():
                form.save()
                messages.success(request, 'Тип сделки обновлен.')
                return redirect('manager_portal:finance_settings')
            messages.error(request, 'Не удалось обновить тип сделки.')
        elif action == 'delete_deal_type':
            deal_type = get_object_or_404(FinanceDealType, pk=request.POST.get('deal_type_id'))
            try:
                deal_type.delete()
                messages.success(request, 'Тип сделки удален.')
            except Exception:
                messages.error(request, 'Тип сделки используется в операциях и не может быть удален.')
            return redirect('manager_portal:finance_settings')
        elif action == 'create_expense_category':
            finance_expense_category_form = FinanceExpenseCategoryForm(request.POST, prefix='expense-category')
            if finance_expense_category_form.is_valid():
                finance_expense_category_form.save()
                messages.success(request, 'Категория расхода добавлена.')
                return redirect('manager_portal:finance_settings')
            messages.error(request, 'Не удалось добавить категорию расхода.')
        elif action == 'update_expense_category':
            category = get_object_or_404(FinanceExpenseCategory, pk=request.POST.get('category_id'))
            form = FinanceExpenseCategoryForm(request.POST, instance=category)
            if form.is_valid():
                form.save()
                messages.success(request, 'Категория расхода обновлена.')
                return redirect('manager_portal:finance_settings')
            messages.error(request, 'Не удалось обновить категорию расхода.')
        elif action == 'delete_expense_category':
            category = get_object_or_404(FinanceExpenseCategory, pk=request.POST.get('category_id'))
            try:
                category.delete()
                messages.success(request, 'Категория расхода удалена.')
            except Exception:
                messages.error(request, 'Категория используется в операциях и не может быть удалена.')
            return redirect('manager_portal:finance_settings')
    return _render(
        request,
        'manager_portal/finance_settings.html',
        active_tab='finance_settings',
        finance_settings_readonly=finance_settings_readonly,
        finance_deal_type_form=finance_deal_type_form,
        finance_expense_category_form=finance_expense_category_form,
        finance_deal_types=FinanceDealType.objects.order_by('name'),
        finance_our_categories=FinanceExpenseCategory.objects.filter(expense_side=FinanceExpenseCategory.SIDE_OURS).order_by('name'),
        finance_partner_categories=FinanceExpenseCategory.objects.filter(expense_side=FinanceExpenseCategory.SIDE_PARTNER).order_by('name'),
    )

def _contract_profile_initial():
    return {
        'name': 'Основной профиль BizonVR',
        'legal_type': ContractCompanyProfile.LEGAL_TYPE_IP,
        'company_name': settings.LEGAL_OPERATOR_FULL_NAME,
        'inn': settings.LEGAL_OPERATOR_INN,
        'ogrn': settings.LEGAL_OPERATOR_OGRN,
        'ogrnip': settings.LEGAL_OPERATOR_OGRN,
        'director_genitive': settings.LEGAL_OPERATOR_FULL_NAME,
        'legal_address': settings.LEGAL_OPERATOR_LEGAL_ADDRESS,
        'email': settings.SITE_CONTACT_EMAIL,
        'phone': settings.SITE_CONTACT_PHONE,
        'bank_name': settings.LEGAL_BANK_NAME,
        'checking_account': settings.LEGAL_BANK_ACCOUNT,
        'correspondent_account': settings.LEGAL_BANK_CORR_ACCOUNT,
        'bik': settings.LEGAL_BANK_BIK,
        'is_active': True,
    }


def _get_active_contract_profile():
    profile = ContractCompanyProfile.objects.filter(is_active=True).order_by('-updated_at', '-id').first()
    if profile:
        return profile
    return ContractCompanyProfile(**_contract_profile_initial())


def _contract_preview_context(document):
    """Контекст для рендера шаблона (Django + legacy-переменные)."""
    from .contract_template_render import build_contract_preview_context

    profile = document.company_profile or _get_active_contract_profile()
    return build_contract_preview_context(document, profile=profile)


def _render_contract_preview(document):
    if document.template_id and document.template and document.template.content_html:
        from .contract_template_render import render_contract_template

        template_html = document.template.content_html
        css_text = document.template.css_text.strip()
        return render_contract_template(template_html, document, css_text=css_text)
    if document.html_snapshot:
        if document.snapshot_css:
            return f'<style>{document.snapshot_css}</style>{document.html_snapshot}'
        return document.html_snapshot
    amount = format_currency_amount(document.amount, document.currency, default='') if document.amount is not None else 'Не указана'
    return (
        '<div class="space-y-4">'
        f'<h3>{document.title or document.get_document_type_display()}</h3>'
        f'<p><strong>Номер:</strong> {document.number}</p>'
        f'<p><strong>Контрагент:</strong> {document.counterparty_display}</p>'
        f'<p><strong>Дата:</strong> {document.issue_date:%d.%m.%Y}</p>'
        f'<p><strong>Сумма:</strong> {amount}</p>'
        f'<p><strong>Предмет:</strong> {document.subject or "Не заполнен"}</p>'
        '</div>'
    )


def _save_contract_snapshot(document):
    preview_html = _render_contract_preview(document)
    if preview_html != document.html_snapshot:
        ContractDocument.objects.filter(pk=document.pk).update(html_snapshot=preview_html)
        document.html_snapshot = preview_html


def _prepare_contract_document(document, *, actor):
    if not document.company_profile_id:
        active_profile = ContractCompanyProfile.objects.filter(is_active=True).order_by('-updated_at', '-id').first()
        if active_profile:
            document.company_profile = active_profile
    if actor and not document.responsible_manager_id:
        document.responsible_manager = actor
    if actor and not document.created_by_id:
        document.created_by = actor
    document.populate_runtime_defaults()
    return document


def _contracts_dashboard_context():
    documents = ContractDocument.objects.select_related('manager_client', 'responsible_manager', 'linked_order')
    total_amount = documents.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    recent_documents = documents[:6]
    top_managers = (
        documents.exclude(responsible_manager__isnull=True)
        .values('responsible_manager__username')
        .annotate(total=Count('id'))
        .order_by('-total', 'responsible_manager__username')[:5]
    )
    top_clients = (
        documents.exclude(manager_client__isnull=True)
        .values('manager_client__name')
        .annotate(total=Count('id'))
        .order_by('-total', 'manager_client__name')[:5]
    )
    return {
        'contracts_total_documents': documents.count(),
        'contracts_draft_documents': documents.filter(status=ContractDocument.STATUS_DRAFT).count(),
        'contracts_pending_documents': documents.filter(status__in=[ContractDocument.STATUS_REVIEW, ContractDocument.STATUS_SENT]).count(),
        'contracts_signed_documents': documents.filter(status=ContractDocument.STATUS_SIGNED).count(),
        'contracts_linked_orders': documents.exclude(linked_order__isnull=True).count(),
        'contracts_total_amount': total_amount,
        'contracts_recent_documents': recent_documents,
        'contracts_top_managers': top_managers,
        'contracts_top_clients': top_clients,
    }


@staff_required
def contracts_app_view(request, app_path=''):
    return redirect('manager_portal:contracts')


@staff_required
def contracts_asset_view(request, asset_path):
    return redirect('manager_portal:contracts')


@staff_required
def contracts_api_proxy_view(request, api_path=''):
    return JsonResponse(
        {
            'error': (
                'Внешний contracts API отключен. '
                'Модуль работает как внутренний кабинет manager_portal на общей базе сайта.'
            )
        },
        status=410,
        json_dumps_params={'ensure_ascii': False},
    )


@staff_required
def contracts_view(request):
    return _render(
        request,
        'manager_portal/contracts_dashboard.html',
        active_tab='contracts_dashboard',
        **_contracts_dashboard_context(),
    )


@staff_required
def contracts_documents_view(request):
    filter_form = ContractDocumentFilterForm(request.GET or None)
    documents = ContractDocument.objects.select_related(
        'template',
        'company_profile',
        'manager_client',
        'linked_order',
        'responsible_manager',
    )
    if filter_form.is_valid():
        q = (filter_form.cleaned_data.get('q') or '').strip()
        if q:
            query = (
                Q(number__icontains=q)
                | Q(title__icontains=q)
                | Q(counterparty_name__icontains=q)
                | Q(manager_client__name__icontains=q)
            )
            if q.isdigit():
                query |= Q(linked_order_id=int(q))
            documents = documents.filter(query)
        if filter_form.cleaned_data.get('document_type'):
            documents = documents.filter(document_type=filter_form.cleaned_data['document_type'])
        if filter_form.cleaned_data.get('status'):
            documents = documents.filter(status=filter_form.cleaned_data['status'])
    return _render(
        request,
        'manager_portal/contracts_documents.html',
        active_tab='contracts_documents',
        contracts_filter_form=filter_form,
        contract_documents=documents,
        contract_document_total=documents.count(),
    )


@staff_required
def contracts_detail_view(request, pk):
    document = get_object_or_404(
        ContractDocument.objects.select_related(
            'template',
            'company_profile',
            'manager_client',
            'linked_order',
            'responsible_manager',
            'created_by',
        ),
        pk=pk,
    )
    return _render(
        request,
        'manager_portal/contracts_detail.html',
        active_tab='contracts_documents',
        contract_document=document,
        contract_preview_html=_render_contract_preview(document),
        contract_missing_fields=contract_document_missing_fields(document),
    )


@staff_required
def contracts_create_view(request):
    create_from_deal = _deal_request_target(request)
    document = ContractDocument(created_by=request.user, responsible_manager=request.user)
    contract_prefill_note = ''
    contract_prefill_missing_fields = []
    if create_from_deal is not None:
        requested_type = (request.POST.get('document_type') or request.GET.get('document_type') or '').strip()
        recommendation = _deal_document_recommendation(
            client=deal_manager_client(create_from_deal),
            deal_type=create_from_deal.deal_type,
        )
        if not requested_type:
            requested_type = recommendation['document_type'] or ContractTemplate.DOC_TYPE_CONTRACT
        document = prefill_contract_document_from_manager_deal(
            ContractDocument(
                manager_deal=create_from_deal,
                created_by=request.user,
                responsible_manager=create_from_deal.responsible_manager or request.user,
                document_type=requested_type,
                template=recommendation['template'] if requested_type == recommendation['document_type'] else None,
                status=ContractDocument.STATUS_DRAFT,
                title=f'{dict(ContractTemplate.DOCUMENT_TYPE_CHOICES).get(requested_type, "Документ")} по сделке #{create_from_deal.order_id}',
            ),
            create_from_deal,
            actor=request.user,
            document_type=requested_type,
        )
        contract_prefill_note = f'Документ будет связан со сделкой #{create_from_deal.order_id}.'
        contract_prefill_missing_fields = contract_document_missing_fields(document)
    contract_preview_html = ''
    contract_preview_requested = False
    if request.method == 'POST':
        action = (request.POST.get('action') or 'create').strip()
        form = ContractDocumentForm(request.POST, instance=document)
        if action == 'preview':
            contract_preview_requested = True
            if form.is_valid():
                preview_document = _prepare_contract_document(form.save(commit=False), actor=request.user)
                contract_preview_html = _render_contract_preview(preview_document)
        elif form.is_valid():
            document = _prepare_contract_document(form.save(commit=False), actor=request.user)
            document.save()
            _save_contract_snapshot(document)
            messages.success(request, f'Документ {document.number} создан во внутреннем кабинете.')
            if document.manager_deal_id:
                record_deal_activity(
                    document.manager_deal,
                    event_type='document.created',
                    source=DealActivity.SOURCE_USER,
                    actor=request.user,
                    payload={'document_id': document.id, 'document_type': document.document_type},
                )
                recompute_deal_workflow(document.manager_deal, actor=request.user)
            return _redirect_back_to_deal(
                request,
                fallback=redirect('manager_portal:contracts_detail', pk=document.pk),
                anchor='documents',
            )
    else:
        form = ContractDocumentForm(instance=document)
    return _render(
        request,
        'manager_portal/contracts_create.html',
        active_tab='contracts_create',
        contract_form=form,
        contract_preview_html=contract_preview_html,
        contract_preview_requested=contract_preview_requested,
        contracts_has_templates=ContractTemplate.objects.filter(is_active=True).exists(),
        contracts_has_profiles=ContractCompanyProfile.objects.filter(is_active=True).exists(),
        contract_prefill_deal=create_from_deal,
        contract_prefill_note=contract_prefill_note,
        contract_prefill_missing_fields=contract_prefill_missing_fields,
    )


@staff_required
def contracts_templates_view(request):
    create_form = ContractTemplateForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_template':
            create_form = ContractTemplateForm(request.POST)
            if create_form.is_valid():
                template = create_form.save()
                messages.success(request, f'Шаблон {template.name} создан.')
                return redirect('manager_portal:contracts_templates')
        elif action == 'update_template':
            template = get_object_or_404(ContractTemplate, pk=request.POST.get('template_id'))
            update_form = ContractTemplateForm(request.POST, instance=template)
            if update_form.is_valid():
                update_form.save()
                messages.success(request, f'Шаблон {template.name} обновлен.')
                return redirect('manager_portal:contracts_templates')
            create_form = ContractTemplateForm()
            messages.error(request, 'Не удалось обновить шаблон. Проверьте заполнение полей.')
        elif action == 'delete_template':
            template = get_object_or_404(ContractTemplate, pk=request.POST.get('template_id'))
            template_name = template.name
            template.delete()
            messages.success(request, f'Шаблон {template_name} удален.')
            return redirect('manager_portal:contracts_templates')
    return _render(
        request,
        'manager_portal/contracts_templates.html',
        active_tab='contracts_templates',
        contract_template_form=create_form,
        contract_templates=ContractTemplate.objects.order_by('-is_active', 'sort_order', 'name'),
    )


@staff_required
def contracts_settings_view(request):
    active_profile = ContractCompanyProfile.objects.filter(is_active=True).order_by('-updated_at', '-id').first()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'set_active_profile':
            target_profile = get_object_or_404(ContractCompanyProfile, pk=request.POST.get('profile_id'))
            ContractCompanyProfile.objects.exclude(pk=target_profile.pk).update(is_active=False)
            ContractCompanyProfile.objects.filter(pk=target_profile.pk).update(is_active=True)
            messages.success(request, f'Профиль {target_profile.name} активирован.')
            return redirect('manager_portal:contracts_settings')
        profile_instance = active_profile or ContractCompanyProfile(**_contract_profile_initial())
        form = ContractCompanyProfileForm(request.POST, instance=profile_instance)
        if form.is_valid():
            profile = form.save()
            if profile.is_active:
                ContractCompanyProfile.objects.exclude(pk=profile.pk).update(is_active=False)
            messages.success(request, 'Настройки договорного кабинета сохранены.')
            return redirect('manager_portal:contracts_settings')
    else:
        profile_instance = active_profile or ContractCompanyProfile(**_contract_profile_initial())
        form = ContractCompanyProfileForm(instance=profile_instance)
    return _render(
        request,
        'manager_portal/contracts_settings.html',
        active_tab='contracts_settings',
        contract_profile_form=form,
        contract_profiles=ContractCompanyProfile.objects.order_by('-is_active', 'name'),
    )


def _manager_proposal_contact_data(user):
    manager_first_name = (user.first_name or '').strip()
    manager_last_name = (user.last_name or '').strip()
    manager_email = (getattr(user, 'email', '') or '').strip()
    manager_phone = ''
    try:
        cp_contact = user.cp_contact
        if getattr(cp_contact, 'email', ''):
            manager_email = (cp_contact.email or '').strip()
        if getattr(cp_contact, 'phone', ''):
            manager_phone = (cp_contact.phone or '').strip()
    except Exception:
        pass
    try:
        profile = user.profile
        if not manager_phone:
            manager_phone = profile.phone or ''
    except Exception:
        pass
    if not manager_first_name and not manager_last_name:
        manager_first_name = user.get_full_name() or user.get_username() or ''
    if not manager_phone:
        manager_phone = getattr(settings, 'SITE_CONTACT_PHONE', '')
    return {
        'manager_first_name': manager_first_name,
        'manager_last_name': manager_last_name,
        'manager_email': manager_email,
        'manager_phone': manager_phone,
    }


def _commercial_proposal_products(request):
    product_ids = request.POST.getlist('products')
    if not product_ids:
        return [], Decimal('0')
    products = (
        Product.objects.filter(pk__in=product_ids)
        .select_related('category')
        .prefetch_related('variants', 'images')
        .order_by('category__name', 'name')
    )
    rows = []
    total = Decimal('0')
    for idx, product in enumerate(products, 1):
        qty_str = request.POST.get(f'qty_{product.pk}', '1').strip() or '1'
        try:
            qty = max(1, int(qty_str))
        except ValueError:
            qty = 1
        price_str = request.POST.get(f'price_{product.pk}', '').strip()
        if price_str:
            try:
                price = Decimal(price_str.replace(',', '.'))
                if price < 0:
                    price = product.price
            except Exception:
                price = product.price
        else:
            price = product.price
        row_total = price * qty
        total += row_total
        img = product.get_display_image()
        image_url = request.build_absolute_uri(img.url) if img else ''
        rows.append(
            {
                'num': idx,
                'name': product.name,
                'category': product.category.name,
                'description': product.description or '',
                'image_url': image_url,
                'price': price,
                'qty': qty,
                'row_total': row_total,
            }
        )
    return rows, total


@staff_required
def commercial_proposals_search_view(request):
    if not _can_use_commercial_proposals(request.user):
        raise PermissionDenied
    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return JsonResponse([], safe=False)
    products = (
        Product.objects.filter(name__icontains=q)
        .select_related('category')
        .prefetch_related('variants', 'images')
        .order_by('category__name', 'name')[:15]
    )
    result = []
    for product in products:
        img = product.get_display_image()
        image_url = request.build_absolute_uri(img.url) if img else ''
        result.append(
            {
                'id': product.pk,
                'name': product.name,
                'price': str(product.price),
                'category': product.category.name,
                'image_url': image_url,
            }
        )
    return JsonResponse(result, safe=False, json_dumps_params={'ensure_ascii': False})


@staff_required
def client_lookup_view(request):
    q = (request.GET.get('q') or '').strip()
    mode = request.GET.get('mode')
    if mode not in {CREATE_MODE_QUICK, CREATE_MODE_FULL}:
        mode = CREATE_MODE_QUICK
    if len(q) < 2:
        return JsonResponse([], safe=False, json_dumps_params={'ensure_ascii': False})
    clients = (
        _manager_client_queryset()
        .filter(status=ManagerClient.STATUS_ACTIVE)
        .filter(
            Q(name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
            | Q(telegram__icontains=q)
        )[:CLIENT_LOOKUP_RESULT_LIMIT]
    )
    clients = _decorate_manager_clients(list(clients))
    url_name = 'manager_portal:deal_create' if mode == CREATE_MODE_QUICK else 'manager_portal:order_create'
    return JsonResponse(
        [
            {
                'id': client.pk,
                'name': client.name,
                'phone': client.phone,
                'email': client.email,
                'buyer_type': client.crm_buyer_type_label,
                'source': client.crm_source_label,
                'responsible': client.crm_responsible_label,
                'select_url': f"{reverse(url_name)}?{urlencode({'client': client.pk})}",
            }
            for client in clients
        ],
        safe=False,
        json_dumps_params={'ensure_ascii': False},
    )


@staff_required
def commercial_proposals_view(request):
    if not _can_use_commercial_proposals(request.user):
        raise PermissionDenied
    if request.method == 'POST':
        if not request.POST.getlist('products'):
            messages.warning(request, 'Выберите хотя бы один товар.')
            return redirect('manager_portal:commercial_proposals')
        rows, total = _commercial_proposal_products(request)
        timestamp = timezone.now().strftime('%Y%m%d_%H%M')
        date_display = timezone.now().strftime('%d.%m.%Y')
        valid_until = (timezone.now() + timezone.timedelta(days=7)).strftime('%d.%m.%Y')
        html_content = build_commercial_proposal_html(
            rows=rows,
            total=total,
            date_display=date_display,
            valid_until=valid_until,
            site_url=getattr(settings, 'SITE_URL', ''),
            site_brand=getattr(settings, 'SITE_BRAND', 'BizonVR'),
            logo_url=(
                request.build_absolute_uri(settings.STATIC_URL + getattr(settings, 'SITE_LOGO', ''))
                if getattr(settings, 'SITE_LOGO', '')
                else ''
            ),
            site_phone=getattr(settings, 'SITE_CONTACT_PHONE', ''),
            site_email=getattr(settings, 'SITE_CONTACT_EMAIL', ''),
            site_address=getattr(settings, 'SITE_CONTACT_ADDRESS', ''),
            **_manager_proposal_contact_data(request.user),
        )
        export_format = (request.POST.get('export_format') or 'pdf').lower()
        if export_format == 'pdf':
            try:
                from weasyprint import HTML
                pdf_bytes = HTML(string=html_content, base_url=request.build_absolute_uri('/')).write_pdf()
            except Exception as exc:
                messages.error(
                    request,
                    f'Не удалось сформировать PDF: {exc}. Скачайте HTML и сохраните документ через печать.',
                )
            else:
                response = HttpResponse(pdf_bytes, content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="commercial_proposal_{timestamp}.pdf"'
                return response
        response = HttpResponse(html_content, content_type='text/html; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="commercial_proposal_{timestamp}.html"'
        return response
    return _render(
        request,
        'manager_portal/commercial_proposals.html',
        active_tab='proposals',
    )


@staff_required
def dashboard_view(request):
    target = reverse('manager_portal:deal_list')
    return redirect(f'{target}?{urlencode({"only_problematic": "1"})}')


def _split_full_name(full_name):
    parts = [part for part in (full_name or '').strip().split() if part]
    if not parts:
        return '', ''
    return parts[0], ' '.join(parts[1:])


def _resolve_deal_creation_mode(request):
    mode = request.POST.get('creation_mode') or request.GET.get('mode')
    if mode in {CREATE_MODE_QUICK, CREATE_MODE_FULL}:
        return mode
    if getattr(request, 'resolver_match', None) and request.resolver_match.url_name == 'order_create':
        return CREATE_MODE_FULL
    return CREATE_MODE_QUICK


def _default_deal_status_for_creation(deal_type, customer_source=''):
    allowed_statuses = ManagerDeal.allowed_status_choices(deal_type, customer_source)
    return allowed_statuses[0][0] if allowed_statuses else ManagerDeal.DEAL_STATUS_NEW


def _deal_creation_switch_urls(*, selected_client=None):
    query_string = urlencode({'client': selected_client.pk}) if selected_client is not None else ''
    quick_url = reverse('manager_portal:deal_create')
    full_url = reverse('manager_portal:order_create')
    if query_string:
        quick_url = f'{quick_url}?{query_string}'
        full_url = f'{full_url}?{query_string}'
    return {
        'quick_create_url': quick_url,
        'full_create_url': full_url,
    }


def _default_deal_creation_initial(*, user):
    return {
        'deal_type': ManagerDeal.DEAL_SALE_FROM_STOCK,
        'deal_status': ManagerDeal.DEAL_STATUS_NEW,
        'buyer_type': ManagerDeal.BUYER_INDIVIDUAL,
        'responsible_manager': user.pk,
        'customer_source': ManagerDeal.SOURCE_WEBSITE,
        'delivery_method': ManagerDeal.DELIVERY_CDEK_PVZ,
        'delivery_payer': ManagerDeal.DELIVERY_PAYER_CLIENT,
        'shipment_status': ManagerDeal.SHIPMENT_DRAFT,
    }


def _deal_document_type_for_deal_type(deal_type):
    mapping = {
        ManagerDeal.DEAL_SALE_ON_REQUEST: ContractTemplate.DOC_TYPE_CONTRACT,
        ManagerDeal.DEAL_SALE_FROM_STOCK: ContractTemplate.DOC_TYPE_INVOICE,
        ManagerDeal.DEAL_TRADE_IN: ContractTemplate.DOC_TYPE_APPENDIX,
        ManagerDeal.DEAL_AVITO: '',
    }
    return mapping.get(deal_type, '')


def _recommended_contract_template_for_client(*, client, document_type):
    if not document_type:
        return None
    if client is not None:
        latest_document = (
            client.contract_documents.select_related('template')
            .filter(document_type=document_type)
            .exclude(status=ContractDocument.STATUS_ARCHIVED)
            .order_by('-issue_date', '-id')
            .first()
        )
        if (
            latest_document is not None
            and latest_document.template_id
            and latest_document.template is not None
            and latest_document.template.is_active
            and latest_document.template.document_type == document_type
        ):
            return latest_document.template
    return (
        ContractTemplate.objects.filter(is_active=True, document_type=document_type)
        .order_by('sort_order', 'name')
        .first()
    )


def _deal_document_recommendation(*, client, deal_type):
    document_type = _deal_document_type_for_deal_type(deal_type)
    template = _recommended_contract_template_for_client(client=client, document_type=document_type)
    labels = dict(ContractTemplate.DOCUMENT_TYPE_CHOICES)
    if not document_type:
        return {
            'document_type': '',
            'document_type_label': 'Не требуется',
            'template': None,
            'description': 'Для этого типа сделки документ по умолчанию не рекомендуем.',
        }
    return {
        'document_type': document_type,
        'document_type_label': labels.get(document_type, document_type),
        'template': template,
        'description': 'Черновик документа не создаётся автоматически. Рекомендация подставится при переходе в создание документа.',
    }


def _manual_order_item_payloads(formset):
    payloads = []
    for form in formset:
        if not hasattr(form, 'cleaned_data') or form.cleaned_data.get('DELETE') or not form.has_item_data():
            continue
        product = form.cleaned_data.get('product')
        variant = form.cleaned_data.get('variant')
        payloads.append({
            'product': product,
            'product_name': (form.cleaned_data.get('product_name') or '').strip() or (product.name if product else ''),
            'product_image_url': resolve_order_item_image_url(product=product, variant=variant) if product else '',
            'variant': variant if product else None,
            'configuration': (form.cleaned_data.get('configuration') or '').strip(),
            'condition': form.cleaned_data.get('condition') or OrderItem.CONDITION_NEW,
            'quantity': form.cleaned_data['quantity'],
            'purchase_price': form.cleaned_data.get('purchase_price') or Decimal('0'),
            'sale_price': form.cleaned_data.get('sale_price') or Decimal('0'),
            'discount_amount': form.cleaned_data.get('discount_amount') or Decimal('0'),
            'comment': (form.cleaned_data.get('comment') or '').strip(),
        })
    return payloads


def _manual_tradein_payloads(formset):
    payloads = []
    for form in formset:
        if not hasattr(form, 'cleaned_data') or form.cleaned_data.get('DELETE') or not form.has_item_data():
            continue
        payloads.append({
            'device_type': (form.cleaned_data.get('device_type') or '').strip(),
            'model_name': (form.cleaned_data.get('model_name') or '').strip(),
            'version': (form.cleaned_data.get('version') or '').strip(),
            'kit_description': (form.cleaned_data.get('kit_description') or '').strip(),
            'condition': (form.cleaned_data.get('condition') or '').strip(),
            'is_working': bool(form.cleaned_data.get('is_working')),
            'has_box': bool(form.cleaned_data.get('has_box')),
            'has_controllers': bool(form.cleaned_data.get('has_controllers')),
            'has_accessories': bool(form.cleaned_data.get('has_accessories')),
            'defects': (form.cleaned_data.get('defects') or '').strip(),
            'preliminary_estimate': form.cleaned_data.get('preliminary_estimate') or Decimal('0'),
            'final_estimate': form.cleaned_data.get('final_estimate') or Decimal('0'),
        })
    return payloads


def _manual_order_contact_snapshot(cleaned_data):
    if cleaned_data['buyer_type'] == ManagerDeal.BUYER_BUSINESS:
        first_name, last_name = _split_full_name(cleaned_data.get('business_contact_person'))
        return {
            'first_name': first_name,
            'last_name': last_name,
            'phone': (cleaned_data.get('business_phone') or '').strip(),
            'email': (cleaned_data.get('business_email') or '').strip(),
            'recipient_name': (cleaned_data.get('business_company_name') or cleaned_data.get('business_contact_person') or '').strip(),
            'city': (cleaned_data.get('business_city') or '').strip(),
        }
    first_name, last_name = _split_full_name(cleaned_data.get('individual_full_name'))
    return {
        'first_name': first_name,
        'last_name': last_name,
        'phone': (cleaned_data.get('individual_phone') or '').strip(),
        'email': '',
        'recipient_name': (cleaned_data.get('individual_full_name') or '').strip(),
        'city': (cleaned_data.get('individual_city') or '').strip(),
    }


def _manual_order_payment_status(*, gross_total, paid_amount):
    gross_total = Decimal(gross_total or 0)
    paid_amount = Decimal(paid_amount or 0)
    if paid_amount <= 0:
        return Order.PAYMENT_STATUS_UNPAID
    if paid_amount >= gross_total:
        return Order.PAYMENT_STATUS_PAID
    return Order.PAYMENT_STATUS_PENDING_CONFIRMATION


def _get_or_create_manager_client_for_order(cleaned_data, order):
    if cleaned_data['buyer_type'] == ManagerDeal.BUYER_BUSINESS:
        name = (cleaned_data.get('business_company_name') or '').strip()
        phone = (cleaned_data.get('business_phone') or '').strip()
        email = (cleaned_data.get('business_email') or '').strip().lower()
        address = (cleaned_data.get('business_delivery_address') or cleaned_data.get('business_legal_address') or '').strip()
        comments = (cleaned_data.get('business_comment') or '').strip()
    else:
        name = (cleaned_data.get('individual_full_name') or '').strip()
        phone = (cleaned_data.get('individual_phone') or '').strip()
        email = ''
        address = (cleaned_data.get('individual_delivery_address') or cleaned_data.get('individual_pickup_address') or '').strip()
        comments = (cleaned_data.get('individual_comment') or '').strip()
    return resolve_manager_client(
        name=name,
        phone=phone,
        email=email,
        address=address,
        comments=comments,
        order=order,
    )


def _guess_buyer_type_for_client(*, client, initial):
    buyer_type = initial.get('buyer_type')
    if buyer_type in {ManagerDeal.BUYER_BUSINESS, ManagerDeal.BUYER_INDIVIDUAL}:
        return buyer_type
    normalized_name = (client.name or '').strip().lower()
    company_markers = ('ооо', 'ип', 'зао', 'ао', 'пао', 'ooo', 'llc')
    if any(normalized_name.startswith(marker) for marker in company_markers):
        return ManagerDeal.BUYER_BUSINESS
    return ManagerDeal.BUYER_INDIVIDUAL


def _quick_deal_cleaned_data(*, form, initial):
    client = form.cleaned_data['client']
    buyer_type = _guess_buyer_type_for_client(client=client, initial=initial)
    cleaned_data = {
        'deal_type': form.cleaned_data['deal_type'],
        'deal_status': _default_deal_status_for_creation(
            form.cleaned_data['deal_type'],
            form.cleaned_data['customer_source'],
        ),
        'buyer_type': buyer_type,
        'responsible_manager': form.cleaned_data['responsible_manager'],
        'deal_created_at': timezone.localtime().replace(second=0, microsecond=0),
        'customer_source': form.cleaned_data['customer_source'],
        'deal_comment': '',
        'delivery_method': ManagerDeal.DELIVERY_PICKUP,
        'delivery_from_city': '',
        'delivery_to_city': initial.get('delivery_to_city') or '',
        'delivery_pickup_address': '',
        'delivery_full_address': '',
        'delivery_cost': Decimal('0'),
        'delivery_payer': ManagerDeal.DELIVERY_PAYER_CLIENT,
        'tracking_number': '',
        'shipping_comment': '',
        'shipment_status': ManagerDeal.SHIPMENT_DRAFT,
        'shipped_at': None,
        'planned_receipt_at': None,
        'prepayment_required_amount': Decimal('0'),
        'prepayment_amount': Decimal('0'),
        'stock_warehouse': (
            Warehouse.objects.filter(pk=initial.get('stock_warehouse')).first()
            if form.cleaned_data['deal_type'] == ManagerDeal.DEAL_SALE_FROM_STOCK and initial.get('stock_warehouse')
            else None
        ),
        'procurement_origin': '',
        'supplier_name': '',
        'supplier_agent': '',
        'planned_purchase_date': None,
        'expected_arrival_date': None,
        'expected_customer_ship_date': None,
        'avito_listing_url': '',
        'avito_listing_id': '',
        'avito_listing_title': '',
        'avito_contact_channel': '',
        'avito_list_price': Decimal('0'),
        'avito_final_price': Decimal('0'),
        'avito_commission': Decimal('0'),
        'customer_request': initial.get('customer_request') or '',
        'customer_deadline': None,
        'customer_request_comment': initial.get('customer_request_comment') or '',
        'answered_person_alias': None,
        'shipped_person_alias': None,
        'individual_full_name': '',
        'individual_phone': '',
        'individual_additional_phone': '',
        'individual_city': '',
        'individual_pickup_address': '',
        'individual_delivery_address': '',
        'individual_messenger': client.telegram or '',
        'individual_comment': client.comments or '',
        'business_company_name': '',
        'business_inn': '',
        'business_kpp': '',
        'business_ogrn': '',
        'business_legal_address': '',
        'business_contact_person': '',
        'business_phone': '',
        'business_email': '',
        'business_city': '',
        'business_delivery_address': '',
        'business_comment': client.comments or '',
    }
    if buyer_type == ManagerDeal.BUYER_BUSINESS:
        cleaned_data.update(
            {
                'business_company_name': client.name,
                'business_contact_person': initial.get('business_contact_person') or '',
                'business_phone': client.phone or '',
                'business_email': client.email or '',
                'business_city': initial.get('business_city') or '',
                'business_legal_address': initial.get('business_legal_address') or client.address or '',
                'business_delivery_address': initial.get('business_delivery_address') or client.address or '',
                'business_inn': initial.get('business_inn') or '',
                'business_kpp': initial.get('business_kpp') or '',
                'business_ogrn': initial.get('business_ogrn') or '',
            }
        )
    else:
        cleaned_data.update(
            {
                'individual_full_name': client.name,
                'individual_phone': client.phone or '',
                'individual_additional_phone': initial.get('individual_additional_phone') or '',
                'individual_city': initial.get('individual_city') or '',
                'individual_pickup_address': initial.get('individual_pickup_address') or client.address or '',
                'individual_delivery_address': initial.get('individual_delivery_address') or client.address or '',
            }
        )
    return cleaned_data


def _create_manual_deal(
    *,
    cleaned_data,
    item_payloads,
    tradein_payloads,
    actor,
    creation_mode,
    next_step_code='',
    auto_reserve=False,
    promote_stock_sale=False,
):
    contact = _manual_order_contact_snapshot(cleaned_data)
    delivery_address = (
        (cleaned_data.get('delivery_pickup_address') or '').strip()
        if cleaned_data['delivery_method'] == ManagerDeal.DELIVERY_CDEK_PVZ
        else (cleaned_data.get('delivery_full_address') or '').strip()
    )
    goods_total = sum(
        (
            max(item['sale_price'] - item['discount_amount'], Decimal('0')) * item['quantity']
            for item in item_payloads
        ),
        Decimal('0'),
    )
    tradein_credit = sum(
        (
            item['final_estimate'] if item['final_estimate'] > 0 else item['preliminary_estimate']
            for item in tradein_payloads
        ),
        Decimal('0'),
    )
    client_total = goods_total - tradein_credit + (cleaned_data.get('delivery_cost') or Decimal('0'))
    payment_status = _manual_order_payment_status(
        gross_total=client_total,
        paid_amount=cleaned_data.get('prepayment_amount') or Decimal('0'),
    )
    with transaction.atomic():
        order = Order.objects.create(
            user=None,
            status=ManagerDeal.order_status_for_deal_status(cleaned_data['deal_status']),
            total=goods_total,
            promo_discount=Decimal('0'),
            payment_method=Order.PAYMENT_METHOD_MANAGER_PAYMENT,
            payment_status=payment_status,
            delivery_type=cleaned_data['delivery_method'],
            phone=contact['phone'],
            email=contact['email'],
            first_name=contact['first_name'],
            last_name=contact['last_name'],
            recipient_name=contact['recipient_name'],
            recipient_phone=contact['phone'],
            recipient_is_customer=True,
            country='Россия',
            city_text=(cleaned_data.get('delivery_to_city') or contact['city']).strip(),
            address_line=delivery_address,
            address=delivery_address,
            delivery_comment='',
            delivery_cost=cleaned_data.get('delivery_cost') or Decimal('0'),
            comment=(cleaned_data.get('deal_comment') or '').strip(),
        )
        Order.objects.filter(pk=order.pk).update(created_at=cleaned_data['deal_created_at'])
        order.refresh_from_db()
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=item['product'],
                    product_name=item['product_name'],
                    product_image_url=item['product_image_url'],
                    variant=item['variant'],
                    quantity=item['quantity'],
                    price=item['sale_price'],
                    variant_name=item['configuration'] or (item['variant'].name if item['variant'] else ''),
                    condition=item['condition'] or OrderItem.CONDITION_NEW,
                    purchase_price=item['purchase_price'],
                    discount_amount=item['discount_amount'],
                    comment=item['comment'],
                    is_on_request=cleaned_data['deal_type'] == ManagerDeal.DEAL_SALE_ON_REQUEST,
                )
                for item in item_payloads
            ]
        )
        deal_status = cleaned_data['deal_status']
        is_avito_workflow = ManagerDeal.uses_avito_workflow(
            cleaned_data['deal_type'],
            cleaned_data['customer_source'],
        )
        if (
            promote_stock_sale
            and cleaned_data['deal_type'] == ManagerDeal.DEAL_SALE_FROM_STOCK
            and not is_avito_workflow
            and deal_status == ManagerDeal.DEAL_STATUS_NEW
        ):
            deal_status = ManagerDeal.DEAL_STATUS_RESERVED
            Order.objects.filter(pk=order.pk).update(status=ManagerDeal.order_status_for_deal_status(deal_status))
            order.refresh_from_db()
        case_status = (
            ManagerDeal.CASE_STATUS_NEW
            if creation_mode == CREATE_MODE_QUICK
            else ManagerDeal.CASE_STATUS_CONFIRMED if deal_status != ManagerDeal.DEAL_STATUS_NEW else ManagerDeal.CASE_STATUS_NEW
        )
        deal = ManagerDeal.objects.create(
            order=order,
            responsible_manager=cleaned_data['responsible_manager'],
            assigned_at=timezone.now(),
            assigned_by=actor,
            deal_type=cleaned_data['deal_type'],
            deal_status=deal_status,
            case_status=case_status,
            buyer_type=cleaned_data['buyer_type'],
            customer_source=cleaned_data['customer_source'],
            deal_created_at=cleaned_data['deal_created_at'],
            individual_full_name=(cleaned_data.get('individual_full_name') or '').strip(),
            individual_phone=(cleaned_data.get('individual_phone') or '').strip(),
            individual_additional_phone=(cleaned_data.get('individual_additional_phone') or '').strip(),
            individual_city=(cleaned_data.get('individual_city') or '').strip(),
            individual_pickup_address=(cleaned_data.get('individual_pickup_address') or '').strip(),
            individual_delivery_address=(cleaned_data.get('individual_delivery_address') or '').strip(),
            individual_messenger=(cleaned_data.get('individual_messenger') or '').strip(),
            individual_comment=(cleaned_data.get('individual_comment') or '').strip(),
            business_company_name=(cleaned_data.get('business_company_name') or '').strip(),
            business_inn=(cleaned_data.get('business_inn') or '').strip(),
            business_kpp=(cleaned_data.get('business_kpp') or '').strip(),
            business_ogrn=(cleaned_data.get('business_ogrn') or '').strip(),
            business_legal_address=(cleaned_data.get('business_legal_address') or '').strip(),
            business_contact_person=(cleaned_data.get('business_contact_person') or '').strip(),
            business_phone=(cleaned_data.get('business_phone') or '').strip(),
            business_email=(cleaned_data.get('business_email') or '').strip(),
            business_city=(cleaned_data.get('business_city') or '').strip(),
            business_delivery_address=(cleaned_data.get('business_delivery_address') or '').strip(),
            business_comment=(cleaned_data.get('business_comment') or '').strip(),
            customer_request=(cleaned_data.get('customer_request') or '').strip(),
            customer_deadline=None if is_avito_workflow else cleaned_data.get('customer_deadline'),
            customer_request_comment=(cleaned_data.get('customer_request_comment') or '').strip(),
            delivery_method=cleaned_data['delivery_method'],
            delivery_from_city=(cleaned_data.get('delivery_from_city') or '').strip(),
            delivery_to_city=(cleaned_data.get('delivery_to_city') or '').strip(),
            delivery_pickup_address=(cleaned_data.get('delivery_pickup_address') or '').strip(),
            delivery_full_address=(cleaned_data.get('delivery_full_address') or '').strip(),
            delivery_payer=cleaned_data['delivery_payer'],
            tracking_number=(cleaned_data.get('tracking_number') or '').strip(),
            shipping_comment=(cleaned_data.get('shipping_comment') or '').strip(),
            shipment_status=cleaned_data['shipment_status'],
            shipped_at=cleaned_data.get('shipped_at'),
            planned_receipt_at=cleaned_data.get('planned_receipt_at'),
            prepayment_required_amount=cleaned_data.get('prepayment_required_amount') or Decimal('0'),
            prepayment_amount=cleaned_data.get('prepayment_amount') or Decimal('0'),
            stock_warehouse=cleaned_data.get('stock_warehouse'),
            procurement_origin=(cleaned_data.get('procurement_origin') or '').strip(),
            supplier_name=(cleaned_data.get('supplier_name') or '').strip(),
            supplier_agent=(cleaned_data.get('supplier_agent') or '').strip(),
            planned_purchase_date=cleaned_data.get('planned_purchase_date'),
            expected_arrival_date=cleaned_data.get('expected_arrival_date'),
            expected_customer_ship_date=cleaned_data.get('expected_customer_ship_date'),
            avito_listing_url=(cleaned_data.get('avito_listing_url') or '').strip(),
            avito_listing_id=(cleaned_data.get('avito_listing_id') or '').strip(),
            avito_listing_title=(cleaned_data.get('avito_listing_title') or '').strip(),
            avito_contact_channel=(cleaned_data.get('avito_contact_channel') or '').strip(),
            avito_list_price=cleaned_data.get('avito_list_price') or Decimal('0'),
            avito_final_price=cleaned_data.get('avito_final_price') or Decimal('0'),
            avito_commission=cleaned_data.get('avito_commission') or Decimal('0'),
        )
        _sync_deal_participants(
            deal=deal,
            answered_person_alias=cleaned_data.get('answered_person_alias'),
            shipped_person_alias=cleaned_data.get('shipped_person_alias'),
            actor=actor,
        )
        client_resolution = _get_or_create_manager_client_for_order(cleaned_data, order)
        client = client_resolution['client']
        if auto_reserve and cleaned_data['deal_type'] == ManagerDeal.DEAL_SALE_FROM_STOCK and cleaned_data.get('stock_warehouse'):
            order.refresh_from_db()
            reservation = _create_reservation_for_sale_from_stock(
                deal=deal,
                item_payloads=item_payloads,
                client=client,
                author=actor,
            )
            if reservation is not None:
                deal.reservation = reservation
                deal.reserve_created_at = timezone.now()
                deal.save(update_fields=['primary_reservation', 'reserve_created_at', 'updated_at'])
        if tradein_payloads:
            TradeInItem.objects.bulk_create(
                [
                    TradeInItem(
                        deal=deal,
                        device_type=item['device_type'],
                        model_name=item['model_name'],
                        version=item['version'],
                        kit_description=item['kit_description'],
                        condition=item['condition'],
                        is_working=item['is_working'],
                        has_box=item['has_box'],
                        has_controllers=item['has_controllers'],
                        has_accessories=item['has_accessories'],
                        defects=item['defects'],
                        preliminary_estimate=item['preliminary_estimate'],
                        final_estimate=item['final_estimate'],
                    )
                    for item in tradein_payloads
                ]
            )
        record_deal_activity(
            deal,
            event_type='deal.created',
            source='user',
            actor=actor,
            payload={'order_id': order.id, 'manual': True, 'creation_mode': creation_mode},
        )
        if next_step_code:
            apply_deal_next_step_override(
                deal,
                next_step_code=next_step_code,
                reason='',
                actor=actor,
            )
        recompute_deal_workflow(deal, actor=actor)
    return {
        'order': order,
        'deal': deal,
        'client_resolution': client_resolution,
    }


def _manual_order_prefill_for_client(*, client, user):
    initial = _default_deal_creation_initial(user=user)
    latest_deal = (
        ManagerDeal.objects.filter(order__manager_client_links=client)
        .select_related('responsible_manager')
        .annotate(activity_sort=Coalesce('last_activity_at', 'deal_created_at'))
        .order_by('-activity_sort', '-pk')
        .first()
    )
    if latest_deal is not None:
        initial['deal_type'] = latest_deal.deal_type
        initial['deal_status'] = latest_deal.deal_status
        initial['buyer_type'] = latest_deal.buyer_type
        initial['delivery_method'] = latest_deal.delivery_method
        initial['delivery_payer'] = latest_deal.delivery_payer
        initial['delivery_from_city'] = latest_deal.delivery_from_city
        initial['delivery_to_city'] = latest_deal.delivery_to_city
        initial['delivery_pickup_address'] = latest_deal.delivery_pickup_address or client.address
        initial['delivery_full_address'] = latest_deal.delivery_full_address or client.address
        initial['delivery_cost'] = latest_deal.order.delivery_cost
        initial['shipping_comment'] = latest_deal.shipping_comment
        initial['shipment_status'] = latest_deal.shipment_status
        initial['planned_receipt_at'] = latest_deal.planned_receipt_at
        initial['stock_warehouse'] = latest_deal.stock_warehouse_id
        if not latest_deal.is_avito:
            initial['customer_deadline'] = latest_deal.customer_deadline
        initial['prepayment_required_amount'] = latest_deal.prepayment_required_amount
        initial['prepayment_amount'] = latest_deal.prepayment_amount
        initial['customer_request'] = latest_deal.customer_request
        initial['customer_request_comment'] = latest_deal.customer_request_comment
        initial['procurement_origin'] = latest_deal.procurement_origin
        initial['supplier_name'] = latest_deal.supplier_name
        initial['supplier_agent'] = latest_deal.supplier_agent
        initial['planned_purchase_date'] = latest_deal.planned_purchase_date
        initial['expected_arrival_date'] = latest_deal.expected_arrival_date
        initial['expected_customer_ship_date'] = latest_deal.expected_customer_ship_date
        initial['avito_listing_url'] = latest_deal.avito_listing_url
        initial['avito_listing_id'] = latest_deal.avito_listing_id
        initial['avito_listing_title'] = latest_deal.avito_listing_title
        initial['avito_contact_channel'] = latest_deal.avito_contact_channel
        initial['avito_list_price'] = latest_deal.avito_list_price
        initial['avito_final_price'] = latest_deal.avito_final_price
        initial['avito_commission'] = latest_deal.avito_commission
        answered_participant = latest_deal.participants.filter(
            role=ManagerDealParticipant.ROLE_ANSWERED,
            order_item__isnull=True,
        ).first()
        shipped_participant = latest_deal.participants.filter(
            role=ManagerDealParticipant.ROLE_SHIPPED,
            order_item__isnull=True,
        ).first()
        if answered_participant is not None:
            initial['answered_person_alias'] = answered_participant.person_alias_id
        if shipped_participant is not None:
            initial['shipped_person_alias'] = shipped_participant.person_alias_id
    if initial['buyer_type'] == ManagerDeal.BUYER_BUSINESS:
        initial.update(
            {
                'business_company_name': latest_deal.business_company_name if latest_deal else client.name,
                'business_contact_person': latest_deal.business_contact_person if latest_deal else '',
                'business_inn': latest_deal.business_inn if latest_deal else '',
                'business_kpp': latest_deal.business_kpp if latest_deal else '',
                'business_ogrn': latest_deal.business_ogrn if latest_deal else '',
                'business_phone': latest_deal.business_phone if latest_deal and latest_deal.business_phone else client.phone,
                'business_email': latest_deal.business_email if latest_deal and latest_deal.business_email else client.email,
                'business_comment': latest_deal.business_comment if latest_deal and latest_deal.business_comment else client.comments,
                'business_city': latest_deal.business_city if latest_deal else '',
                'business_legal_address': latest_deal.business_legal_address if latest_deal else client.address,
                'business_delivery_address': latest_deal.business_delivery_address if latest_deal else client.address,
            }
        )
    else:
        initial.update(
            {
                'individual_full_name': latest_deal.individual_full_name if latest_deal and latest_deal.individual_full_name else client.name,
                'individual_phone': latest_deal.individual_phone if latest_deal and latest_deal.individual_phone else client.phone,
                'individual_additional_phone': latest_deal.individual_additional_phone if latest_deal else '',
                'individual_city': latest_deal.individual_city if latest_deal else '',
                'individual_pickup_address': latest_deal.individual_pickup_address if latest_deal else client.address,
                'individual_messenger': latest_deal.individual_messenger if latest_deal and latest_deal.individual_messenger else client.telegram,
                'individual_comment': latest_deal.individual_comment if latest_deal and latest_deal.individual_comment else client.comments,
                'individual_delivery_address': latest_deal.individual_delivery_address if latest_deal and latest_deal.individual_delivery_address else client.address,
            }
        )
    if client.address:
        initial['delivery_pickup_address'] = initial.get('delivery_pickup_address') or client.address
        initial['delivery_full_address'] = initial.get('delivery_full_address') or client.address
    item_initial = []
    tradein_initial = []
    summary = []
    if latest_deal is not None:
        item_initial = [
            {
                'product_name': item.product_name or (item.product.name if item.product_id else ''),
                'product': item.product_id,
                'variant': item.variant_id,
                'configuration': item.variant_name or (item.variant.name if item.variant_id else ''),
                'condition': item.condition,
                'quantity': item.quantity,
                'purchase_price': item.purchase_price,
                'sale_price': item.price,
                'discount_amount': item.discount_amount,
                'comment': item.comment,
            }
            for item in latest_deal.order.items.select_related('variant').all()
        ]
        tradein_initial = [
            {
                'device_type': item.device_type,
                'model_name': item.model_name,
                'version': item.version,
                'kit_description': item.kit_description,
                'condition': item.condition,
                'is_working': item.is_working,
                'has_box': item.has_box,
                'has_controllers': item.has_controllers,
                'has_accessories': item.has_accessories,
                'defects': item.defects,
                'preliminary_estimate': item.preliminary_estimate,
                'final_estimate': item.final_estimate,
            }
            for item in latest_deal.trade_in_items.all()
        ]
        summary = [
            {'label': 'Последняя сделка', 'value': f'#{latest_deal.order_id} · {latest_deal.get_deal_type_display()}'},
            {'label': 'Доставка', 'value': latest_deal.get_delivery_method_display()},
            {'label': 'Позиции', 'value': f'{len(item_initial)} автоподставлено'},
        ]
        if tradein_initial:
            summary.append({'label': 'Trade-in', 'value': f'{len(tradein_initial)} поз.'})
        if latest_deal.customer_request:
            summary.append({'label': 'Интерес', 'value': latest_deal.customer_request[:80]})
        if latest_deal.customer_request_comment:
            summary.append({'label': 'Комментарий', 'value': latest_deal.customer_request_comment[:80]})
        if latest_deal.customer_source:
            summary.append({'label': 'Прошлый источник', 'value': latest_deal.get_customer_source_display()})
        if latest_deal.responsible_manager_id:
            summary.append(
                {
                    'label': 'Прошлый ответственный',
                    'value': latest_deal.responsible_manager.get_username(),
                }
            )
    document_recommendation = _deal_document_recommendation(client=client, deal_type=initial['deal_type'])
    return {
        'initial': initial,
        'item_initial': item_initial,
        'tradein_initial': tradein_initial,
        'summary': summary,
        'latest_deal': latest_deal,
        'history_hints': {
            'customer_source': latest_deal.get_customer_source_display() if latest_deal and latest_deal.customer_source else '',
            'responsible_manager': latest_deal.responsible_manager.get_username()
            if latest_deal and latest_deal.responsible_manager_id
            else '',
        },
        'document_recommendation': document_recommendation,
    }


def _create_reservation_for_sale_from_stock(*, deal, item_payloads, client, author):
    reservations = ensure_order_reservations(
        deal.order,
        client,
        warehouse=deal.stock_warehouse,
        author=author,
        strict=True,
        comment='Автоматический резерв по ручной сделке.',
    )
    return reservations[0] if reservations else None


def _validate_manager_deal_state_transition(deal, *, target_status, paid_amount, tracking_number):
    if target_status == ManagerDeal.DEAL_STATUS_READY_TO_SHIP and deal.deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST:
        if deal.deal_status not in {
            ManagerDeal.DEAL_STATUS_RECEIVED,
            ManagerDeal.DEAL_STATUS_READY_TO_SHIP,
            ManagerDeal.DEAL_STATUS_SHIPPED,
            ManagerDeal.DEAL_STATUS_COMPLETED,
        }:
            raise ValueError('Нельзя отметить заказ как "Готов к отправке", пока товар не поступил.')
    if target_status == ManagerDeal.DEAL_STATUS_SUPPLIER_ORDERED and deal.deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST:
        if deal.prepayment_required_amount > 0 and Decimal(paid_amount or 0) < deal.prepayment_required_amount:
            raise ValueError('Нельзя запускать закупку без суммы предоплаты.')
    if deal.deal_type == ManagerDeal.DEAL_TRADE_IN and target_status in {
        ManagerDeal.DEAL_STATUS_TERMS_AGREED,
        ManagerDeal.DEAL_STATUS_READY_FOR_EXCHANGE,
        ManagerDeal.DEAL_STATUS_TOPUP_RECEIVED,
        ManagerDeal.DEAL_STATUS_NEW_ITEM_SHIPPED,
        ManagerDeal.DEAL_STATUS_COMPLETED,
    }:
        if deal.trade_in_value <= 0:
            raise ValueError('Без оценки входящего товара нельзя финализировать сумму trade-in.')
    if target_status in {
        ManagerDeal.DEAL_STATUS_SHIPPED,
        ManagerDeal.DEAL_STATUS_NEW_ITEM_SHIPPED,
    } and deal.delivery_method in {
        ManagerDeal.DELIVERY_CDEK_PVZ,
        ManagerDeal.DELIVERY_CDEK_COURIER,
    } and not deal.is_avito and not (tracking_number or deal.tracking_number):
        raise ValueError('Для отправки через СДЭК укажите номер заказа / отправления.')


@staff_required
def order_create_view(request):
    creation_mode = _resolve_deal_creation_mode(request)
    selected_client_id = request.POST.get('client') or request.GET.get('client', '')
    selected_client = (
        ManagerClient.objects.filter(pk=int(selected_client_id)).first()
        if selected_client_id.isdigit()
        else None
    )
    selected_client_prefill = (
        _manual_order_prefill_for_client(client=selected_client, user=request.user)
        if selected_client is not None
        else None
    )
    default_initial = _default_deal_creation_initial(user=request.user)
    initial = selected_client_prefill['initial'] if selected_client_prefill is not None else default_initial
    tradein_formset = None

    if creation_mode == CREATE_MODE_QUICK:
        quick_initial = {
            'client': selected_client.pk if selected_client is not None else '',
            'deal_type': initial.get('deal_type', ManagerDeal.DEAL_SALE_FROM_STOCK),
            'customer_source': initial.get('customer_source', ManagerDeal.SOURCE_WEBSITE),
            'responsible_manager': initial.get('responsible_manager', request.user.pk),
            'next_step_code': ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION,
        }
        if request.method == 'POST':
            form = QuickDealForm(request.POST)
            formset = QuickOrderItemFormSet(request.POST, prefix='items')
            form_valid = form.is_valid()
            items_valid = formset.is_valid()
            if form_valid and items_valid:
                item_payloads = _manual_order_item_payloads(formset)
                quick_prefill = _manual_order_prefill_for_client(client=form.cleaned_data['client'], user=request.user)
                cleaned_data = _quick_deal_cleaned_data(form=form, initial=quick_prefill['initial'])
                try:
                    creation_result = _create_manual_deal(
                        cleaned_data=cleaned_data,
                        item_payloads=item_payloads,
                        tradein_payloads=[],
                        actor=request.user,
                        creation_mode=CREATE_MODE_QUICK,
                        next_step_code=form.cleaned_data['next_step_code'],
                        auto_reserve=False,
                        promote_stock_sale=False,
                    )
                    order = creation_result['order']
                    deal = creation_result['deal']
                    client_resolution = creation_result['client_resolution']
                    client_state_message = {
                        'created': 'клиент создан',
                        'user': 'клиент найден по user',
                        'phone': 'клиент найден по телефону',
                        'email': 'клиент найден по email',
                    }.get(client_resolution['match_source'], 'клиент связан')
                    messages.success(request, f'Сделка создана, {client_state_message}.')
                    created_url = _deal_detail_url(deal, created=True)
                    if _is_htmx_request(request):
                        response = HttpResponse(status=204)
                        response['HX-Redirect'] = created_url
                        return response
                    return redirect(created_url)
                except ValueError as exc:
                    form.add_error(None, str(exc))
        else:
            form = QuickDealForm(initial=quick_initial)
            formset = QuickOrderItemFormSet(prefix='items', initial=(selected_client_prefill or {}).get('item_initial'))
        form.fields['client'].widget = forms.HiddenInput()
    else:
        if request.method == 'POST':
            form = ManualOrderForm(request.POST)
            formset = ManualOrderItemFormSet(request.POST, prefix='items')
            tradein_formset = TradeInItemFormSet(request.POST, prefix='tradein')
            form_valid = form.is_valid()
            items_valid = formset.is_valid()
            tradein_required = form_valid and form.cleaned_data.get('deal_type') == ManagerDeal.DEAL_TRADE_IN
            tradein_valid = tradein_formset.is_valid() if tradein_required else True
            if form_valid and items_valid and tradein_valid:
                item_payloads = _manual_order_item_payloads(formset)
                tradein_payloads = _manual_tradein_payloads(tradein_formset)
                try:
                    creation_result = _create_manual_deal(
                        cleaned_data=form.cleaned_data,
                        item_payloads=item_payloads,
                        tradein_payloads=tradein_payloads,
                        actor=request.user,
                        creation_mode=CREATE_MODE_FULL,
                        auto_reserve=True,
                        promote_stock_sale=True,
                    )
                    order = creation_result['order']
                    deal = creation_result['deal']
                    client_resolution = creation_result['client_resolution']
                    client_state_message = {
                        'created': 'клиент создан',
                        'user': 'клиент найден по user',
                        'phone': 'клиент найден по телефону',
                        'email': 'клиент найден по email',
                    }.get(client_resolution['match_source'], 'клиент связан')
                    messages.success(request, f'Заказ #{order.pk} создан, {client_state_message}.')
                    created_url = _deal_detail_url(
                        deal,
                        created=not (
                            form.cleaned_data['buyer_type'] == ManagerDeal.BUYER_INDIVIDUAL
                            and ManagerDeal.uses_avito_workflow(
                                form.cleaned_data['deal_type'],
                                form.cleaned_data.get('customer_source') or '',
                            )
                        ),
                    )
                    if _is_htmx_request(request):
                        response = HttpResponse(status=204)
                        response['HX-Redirect'] = created_url
                        return response
                    return redirect(created_url)
                except ValueError as exc:
                    form.add_error(None, str(exc))
        else:
            form = ManualOrderForm(initial=initial)
            formset = ManualOrderItemFormSet(prefix='items', initial=(selected_client_prefill or {}).get('item_initial'))
            tradein_formset = TradeInItemFormSet(prefix='tradein', initial=(selected_client_prefill or {}).get('tradein_initial'))

    switch_urls = _deal_creation_switch_urls(selected_client=selected_client)
    current_deal_type = (
        getattr(form, 'cleaned_data', {}).get('deal_type')
        or form.data.get('deal_type')
        or form.initial.get('deal_type')
        or default_initial['deal_type']
    )
    document_recommendation = _deal_document_recommendation(client=selected_client, deal_type=current_deal_type)
    return _render(
        request,
        'manager_portal/order_create.html',
        active_tab='deals' if creation_mode == CREATE_MODE_QUICK else 'orders',
        creation_mode=creation_mode,
        form=form,
        formset=formset,
        tradein_formset=tradein_formset,
        product_catalog=[
            {
                'id': product.pk,
                'name': product.name,
                'price': str(product.price),
                'image_url': resolve_order_item_image_url(product=product),
            }
            for product in Product.objects.filter(is_active=True).prefetch_related('variants', 'images').order_by('name')
        ],
        inventory_rows=inventory_snapshot()[:100],
        selected_client=selected_client,
        selected_client_prefill=selected_client_prefill,
        document_recommendation=document_recommendation,
        client_lookup_url=reverse('manager_portal:client_lookup'),
        quick_create_url=switch_urls['quick_create_url'],
        full_create_url=switch_urls['full_create_url'],
    )


def _deal_queryset(*, lightweight=False):
    queryset = ManagerDeal.objects.select_related(
        'order',
        'responsible_manager',
        'assigned_by',
        'next_step_overridden_by',
        'stock_warehouse',
        'primary_reservation',
    )
    if lightweight:
        queryset = queryset.prefetch_related(
            'order__items__product',
            'order__items__variant',
            'trade_in_items',
            'contract_documents',
        )
    else:
        queryset = queryset.prefetch_related(
            'order__items__product',
            'order__items__variant',
            'trade_in_items',
            'activities__actor',
            'contract_documents',
            'shipments',
            'reservations',
        )
    return queryset.order_by(
        F('sla_due_at').asc(nulls_last=True),
        F('last_activity_at').desc(nulls_last=True),
        '-deal_created_at',
        '-id',
    )


def _active_deals(queryset):
    return queryset.exclude(
        case_status__in=[ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED]
    )


def _apply_deal_scope(queryset, scope):
    avito_filter = Q(customer_source=ManagerDeal.SOURCE_AVITO) | Q(deal_type=ManagerDeal.DEAL_AVITO)
    if scope == DEAL_SCOPE_AVITO:
        return queryset.filter(avito_filter)
    return queryset.exclude(avito_filter)


def _today_action_cutoff():
    now = manager_portal_now()
    return now.replace(hour=23, minute=59, second=59, microsecond=999999)


def _use_default_work_scope(params):
    for key, values in params.lists():
        if key in {'page', 'view', 'scope', 'kanban_scope', 'focus'}:
            continue
        if any((value or '').strip() for value in values):
            return False
    return True


def _apply_deal_sorting(deals, sort_value):
    if sort_value == '-sla_due_at':
        return deals.order_by(
            F('sla_due_at').desc(nulls_last=True),
            F('last_activity_at').desc(nulls_last=True),
            '-deal_created_at',
            '-id',
        )
    if sort_value == '-last_activity_at':
        return deals.order_by(
            F('last_activity_at').desc(nulls_last=True),
            F('sla_due_at').asc(nulls_last=True),
            '-deal_created_at',
            '-id',
        )
    if sort_value == 'last_activity_at':
        return deals.order_by(
            F('last_activity_at').asc(nulls_last=True),
            F('sla_due_at').asc(nulls_last=True),
            '-deal_created_at',
            '-id',
        )
    return deals.order_by(
        F('sla_due_at').asc(nulls_last=True),
        F('last_activity_at').desc(nulls_last=True),
        '-deal_created_at',
        '-id',
    )


def _apply_deal_preset(queryset, params):
    queue = params.get('queue')
    overlay = params.get('overlay')
    problem_view = params.get('problem_view')
    if queue:
        queryset = queryset.filter(next_step_code=queue)
    if overlay:
        queryset = queryset.filter(problem_flags__contains=[overlay])
    if problem_view:
        queryset = _apply_deal_problem_view(queryset, problem_view)
    if params.get('only_active'):
        queryset = _active_deals(queryset)
    if params.get('only_unassigned'):
        queryset = queryset.filter(responsible_manager__isnull=True)
    if params.get('only_problematic'):
        queryset = queryset.exclude(problem_flags=[])
    if params.get('action_today'):
        queryset = _active_deals(queryset).filter(sla_due_at__isnull=False, sla_due_at__lte=_today_action_cutoff())
    return queryset


def _apply_deal_problem_view(deals, problem_view):
    if not problem_view:
        return deals
    active_deals = _active_deals(deals)
    today = timezone.localdate()
    if problem_view == DEAL_PROBLEM_VIEW_SLA_OVERDUE:
        return active_deals.filter(problem_flags__contains=[ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE])
    if problem_view == DEAL_PROBLEM_VIEW_STALE_UPDATES:
        return active_deals.filter(problem_flags__contains=[ManagerDeal.PROBLEM_FLAG_STALE_UPDATES])
    if problem_view == DEAL_PROBLEM_VIEW_ETA_OVERDUE:
        return active_deals.filter(
            Q(expected_arrival_date__lt=today) | Q(expected_customer_ship_date__lt=today)
        )
    if problem_view == DEAL_PROBLEM_VIEW_STOCK_CONFLICT:
        return active_deals.filter(problem_flags__contains=[ManagerDeal.PROBLEM_FLAG_STOCK_CONFLICT])
    if problem_view == DEAL_PROBLEM_VIEW_MISSING_CONTACTS:
        return active_deals.filter(problem_flags__contains=[ManagerDeal.PROBLEM_FLAG_MISSING_CONTACTS])
    if problem_view == DEAL_PROBLEM_VIEW_NO_ASSIGNEE:
        return active_deals.filter(responsible_manager__isnull=True)
    if problem_view == DEAL_PROBLEM_VIEW_RESERVATIONS_EXPIRING:
        return active_deals.filter(
            fulfillment_status__in=[
                ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK,
                ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING,
            ],
            reserve_created_at__isnull=False,
            reserve_created_at__lte=timezone.now() - DEAL_SIGNAL_RESERVATION_AGE,
        )
    if problem_view == DEAL_PROBLEM_VIEW_MISSING_B2B_DOCUMENTS:
        return active_deals.filter(buyer_type=ManagerDeal.BUYER_BUSINESS).exclude(
            documents_status=ManagerDeal.DOCUMENTS_STATUS_SIGNED
        )
    if problem_view == DEAL_PROBLEM_VIEW_RESERVED_UNPAID:
        return active_deals.filter(
            fulfillment_status__in=[
                ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK,
                ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING,
            ],
            payment_state__in=[
                ManagerDeal.PAYMENT_STATE_UNPAID,
                ManagerDeal.PAYMENT_STATE_PARTIAL,
            ],
        )
    return deals


def _apply_deal_filters(deals, form, *, user):
    if not form.is_valid():
        return deals
    q = (form.cleaned_data.get('q') or '').strip()
    if q:
        search_query = (
            Q(order__phone__icontains=q)
            | Q(order__email__icontains=q)
            | Q(individual_full_name__icontains=q)
            | Q(individual_phone__icontains=q)
            | Q(business_company_name__icontains=q)
            | Q(business_contact_person__icontains=q)
            | Q(business_phone__icontains=q)
            | Q(contract_documents__number__icontains=q)
            | Q(shipments__tracking_number__icontains=q)
            | Q(order__items__product__name__icontains=q)
            | Q(order__items__product__sku__icontains=q)
            | Q(order__items__variant__name__icontains=q)
            | Q(order__items__variant__sku__icontains=q)
        )
        if q.isdigit():
            search_query |= Q(order_id=int(q))
        deals = deals.filter(search_query).distinct()
    if form.cleaned_data.get('queue'):
        deals = deals.filter(next_step_code=form.cleaned_data['queue'])
    if form.cleaned_data.get('overlay'):
        deals = deals.filter(problem_flags__contains=[form.cleaned_data['overlay']])
    if form.cleaned_data.get('problem_view'):
        deals = _apply_deal_problem_view(deals, form.cleaned_data['problem_view'])
    if form.cleaned_data.get('case_status'):
        case_status = form.cleaned_data['case_status']
        if case_status == ManagerDeal.CASE_STATUS_COMPLETED:
            deals = deals.filter(
                case_status__in=[
                    ManagerDeal.CASE_STATUS_COMPLETED,
                    ManagerDeal.CASE_STATUS_CANCELLED,
                ]
            )
        else:
            deals = deals.filter(case_status=case_status)
    if form.cleaned_data.get('payment_state'):
        deals = deals.filter(payment_state=form.cleaned_data['payment_state'])
    if form.cleaned_data.get('fulfillment_status'):
        deals = deals.filter(fulfillment_status=form.cleaned_data['fulfillment_status'])
    if form.cleaned_data.get('documents_status'):
        deals = deals.filter(documents_status=form.cleaned_data['documents_status'])
    if form.cleaned_data.get('deal_type'):
        deals = deals.filter(deal_type=form.cleaned_data['deal_type'])
    if form.cleaned_data.get('sla_status'):
        sla_status = form.cleaned_data['sla_status']
        if sla_status == 'today':
            deals = _active_deals(deals).filter(sla_due_at__isnull=False, sla_due_at__lte=_today_action_cutoff())
        elif sla_status == 'overdue':
            deals = deals.filter(problem_flags__contains=[ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE])
        elif sla_status == 'missing':
            deals = deals.filter(sla_due_at__isnull=True)
    if form.cleaned_data.get('responsible_manager'):
        deals = deals.filter(responsible_manager=form.cleaned_data['responsible_manager'])
    if form.cleaned_data.get('mine'):
        deals = deals.filter(responsible_manager=user)
    if form.cleaned_data.get('only_active'):
        deals = _active_deals(deals)
    if form.cleaned_data.get('only_unassigned'):
        deals = deals.filter(responsible_manager__isnull=True)
    if form.cleaned_data.get('only_problematic'):
        deals = deals.exclude(problem_flags=[])
    if form.cleaned_data.get('action_today'):
        deals = _active_deals(deals).filter(sla_due_at__isnull=False, sla_due_at__lte=_today_action_cutoff())
    return _apply_deal_sorting(deals, form.cleaned_data.get('sort'))


def _deal_advanced_filter_state(form):
    advanced_fields = (
        'payment_state',
        'fulfillment_status',
        'documents_status',
        'deal_type',
        'sla_status',
        'overlay',
        'problem_view',
        'case_status',
        'mine',
        'only_active',
        'only_unassigned',
        'action_today',
    )
    active_count = 0
    if form.is_valid():
        for field_name in advanced_fields:
            if form.cleaned_data.get(field_name):
                active_count += 1
        sort_value = form.cleaned_data.get('sort') or ''
    else:
        for field_name in advanced_fields:
            if form.data.get(field_name):
                active_count += 1
        sort_value = (form.data.get('sort') or '').strip()
    if sort_value and sort_value != (form.fields['sort'].initial or ''):
        active_count += 1
    return active_count > 0, active_count


def _deal_queue_views(base_queryset):
    tone_map = {
        'problematic': 'danger',
        'unassigned': 'danger',
        ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS: 'warning',
        ManagerDeal.NEXT_STEP_NEEDS_PAYMENT: 'warning',
        ManagerDeal.NEXT_STEP_NEEDS_RESERVATION: 'muted',
        ManagerDeal.NEXT_STEP_READY_TO_SHIP: 'success',
    }
    compact_presets = (
        {
            'key': 'problematic',
            'label': 'Проблемные',
            'params': {'only_problematic': '1'},
        },
        {
            'key': 'unassigned',
            'label': 'Без ответственного',
            'params': {'only_unassigned': '1'},
        },
        {
            'key': ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS,
            'label': 'Ждут документы',
            'params': {'queue': ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS},
        },
        {
            'key': ManagerDeal.NEXT_STEP_NEEDS_PAYMENT,
            'label': 'Ждут оплату',
            'params': {'queue': ManagerDeal.NEXT_STEP_NEEDS_PAYMENT},
        },
        {
            'key': ManagerDeal.NEXT_STEP_NEEDS_RESERVATION,
            'label': 'Ждут резерв',
            'params': {'queue': ManagerDeal.NEXT_STEP_NEEDS_RESERVATION},
        },
        {
            'key': ManagerDeal.NEXT_STEP_READY_TO_SHIP,
            'label': 'Готовы к отгрузке',
            'params': {'queue': ManagerDeal.NEXT_STEP_READY_TO_SHIP},
        },
    )
    presets = []
    for preset in compact_presets:
        params = dict(preset['params'])
        queryset = _apply_deal_preset(base_queryset, params)
        presets.append(
            {
                'key': preset['key'],
                'label': preset['label'],
                'count': queryset.count(),
                'query_string': urlencode(params),
                'tone': tone_map[preset['key']],
            }
        )
    return presets


def _deal_signal_views(base_queryset):
    signal_views = []
    for definition in DEAL_PROBLEM_VIEW_DEFINITIONS:
        params = {'problem_view': definition['code']}
        queryset = _apply_deal_problem_view(base_queryset, definition['code'])
        signal_views.append(
            {
                'code': definition['code'],
                'label': definition['label'],
                'description': definition['description'],
                'count': queryset.count(),
                'query_string': urlencode(params),
            }
        )
    return signal_views


def _deal_priority_metrics(scope, query_params):
    overdue_count = scope.filter(sla_due_at__isnull=False).filter(
        Q(sla_breached_at__isnull=False) | Q(sla_due_at__lte=timezone.now())
    ).count()
    return [
        {
            'key': 'sla_overdue',
            'label': 'Просрочено SLA',
            'count': overdue_count,
            'value': overdue_count,
            'tone': 'critical',
            'query_string': _deal_query_string_with_updates(
                query_params,
                page=None,
                problem_view=DEAL_PROBLEM_VIEW_SLA_OVERDUE,
            ),
        },
        {
            'key': 'unassigned',
            'label': 'Без ответственного',
            'count': scope.filter(responsible_manager__isnull=True).count(),
            'value': scope.filter(responsible_manager__isnull=True).count(),
            'tone': 'neutral',
            'query_string': _deal_query_string_with_updates(query_params, page=None, only_unassigned='1'),
        },
        {
            'key': 'needs_payment',
            'label': 'Ждут оплату',
            'count': scope.filter(next_step_code=ManagerDeal.NEXT_STEP_NEEDS_PAYMENT).count(),
            'value': scope.filter(next_step_code=ManagerDeal.NEXT_STEP_NEEDS_PAYMENT).count(),
            'tone': 'warning',
            'query_string': _deal_query_string_with_updates(
                query_params,
                page=None,
                queue=ManagerDeal.NEXT_STEP_NEEDS_PAYMENT,
            ),
        },
        {
            'key': 'needs_documents',
            'label': 'Ждут документы',
            'count': scope.filter(next_step_code=ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS).count(),
            'value': scope.filter(next_step_code=ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS).count(),
            'tone': 'notice',
            'query_string': _deal_query_string_with_updates(
                query_params,
                page=None,
                queue=ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS,
            ),
        },
        {
            'key': 'problematic',
            'label': 'Проблемные',
            'count': scope.exclude(problem_flags=[]).count(),
            'value': scope.exclude(problem_flags=[]).count(),
            'tone': 'problem',
            'query_string': _deal_query_string_with_updates(query_params, page=None, only_problematic='1'),
        },
    ]


def _deal_overview_metrics(scope, query_params):
    return _deal_priority_metrics(scope, query_params)


def _deal_stage_metrics(scope, query_params):
    definitions = (
        (ManagerDeal.CASE_STATUS_NEW, 'Новые'),
        (ManagerDeal.CASE_STATUS_CONFIRMED, 'Подтверждены'),
        (ManagerDeal.CASE_STATUS_IN_PROGRESS, 'В работе'),
        (ManagerDeal.CASE_STATUS_WAITING_CLIENT, 'Ждут клиента'),
        (ManagerDeal.CASE_STATUS_READY_TO_SHIP, 'Готовы к отправке'),
        (ManagerDeal.CASE_STATUS_COMPLETED, 'Завершены'),
    )
    metrics = []
    for status, label in definitions:
        metrics.append(
            {
                'key': status,
                'label': label,
                'count': scope.filter(case_status=status).count(),
                'query_string': _deal_query_string_with_updates(query_params, page=None, case_status=status),
            }
        )
    return metrics


def _deal_desktop_summary_metrics(scope, query_params):
    return _deal_priority_metrics(scope, query_params)


def _deal_saved_views(user):
    return DealSavedView.objects.filter(owner=user).order_by('name', 'id')


def _deal_toolbar_presets(query_params):
    definitions = (
        ('all', 'Все сделки', {}),
        ('mine', 'Мои сделки', {'mine': '1'}),
        ('problematic', 'Проблемные', {'only_problematic': '1'}),
        ('today', 'На сегодня', {'action_today': '1'}),
        ('unassigned', 'Без ответственного', {'only_unassigned': '1'}),
    )
    active_key = 'all'
    if (query_params.get('mine') or '').strip():
        active_key = 'mine'
    elif (query_params.get('only_problematic') or '').strip():
        active_key = 'problematic'
    elif (query_params.get('action_today') or '').strip():
        active_key = 'today'
    elif (query_params.get('only_unassigned') or '').strip():
        active_key = 'unassigned'
    presets = []
    for key, label, updates in definitions:
        params = {
            'mine': None,
            'only_problematic': None,
            'action_today': None,
            'only_unassigned': None,
            'page': None,
        }
        params.update(updates)
        presets.append(
            {
                'key': key,
                'label': label,
                'active': active_key == key,
                'query_string': _deal_query_string_with_updates(query_params, **params),
            }
        )
    return presets


def _deal_quick_toggle_filters(query_params):
    definitions = (
        ('mine', 'Только мои', 'mine', '1'),
        ('overdue', 'Только просроченные', 'sla_status', 'overdue'),
        ('active', 'Только активные', 'only_active', '1'),
    )
    toggles = []
    for key, label, param_key, param_value in definitions:
        is_active = (query_params.get(param_key) or '').strip() == param_value
        toggles.append(
            {
                'key': key,
                'label': label,
                'active': is_active,
                'query_string': _deal_query_string_with_updates(
                    query_params,
                    page=None,
                    **{param_key: None if is_active else param_value},
                ),
            }
        )
    return toggles


def _deal_reset_filters_query_string(query_params):
    return _deal_query_string_with_updates(
        query_params,
        page=None,
        q=None,
        overlay=None,
        problem_view=None,
        case_status=None,
        payment_state=None,
        fulfillment_status=None,
        documents_status=None,
        deal_type=None,
        sla_status=None,
        responsible_manager=None,
        mine=None,
        only_active=None,
        only_unassigned=None,
        only_problematic=None,
        action_today=None,
        queue=None,
        sort=None,
        focus=None,
    )


def _deal_customer_label(deal):
    if deal.is_avito:
        return deal.avito_listing_title or deal.main_product_label() or deal.order.phone or f'Заказ #{deal.order_id}'
    return deal.customer_name or deal.order.shipping_contact_name or deal.order.phone or f'Заказ #{deal.order_id}'


def _deal_query_string_without_page(query_params):
    params = query_params.copy()
    params.pop('page', None)
    return params.urlencode()


def _deal_query_string_with_updates(query_params, **updates):
    params = query_params.copy()
    for key, value in updates.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


def _deal_view_mode(request):
    raw_value = (request.GET.get('view') or request.POST.get('view') or '').strip()
    if raw_value in DEAL_VIEW_CHOICES:
        return raw_value
    return DEAL_VIEW_LIST


def _deal_scope_mode(request):
    raw_value = (
        request.GET.get('scope')
        or request.POST.get('scope')
        or request.GET.get('kanban_scope')
        or request.POST.get('kanban_scope')
        or ''
    ).strip()
    if raw_value in DEAL_SCOPE_CHOICES:
        return raw_value
    return DEAL_SCOPE_CORE


def _deal_page_numbers(page_obj):
    total_pages = page_obj.paginator.num_pages
    current = page_obj.number
    markers = []
    for page_number in range(1, total_pages + 1):
        if page_number in {1, total_pages} or abs(page_number - current) <= 1:
            if markers and page_number - markers[-1] > 1:
                markers.append(None)
            markers.append(page_number)
    return markers


def _deal_blockers(deal, *, documents, reservations, shipments, finance_deal, purchase_items, cargo_items):
    blockers = []
    seen = set()
    deal_detail_url = reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk})
    deal_supply_url = f'{deal_detail_url}?tab=supply'
    deal_contract_url = reverse('manager_portal:deal_document_action', kwargs={'pk': deal.pk, 'document_type': 'contract'})
    deal_finance_url = reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk})
    deal_shipment_url = reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk})
    assign_self_action = {
        'label': 'Назначить себя',
        'kind': 'form',
        'url': deal_detail_url,
        'fields': {'action': 'assign_self'},
    }
    settings_action = {
        'label': 'Настройки сделки',
        'kind': 'drawer',
        'target': '#deal-management-drawer',
    }

    def add(key, text, tone='blocked', action=None):
        if key in seen:
            return
        blockers.append({'text': text, 'tone': tone, 'action': action})
        seen.add(key)

    for flag, label in zip(deal.problem_flags or [], deal.problem_flag_labels):
        if flag == ManagerDeal.PROBLEM_FLAG_NO_ASSIGNEE:
            add(f'flag:{flag}', label, action=assign_self_action)
        elif flag == ManagerDeal.PROBLEM_FLAG_MISSING_CONTACTS:
            add(f'flag:{flag}', 'Нет контактов для связи с клиентом.', action=settings_action)
        elif flag == ManagerDeal.PROBLEM_FLAG_STOCK_CONFLICT:
            add(
                f'flag:{flag}',
                label,
                action={'label': 'Открыть обеспечение', 'kind': 'link', 'url': f'{deal_supply_url}#goods'},
            )
        elif flag == ManagerDeal.PROBLEM_FLAG_MISSING_PAYMENT:
            add(
                f'flag:{flag}',
                'Нет оплаты по сделке.',
                action={'label': 'Открыть финансы', 'kind': 'link', 'url': deal_finance_url},
            )
        elif flag == ManagerDeal.PROBLEM_FLAG_MISSING_DOCUMENTS:
            add(
                f'flag:{flag}',
                'Нет документа, готового к отправке клиенту.',
                action={'label': 'Создать договор', 'kind': 'link', 'url': deal_contract_url},
            )
        elif flag == ManagerDeal.PROBLEM_FLAG_PAYMENT_BLOCKED:
            add(
                f'flag:{flag}',
                label,
                action={'label': 'Открыть финансы', 'kind': 'link', 'url': deal_finance_url},
            )
        elif flag == ManagerDeal.PROBLEM_FLAG_SHIPMENT_BLOCKED:
            add(
                f'flag:{flag}',
                label,
                action={'label': 'Создать отправление', 'kind': 'link', 'url': deal_shipment_url},
            )
        elif flag == ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE:
            add(f'flag:{flag}', label, tone='working', action=settings_action)
        elif flag == ManagerDeal.PROBLEM_FLAG_STALE_UPDATES:
            add(f'flag:{flag}', 'По сделке давно не было обновлений.', tone='working', action=settings_action)
        else:
            add(f'flag:{flag}', label)
    if deal.responsible_manager_id is None:
        add('manager', 'Не назначен ответственный менеджер.', action=assign_self_action)
    if not deal.is_avito and deal.customer_deadline and deal.customer_deadline < timezone.localdate():
        add(
            'deadline',
            f'Дедлайн клиента истек {deal.customer_deadline:%d.%m.%Y}.',
            tone='working',
            action=settings_action,
        )
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT and deal.balance_due > 0:
        add('payment', 'Сделка ждет оплату от клиента.', action={'label': 'Открыть финансы', 'kind': 'link', 'url': deal_finance_url})
        if finance_deal is None:
            add('finance', 'Финансовая сделка еще не создана.', action={'label': 'Открыть финансы', 'kind': 'link', 'url': deal_finance_url})
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION:
        add('availability', 'Нужно подтвердить наличие и выбрать склад под бронь.', action={'label': 'Открыть обеспечение', 'kind': 'link', 'url': f'{deal_supply_url}#goods'})
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS and not documents:
        add('documents', 'Нет документа, который можно отправить клиенту.', action={'label': 'Создать договор', 'kind': 'link', 'url': deal_contract_url})
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_DOCUMENT_DISPATCH:
        add('document_dispatch', 'Документы готовы, но еще не отправлены клиенту.', action={'label': 'Открыть документы', 'kind': 'link', 'url': f'{deal_detail_url}?tab=documents#documents'})
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_RESERVATION and not reservations:
        add('reservation', 'Нет резерва под заказ.', action={'label': 'Открыть обеспечение', 'kind': 'link', 'url': f'{deal_supply_url}#reservation'})
    if deal.next_step_code == ManagerDeal.NEXT_STEP_READY_TO_SHIP and not shipments:
        add('shipment', 'Отправление еще не создано.', action={'label': 'Создать отправление', 'kind': 'link', 'url': deal_shipment_url})
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT and not purchase_items:
        add('purchase', 'Нет закупки под заказ.', action={'label': 'Открыть обеспечение', 'kind': 'link', 'url': f'{deal_supply_url}#supply'})
    if cargo_items and any(item.remaining_quantity > 0 for item in cargo_items):
        add(
            'cargo',
            'Не весь входящий груз принят на склад.',
            tone='working',
            action={'label': 'Открыть поставку', 'kind': 'link', 'url': f'{deal_supply_url}#supply'},
        )
    return blockers


def _status_chip(label, *, tone, detail, url=''):
    return {
        'label': label,
        'tone': tone,
        'detail': detail,
        'url': url,
        'status_label': {
            'ready': 'Готово',
            'working': 'Нужно проверить',
            'blocked': 'Не создано',
            'neutral': 'Не требуется',
        }[tone],
    }


def _deal_linked_entities_strip(deal, *, documents, reservations, shipments, finance_deal):
    coverage = reservation_coverage_snapshot(deal.order)
    latest_document = documents[0] if documents else None
    latest_shipment = shipments[0] if shipments else None

    if reservations and coverage['is_complete']:
        reservation_chip = {'label': 'Бронь', 'tone': 'ready', 'status': 'Есть', 'url': '#reservation'}
    elif reservations:
        reservation_chip = {'label': 'Бронь', 'tone': 'working', 'status': 'Частично', 'url': '#reservation'}
    else:
        reservation_chip = {'label': 'Бронь', 'tone': 'blocked', 'status': 'Нет', 'url': '#reservation'}

    if latest_document:
        missing_document_fields = contract_document_missing_fields(latest_document)
        document_chip = {
            'label': 'Документы',
            'tone': 'ready' if not missing_document_fields else 'working',
            'status': 'Готово' if not missing_document_fields else 'Черновик',
            'url': '#process-documents',
        }
    elif deal.documents_status == ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED:
        document_chip = {'label': 'Документы', 'tone': 'neutral', 'status': 'Не нужны', 'url': '#process-documents'}
    else:
        document_chip = {'label': 'Документы', 'tone': 'blocked', 'status': 'Нет', 'url': '#process-documents'}

    if latest_shipment:
        missing_shipment_fields = shipment_missing_fields(latest_shipment)
        shipment_chip = {
            'label': 'Отгрузка',
            'tone': 'ready' if not missing_shipment_fields else 'working',
            'status': deal.get_delivery_status_display() if not missing_shipment_fields else 'Создана',
            'url': '#process-shipment',
        }
    elif deal.delivery_status == ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED:
        shipment_chip = {'label': 'Отгрузка', 'tone': 'neutral', 'status': 'Не нужна', 'url': '#process-shipment'}
    else:
        shipment_chip = {'label': 'Отгрузка', 'tone': 'blocked', 'status': 'Не создана', 'url': '#process-shipment'}

    if finance_deal:
        missing_finance_fields = finance_case_missing_fields(finance_deal)
        finance_chip = {
            'label': 'Финансы',
            'tone': 'ready' if not missing_finance_fields else 'working',
            'status': 'ОК' if not missing_finance_fields else 'Частично',
            'url': '#process-finance',
        }
    else:
        finance_chip = {'label': 'Финансы', 'tone': 'blocked', 'status': 'Не заполнены', 'url': '#process-finance'}

    return [reservation_chip, shipment_chip, document_chip, finance_chip]


def _deal_supply_summary(deal, *, reservations, purchase_items, cargo_items):
    purchase_quantity = sum(item.quantity for item in purchase_items)
    purchase_received = sum(item.received_quantity for item in purchase_items)
    cargo_quantity = sum(item.quantity for item in cargo_items)
    cargo_received = sum(item.received_quantity for item in cargo_items)
    cargo_etas = sorted(item.cargo.eta for item in cargo_items if item.cargo.eta)
    primary_reservation = reservations[0] if reservations else None
    latest_purchase_item = purchase_items[0] if purchase_items else None
    latest_cargo_item = cargo_items[0] if cargo_items else None
    latest_shipment = deal.shipments.order_by('-created_at', '-id').first()
    risk_label = 'Риск не выявлен'
    risk_tone = 'ready'
    problem_source = 'Обеспечение собрано'
    primary_cta = {'label': 'Открыть снабжение', 'url': reverse('manager_portal:purchase_list')}
    if cargo_items and cargo_received < cargo_quantity:
        risk_label = 'Есть груз, который не принят полностью'
        risk_tone = 'working'
        problem_source = 'Груз в пути'
        primary_cta = {'label': 'Принять груз', 'url': reverse('manager_portal:cargo_list')}
    elif purchase_items and purchase_received < purchase_quantity:
        risk_label = 'Закупка ещё не закрыта'
        risk_tone = 'working'
        problem_source = 'Закупка не оформлена'
        primary_cta = {'label': 'Создать закупку', 'url': reverse('manager_portal:purchase_list')}
    elif not reservations and deal.fulfillment_status not in {
        ManagerDeal.FULFILLMENT_STATUS_FULFILLED,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING,
    }:
        risk_label = 'Резерв под сделку ещё не создан'
        risk_tone = 'blocked'
        problem_source = 'Нет резерва'
        primary_cta = {'label': 'Создать бронь', 'url': reverse('manager_portal:deal_reservation_action', kwargs={'pk': deal.pk})}
    elif latest_shipment and not latest_shipment.tracking_number:
        risk_label = 'Отгрузка без трека'
        risk_tone = 'working'
        problem_source = 'Отгрузка без трека'
        primary_cta = {'label': 'Добавить трек', 'url': reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk})}
    return {
        'reservation_count': len(reservations),
        'primary_reservation': primary_reservation,
        'reserve_status_label': deal.get_fulfillment_status_display(),
        'reserve_source_label': (
            deal.stock_warehouse.name
            if deal.stock_warehouse
            else primary_reservation.source_warehouse.name
            if primary_reservation and primary_reservation.source_warehouse
            else primary_reservation.source_cargo.cargo_number
            if primary_reservation and primary_reservation.source_cargo
            else ''
        ),
        'purchase_count': len(purchase_items),
        'purchase_quantity': purchase_quantity,
        'purchase_received': purchase_received,
        'purchase_remaining': max(purchase_quantity - purchase_received, 0),
        'cargo_count': len(cargo_items),
        'cargo_quantity': cargo_quantity,
        'cargo_received': cargo_received,
        'cargo_remaining': max(cargo_quantity - cargo_received, 0),
        'earliest_eta': cargo_etas[0] if cargo_etas else None,
        'latest_eta': cargo_etas[-1] if cargo_etas else None,
        'risk_label': risk_label,
        'risk_tone': risk_tone,
        'problem_source': problem_source,
        'primary_cta': primary_cta,
        'linked_entities': [
            entity for entity in [
                {
                    'label': latest_purchase_item.purchase.code or f'PO #{latest_purchase_item.purchase_id}',
                    'status': latest_purchase_item.purchase.get_status_display(),
                    'url': reverse('manager_portal:purchase_list'),
                } if latest_purchase_item else None,
                {
                    'label': latest_cargo_item.cargo.cargo_number,
                    'status': latest_cargo_item.cargo.get_status_display(),
                    'url': reverse('manager_portal:cargo_list'),
                } if latest_cargo_item else None,
                {
                    'label': latest_shipment.code or f'SHP #{latest_shipment.pk}',
                    'status': latest_shipment.get_status_display(),
                    'url': reverse('manager_portal:shipment_detail', kwargs={'pk': latest_shipment.pk}),
                } if latest_shipment else None,
            ] if entity
        ],
    }


def _document_type_label(document_type):
    return dict(ContractTemplate.DOCUMENT_TYPE_CHOICES).get(document_type, document_type or '—')


def _deal_required_document_type(deal, *, latest_document=None):
    if latest_document is not None:
        return latest_document.document_type
    if deal.documents_status == ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED:
        return ''
    if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT:
        return ContractTemplate.DOC_TYPE_INVOICE
    return ContractTemplate.DOC_TYPE_CONTRACT


def _deal_document_slot(deal, *, documents, title, document_types, action_document_type, empty_label='Не подготовлен'):
    document = next((item for item in documents if item.document_type in document_types), None)
    if document is None:
        return {
            'title': title,
            'status': empty_label,
            'detail': 'Документ ещё не создан.',
            'tone': 'blocked',
            'open_url': '',
            'action_url': reverse(
                'manager_portal:deal_document_action',
                kwargs={'pk': deal.pk, 'document_type': action_document_type},
            ),
        }
    missing_fields = contract_document_missing_fields(document)
    return {
        'title': title,
        'status': document.get_status_display(),
        'detail': document.number or document.title or 'Без номера',
        'tone': 'ready' if not missing_fields else 'working',
        'open_url': (
            f'{reverse("manager_portal:contracts_detail", kwargs={"pk": document.pk})}'
            f'?deal={deal.pk}&return_anchor=documents'
        ),
        'action_url': reverse(
            'manager_portal:deal_document_action',
            kwargs={'pk': deal.pk, 'document_type': document.document_type},
        ),
    }


def _deal_documents_summary(deal, *, documents):
    latest_document = documents[0] if documents else None
    required_document_type = _deal_required_document_type(deal, latest_document=latest_document)
    required_document_label = 'Не требуется' if not required_document_type else _document_type_label(required_document_type)
    template = (
        latest_document.template
        if latest_document is not None and latest_document.template_id
        else ContractTemplate.objects.filter(is_active=True, document_type=required_document_type)
        .order_by('sort_order', 'name')
        .first()
        if required_document_type
        else None
    )
    if latest_document is not None:
        status_label = latest_document.get_status_display()
        draft_label = 'Есть черновик' if latest_document.status in {
            ContractDocument.STATUS_DRAFT,
            ContractDocument.STATUS_REVIEW,
        } else 'Черновика нет'
        last_editor = str(latest_document.responsible_manager or latest_document.created_by or '') or '—'
        updated_at = latest_document.updated_at
        open_latest_url = (
            f'{reverse("manager_portal:contracts_detail", kwargs={"pk": latest_document.pk})}'
            f'?deal={deal.pk}&return_anchor=documents'
        )
        primary_document_type = latest_document.document_type
    elif deal.documents_status == ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED:
        status_label = deal.get_documents_status_display()
        draft_label = 'Не нужен'
        last_editor = '—'
        updated_at = None
        open_latest_url = ''
        primary_document_type = ContractTemplate.DOC_TYPE_CONTRACT
    else:
        status_label = 'Не создан'
        draft_label = 'Черновика нет'
        last_editor = '—'
        updated_at = None
        open_latest_url = ''
        primary_document_type = required_document_type or ContractTemplate.DOC_TYPE_CONTRACT

    primary_action_label = f'Подготовить {_document_type_label(primary_document_type).lower()}'
    recent_documents = [
        {
            'title': document.number or document.title or 'Черновик',
            'subtitle': document.get_document_type_display(),
            'status': document.get_status_display(),
            'updated_at': document.updated_at,
            'url': (
                f'{reverse("manager_portal:contracts_detail", kwargs={"pk": document.pk})}'
                f'?deal={deal.pk}&return_anchor=documents'
            ),
        }
        for document in documents[:3]
    ]
    return {
        'required_document_label': required_document_label,
        'draft_label': draft_label,
        'template_label': template.name if template is not None else 'Шаблон не выбран',
        'last_editor': last_editor,
        'updated_at': updated_at,
        'status_label': status_label,
        'primary_action': {
            'label': primary_action_label,
            'url': reverse(
                'manager_portal:deal_document_action',
                kwargs={'pk': deal.pk, 'document_type': primary_document_type},
            ),
        },
        'open_latest_action': {
            'label': 'Открыть последний документ',
            'url': open_latest_url,
        } if open_latest_url else None,
        'recent_documents': recent_documents,
        'document_slots': [
            _deal_document_slot(
                deal,
                documents=documents,
                title='Договор',
                document_types=[ContractTemplate.DOC_TYPE_CONTRACT],
                action_document_type=ContractTemplate.DOC_TYPE_CONTRACT,
            ),
            _deal_document_slot(
                deal,
                documents=documents,
                title='Счёт',
                document_types=[ContractTemplate.DOC_TYPE_INVOICE],
                action_document_type=ContractTemplate.DOC_TYPE_INVOICE,
            ),
            _deal_document_slot(
                deal,
                documents=documents,
                title='УПД / акт',
                document_types=[ContractTemplate.DOC_TYPE_APPENDIX, ContractTemplate.DOC_TYPE_ACT],
                action_document_type=ContractTemplate.DOC_TYPE_ACT,
            ),
        ],
    }


def _deal_finance_summary(deal, *, finance_deal, finance_expenses, finance_payouts, participant_summary, latest_payment=None):
    expenses_total = sum((expense.amount for expense in finance_expenses), Decimal('0'))
    payouts_total = sum((payout.amount for payout in finance_payouts), Decimal('0'))
    missing_items = []
    if finance_deal is None:
        missing_items.append('Нет кейса')
    if not finance_expenses:
        missing_items.append('Нет расходов')
    if not finance_payouts:
        missing_items.append('Нет выплат')
    if finance_deal is None or finance_deal.cost_price <= 0:
        missing_items.append('Нет себестоимости')

    finance_case_url = (
        f'{reverse("manager_portal:finance_deal_detail", kwargs={"pk": finance_deal.pk})}?deal={deal.pk}&return_anchor=finance'
        if finance_deal is not None
        else reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk})
    )
    status_label = 'Не создан'
    if finance_deal is not None:
        status_label = 'ОК'
        if missing_items or finance_case_missing_fields(finance_deal):
            status_label = 'Частично'

    cost_total = finance_deal.cost_price if finance_deal is not None else deal.outgoing_cost_total
    operating_expenses_total = finance_deal.direct_expenses if finance_deal is not None else Decimal('0')
    margin_total = finance_deal.margin if finance_deal is not None else deal.expected_margin

    return {
        'status_label': status_label,
        'missing_items': missing_items,
        'revenue': finance_deal.revenue if finance_deal is not None else None,
        'margin': finance_deal.margin if finance_deal is not None else None,
        'sum_total': deal.grand_total,
        'paid_total': deal.amount_paid,
        'remaining_total': deal.balance_due,
        'cost_total': cost_total,
        'operating_expenses_total': operating_expenses_total,
        'margin_total': margin_total,
        'expenses_total': expenses_total,
        'payouts_total': payouts_total,
        'balance': (finance_deal.margin - payouts_total) if finance_deal is not None else None,
        'updated_at': finance_deal.updated_at if finance_deal is not None else None,
        'uses_finance_case': finance_deal is not None,
        'payment_method_label': deal.order.get_payment_method_display(),
        'payment_status_label': deal.order.get_payment_status_display(),
        'workflow_payment_status_label': deal.get_payment_state_display(),
        'last_payment_at': latest_payment.created_at if latest_payment is not None else None,
        'last_payment_amount': latest_payment.price_amount if latest_payment is not None else None,
        'case_action': {'label': 'Открыть кейс', 'url': finance_case_url},
        'expense_action': {
            'label': 'Добавить расход',
            'url': finance_case_url if finance_deal is not None else reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk}),
        },
        'payout_action': {
            'label': 'Добавить выплату',
            'url': reverse('manager_portal:finance_payout_list'),
        },
        'planned_allocations': participant_summary['planned_allocations'],
    }


def _deal_finance_summary_compact(finance_summary):
    return {
        'status_label': finance_summary['status_label'],
        'sum_total': finance_summary['sum_total'],
        'paid_total': finance_summary['paid_total'],
        'remaining_total': finance_summary['remaining_total'],
        'margin_total': finance_summary['margin_total'],
        'payment_method_label': finance_summary['payment_method_label'],
        'payment_status_label': finance_summary['payment_status_label'],
        'workflow_payment_status_label': finance_summary['workflow_payment_status_label'],
        'last_payment_at': finance_summary['last_payment_at'],
        'last_payment_amount': finance_summary['last_payment_amount'],
        'uses_finance_case': finance_summary['uses_finance_case'],
    }


def _workflow_strip_item(label, status, *, tone, href):
    symbol_map = {
        'ready': '✓',
        'working': '!',
        'neutral': '–',
        'blocked': '○',
    }
    return {
        'label': label,
        'status': status,
        'href': href,
        'tone': tone,
        'symbol': symbol_map[tone],
    }


def _process_card(title, status, detail, *, tone, anchor_id, cta, secondary):
    return {
        'title': title,
        'status': status,
        'detail': detail,
        'tone': tone,
        'anchor_id': anchor_id,
        'cta': cta,
        'secondary': secondary,
    }


def _deal_workflow_strip(deal, *, documents, shipments, finance_deal, purchase_items, cargo_items):
    payment_tone = 'blocked'
    if deal.payment_state in {ManagerDeal.PAYMENT_STATE_PAID, ManagerDeal.PAYMENT_STATE_REFUNDED} or deal.balance_due <= 0:
        payment_tone = 'ready'
    elif deal.payment_state == ManagerDeal.PAYMENT_STATE_PARTIAL or deal.amount_paid > 0:
        payment_tone = 'working'

    fulfillment_tone = 'blocked'
    if deal.fulfillment_status in {
        ManagerDeal.FULFILLMENT_STATUS_FULFILLED,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING,
    }:
        fulfillment_tone = 'ready'
    elif deal.fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED:
        fulfillment_tone = 'working'

    documents_tone = 'blocked'
    documents_status = deal.get_documents_status_display()
    if deal.documents_status == ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED:
        documents_tone = 'neutral'
    elif deal.documents_status == ManagerDeal.DOCUMENTS_STATUS_SIGNED:
        documents_tone = 'ready'
    elif documents or deal.documents_status in {
        ManagerDeal.DOCUMENTS_STATUS_DRAFT,
        ManagerDeal.DOCUMENTS_STATUS_SENT,
    }:
        documents_tone = 'working'

    shipment_tone = 'blocked'
    shipment_status = 'Не создана'
    if deal.delivery_status == ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED:
        shipment_tone = 'neutral'
        shipment_status = deal.get_delivery_status_display()
    elif deal.delivery_status in {
        ManagerDeal.DELIVERY_STATUS_READY,
        ManagerDeal.DELIVERY_STATUS_SHIPPED,
        ManagerDeal.DELIVERY_STATUS_DELIVERED,
    }:
        shipment_tone = 'ready'
        shipment_status = deal.get_delivery_status_display()
    elif shipments or deal.delivery_status == ManagerDeal.DELIVERY_STATUS_PREPARING:
        shipment_tone = 'working'
        shipment_status = deal.get_delivery_status_display()

    finance_tone = 'blocked'
    finance_status = 'Не заполнены'
    if finance_deal is not None:
        missing_finance_fields = finance_case_missing_fields(finance_deal)
        if missing_finance_fields:
            finance_tone = 'working'
            finance_status = 'Нужно дозаполнить'
        else:
            finance_tone = 'ready'
            finance_status = 'Заполнены'

    return [
        _workflow_strip_item('Оплата', deal.get_payment_state_display(), tone=payment_tone, href='#process-finance'),
        _workflow_strip_item('Снабжение', deal.get_fulfillment_status_display(), tone=fulfillment_tone, href='#process-supply'),
        _workflow_strip_item('Документы', documents_status, tone=documents_tone, href='#process-documents'),
        _workflow_strip_item('Отгрузка', shipment_status, tone=shipment_tone, href='#process-shipment'),
        _workflow_strip_item('Финансы', finance_status, tone=finance_tone, href='#process-finance'),
    ]


def _deal_operation_hub(deal, *, next_step_panel, workflow_strip, blockers, activities, finance_deal=None):
    state_label_map = {'Снабжение': 'Обеспечение'}
    latest_event = _deal_latest_event_summary(activities)
    state_pills = [
        {
            'label': state_label_map.get(item['label'], item['label']),
            'status': item['status'],
            'tone': item['tone'],
            'href': item['href'],
        }
        for item in workflow_strip
    ]
    return {
        'next_step': next_step_panel,
        'responsible_manager': str(deal.responsible_manager) if deal.responsible_manager else 'Не назначен',
        'actions': _deal_operation_actions(deal, finance_deal=finance_deal),
        'state_pills': state_pills,
        'blockers': blockers[:3],
        'latest_event': latest_event,
        'has_manual_override': deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL,
    }


def _deal_management_summary(deal, activities):
    latest_comment = next((activity for activity in activities if activity.event_type == 'comment.added'), None)
    latest_comment_text = _deal_activity_body(latest_comment) if latest_comment is not None else ''
    return {
        'case_status': deal.get_case_status_display(),
        'responsible_manager': str(deal.responsible_manager) if deal.responsible_manager else 'Не назначен',
        'customer_deadline': deal.customer_deadline,
        'manual_next_step': (
            ManagerDeal.next_step_label_for(deal.next_step_code)
            if deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL
            else 'Не задан'
        ),
        'latest_comment': latest_comment_text or 'Комментария пока нет.',
        'has_manual_override': deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL,
    }


def _deal_operational_summary(deal, *, next_step_panel, blockers):
    primary_blocker = blockers[0] if blockers else None
    return {
        'status_label': deal.get_deal_status_display(),
        'stage_label': deal.get_case_status_display(),
        'next_step_label': next_step_panel['label'],
        'next_step_reason': next_step_panel['reason'],
        'deadline': deal.customer_deadline,
        'deadline_is_overdue': bool(deal.customer_deadline and deal.customer_deadline < timezone.localdate()),
        'sla_due_at': next_step_panel['sla_due_at'],
        'risk_label': primary_blocker['text'] if primary_blocker else 'Блокеров нет',
        'risk_tone': primary_blocker['tone'] if primary_blocker else 'ready',
        'risk_count': len(blockers),
        'responsible_manager': str(deal.responsible_manager) if deal.responsible_manager else 'Не назначен',
    }


def _deal_client_summary(deal, *, deal_client, activities, client_comment):
    phone = getattr(deal_client, 'phone', '') or deal.customer_phone or getattr(deal.order, 'shipping_phone', '') or deal.order.phone
    email = getattr(deal_client, 'email', '') or deal.business_email or deal.order.email
    additional_phone = deal.individual_additional_phone if deal.buyer_type == ManagerDeal.BUYER_INDIVIDUAL else ''
    messenger = deal.individual_messenger if deal.buyer_type == ManagerDeal.BUYER_INDIVIDUAL else ''
    address = (
        deal.delivery_full_address
        or deal.delivery_pickup_address
        or deal.business_delivery_address
        or deal.individual_delivery_address
        or deal.individual_pickup_address
        or deal.business_legal_address
    )
    contacts = []
    for label, value in (
        ('Телефон', phone),
        ('Доп. телефон', additional_phone),
        ('Email', email),
        ('Telegram / WhatsApp', messenger),
        ('Город', deal.customer_city or deal.delivery_to_city or deal.order.city_text),
        ('Адрес', address),
    ):
        value = (value or '').strip()
        if value:
            contacts.append({'label': label, 'value': value})
    history_entries = []
    for activity in activities:
        if activity.event_type == 'workflow.recomputed':
            continue
        history_entries.append(
            {
                'title': _deal_activity_title(activity),
                'meta': activity.actor.get_username() if activity.actor else activity.get_source_display(),
                'timestamp': activity.created_at,
            }
        )
        if len(history_entries) == 4:
            break
    return {
        'display_name': getattr(deal_client, 'name', '') or _deal_customer_label(deal),
        'company_name': deal.business_company_name if deal.buyer_type == ManagerDeal.BUYER_BUSINESS else '',
        'contact_name': deal.business_contact_person if deal.buyer_type == ManagerDeal.BUYER_BUSINESS else deal.individual_full_name,
        'client_type_label': deal.get_buyer_type_display(),
        'channel_label': deal.get_customer_source_display(),
        'client_url': reverse('manager_portal:client_detail', kwargs={'pk': deal_client.pk}) if deal_client else '',
        'contacts': contacts,
        'history_entries': history_entries,
        'comment': (client_comment or '').strip(),
    }


def _deal_subject_summary(deal, *, order_item_rows, finance_deal=None):
    total_discount = sum((row['item'].discount_total for row in order_item_rows), Decimal('0')) + Decimal(deal.order.promo_discount or 0)
    rows = []
    for row in order_item_rows:
        item = row['item']
        rows.append(
            {
                'title': item.resolved_product_name,
                'sku': row['sku'],
                'quantity': item.quantity,
                'configuration': item.resolved_variant_name,
                'unit_price': item.unit_price,
                'subtotal': item.subtotal,
                'discount_total': item.discount_total,
            }
        )
    return {
        'title': deal.main_product_label() or 'Позиции не добавлены',
        'positions_count': len(order_item_rows),
        'total_quantity': sum(row['item'].quantity for row in order_item_rows),
        'goods_total': deal.goods_total,
        'discount_total': total_discount,
        'delivery_total': deal.order.delivery_cost,
        'grand_total': deal.grand_total,
        'internal_margin': finance_deal.margin if finance_deal is not None else deal.expected_margin,
        'margin_source': 'Финансовый кейс' if finance_deal is not None else 'Карточка сделки',
        'rows': rows,
    }


def _deal_history_summary(deal, *, activities, timeline_entries):
    latest_comment = next((activity for activity in activities if activity.event_type == 'comment.added'), None)
    latest_status_change = next((activity for activity in activities if activity.event_type == 'case_status.changed'), None)
    latest_deadline_change = next((activity for activity in activities if activity.event_type == 'deadline.changed'), None)
    return {
        'events_count': len(timeline_entries),
        'comments_count': sum(1 for activity in activities if activity.event_type == 'comment.added'),
        'status_changes_count': sum(1 for activity in activities if activity.event_type == 'case_status.changed'),
        'latest_comment_at': latest_comment.created_at if latest_comment is not None else None,
        'latest_status_change_at': latest_status_change.created_at if latest_status_change is not None else None,
        'latest_deadline_change_at': latest_deadline_change.created_at if latest_deadline_change is not None else None,
        'updated_at': deal.updated_at,
    }


def _deal_logistics_summary(deal, *, reservations, shipments, purchase_items, cargo_items, order_item_rows, supply_summary):
    coverage = reservation_coverage_snapshot(deal.order)
    latest_reservation = reservations[0] if reservations else None
    latest_shipment = shipments[0] if shipments else None
    latest_cargo_item = cargo_items[0] if cargo_items else None
    latest_purchase_item = purchase_items[0] if purchase_items else None
    tracking_number = getattr(latest_shipment, 'tracking_number', '') or deal.tracking_number
    return {
        'reservation_status': latest_reservation.get_status_display() if latest_reservation else 'Не создана',
        'reservation_source': (
            supply_summary['reserve_source_label']
            or getattr(getattr(latest_reservation, 'source_warehouse', None), 'name', '')
            or getattr(getattr(latest_reservation, 'source_cargo', None), 'cargo_number', '')
            or 'Источник не определён'
        ),
        'warehouse_label': deal.stock_warehouse.name if deal.stock_warehouse else 'Склад не выбран',
        'coverage_status': 'Полное покрытие' if coverage['is_complete'] else 'Нужно покрытие',
        'coverage_detail': (
            'Все строки заказа закрыты резервом или отгрузкой.'
            if coverage['is_complete']
            else f'Не покрыто строк: {len(coverage["missing_lines"])}.'
        ),
        'availability_rows': [
            {
                'title': row['item'].resolved_product_name,
                'sku': row['sku'],
                'quantity': row['item'].quantity,
                'free_stock': row['free_stock'],
                'coverage_label': row['coverage_label'],
                'coverage_summary': row['coverage_summary'],
            }
            for row in order_item_rows
        ],
        'shipment_status': latest_shipment.get_status_display() if latest_shipment else 'Не создана',
        'shipment_code': latest_shipment.code if latest_shipment else '',
        'delivery_method_label': deal.get_delivery_method_display(),
        'delivery_status_label': deal.get_delivery_status_display(),
        'tracking_number': tracking_number,
        'cargo_status': latest_cargo_item.cargo.get_status_display() if latest_cargo_item else 'Нет груза',
        'cargo_code': latest_cargo_item.cargo.cargo_number if latest_cargo_item else '',
        'earliest_eta': supply_summary['earliest_eta'],
        'latest_eta': supply_summary['latest_eta'],
        'purchase_status': latest_purchase_item.purchase.get_status_display() if latest_purchase_item else 'Нет закупки',
        'purchase_code': latest_purchase_item.purchase.code if latest_purchase_item else '',
    }


def _deal_related_process_cards(
    deal,
    *,
    documents,
    reservations,
    shipments,
    finance_deal,
    purchase_items,
    cargo_items,
    supply_summary,
):
    coverage = reservation_coverage_snapshot(deal.order)
    latest_document = documents[0] if documents else None
    latest_shipment = shipments[0] if shipments else None

    supply_detail = 'Обеспечение ещё не собрано.'
    if supply_summary['cargo_count']:
        supply_detail = (
            f'Закупок {supply_summary["purchase_count"]}, грузов {supply_summary["cargo_count"]}. '
            f'ETA {supply_summary["earliest_eta"]:%d.%m.%Y}.' if supply_summary['earliest_eta']
            else f'Закупок {supply_summary["purchase_count"]}, грузов {supply_summary["cargo_count"]}. ETA не указан.'
        )
    elif supply_summary['purchase_count']:
        supply_detail = (
            f'В закупке {supply_summary["purchase_count"]} позиций. '
            f'Принято {supply_summary["purchase_received"]} из {supply_summary["purchase_quantity"]}.'
        )
    elif supply_summary['reservation_count']:
        supply_detail = (
            f'Резервов {supply_summary["reservation_count"]}. '
            f'Источник: {supply_summary["reserve_source_label"] or "не определён"}.' 
        )
    supply_tone = 'blocked'
    if deal.fulfillment_status in {
        ManagerDeal.FULFILLMENT_STATUS_FULFILLED,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING,
    }:
        supply_tone = 'ready'
    elif supply_summary['purchase_count'] or supply_summary['cargo_count'] or deal.fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED:
        supply_tone = 'working'

    if reservations:
        reservation_status = reservations[0].get_status_display()
        reservation_detail = (
            'Все строки заказа покрыты резервом.'
            if coverage['is_complete']
            else f'Не покрыто строк: {len(coverage["missing_lines"])}.'
        )
        reservation_cta = {'label': 'Открыть бронь', 'url': reverse('manager_portal:deal_reservation_action', kwargs={'pk': deal.pk})}
        reservation_tone = 'ready' if coverage['is_complete'] else 'working'
    else:
        reservation_status = 'Не создана'
        reservation_detail = 'Товара под сделку ещё не зарезервировано.'
        reservation_cta = {'label': 'Создать бронь', 'url': reverse('manager_portal:deal_reservation_action', kwargs={'pk': deal.pk})}
        reservation_tone = 'blocked'

    if latest_document:
        missing_document_fields = contract_document_missing_fields(latest_document)
        documents_status = latest_document.get_status_display()
        documents_detail = (
            'Документ готов к отправке клиенту.'
            if not missing_document_fields
            else f'Не хватает: {", ".join(missing_document_fields[:3])}.'
        )
        documents_cta = {'label': 'Открыть документ', 'url': reverse('manager_portal:contracts_detail', kwargs={'pk': latest_document.pk})}
        documents_tone = 'ready' if not missing_document_fields else 'working'
    elif deal.documents_status == ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED:
        documents_status = deal.get_documents_status_display()
        documents_detail = 'Для этой сделки документы не обязательны.'
        documents_cta = {'label': 'Подготовить договор', 'url': reverse('manager_portal:deal_document_action', kwargs={'pk': deal.pk, 'document_type': 'contract'})}
        documents_tone = 'neutral'
    else:
        documents_status = 'Не подготовлены'
        documents_detail = 'По сделке ещё нет рабочего договора или счёта.'
        documents_cta = {'label': 'Подготовить договор', 'url': reverse('manager_portal:deal_document_action', kwargs={'pk': deal.pk, 'document_type': 'contract'})}
        documents_tone = 'blocked'

    if latest_shipment:
        missing_shipment_fields = shipment_missing_fields(latest_shipment)
        shipment_status = latest_shipment.get_status_display()
        shipment_detail = (
            f'Трек: {latest_shipment.tracking_number or "без номера"}.'
            if not missing_shipment_fields
            else f'Не хватает: {", ".join(missing_shipment_fields[:3])}.'
        )
        shipment_cta = {'label': 'Открыть shipment', 'url': reverse('manager_portal:shipment_detail', kwargs={'pk': latest_shipment.pk})}
        shipment_tone = 'ready' if not missing_shipment_fields else 'working'
    elif deal.delivery_status == ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED:
        shipment_status = deal.get_delivery_status_display()
        shipment_detail = 'Отгрузка для этой сделки не требуется.'
        shipment_cta = {'label': 'Проверить отгрузку', 'url': reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk})}
        shipment_tone = 'neutral'
    else:
        shipment_status = 'Не создана'
        shipment_detail = 'Отправление по сделке ещё не подготовлено.'
        shipment_cta = {'label': 'Создать shipment', 'url': reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk})}
        shipment_tone = 'blocked'

    if finance_deal is not None:
        missing_finance_fields = finance_case_missing_fields(finance_deal)
        finance_status = 'Заполнен' if not missing_finance_fields else 'Нужно дозаполнить'
        finance_detail = (
            f'Выручка {format_currency_amount(finance_deal.revenue)} · маржа {format_currency_amount(finance_deal.margin)}.'
            if not missing_finance_fields
            else f'Не хватает: {", ".join(missing_finance_fields[:3])}.'
        )
        finance_cta = {'label': 'Открыть кейс', 'url': reverse('manager_portal:finance_deal_detail', kwargs={'pk': finance_deal.pk})}
        finance_tone = 'ready' if not missing_finance_fields else 'working'
    else:
        finance_status = 'Не создан'
        finance_detail = 'Финансовый кейс по сделке ещё не открыт.'
        finance_cta = {'label': 'Открыть кейс', 'url': reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk})}
        finance_tone = 'blocked'

    return [
        _process_card(
            'Снабжение',
            deal.get_fulfillment_status_display(),
            supply_detail,
            tone=supply_tone,
            anchor_id='process-supply',
            cta={'label': 'Открыть снабжение', 'url': reverse('manager_portal:purchase_list')},
            secondary={'label': 'Реестр закупок', 'url': reverse('manager_portal:purchase_list')},
        ),
        _process_card(
            'Бронь',
            reservation_status,
            reservation_detail,
            tone=reservation_tone,
            anchor_id='process-reservation',
            cta=reservation_cta,
            secondary={'label': 'Реестр броней', 'url': reverse('manager_portal:reservation_list')},
        ),
        _process_card(
            'Отгрузка',
            shipment_status,
            shipment_detail,
            tone=shipment_tone,
            anchor_id='process-shipment',
            cta=shipment_cta,
            secondary={'label': 'Реестр отправлений', 'url': reverse('manager_portal:shipments')},
        ),
        _process_card(
            'Документы',
            documents_status,
            documents_detail,
            tone=documents_tone,
            anchor_id='process-documents',
            cta=documents_cta,
            secondary={'label': 'Реестр документов', 'url': reverse('manager_portal:contracts_documents')},
        ),
        _process_card(
            'Финансы',
            finance_status,
            finance_detail,
            tone=finance_tone,
            anchor_id='process-finance',
            cta=finance_cta,
            secondary={'label': 'Реестр финансов', 'url': reverse('manager_portal:finance_deal_list')},
        ),
    ]


def _deal_order_item_rows(order_items, *, deal, reservations, purchase_items, cargo_items, shipments):
    if not order_items:
        return []

    catalog_product_ids = [item.product_id for item in order_items if item.product_id]
    stock_rows = (
        ProductStock.objects
        .filter(
            product_id__in=catalog_product_ids,
        )
        .values('product_id', 'variant_id')
        .annotate(total=Sum('quantity'))
    )
    stock_map = {
        (row['product_id'], row['variant_id']): int(row['total'] or 0)
        for row in stock_rows
    }
    reserved_stock_rows = (
        ReservationItem.objects.filter(
            reservation__status__in=ACTIVE_RESERVATION_STATUSES,
            reservation__source_type=Reservation.SOURCE_WAREHOUSE,
            product_id__in=catalog_product_ids,
        )
        .values('product_id', 'variant_id')
        .annotate(total=Sum('quantity'))
    )
    reserved_stock_map = {
        (row['product_id'], row['variant_id']): int(row['total'] or 0)
        for row in reserved_stock_rows
    }

    reserved_by_item = defaultdict(int)
    reserved_from_stock_by_item = defaultdict(int)
    reservation_labels_by_item = defaultdict(list)
    for reservation in reservations:
        for reservation_item in reservation.items.select_related('product', 'variant').all():
            if reservation_item.order_item_id:
                reserved_by_item[reservation_item.order_item_id] += reservation_item.quantity
                if reservation.source_type == Reservation.SOURCE_WAREHOUSE:
                    reserved_from_stock_by_item[reservation_item.order_item_id] += reservation_item.quantity
                reservation_labels_by_item[reservation_item.order_item_id].append(
                    f'{reservation.code or f"RSV #{reservation.pk}"} · {reservation_item.quantity} шт.'
                )

    purchased_by_item = defaultdict(int)
    purchase_received_by_item = defaultdict(int)
    purchase_labels_by_item = defaultdict(list)
    cargo_qty_by_item = defaultdict(int)
    cargo_received_by_item = defaultdict(int)
    cargo_labels_by_item = defaultdict(list)

    for purchase_item in purchase_items:
        if purchase_item.order_item_id:
            purchased_by_item[purchase_item.order_item_id] += purchase_item.quantity
            purchase_received_by_item[purchase_item.order_item_id] += purchase_item.received_quantity
            purchase_labels_by_item[purchase_item.order_item_id].append(
                f'{purchase_item.purchase.code or f"PO #{purchase_item.purchase_id}"} · {purchase_item.received_quantity}/{purchase_item.quantity}'
            )
        for cargo_item in purchase_item.cargo_items.all():
            if purchase_item.order_item_id:
                cargo_qty_by_item[purchase_item.order_item_id] += cargo_item.quantity
                cargo_received_by_item[purchase_item.order_item_id] += cargo_item.received_quantity
                cargo_labels_by_item[purchase_item.order_item_id].append(
                    f'Груз {cargo_item.cargo.cargo_number} · {cargo_item.received_quantity}/{cargo_item.quantity}'
                )

    shipment_qty_by_item = defaultdict(int)
    shipment_labels_by_item = defaultdict(list)
    for shipment in shipments:
        for shipment_item in shipment.items.select_related('product', 'variant', 'reservation_item__order_item').all():
            order_item_id = shipment_item.order_item_id or (
                shipment_item.reservation_item.order_item_id
                if shipment_item.reservation_item_id and shipment_item.reservation_item
                else None
            )
            if order_item_id:
                shipment_qty_by_item[order_item_id] += shipment_item.quantity
                shipment_labels_by_item[order_item_id].append(
                    f'{shipment.code or f"SHP #{shipment.pk}"} · {shipment_item.quantity} шт.'
                )

    rows = []
    for item in order_items:
        if not item.product_id:
            rows.append(
                {
                    'item': item,
                    'sku': '—',
                    'has_sku': False,
                    'scenario': 'Ручная позиция',
                    'availability_label': 'Без связи с каталогом',
                    'availability_code': 'manual',
                    'free_stock': 0,
                    'reserved_from_stock': 0,
                    'coverage_summary': 'Позиция введена вручную и не участвует в складском контуре.',
                    'coverage_label': 'Ручная позиция',
                    'coverage_tone': 'neutral',
                    'position_status': 'Ручная',
                    'position_status_detail': 'Для этой строки нет каталожного товара, поэтому бронь, склад и закупка не создаются автоматически.',
                    'position_status_tone': 'neutral',
                    'next_step': 'Проверить вручную',
                    'quick_actions': [],
                    'linked_entities': [],
                    'reservation_links': [],
                    'purchase_links': [],
                    'cargo_links': [],
                    'shipment_links': [],
                }
            )
            continue
        stock_total = stock_map.get((item.product_id, item.variant_id), 0)
        stock_status = public_stock_status(stock_total)
        free_stock = max(stock_total - reserved_stock_map.get((item.product_id, item.variant_id), 0), 0)
        reserved_quantity = reserved_by_item.get(item.id, 0)
        reserved_from_stock = reserved_from_stock_by_item.get(item.id, 0)
        purchase_quantity = purchased_by_item.get(item.id, 0)
        purchase_received = purchase_received_by_item.get(item.id, 0)
        cargo_quantity = cargo_qty_by_item.get(item.id, 0)
        cargo_received = cargo_received_by_item.get(item.id, 0)
        shipment_quantity = shipment_qty_by_item.get(item.id, 0)
        reserve_gap = max(item.quantity - reserved_quantity, 0)

        scenario = 'Под заказ' if item.is_on_request else 'Из наличия'
        reservation_url = reverse('manager_portal:deal_reservation_action', kwargs={'pk': deal.pk})
        shipment_url = reverse('manager_portal:deal_shipment_action', kwargs={'pk': deal.pk})
        purchase_url = reverse('manager_portal:purchase_list')
        cargo_url = reverse('manager_portal:cargo_list')
        if shipment_quantity >= item.quantity:
            position_status = 'В отгрузке'
            position_status_detail = f'В shipment уже {shipment_quantity}/{item.quantity} шт.'
            position_status_tone = 'ready'
            next_step = 'Контролировать доставку'
            primary_action = {
                'label': 'Отгрузка',
                'url': shipment_url,
                'tone': 'ready',
                'is_drawer': True,
            }
        elif reserved_quantity >= item.quantity:
            position_status = 'В резерве'
            position_status_detail = f'Резерв покрывает {reserved_quantity}/{item.quantity} шт.'
            position_status_tone = 'ready'
            next_step = 'Добавить в shipment' if deal.delivery_status != ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED else 'Позиция готова'
            primary_action = {
                'label': 'Отгрузка' if deal.delivery_status != ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED else 'Резерв',
                'url': shipment_url if deal.delivery_status != ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED else reservation_url,
                'tone': 'ready',
                'is_drawer': True,
            }
        elif cargo_quantity and cargo_received < cargo_quantity:
            position_status = 'В грузе'
            position_status_detail = f'В пути {cargo_received}/{cargo_quantity} шт.'
            position_status_tone = 'working'
            next_step = 'Контролировать груз'
            primary_action = {
                'label': 'Открыть грузы',
                'url': cargo_url,
                'tone': 'working',
                'is_drawer': False,
            }
        elif purchase_quantity and purchase_received < purchase_quantity:
            position_status = 'Под заказ'
            position_status_detail = f'В закупке {purchase_received}/{purchase_quantity} шт.'
            position_status_tone = 'working'
            next_step = 'Контролировать закупку'
            primary_action = {
                'label': 'В закупку',
                'url': purchase_url,
                'tone': 'working',
                'is_drawer': False,
            }
        elif item.is_on_request and purchase_quantity == 0:
            position_status = 'Под заказ'
            position_status_detail = 'Позиция продана под заказ, закупка еще не заведена.'
            position_status_tone = 'working'
            next_step = 'Запустить закупку'
            primary_action = {
                'label': 'В закупку',
                'url': purchase_url,
                'tone': 'working',
                'is_drawer': False,
            }
        elif not item.is_on_request and free_stock >= reserve_gap and reserve_gap > 0:
            position_status = 'В наличии' if reserved_quantity == 0 else 'Нужен резерв'
            if reserved_quantity:
                position_status_detail = (
                    f'В резерве {reserved_quantity}/{item.quantity} шт., свободно еще {free_stock} шт.'
                )
            else:
                position_status_detail = f'Свободно {free_stock} шт., позицию можно закрыть сейчас.'
            position_status_tone = 'working'
            next_step = 'Создать бронь'
            primary_action = {
                'label': 'Резерв',
                'url': reservation_url,
                'tone': 'ready',
                'is_drawer': True,
            }
        elif not item.is_on_request and stock_total >= item.quantity and free_stock < reserve_gap:
            position_status = 'Конфликт остатков'
            position_status_detail = f'На руках {stock_total} шт., свободно только {free_stock} шт.'
            position_status_tone = 'blocked'
            next_step = 'Проверить обеспечение'
            primary_action = {
                'label': 'Открыть остатки',
                'url': '',
                'tone': 'blocked',
                'is_drawer': False,
            }
        else:
            position_status = 'Под заказ'
            position_status_detail = 'Свободного остатка нет, позицию нужно отправлять в закупку.'
            position_status_tone = 'blocked'
            next_step = 'Запустить закупку'
            primary_action = {
                'label': 'В закупку',
                'url': purchase_url,
                'tone': 'working',
                'is_drawer': False,
            }

        coverage_tone = 'blocked'
        coverage_label = 'Не обеспечена'
        if shipment_quantity >= item.quantity:
            coverage_tone = 'ready'
            coverage_label = 'В отгрузке'
        elif reserved_quantity >= item.quantity:
            coverage_tone = 'ready'
            coverage_label = 'Обеспечена'
        elif cargo_quantity and cargo_received < cargo_quantity:
            coverage_tone = 'working'
            coverage_label = 'В поставке'
        elif purchase_quantity:
            coverage_tone = 'working'
            coverage_label = 'В закупке'
        elif stock_total >= item.quantity and not item.is_on_request:
            coverage_tone = 'working'
            coverage_label = 'Можно резервировать'

        coverage_parts = []
        if reserved_quantity:
            coverage_parts.append(f'Резерв {reserved_quantity}/{item.quantity}')
        if purchase_quantity:
            coverage_parts.append(f'Закупка {purchase_received}/{purchase_quantity}')
        if cargo_quantity:
            coverage_parts.append(f'Груз {cargo_received}/{cargo_quantity}')
        if shipment_quantity:
            coverage_parts.append(f'Отгрузка {shipment_quantity}/{item.quantity}')
        if not coverage_parts:
            coverage_parts.append('Связей пока нет')

        sku_value = item.sku
        inventory_query = sku_value or ' '.join(
            part
            for part in [
                item.resolved_product_name,
                item.resolved_variant_name,
            ]
            if part
        )
        inventory_url = f'{reverse("manager_portal:inventory")}?{urlencode({"q": inventory_query})}' if inventory_query else reverse('manager_portal:inventory')
        if not primary_action['url']:
            primary_action['url'] = inventory_url
        linked_entities = [
            {
                'label': 'Бронь',
                'status': f'{reserved_quantity}/{item.quantity}',
                'tone': 'ready' if reserved_quantity >= item.quantity else 'working' if reserved_quantity else 'blocked',
                'url': reservation_url,
            },
            {
                'label': 'PO',
                'status': f'{purchase_quantity}/{item.quantity}',
                'tone': 'ready' if purchase_quantity >= item.quantity else 'working' if purchase_quantity else 'blocked',
                'url': purchase_url,
            },
            {
                'label': 'CG',
                'status': f'{cargo_quantity}/{item.quantity}',
                'tone': 'ready' if cargo_quantity >= item.quantity else 'working' if cargo_quantity else 'blocked',
                'url': cargo_url,
            },
            {
                'label': 'SHP',
                'status': f'{shipment_quantity}/{item.quantity}',
                'tone': 'ready' if shipment_quantity >= item.quantity else 'working' if shipment_quantity else 'blocked',
                'url': shipment_url,
            },
        ]
        quick_actions = [primary_action]
        secondary_action = None
        if cargo_quantity:
            secondary_action = {
                'label': 'Открыть грузы',
                'url': cargo_url,
                'tone': 'working',
                'is_drawer': False,
            }
        elif purchase_quantity or item.is_on_request:
            secondary_action = {
                'label': 'Открыть закупки',
                'url': purchase_url,
                'tone': 'working',
                'is_drawer': False,
            }
        elif primary_action['url'] != inventory_url:
            secondary_action = {
                'label': 'Открыть остатки',
                'url': inventory_url,
                'tone': 'neutral',
                'is_drawer': False,
            }
        if secondary_action is not None and secondary_action['url'] != primary_action['url']:
            quick_actions.append(secondary_action)

        rows.append(
            {
                'item': item,
                'sku': sku_value or '—',
                'has_sku': bool(sku_value),
                'scenario': scenario,
                'availability_label': f'{stock_status["label"]} · {stock_total} шт.',
                'availability_code': stock_status['code'],
                'free_stock': free_stock,
                'reserved_from_stock': reserved_from_stock,
                'coverage_summary': ' · '.join(coverage_parts),
                'coverage_label': coverage_label,
                'coverage_tone': coverage_tone,
                'position_status': position_status,
                'position_status_detail': position_status_detail,
                'position_status_tone': position_status_tone,
                'next_step': next_step,
                'quick_actions': quick_actions,
                'linked_entities': linked_entities,
                'reservation_links': reservation_labels_by_item.get(item.id, []),
                'purchase_links': purchase_labels_by_item.get(item.id, []),
                'cargo_links': cargo_labels_by_item.get(item.id, []),
                'shipment_links': shipment_labels_by_item.get(item.id, []),
            }
        )
    return rows


def _manager_client_queryset():
    latest_deal = (
        ManagerDeal.objects.filter(order__manager_client_links=OuterRef('pk'))
        .annotate(activity_sort=Coalesce('last_activity_at', 'deal_created_at'))
        .order_by('-activity_sort', '-pk')
    )
    return (
        ManagerClient.objects.select_related('user')
        .annotate(
            orders_count=Count('orders', distinct=True),
            reservations_count=Count('reservations', distinct=True),
            active_reservations_count=Count(
                'reservations',
                filter=Q(reservations__status__in=ACTIVE_RESERVATION_STATUSES),
                distinct=True,
            ),
            documents_count=Count('contract_documents', distinct=True),
            latest_order_created_at=Max('orders__created_at'),
            latest_deal_activity_at=Max('orders__manager_deal__last_activity_at'),
            latest_reservation_updated_at=Max('reservations__updated_at'),
            latest_document_updated_at=Max('contract_documents__updated_at'),
            latest_deal_id=Subquery(latest_deal.values('pk')[:1]),
            latest_buyer_type=Subquery(latest_deal.values('buyer_type')[:1]),
            latest_customer_source=Subquery(latest_deal.values('customer_source')[:1]),
            latest_responsible_manager_id=Subquery(latest_deal.values('responsible_manager_id')[:1]),
            latest_responsible_manager_name=Subquery(latest_deal.values('responsible_manager__username')[:1]),
            latest_deal_case_status=Subquery(latest_deal.values('case_status')[:1]),
            latest_deal_next_step_code=Subquery(latest_deal.values('next_step_code')[:1]),
            latest_deal_problem_flags=Subquery(latest_deal.values('problem_flags')[:1]),
        )
        .annotate(
            last_activity_at=Greatest(
                F('updated_at'),
                Coalesce(F('latest_order_created_at'), F('updated_at')),
                Coalesce(F('latest_deal_activity_at'), F('updated_at')),
                Coalesce(F('latest_reservation_updated_at'), F('updated_at')),
                Coalesce(F('latest_document_updated_at'), F('updated_at')),
                output_field=DateTimeField(),
            )
        )
        .order_by(F('last_activity_at').desc(nulls_last=True), 'name', 'id')
    )


def _decorate_manager_clients(clients):
    buyer_type_labels = dict(ManagerDeal.BUYER_TYPE_CHOICES)
    source_labels = dict(ManagerDeal.CUSTOMER_SOURCE_CHOICES)
    case_status_labels = dict(ManagerDeal.CASE_STATUS_CHOICES)
    for client in clients:
        client.crm_buyer_type_label = buyer_type_labels.get(client.latest_buyer_type, 'Не указан')
        client.crm_source_label = source_labels.get(client.latest_customer_source, 'Не указан')
        client.crm_responsible_label = client.latest_responsible_manager_name or 'Не назначен'
        client.crm_latest_deal_label = f'Сделка #{client.latest_deal_id}' if client.latest_deal_id else 'Сделки нет'
        client.crm_latest_deal_step_label = (
            ManagerDeal.next_step_label_for(client.latest_deal_next_step_code)
            if client.latest_deal_next_step_code
            else 'Нет активного следующего шага'
        )
        client.crm_latest_deal_status_label = case_status_labels.get(client.latest_deal_case_status, '—')
        client.crm_latest_problem_labels = [
            ManagerDeal.PROBLEM_FLAG_LABELS.get(flag, flag)
            for flag in (client.latest_deal_problem_flags or [])
        ][:2]
        tags = []
        if client.user_id:
            tags.append('Аккаунт')
        if client.latest_buyer_type:
            tags.append(client.crm_buyer_type_label)
        if client.latest_customer_source:
            tags.append(client.crm_source_label)
        if client.active_reservations_count:
            tags.append(f'Активных броней {client.active_reservations_count}')
        if client.documents_count:
            tags.append(f'Документов {client.documents_count}')
        elif client.comments:
            tags.append('Есть комментарий')
        client.crm_tags = tags[:4]
    return clients


def _decorate_highlighted_client_preview(client):
    preview_orders = list(getattr(client, 'preview_orders', []))
    preview_reservations = list(getattr(client, 'preview_reservations', []))
    preview_documents = list(getattr(client, 'preview_documents', []))
    client.latest_order = preview_orders[0] if preview_orders else None
    active_deals = [
        order.manager_deal
        for order in preview_orders
        if getattr(order, 'manager_deal', None) is not None
    ]
    active_deals.sort(
        key=lambda deal: (
            deal.case_status in {ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED},
            -(deal.last_activity_at or deal.deal_created_at or timezone.now()).timestamp(),
        )
    )
    client.active_deal = next(
        (
            deal
            for deal in active_deals
            if deal.case_status not in {ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED}
        ),
        active_deals[0] if active_deals else None,
    )
    client.active_deal_problem_labels = (
        list(client.active_deal.problem_flag_labels[:3])
        if client.active_deal is not None
        else []
    )
    client.active_deal_url = (
        reverse('manager_portal:deal_detail', kwargs={'pk': client.active_deal.pk})
        if client.active_deal is not None
        else ''
    )
    client.active_deal_primary_action = (
        _deal_primary_cta(client.active_deal, scope='detail')
        if client.active_deal is not None
        else None
    )
    client.active_deal_secondary_actions = (
        _resolve_deal_scoped_actions(
            _deal_secondary_ctas(client.active_deal, deal_client=client),
            detail_url=client.active_deal_url,
        )
        if client.active_deal is not None
        else []
    )
    client.preview_reservations = preview_reservations
    client.preview_documents = preview_documents
    return client


def _inventory_row_matches_business_view(row, business_view):
    if not business_view:
        return True
    problem_codes = set(row.get('problem_codes') or [])
    linked_deals = row.get('linked_deals') or []
    if business_view == INVENTORY_BUSINESS_VIEW_DEAL_RISK:
        return row.get('has_problem') and bool(linked_deals)
    if business_view == INVENTORY_BUSINESS_VIEW_REPLENISHMENT:
        return 'below_min_stock' in problem_codes and row.get('inbound_available', 0) <= 0
    if business_view == INVENTORY_BUSINESS_VIEW_OVERSOLD:
        return bool({'negative_available', 'reserved_gt_on_hand'} & problem_codes)
    if business_view == INVENTORY_BUSINESS_VIEW_SITE_MISMATCH:
        return 'public_mismatch' in problem_codes
    return True


def _deal_list_redirect(query_string=''):
    target = reverse('manager_portal:deal_list')
    return redirect(f'{target}?{query_string}' if query_string else target)


def _deal_kanban_columns(deals):
    columns = []
    for case_status, label in ManagerDeal.CASE_STATUS_CHOICES:
        column_deals = [deal for deal in deals if deal.case_status == case_status]
        columns.append(
            {
                'key': case_status,
                'label': label,
                'count': len(column_deals),
                'deals': column_deals,
            }
        )
    return columns


class _ContextRows(list):
    def values_list(self, field_name, flat=False):
        values = [getattr(item, field_name) for item in self]
        if flat:
            return values
        return [(value,) for value in values]


def _confirm_deal_case(deal, *, actor):
    target_status = ManagerDeal.CASE_STATUS_CONFIRMED
    if deal.case_status not in {ManagerDeal.CASE_STATUS_NEW, ManagerDeal.CASE_STATUS_CONFIRMED}:
        target_status = ManagerDeal.CASE_STATUS_IN_PROGRESS
    apply_deal_case_status_change(deal, case_status=target_status, actor=actor)
    recompute_deal_workflow(deal, actor=actor)


def _global_search_context(query):
    normalized_query = (query or '').strip()
    result_groups = [group for group in deal_search_groups(normalized_query) if group['items']] if normalized_query else []
    return {
        'query': normalized_query,
        'result_groups': result_groups,
        'result_count': sum(len(group['items']) for group in result_groups),
    }


@staff_required
def deal_list_view(request):
    current_view_mode = _deal_view_mode(request)
    current_scope = _deal_scope_mode(request)
    if current_view_mode == DEAL_VIEW_KANBAN:
        current_scope = DEAL_SCOPE_CORE
    deal_queryset_factory = _deal_queryset if current_view_mode != DEAL_VIEW_KANBAN else (lambda **_: _deal_queryset(lightweight=True))
    deals = deal_queryset_factory()
    deals = _apply_deal_scope(deals, current_scope)
    if _use_default_work_scope(request.GET):
        deals = _active_deals(deals)
    filter_form = DealFilterForm(request.GET or None)
    deals = _apply_deal_filters(deals, filter_form, user=request.user)
    deal_advanced_filters_open, deal_advanced_filters_count = _deal_advanced_filter_state(filter_form)
    bulk_form = DealBulkAssignForm()
    bulk_case_status_form = DealBulkCaseStatusForm()
    save_view_form = DealSavedViewForm()
    return_query = (request.POST.get('return_query') or request.GET.urlencode()).strip()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'bulk_assign':
            bulk_form = DealBulkAssignForm(request.POST)
            if bulk_form.is_valid():
                selected_ids = bulk_form.selected_ids()
                target_manager = bulk_form.cleaned_data['responsible_manager']
                for deal in ManagerDeal.objects.filter(pk__in=selected_ids):
                    apply_deal_assignment(deal, responsible_manager=target_manager, actor=request.user)
                messages.success(request, f'Назначено заказов: {len(selected_ids)}.')
                return _deal_list_redirect(return_query)
            messages.error(request, 'Не удалось назначить ответственного.')
        elif action == 'bulk_case_status':
            bulk_case_status_form = DealBulkCaseStatusForm(request.POST)
            if bulk_case_status_form.is_valid():
                selected_ids = bulk_case_status_form.selected_ids()
                case_status = bulk_case_status_form.cleaned_data['case_status']
                for deal in ManagerDeal.objects.select_related('order').filter(pk__in=selected_ids):
                    apply_deal_case_status_change(deal, case_status=case_status, actor=request.user)
                messages.success(request, f'Обновлен этап у заказов: {len(selected_ids)}.')
                return _deal_list_redirect(return_query)
            messages.error(request, 'Не удалось массово обновить этап заказа.')
        elif action == 'bulk_export':
            selected_ids = _selected_deal_ids(request.POST.get('deal_ids'))
            if not selected_ids:
                messages.error(request, 'Выберите хотя бы один заказ для экспорта.')
                return _deal_list_redirect(return_query)
            export_queryset = (
                ManagerDeal.objects.select_related('order', 'responsible_manager')
                .filter(pk__in=selected_ids)
                .order_by('order_id')
            )
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="manager-deals-selection.csv"'
            response.write('\ufeff')
            writer = csv.writer(response)
            writer.writerow([
                'deal_id',
                'customer',
                'phone',
                'email',
                'next_step',
                'case_status',
                'payment_state',
                'fulfillment_status',
                'documents_status',
                'responsible_manager',
                'sla_due_at',
            ])
            for deal in export_queryset:
                writer.writerow([
                    deal.order_id,
                    _deal_customer_label(deal),
                    deal.customer_phone or deal.order.phone,
                    deal.order.email or deal.business_email,
                    deal.next_step_label,
                    deal.get_case_status_display(),
                    deal.get_payment_state_display(),
                    deal.get_fulfillment_status_display(),
                    deal.get_documents_status_display(),
                    deal.responsible_manager.get_username() if deal.responsible_manager else '',
                    timezone.localtime(deal.sla_due_at).strftime('%Y-%m-%d %H:%M') if deal.sla_due_at else '',
                ])
            return response
        elif action == 'assign_self':
            deal = get_object_or_404(ManagerDeal, pk=request.POST.get('deal_id'))
            apply_deal_assignment(deal, responsible_manager=request.user, actor=request.user)
            messages.success(request, f'Заказ #{deal.order_id} назначен на вас.')
            return _deal_list_redirect(return_query)
        elif action == 'confirm_case':
            deal = get_object_or_404(ManagerDeal, pk=request.POST.get('deal_id'))
            _confirm_deal_case(deal, actor=request.user)
            messages.success(request, f'Сделка #{deal.order_id} подтверждена.')
            return _deal_list_redirect(return_query)
        elif action == 'save_view':
            save_view_form = DealSavedViewForm(request.POST)
            if save_view_form.is_valid():
                saved_view = save_view_form.save(commit=False)
                saved_view.owner = request.user
                saved_view.query_string = request.POST.get('query_string', '')
                saved_view.save()
                messages.success(request, f'Вид "{saved_view.name}" сохранен.')
                return _deal_list_redirect(return_query)
            messages.error(request, 'Не удалось сохранить представление.')
    total_deals = deals.count()
    deal_rows = _ContextRows()
    deals_page = None
    deal_page_numbers = []
    deal_kanban_columns = []
    if current_view_mode == DEAL_VIEW_KANBAN:
        kanban_deals = list(deals)
        decorated_kanban_deals = _decorate_deal_kanban_rows(kanban_deals)
        deal_kanban_columns = _deal_kanban_columns(decorated_kanban_deals)
    else:
        paginator = Paginator(deals, DEAL_LIST_PAGE_SIZE)
        deals_page = paginator.get_page(request.GET.get('page') or 1)
        deals_on_page = list(deals_page.object_list)
        finance_map = {
            finance.manager_deal_id: finance
            for finance in FinanceDeal.objects.filter(manager_deal__in=deals_on_page)
        }
        deal_rows = _ContextRows(_decorate_deal_list_rows(
            deals_on_page,
            finance_map=finance_map,
            current_user=request.user,
            return_query=request.GET.urlencode(),
        ))
        deals_page.object_list = deal_rows
        deal_page_numbers = _deal_page_numbers(deals_page)
    current_filter_query_string = _deal_query_string_without_page(request.GET)
    all_deals = deal_queryset_factory()
    all_deals = _apply_deal_scope(all_deals, current_scope)
    active_scope = _active_deals(all_deals)
    queue_chips = _deal_queue_views(active_scope)
    queue_chip_keys = {chip['key'] for chip in queue_chips if chip['key'] != 'all'}
    active_queue = (request.GET.get('queue') or '').strip()
    problem_views_expanded = any(
        (request.GET.get(key) or '').strip()
        for key in ('problem_view', 'overlay', 'only_problematic')
    )
    has_non_queue_filter = any(
        (request.GET.get(key) or '').strip()
        for key in (
            'q',
            'overlay',
            'problem_view',
            'case_status',
            'payment_state',
            'fulfillment_status',
            'documents_status',
            'deal_type',
            'sla_status',
            'responsible_manager',
            'mine',
            'only_active',
            'only_unassigned',
            'only_problematic',
            'action_today',
        )
    )
    if active_queue in queue_chip_keys:
        active_queue_chip = active_queue
    elif has_non_queue_filter:
        active_queue_chip = ''
    else:
        active_queue_chip = 'all'
    saved_views = _deal_saved_views(request.user)
    return _render(
        request,
        'manager_portal/deals.html',
        active_tab='deals',
        manager_topbar_compact=True,
        deals=deal_rows,
        deal_rows=deal_rows,
        deals_page=deals_page,
        deal_page_numbers=deal_page_numbers,
        filter_form=filter_form,
        bulk_form=bulk_form,
        bulk_case_status_form=bulk_case_status_form,
        save_view_form=save_view_form,
        saved_views=saved_views,
        total_deals=total_deals,
        deal_kpis=_deal_overview_metrics(active_scope, request.GET),
        deal_desktop_summary_metrics=_deal_desktop_summary_metrics(active_scope, request.GET),
        deal_stage_metrics=_deal_stage_metrics(active_scope, request.GET),
        queue_chips=queue_chips,
        signal_views=_deal_signal_views(active_scope),
        deal_quick_toggle_filters=_deal_quick_toggle_filters(request.GET),
        deal_reset_filters_query_string=_deal_reset_filters_query_string(request.GET),
        active_queue_chip=active_queue_chip,
        current_view_mode=current_view_mode,
        current_scope=current_scope,
        list_view_query_string=_deal_query_string_with_updates(request.GET, page=None, view=None, scope=None, kanban_scope=None),
        kanban_view_query_string=_deal_query_string_with_updates(
            request.GET,
            page=None,
            view=DEAL_VIEW_KANBAN,
            scope=None,
            kanban_scope=None,
        ),
        avito_view_query_string=_deal_query_string_with_updates(
            request.GET,
            page=None,
            view=None,
            scope=DEAL_SCOPE_AVITO,
            kanban_scope=None,
        ),
        deal_kanban_columns=deal_kanban_columns,
        deal_advanced_filters_open=deal_advanced_filters_open,
        deal_advanced_filters_count=deal_advanced_filters_count,
        problem_views_expanded=problem_views_expanded,
        current_query_string=request.GET.urlencode(),
        current_filter_query_string=current_filter_query_string,
    )


@staff_required
def deal_move_view(request, pk):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Метод не поддерживается.'}, status=405)

    target_case_status = (request.POST.get('case_status') or '').strip()
    allowed_statuses = {choice[0] for choice in ManagerDeal.CASE_STATUS_CHOICES}
    if target_case_status not in allowed_statuses:
        return JsonResponse({'ok': False, 'error': 'Неизвестный этап сделки.'}, status=400)

    deal = get_object_or_404(ManagerDeal.objects.select_related('order'), pk=pk)
    return_query = (request.POST.get('return_query') or '').strip()
    apply_deal_case_status_change(deal, case_status=target_case_status, actor=request.user)

    refreshed_deal = _deal_queryset(lightweight=True).get(pk=deal.pk)
    _decorate_deal_kanban_rows([refreshed_deal])
    card_html = render_to_string(
        'manager_portal/_deal_kanban_card.html',
        {
            'deal': refreshed_deal,
            'current_query_string': return_query,
        },
        request=request,
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'ok': True,
                'deal_id': refreshed_deal.pk,
                'case_status': refreshed_deal.case_status,
                'case_status_display': refreshed_deal.get_case_status_display(),
                'html': card_html,
            }
        )

    messages.success(request, f'Этап сделки #{refreshed_deal.order_id} обновлен.')
    return _deal_list_redirect(return_query)


@staff_required
def deal_search_view(request):
    messages.info(request, 'Глобальный поиск перенесен в верхнюю панель shell. Используйте / или Cmd+K.')
    query = (request.GET.get('q') or '').strip()
    if not query:
        return redirect('manager_portal:deal_list')
    return redirect(f"{reverse('manager_portal:deal_list')}?{urlencode({'q': query})}")


@staff_required
def global_search_results_view(request):
    form = GlobalSearchForm(request.GET or None)
    query = ''
    if form.is_valid():
        query = form.cleaned_data.get('q') or ''
    return render(
        request,
        'manager_portal/_global_search_results.html',
        _global_search_context(query),
    )


@staff_required
def deal_detail_view(request, pk):
    deal = get_object_or_404(
        _deal_queryset()
        .select_related('order', 'responsible_manager', 'stock_warehouse', 'primary_reservation')
        .prefetch_related(
            'order__items__product',
            'order__items__variant',
            'order__payments',
            'trade_in_items',
            'contract_documents__template',
            'contract_documents__responsible_manager',
            'shipments__client',
            'shipments__reservation',
            'shipments__source_warehouse',
            'shipments__target_warehouse',
            'reservations__client',
            'reservations__target_warehouse',
            'activities__actor',
        ),
        pk=pk,
    )
    deal_tab_initial = request.GET.get('tab') or 'overview'
    if deal_tab_initial not in {'overview', 'supply', 'documents', 'finance', 'history'}:
        deal_tab_initial = 'overview'
    is_just_created = request.GET.get('created') == '1'
    management_form = DealManagementForm(deal=deal)
    comment_form = DealCommentForm()
    comment_widget_class = comment_form.fields['comment'].widget.attrs.get('class', '')
    comment_form.fields['comment'].widget.attrs.update(
        {
            'rows': 1,
            'placeholder': 'Добавить комментарий',
            'class': f'{comment_widget_class} min-h-[44px] focus:min-h-[7rem] transition-[min-height] duration-200',
        }
    )
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_management':
            management_form = DealManagementForm(request.POST, deal=deal)
            if management_form.is_valid():
                previous_deadline = deal.customer_deadline
                previous_manager = deal.responsible_manager
                previous_next_step_source = deal.next_step_source
                previous_next_step_code = deal.next_step_code
                previous_next_step_reason = deal.next_step_reason_snapshot or ''
                next_case_status = management_form.cleaned_data['case_status']
                next_responsible_manager = management_form.cleaned_data['responsible_manager']
                next_deadline = None if deal.is_avito else management_form.cleaned_data['customer_deadline']
                if next_responsible_manager != previous_manager:
                    apply_deal_assignment(
                        deal,
                        responsible_manager=next_responsible_manager,
                        actor=request.user,
                    )
                if next_case_status != deal.case_status:
                    apply_deal_case_status_change(deal, case_status=next_case_status, actor=request.user)
                if next_deadline != previous_deadline:
                    deal.customer_deadline = next_deadline
                    deal.save(update_fields=['customer_deadline', 'updated_at'])
                    record_deal_activity(
                        deal,
                        event_type='deadline.changed',
                        source='user',
                        actor=request.user,
                        payload={'customer_deadline': str(deal.customer_deadline or '')},
                    )
                next_step_code = management_form.cleaned_data.get('next_step_code') or ''
                manager_comment = (management_form.cleaned_data.get('manager_comment') or '').strip()
                if next_step_code:
                    if (
                        previous_next_step_source != ManagerDeal.NEXT_STEP_SOURCE_MANUAL
                        or previous_next_step_code != next_step_code
                        or previous_next_step_reason != manager_comment
                    ):
                        apply_deal_next_step_override(
                            deal,
                            next_step_code=next_step_code,
                            reason=manager_comment,
                            actor=request.user,
                        )
                elif previous_next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL:
                    clear_deal_next_step_override(deal, actor=request.user)
                _sync_deal_participants(
                    deal=deal,
                    answered_person_alias=management_form.cleaned_data.get('answered_person_alias'),
                    shipped_person_alias=management_form.cleaned_data.get('shipped_person_alias'),
                    actor=request.user,
                )
                recompute_deal_workflow(deal, actor=request.user)
                messages.success(request, 'Управление заказом сохранено.')
                return redirect('manager_portal:deal_detail', pk=deal.pk)
            messages.error(request, 'Не удалось сохранить управление заказом.')
        elif action == 'add_comment':
            comment_form = DealCommentForm(request.POST)
            comment_widget_class = comment_form.fields['comment'].widget.attrs.get('class', '')
            comment_form.fields['comment'].widget.attrs.update(
                {
                    'rows': 1,
                    'placeholder': 'Добавить комментарий',
                    'class': f'{comment_widget_class} min-h-[44px] focus:min-h-[7rem] transition-[min-height] duration-200',
                }
            )
            if comment_form.is_valid():
                record_deal_activity(
                    deal,
                    event_type='comment.added',
                    source='user',
                    actor=request.user,
                    payload={'comment': comment_form.cleaned_data['comment'].strip()},
                )
                recompute_deal_workflow(deal, actor=request.user)
                messages.success(request, 'Комментарий добавлен в таймлайн.')
                return redirect('manager_portal:deal_detail', pk=deal.pk)
            messages.error(request, 'Не удалось добавить комментарий.')
        elif action == 'assign_self':
            apply_deal_assignment(deal, responsible_manager=request.user, actor=request.user)
            messages.success(request, f'Сделка #{deal.order_id} назначена на вас.')
            return redirect('manager_portal:deal_detail', pk=deal.pk)
        elif action == 'confirm_case':
            _confirm_deal_case(deal, actor=request.user)
            messages.success(request, f'Сделка #{deal.order_id} подтверждена.')
            return redirect('manager_portal:deal_detail', pk=deal.pk)
        elif action == 'return_to_stock':
            try:
                result = restore_avito_return_to_stock(deal, actor=request.user)
                restored_quantity = sum(int(position['quantity']) for position in result['positions'])
                if restored_quantity > 0:
                    messages.success(request, f'Возврат принят на склад: {restored_quantity} шт.')
                else:
                    messages.success(request, 'Резерв снят, товар снова доступен на складе.')
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('manager_portal:deal_detail', pk=deal.pk)

    finance_deal = None
    try:
        finance_deal = deal.finance_deal
    except FinanceDeal.DoesNotExist:
        finance_deal = None
    deal_client = deal_manager_client(deal)
    documents = list(deal.contract_documents.exclude(status=ContractDocument.STATUS_ARCHIVED).order_by('-issue_date', '-id'))
    reservations = list(
        deal.reservations.select_related('client', 'target_warehouse', 'source_warehouse')
        .prefetch_related('items')
        .order_by('-created_at', '-id')
    )
    shipments = list(
        deal.shipments.select_related('client', 'reservation', 'source_warehouse', 'target_warehouse')
        .prefetch_related('items')
        .order_by('-created_at', '-id')
    )
    purchase_items = list(
        PurchaseItem.objects.filter(order_item__order=deal.order)
        .select_related('purchase', 'product', 'variant', 'order_item')
        .prefetch_related('cargo_items__cargo')
        .order_by('purchase_id', 'id')
    )
    cargo_items = list(
        CargoItem.objects.filter(purchase_item__order_item__order=deal.order)
        .select_related('cargo', 'product', 'variant', 'purchase_item')
        .order_by('cargo_id', 'id')
    )
    supply_summary = _deal_supply_summary(
        deal,
        reservations=reservations,
        purchase_items=purchase_items,
        cargo_items=cargo_items,
    )
    finance_expenses = list(deal.finance_expenses.select_related('category', 'created_by').order_by('-date', '-id'))
    finance_payouts = list(deal.finance_payouts.select_related('created_by').order_by('-date', '-id'))
    participant_summary = _deal_participant_summary(
        list(deal.participants.select_related('person_alias', 'order_item').order_by('role', 'id'))
    )
    activities = list(deal.activities.select_related('actor').order_by('-created_at', '-id')[:30])
    timeline_entries = _deal_timeline_entries(activities)
    next_step_panel = _deal_next_step_panel(deal, finance_deal=finance_deal, deal_client=deal_client)
    payments = list(deal.order.payments.all())
    latest_payment = next((payment for payment in payments if payment.status == Payment.STATUS_FINISHED), None)
    if latest_payment is None and payments:
        latest_payment = payments[0]
    workflow_strip = _deal_workflow_strip(
        deal,
        documents=documents,
        shipments=shipments,
        finance_deal=finance_deal,
        purchase_items=purchase_items,
        cargo_items=cargo_items,
    )
    order_item_rows = _deal_order_item_rows(
        list(deal.order.items.select_related('product', 'variant').all()),
        deal=deal,
        reservations=reservations,
        purchase_items=purchase_items,
        cargo_items=cargo_items,
        shipments=shipments,
    )
    blockers = _deal_blockers(
        deal,
        documents=documents,
        reservations=reservations,
        shipments=shipments,
        finance_deal=finance_deal,
        purchase_items=purchase_items,
        cargo_items=cargo_items,
    )
    guided_flow = _deal_guided_flow(
        deal,
        next_step_panel=next_step_panel,
        workflow_strip=workflow_strip,
        blockers=blockers,
        activities=activities,
        reservations=reservations,
        shipments=shipments,
        documents=documents,
        finance_deal=finance_deal,
        supply_summary=supply_summary,
    )
    guided_flow['is_just_created'] = is_just_created
    if is_just_created:
        guided_flow['headline'] = 'Сделка создана'
        guided_flow['summary'] = (
            'Система уже собрала ближайший маршрут: начните с главного шага, затем проверьте обеспечение и смежные процессы.'
        )
    client_comment = (deal_client.comments if deal_client else '') or deal.customer_request_comment or deal.order.comment
    finance_summary = _deal_finance_summary(
        deal,
        finance_deal=finance_deal,
        finance_expenses=finance_expenses,
        finance_payouts=finance_payouts,
        participant_summary=participant_summary,
        latest_payment=latest_payment,
    )
    return _render(
        request,
        'manager_portal/deal_detail.html',
        active_tab='deals',
        deal_tab_initial=deal_tab_initial,
        deal=deal,
        next_step_panel=next_step_panel,
        guided_flow=guided_flow,
        operation_hub=_deal_operation_hub(
            deal,
            next_step_panel=next_step_panel,
            workflow_strip=workflow_strip,
            blockers=blockers,
            activities=activities,
            finance_deal=finance_deal,
        ),
        deal_header=_deal_header_summary(
            deal,
            deal_client=deal_client,
            blockers=blockers,
            next_step_panel=next_step_panel,
            order_item_rows=order_item_rows,
            reservations=reservations,
            shipments=shipments,
            finance_deal=finance_deal,
        ),
        deal_client=deal_client,
        client_comment=client_comment,
        operational_summary=_deal_operational_summary(deal, next_step_panel=next_step_panel, blockers=blockers),
        client_summary=_deal_client_summary(
            deal,
            deal_client=deal_client,
            activities=activities,
            client_comment=client_comment,
        ),
        subject_summary=_deal_subject_summary(deal, order_item_rows=order_item_rows, finance_deal=finance_deal),
        logistics_summary=_deal_logistics_summary(
            deal,
            reservations=reservations,
            shipments=shipments,
            purchase_items=purchase_items,
            cargo_items=cargo_items,
            order_item_rows=order_item_rows,
            supply_summary=supply_summary,
        ),
        management_form=management_form,
        comment_form=comment_form,
        order_items=order_item_rows,
        purchase_items=purchase_items,
        cargo_items=cargo_items,
        supply_summary=supply_summary,
        documents_summary=_deal_documents_summary(deal, documents=documents),
        finance_summary=finance_summary,
        finance_summary_compact=_deal_finance_summary_compact(finance_summary),
        linked_entities_strip=_deal_linked_entities_strip(
            deal,
            documents=documents,
            reservations=reservations,
            shipments=shipments,
            finance_deal=finance_deal,
        ),
        workflow_strip=workflow_strip,
        related_process_cards=_deal_related_process_cards(
            deal,
            documents=documents,
            reservations=reservations,
            shipments=shipments,
            finance_deal=finance_deal,
            purchase_items=purchase_items,
            cargo_items=cargo_items,
            supply_summary=supply_summary,
        ),
        blockers=blockers,
        documents=documents,
        reservations=reservations,
        shipments=shipments,
        finance_deal=finance_deal,
        finance_expenses=finance_expenses,
        finance_payouts=finance_payouts,
        deal_participants_summary=participant_summary,
        activities=activities,
        timeline_entries=timeline_entries,
        timeline_preview=timeline_entries[:5],
        history_summary=_deal_history_summary(deal, activities=activities, timeline_entries=timeline_entries),
        latest_event_summary=_deal_latest_event_summary(activities),
        management_summary=_deal_management_summary(deal, activities),
        customer_label=_deal_customer_label(deal),
    )


@staff_required
def deal_reservation_action_view(request, pk):
    deal = get_object_or_404(ManagerDeal.objects.select_related('order'), pk=pk)
    reservation = deal.primary_reservation or deal.reservations.order_by('-created_at', '-id').first()
    if reservation is not None:
        if reservation.manager_deal_id != deal.id:
            reservation.manager_deal = deal
            reservation.save(update_fields=['manager_deal', 'updated_at'])
        return redirect(f'{reverse("manager_portal:reservation_detail", kwargs={"pk": reservation.pk})}?deal={deal.pk}&return_anchor=reservation')
    return redirect(_deal_reservation_prefill_url(deal))


@staff_required
def deal_document_action_view(request, pk, document_type):
    deal = get_object_or_404(ManagerDeal.objects.select_related('order'), pk=pk)
    document = (
        deal.contract_documents.filter(document_type=document_type)
        .exclude(status=ContractDocument.STATUS_ARCHIVED)
        .order_by('-issue_date', '-id')
        .first()
    )
    if document is not None:
        return redirect(f'{reverse("manager_portal:contracts_detail", kwargs={"pk": document.pk})}?deal={deal.pk}&return_anchor=documents')
    return redirect(_deal_document_prefill_url(deal, document_type=document_type))


@staff_required
def deal_shipment_action_view(request, pk):
    deal = get_object_or_404(ManagerDeal.objects.select_related('order'), pk=pk)
    shipment = ensure_shipment_for_manager_deal(deal, actor=request.user)
    if isinstance(shipment, list):
        messages.info(request, 'У заказа несколько отправлений. Откройте реестр отправлений в блоке карточки.')
        return redirect('manager_portal:deal_detail', pk=deal.pk)
    missing_fields = shipment_missing_fields(shipment)
    if missing_fields:
        messages.warning(request, f'Отправление подготовлено, не хватает: {", ".join(missing_fields[:3])}.')
    else:
        messages.success(request, 'Отправление подготовлено и почти готово к отправке.')
    return redirect(f'{reverse("manager_portal:shipment_detail", kwargs={"pk": shipment.pk})}?deal={deal.pk}&return_anchor=shipment')


@staff_required
def deal_finance_action_view(request, pk):
    deal = get_object_or_404(ManagerDeal.objects.select_related('order'), pk=pk)
    try:
        finance_deal = deal.finance_deal
    except FinanceDeal.DoesNotExist:
        finance_deal = None
    if finance_deal is not None:
        return redirect(f'{reverse("manager_portal:finance_deal_detail", kwargs={"pk": finance_deal.pk})}?deal={deal.pk}&return_anchor=finance')
    return redirect(_deal_finance_prefill_url(deal))


@staff_required
def order_list_view(request):
    target = reverse('manager_portal:deal_list')
    query_string = request.GET.urlencode()
    return redirect(f'{target}?{query_string}' if query_string else target)


@staff_required
def order_detail_view(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        manager_deal = order.manager_deal
    except ManagerDeal.DoesNotExist:
        manager_deal = None
    if manager_deal is None:
        messages.error(request, 'Для заказа не найдена рабочая карточка.')
        return redirect('manager_portal:deal_list')
    return redirect('manager_portal:deal_detail', pk=manager_deal.pk)


@staff_required
def order_state_update_view(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        manager_deal = order.manager_deal
    except ManagerDeal.DoesNotExist:
        manager_deal = None
    if manager_deal is None:
        messages.error(request, 'Для заказа не найдена рабочая карточка.')
        return redirect('manager_portal:deal_list')
    if request.method == 'POST':
        form = ManagerDealStateForm(request.POST, deal=manager_deal)
        if form.is_valid():
            try:
                _validate_manager_deal_state_transition(
                    manager_deal,
                    target_status=form.cleaned_data['deal_status'],
                    paid_amount=form.cleaned_data.get('paid_amount') or Decimal('0'),
                    tracking_number=(form.cleaned_data.get('tracking_number') or '').strip(),
                )
                manager_deal.deal_status = form.cleaned_data['deal_status']
                manager_deal.prepayment_amount = form.cleaned_data.get('paid_amount') or Decimal('0')
                manager_deal.tracking_number = (form.cleaned_data.get('tracking_number') or '').strip()
                manager_deal.save(update_fields=['deal_status', 'prepayment_amount', 'tracking_number', 'updated_at'])
                update_order_state(
                    order,
                    status=ManagerDeal.order_status_for_deal_status(manager_deal.deal_status),
                    payment_status=form.cleaned_data['payment_status'],
                    request=request,
                )
                recompute_deal_workflow(manager_deal, actor=request.user)
                messages.success(request, 'Состояние заказа обновлено.')
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, 'Не удалось обновить заказ.')
    return redirect('manager_portal:deal_detail', pk=manager_deal.pk)


@staff_required
def client_create_view(request):
    if request.method == 'POST':
        form = ManagerClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            messages.success(request, 'Клиент создан.')
            return redirect('manager_portal:client_detail', pk=client.pk)
    else:
        form = ManagerClientForm()
    return _render(
        request,
        'manager_portal/create_form.html',
        active_tab='clients',
        form=form,
        page_kicker='Клиенты',
        page_title='Новый клиент',
        page_description='Создайте карточку клиента и при необходимости сразу привяжите заказы сайта.',
        back_url=reverse('manager_portal:client_list'),
        submit_label='Создать клиента',
        hidden_fields=[],
        form_sections=[],
        secondary_fields=[],
    )


@staff_required
def client_list_view(request):
    clients = _manager_client_queryset()
    filter_form = ClientFilterForm(request.GET or None)
    q = ''
    if filter_form.is_valid():
        q = (filter_form.cleaned_data.get('q') or '').strip()
        if q:
            clients = clients.filter(
                Q(name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
                | Q(telegram__icontains=q)
                | Q(comments__icontains=q)
            )
        if filter_form.cleaned_data.get('status'):
            clients = clients.filter(status=filter_form.cleaned_data['status'])
        if filter_form.cleaned_data.get('buyer_type'):
            clients = clients.filter(latest_buyer_type=filter_form.cleaned_data['buyer_type'])
        if filter_form.cleaned_data.get('customer_source'):
            clients = clients.filter(latest_customer_source=filter_form.cleaned_data['customer_source'])
        if filter_form.cleaned_data.get('responsible_manager'):
            clients = clients.filter(latest_responsible_manager_id=filter_form.cleaned_data['responsible_manager'].pk)
        has_orders = filter_form.cleaned_data.get('has_orders')
        if has_orders != '':
            clients = clients.filter(orders_count__gt=0 if has_orders else 0) if has_orders else clients.filter(orders_count=0)
        has_reservations = filter_form.cleaned_data.get('has_reservations')
        if has_reservations != '':
            clients = clients.filter(reservations_count__gt=0 if has_reservations else 0) if has_reservations else clients.filter(reservations_count=0)
    if request.method == 'POST':
        form = ManagerClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            messages.success(request, 'Клиент создан.')
            return redirect('manager_portal:client_detail', pk=client.pk)
    else:
        form = ManagerClientForm()
    clients = _decorate_manager_clients(list(clients))
    highlighted_client = None
    selected_client_id = request.GET.get('client')
    if selected_client_id and selected_client_id.isdigit():
        highlighted_client = next((client for client in clients if client.pk == int(selected_client_id)), None)
    if highlighted_client is None and clients:
        highlighted_client = clients[0]
    highlighted_client_detail = None
    if highlighted_client is not None:
        highlighted_client_detail = (
            ManagerClient.objects.select_related('user')
            .annotate(
                orders_count=Count('orders', distinct=True),
                reservations_count=Count('reservations', distinct=True),
                active_reservations_count=Count(
                    'reservations',
                    filter=Q(reservations__status__in=ACTIVE_RESERVATION_STATUSES),
                    distinct=True,
                ),
                documents_count=Count('contract_documents', distinct=True),
            )
            .prefetch_related(
                Prefetch(
                    'orders',
                    queryset=Order.objects.select_related('manager_deal', 'manager_deal__responsible_manager').order_by('-created_at', '-pk'),
                    to_attr='preview_orders',
                ),
                Prefetch(
                    'reservations',
                    queryset=Reservation.objects.filter(status__in=ACTIVE_RESERVATION_STATUSES)
                    .select_related('manager_deal', 'source_warehouse', 'target_warehouse')
                    .annotate(items_count=Count('items', distinct=True))
                    .order_by('-updated_at', '-id'),
                    to_attr='preview_reservations',
                ),
                Prefetch(
                    'contract_documents',
                    queryset=ContractDocument.objects.select_related('responsible_manager', 'linked_order').order_by('-updated_at', '-id'),
                    to_attr='preview_documents',
                ),
            )
            .get(pk=highlighted_client.pk)
        )
        for attr_name in (
            'crm_buyer_type_label',
            'crm_source_label',
            'crm_responsible_label',
            'crm_tags',
            'crm_latest_deal_label',
            'crm_latest_deal_step_label',
            'crm_latest_deal_status_label',
            'crm_latest_problem_labels',
            'last_activity_at',
            'latest_deal_id',
        ):
            setattr(highlighted_client_detail, attr_name, getattr(highlighted_client, attr_name))
        highlighted_client_detail = _decorate_highlighted_client_preview(highlighted_client_detail)
    query_params_without_client = request.GET.copy()
    query_params_without_client.pop('client', None)
    client_metrics = {
        'total': len(clients),
        'active': sum(1 for client in clients if client.status == ManagerClient.STATUS_ACTIVE),
        'archived': sum(1 for client in clients if client.status == ManagerClient.STATUS_ARCHIVED),
        'with_orders': sum(1 for client in clients if client.orders_count > 0),
        'without_orders': sum(1 for client in clients if client.orders_count == 0),
        'with_reservations': sum(1 for client in clients if client.reservations_count > 0),
    }
    return _render(
        request,
        'manager_portal/clients.html',
        active_tab='clients',
        clients=clients,
        form=form,
        query=q,
        filter_form=filter_form,
        highlighted_client=highlighted_client_detail,
        client_metrics=client_metrics,
        client_querystring=query_params_without_client.urlencode(),
    )


@staff_required
def client_detail_view(request, pk):
    client = get_object_or_404(
        ManagerClient.objects.select_related('user').prefetch_related('orders', 'reservations__items__product'),
        pk=pk,
    )
    if request.method == 'POST':
        form = ManagerClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, 'Клиент обновлен.')
            return redirect('manager_portal:client_detail', pk=client.pk)
    else:
        form = ManagerClientForm(instance=client)
    return _render(
        request,
        'manager_portal/client_detail.html',
        active_tab='clients',
        client=client,
        form=form,
    )


@staff_required
def warehouse_create_view(request):
    return warehouse_list_view(request)


@staff_required
def warehouse_list_view(request):
    def build_warehouse_row(warehouse):
        rows = inventory_snapshot_for_warehouse(warehouse)
        inventory_problem_rows = sum(1 for row in rows if row['available'] < 0 or row['inbound_available'] < 0)
        pickup_point_admin_url = (
            reverse('admin:catalog_pickuppoint_change', args=[warehouse.pickup_point_id])
            if warehouse.pickup_point_id
            else None
        )
        signals = []
        if inventory_problem_rows:
            signals.append({'label': f'{inventory_problem_rows} строк с отрицательным остатком', 'tone': 'danger'})
        if not warehouse.pickup_point_id:
            signals.append({'label': 'Нет связи с сайтом', 'tone': 'danger'})
        elif warehouse.public_stock_synced_at is None:
            signals.append({'label': 'Остаток на сайте еще не синхронизирован', 'tone': 'warning'})
        sync_status = {
            'label': 'Без связи',
            'class_name': 'manager-status-danger',
        }
        if warehouse.pickup_point_id:
            if warehouse.public_stock_synced_at:
                sync_status = {
                    'label': 'Синхронизирован',
                    'class_name': 'manager-status-positive',
                }
            else:
                sync_status = {
                    'label': 'Не синхронизирован',
                    'class_name': 'manager-status-danger',
                }
        address_missing = not (warehouse.address or '').strip()
        inbound = sum(row['inbound'] for row in rows)
        detail_url = reverse('manager_portal:warehouse_detail', kwargs={'pk': warehouse.pk})
        pickup_point_label = 'Нужно привязать склад к точке сайта'
        if warehouse.pickup_point_id and warehouse.pickup_point:
            pickup_point_label = warehouse.pickup_point.name
            if warehouse.pickup_point.city:
                pickup_point_label = f'{pickup_point_label} · {warehouse.pickup_point.city.name}'
        return {
            'instance': warehouse,
            'detail_url': detail_url,
            'on_hand': sum(row['on_hand'] for row in rows),
            'reserved': sum(row['reserved_on_hand'] for row in rows),
            'available': sum(row['available'] for row in rows),
            'inbound': inbound,
            'inventory_problem_rows': inventory_problem_rows,
            'has_critical_signal': inventory_problem_rows > 0,
            'signals': signals,
            'has_signals': bool(signals),
            'primary_signal': signals[0] if signals else None,
            'status_label': 'Активен' if warehouse.is_active else 'Неактивен',
            'status_class': 'manager-status-positive' if warehouse.is_active else '',
            'is_unlinked': not warehouse.pickup_point_id,
            'address_missing': address_missing,
            'has_inbound': inbound > 0,
            'site_connection_label': 'Есть' if warehouse.pickup_point_id else 'Нет',
            'site_connection_value': pickup_point_label,
            'sync_status': sync_status,
            'pickup_point_admin_url': pickup_point_admin_url,
            'inventory_url': f"{reverse('manager_portal:inventory')}?{urlencode({'warehouse': warehouse.pk})}",
            'inventory_receipt_url': f"{reverse('manager_portal:inventory')}?{urlencode({'warehouse': warehouse.pk, 'open_receipt': 1})}",
            'movements_url': f'{detail_url}#warehouse-movements',
        }

    def filter_row(row, *, only_problematic=False, only_unlinked=False, has_inbound=False, has_signals=False, only_active=False):
        if only_problematic and not row['has_critical_signal']:
            return False
        if only_unlinked and not row['is_unlinked']:
            return False
        if has_inbound and not row['has_inbound']:
            return False
        if has_signals and not row['has_signals']:
            return False
        if only_active and not row['instance'].is_active:
            return False
        return True

    def build_filter_url(**overrides):
        params = request.GET.copy()
        for key, value in overrides.items():
            if value in (None, '', False):
                params.pop(key, None)
            elif value is True:
                params[key] = '1'
            else:
                params[key] = str(value)
        querystring = params.urlencode()
        base_url = reverse('manager_portal:warehouse_list')
        return f'{base_url}?{querystring}' if querystring else base_url

    warehouses = Warehouse.objects.select_related('pickup_point', 'pickup_point__city').order_by('name')
    filter_form = WarehouseFilterForm(request.GET or None)
    quick_filter_values = {
        'only_problematic': False,
        'only_unlinked': False,
        'has_inbound': False,
        'has_signals': False,
        'only_active': False,
    }
    if filter_form.is_valid():
        q = (filter_form.cleaned_data.get('q') or '').strip()
        if q:
            warehouses = warehouses.filter(Q(name__icontains=q) | Q(address__icontains=q))
        status = filter_form.cleaned_data.get('status')
        if status == 'active':
            warehouses = warehouses.filter(is_active=True)
        elif status == 'inactive':
            warehouses = warehouses.filter(is_active=False)
        public_link = filter_form.cleaned_data.get('public_link')
        if public_link == 'linked':
            warehouses = warehouses.filter(pickup_point__isnull=False)
        elif public_link == 'unlinked':
            warehouses = warehouses.filter(pickup_point__isnull=True)
        quick_filter_values = {key: bool(filter_form.cleaned_data.get(key)) for key in quick_filter_values}
    if request.method == 'POST':
        form = WarehouseForm(request.POST)
        if form.is_valid():
            warehouse = form.save()
            messages.success(request, 'Склад создан.')
            return redirect('manager_portal:warehouse_detail', pk=warehouse.pk)
    else:
        form = WarehouseForm()
    warehouse_rows_all = [build_warehouse_row(warehouse) for warehouse in warehouses]
    warehouse_rows = [
        row
        for row in warehouse_rows_all
        if filter_row(row, **quick_filter_values)
    ]
    warehouse_summary = {
        'total': len(warehouse_rows),
        'unlinked_count': sum(1 for row in warehouse_rows if row['is_unlinked']),
        'critical_signal_count': sum(1 for row in warehouse_rows if row['has_critical_signal']),
        'missing_address_count': sum(1 for row in warehouse_rows if row['address_missing']),
    }
    quick_filters = [
        {
            'key': 'only_problematic',
            'label': 'Проблемные',
            'count': sum(1 for row in warehouse_rows_all if row['has_critical_signal']),
            'active': quick_filter_values['only_problematic'],
            'url': build_filter_url(only_problematic=not quick_filter_values['only_problematic']),
            'tone': 'danger',
        },
        {
            'key': 'only_unlinked',
            'label': 'Без связи с сайтом',
            'count': sum(1 for row in warehouse_rows_all if row['is_unlinked']),
            'active': quick_filter_values['only_unlinked'],
            'url': build_filter_url(only_unlinked=not quick_filter_values['only_unlinked']),
            'tone': 'danger',
        },
        {
            'key': 'has_signals',
            'label': 'Есть сигналы',
            'count': sum(1 for row in warehouse_rows_all if row['has_signals']),
            'active': quick_filter_values['has_signals'],
            'url': build_filter_url(has_signals=not quick_filter_values['has_signals']),
            'tone': 'warning',
        },
        {
            'key': 'only_active',
            'label': 'Активные',
            'count': sum(1 for row in warehouse_rows_all if row['instance'].is_active),
            'active': quick_filter_values['only_active'],
            'url': build_filter_url(only_active=not quick_filter_values['only_active']),
            'tone': 'success',
        },
    ]
    search_active = filter_form.is_valid() and bool(
        (filter_form.cleaned_data.get('q') or '').strip()
        or filter_form.cleaned_data.get('status')
        or filter_form.cleaned_data.get('public_link')
    )
    filters_applied = bool(
        search_active or any(quick_filter_values.values())
    )
    return _render(
        request,
        'manager_portal/warehouses.html',
        active_tab='warehouses',
        warehouses=warehouse_rows,
        warehouse_summary=warehouse_summary,
        quick_filters=quick_filters,
        filters_applied=filters_applied,
        form=form,
        filter_form=filter_form,
    )


@staff_required
def warehouse_detail_view(request, pk):
    warehouse = get_object_or_404(Warehouse.objects.select_related('pickup_point', 'pickup_point__city'), pk=pk)
    if request.method == 'POST':
        form = WarehouseForm(request.POST, instance=warehouse)
        if form.is_valid():
            warehouse = form.save()
            sync_public_stock_for_warehouse(warehouse)
            messages.success(request, 'Склад обновлен.')
            return redirect('manager_portal:warehouse_detail', pk=warehouse.pk)
    else:
        form = WarehouseForm(instance=warehouse)
    balances = inventory_snapshot_for_warehouse(warehouse)
    movements = warehouse.inventory_movements.select_related('product', 'variant', 'author')[:20]
    return _render(
        request,
        'manager_portal/warehouse_detail.html',
        active_tab='warehouses',
        warehouse=warehouse,
        form=form,
        balances=balances,
        movements=movements,
    )


@staff_required
def inventory_view(request):
    warehouse_id = request.GET.get('warehouse')
    warehouse = None
    rows = inventory_snapshot()
    if warehouse_id and warehouse_id.isdigit():
        warehouse = Warehouse.objects.filter(pk=int(warehouse_id)).first()
        if warehouse:
            rows = inventory_snapshot_for_warehouse(warehouse)
    search = (request.GET.get('q') or '').strip().lower()
    if search:
        rows = [
            row for row in rows
            if search in row['product_name'].lower()
            or search in row['warehouse_name'].lower()
            or search in (row['variant_name'] or '').lower()
            or search in (row['sku'] or '').lower()
        ]
    selected_problem_filters = [
        filter_item['param']
        for filter_item in INVENTORY_PROBLEM_FILTERS
        if request.GET.get(filter_item['param']) == '1'
    ]
    only_problematic = request.GET.get('problematic') == '1'
    if selected_problem_filters:
        rows = [row for row in rows if any(code in row['problem_codes'] for code in selected_problem_filters)]
    elif only_problematic:
        rows = [row for row in rows if row['has_problem']]
    enrich_inventory_rows(rows)
    selected_business_view = (request.GET.get('business_view') or '').strip()
    business_views = []
    base_query_params = request.GET.copy()
    base_query_params.pop('business_view', None)
    business_views.append(
        {
            'code': '',
            'label': 'Все',
            'description': 'Полный реестр остатков и резервов по текущим фильтрам.',
            'count': len(rows),
            'query_string': base_query_params.urlencode(),
            'active': not selected_business_view,
        }
    )
    for definition in INVENTORY_BUSINESS_VIEW_DEFINITIONS:
        count = sum(1 for row in rows if _inventory_row_matches_business_view(row, definition['code']))
        params = base_query_params.copy()
        params['business_view'] = definition['code']
        business_views.append(
            {
                'code': definition['code'],
                'label': definition['label'],
                'description': definition['description'],
                'count': count,
                'query_string': params.urlencode(),
                'active': selected_business_view == definition['code'],
            }
        )
    if selected_business_view:
        rows = [row for row in rows if _inventory_row_matches_business_view(row, selected_business_view)]
    rows = sorted(
        rows,
        key=lambda row: (
            0 if row['has_problem'] else 1,
            row['problem_rank'],
            row['available'],
            row['warehouse_name'],
            row['product_name'],
            row['variant_name'],
        ),
    )
    summary = inventory_summary(rows)
    affected_deal_ids = {
        linked['deal'].pk
        for row in rows
        for linked in (row.get('linked_deals') or [])
    }
    business_view_map = {item['code']: item for item in business_views if item['code']}
    receipt_form = InventoryReceiptForm(initial={'warehouse': warehouse} if warehouse else None)
    return _render(
        request,
        'manager_portal/inventory.html',
        active_tab='inventory',
        inventory_rows=rows,
        inventory_summary=summary,
        receipt_form=receipt_form,
        selected_warehouse=warehouse,
        warehouse_options=Warehouse.objects.order_by('name'),
        only_problematic=only_problematic,
        problem_filters=INVENTORY_PROBLEM_FILTERS,
        selected_problem_filters=selected_problem_filters,
        search=search,
        selected_business_view=selected_business_view,
        business_views=business_views,
        deal_risk_view=business_view_map.get(INVENTORY_BUSINESS_VIEW_DEAL_RISK),
        replenishment_view=business_view_map.get(INVENTORY_BUSINESS_VIEW_REPLENISHMENT),
        affected_deal_count=len(affected_deal_ids),
        open_receipt_drawer=request.GET.get('open_receipt') == '1',
    )


@staff_required
def inventory_receipt_view(request):
    form = InventoryReceiptForm(request.POST)
    if form.is_valid():
        receipt_inventory(
            warehouse=form.cleaned_data['warehouse'],
            product=form.cleaned_data['product'],
            variant=form.cleaned_data['variant'],
            quantity=form.cleaned_data['quantity'],
            author=request.user,
            comment=form.cleaned_data['comment'],
        )
        messages.success(request, 'Приход записан.')
    else:
        messages.error(request, 'Не удалось записать приход.')
    return redirect('manager_portal:inventory')


@staff_required
def purchase_create_view(request):
    return purchase_list_view(request)


@staff_required
def purchase_list_view(request):
    purchases = Purchase.objects.prefetch_related('items').order_by('-date', '-id')
    filter_form = PurchaseFilterForm(request.GET or None)
    if filter_form.is_valid():
        q = (filter_form.cleaned_data.get('q') or '').strip()
        if q:
            purchase_query = (
                Q(supplier_name__icontains=q)
                | Q(agent__icontains=q)
                | Q(comments__icontains=q)
            )
            if q.isdigit():
                purchase_query |= Q(pk=int(q))
            purchases = purchases.filter(purchase_query)
        if filter_form.cleaned_data.get('status'):
            purchases = purchases.filter(status=filter_form.cleaned_data['status'])
        if filter_form.cleaned_data.get('date_from'):
            purchases = purchases.filter(date__gte=filter_form.cleaned_data['date_from'])
        if filter_form.cleaned_data.get('date_to'):
            purchases = purchases.filter(date__lte=filter_form.cleaned_data['date_to'])
    if request.method == 'POST':
        form = PurchaseForm(request.POST)
        if form.is_valid():
            purchase = form.save()
            messages.success(request, 'Закупка создана.')
            return redirect('manager_portal:purchase_detail', pk=purchase.pk)
    else:
        form = PurchaseForm(initial={'date': timezone.localdate()})
    return _render(
        request,
        'manager_portal/purchases.html',
        active_tab='purchases',
        purchases=purchases,
        form=form,
        filter_form=filter_form,
    )


@staff_required
def purchase_detail_view(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related('items__product', 'items__variant', 'items__order_item__order', 'cargos'),
        pk=pk,
    )
    if request.method == 'POST':
        form = PurchaseForm(request.POST, instance=purchase)
        if form.is_valid():
            form.save()
            messages.success(request, 'Закупка обновлена.')
            return redirect('manager_portal:purchase_detail', pk=purchase.pk)
    else:
        form = PurchaseForm(instance=purchase)
    item_form = PurchaseItemForm()
    return _render(
        request,
        'manager_portal/purchase_detail.html',
        active_tab='purchases',
        purchase=purchase,
        form=form,
        item_form=item_form,
    )


@staff_required
def purchase_add_item_view(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    form = PurchaseItemForm(request.POST, request.FILES)
    if form.is_valid():
        item = form.save(commit=False)
        item.purchase = purchase
        item.save()
        messages.success(request, 'Позиция закупки добавлена.')
    else:
        messages.error(request, 'Не удалось добавить позицию закупки.')
    return redirect('manager_portal:purchase_detail', pk=purchase.pk)


@staff_required
def cargo_create_view(request):
    return cargo_list_view(request)


@staff_required
def cargo_list_view(request):
    cargos = Cargo.objects.select_related('purchase', 'destination_warehouse').prefetch_related('items').order_by('-created_at')
    filter_form = CargoFilterForm(request.GET or None)
    if filter_form.is_valid():
        q = (filter_form.cleaned_data.get('q') or '').strip()
        if q:
            cargos = cargos.filter(
                Q(cargo_number__icontains=q)
                | Q(comments__icontains=q)
                | Q(destination_warehouse__name__icontains=q)
            )
        if filter_form.cleaned_data.get('status'):
            cargos = cargos.filter(status=filter_form.cleaned_data['status'])
        if filter_form.cleaned_data.get('destination_warehouse'):
            cargos = cargos.filter(destination_warehouse=filter_form.cleaned_data['destination_warehouse'])
        if filter_form.cleaned_data.get('overdue'):
            cargos = cargos.filter(eta__lt=timezone.localdate(), status__in=['in_transit', 'arrived_rf', 'delivery_rf', 'awaiting_receipt'])
        if filter_form.cleaned_data.get('has_reservations'):
            cargos = cargos.filter(cargo_reservations__isnull=False).distinct()
    initial = {}
    create_from_purchase = request.GET.get('createFromPurchase')
    if create_from_purchase and create_from_purchase.isdigit():
        initial['purchase'] = create_from_purchase
    if request.method == 'POST':
        form = CargoForm(request.POST)
        if form.is_valid():
            cargo = form.save()
            messages.success(request, 'Груз создан.')
            return redirect('manager_portal:cargo_detail', pk=cargo.pk)
    else:
        form = CargoForm(initial=initial)
    return _render(
        request,
        'manager_portal/cargos.html',
        active_tab='cargos',
        cargos=cargos,
        form=form,
        filter_form=filter_form,
        overdue_count=cargos.filter(eta__lt=timezone.localdate(), status__in=['in_transit', 'arrived_rf', 'delivery_rf', 'awaiting_receipt']).count(),
    )


@staff_required
def cargo_detail_view(request, pk):
    cargo = get_object_or_404(
        Cargo.objects.select_related('purchase', 'destination_warehouse').prefetch_related(
            'items__product',
            'items__variant',
            'items__purchase_item__purchase',
            'items__purchase_item__order_item__order',
            'photos',
            'legs',
            'expenses',
        ),
        pk=pk,
    )
    if request.method == 'POST':
        form = CargoForm(request.POST, instance=cargo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Груз обновлен.')
            return redirect('manager_portal:cargo_detail', pk=cargo.pk)
    else:
        form = CargoForm(instance=cargo)
    context = {
        'cargo': cargo,
        'form': form,
        'item_form': CargoItemForm(),
        'photo_form': CargoPhotoForm(),
        'leg_form': TransportLegForm(),
        'expense_form': ExpenseForm(initial={'date': timezone.localdate()}),
        'split_form': CargoSplitForm(cargo=cargo),
    }
    context['receive_forms'] = {item.id: CargoReceiveForm(initial={'quantity': item.remaining_quantity or 1}) for item in cargo.items.all()}
    return _render(request, 'manager_portal/cargo_detail.html', active_tab='cargos', **context)


@staff_required
def cargo_add_item_view(request, pk):
    cargo = get_object_or_404(Cargo, pk=pk)
    form = CargoItemForm(request.POST, request.FILES)
    if form.is_valid():
        item = form.save(commit=False)
        item.cargo = cargo
        item.save()
        messages.success(request, 'Позиция груза добавлена.')
    else:
        messages.error(request, 'Не удалось добавить позицию груза.')
    return redirect('manager_portal:cargo_detail', pk=cargo.pk)


@staff_required
def cargo_receive_item_view(request, pk, item_id):
    cargo = get_object_or_404(Cargo, pk=pk)
    item = get_object_or_404(cargo.items.all(), pk=item_id)
    form = CargoReceiveForm(request.POST)
    if form.is_valid():
        try:
            receive_cargo_item(item, quantity=form.cleaned_data['quantity'], author=request.user)
            messages.success(request, 'Приемка позиции груза выполнена.')
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, 'Некорректное количество для приемки.')
    return redirect('manager_portal:cargo_detail', pk=cargo.pk)


@staff_required
def cargo_split_view(request, pk):
    cargo = get_object_or_404(Cargo, pk=pk)
    form = CargoSplitForm(request.POST, cargo=cargo)
    if form.is_valid():
        try:
            new_cargo = split_cargo(
                cargo,
                cargo_number=form.cleaned_data['cargo_number'],
                cargo_item=form.cleaned_data['item'],
                quantity=form.cleaned_data['quantity'],
            )
            messages.success(request, f'Создан новый груз {new_cargo.cargo_number}.')
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, 'Не удалось выполнить split груза.')
    return redirect('manager_portal:cargo_detail', pk=cargo.pk)


@staff_required
def cargo_add_photo_view(request, pk):
    cargo = get_object_or_404(Cargo, pk=pk)
    form = CargoPhotoForm(request.POST, request.FILES)
    if form.is_valid():
        photo = form.save(commit=False)
        photo.cargo = cargo
        photo.save()
        messages.success(request, 'Фото груза загружено.')
    else:
        messages.error(request, 'Не удалось загрузить фото.')
    return redirect('manager_portal:cargo_detail', pk=cargo.pk)


@staff_required
def cargo_add_leg_view(request, pk):
    cargo = get_object_or_404(Cargo, pk=pk)
    form = TransportLegForm(request.POST)
    if form.is_valid():
        leg = form.save(commit=False)
        leg.cargo = cargo
        leg.save()
        messages.success(request, 'Этап перевозки добавлен.')
    else:
        messages.error(request, 'Не удалось добавить этап перевозки.')
    return redirect('manager_portal:cargo_detail', pk=cargo.pk)


@staff_required
def cargo_add_expense_view(request, pk):
    cargo = get_object_or_404(Cargo, pk=pk)
    form = ExpenseForm(request.POST, instance=Expense(cargo=cargo))
    if form.is_valid():
        form.save()
        messages.success(request, 'Расход добавлен.')
    else:
        messages.error(request, 'Не удалось добавить расход.')
    return redirect('manager_portal:cargo_detail', pk=cargo.pk)


@staff_required
def reservation_create_view(request):
    return reservation_list_view(request)


@staff_required
def reservation_list_view(request):
    reservations = Reservation.objects.select_related(
        'client',
        'linked_order',
        'source_warehouse',
        'source_cargo',
        'target_warehouse',
    ).prefetch_related('items__product', 'items__variant').order_by('-created_at')
    filter_form = ReservationFilterForm(request.GET or None)
    if filter_form.is_valid():
        q = (filter_form.cleaned_data.get('q') or '').strip()
        if q:
            reservations = reservations.filter(
                Q(client__name__icontains=q)
                | Q(client__phone__icontains=q)
                | Q(comments__icontains=q)
                | Q(source_cargo__cargo_number__icontains=q)
            )
        if filter_form.cleaned_data.get('status'):
            reservations = reservations.filter(status=filter_form.cleaned_data['status'])
        if filter_form.cleaned_data.get('source_type'):
            reservations = reservations.filter(source_type=filter_form.cleaned_data['source_type'])
        if filter_form.cleaned_data.get('source_warehouse'):
            reservations = reservations.filter(source_warehouse=filter_form.cleaned_data['source_warehouse'])
        if filter_form.cleaned_data.get('target_warehouse'):
            reservations = reservations.filter(target_warehouse=filter_form.cleaned_data['target_warehouse'])
        if filter_form.cleaned_data.get('client'):
            reservations = reservations.filter(client=filter_form.cleaned_data['client'])
    initial = {}
    create_from_client = request.GET.get('createFromClient')
    if create_from_client and create_from_client.isdigit():
        initial['client'] = create_from_client
    create_from_deal = _deal_request_target(request)
    reservation_prefill_note = ''
    reservation_prefill_items = []
    if create_from_deal is not None:
        client = deal_manager_client(create_from_deal) or ensure_manager_client_for_order(create_from_deal.order)['client']
        reservation_prefill_items = reservation_prefill_lines_for_deal(create_from_deal)
        initial.update(
            {
                'client': client.pk,
                'linked_order': create_from_deal.order.pk,
                'status': Reservation.STATUS_DRAFT,
                'source_type': Reservation.SOURCE_WAREHOUSE,
                'source_warehouse': create_from_deal.stock_warehouse_id,
                'target_warehouse': create_from_deal.stock_warehouse_id,
                'comments': f'Подготовлено из сделки #{create_from_deal.order_id}.',
            }
        )
        reservation_prefill_note = f'Новая бронь будет связана со сделкой #{create_from_deal.order_id}.'
    if request.method == 'POST':
        form = ReservationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    reservation = form.save(commit=False)
                    if create_from_deal is not None:
                        reservation.manager_deal = create_from_deal
                        if not reservation.linked_order_id:
                            reservation.linked_order = create_from_deal.order
                    reservation.full_clean()
                    reservation.save()
                    autofilled_items = []
                    if create_from_deal is not None:
                        autofilled_items = autofill_reservation_items_from_deal(
                            reservation,
                            create_from_deal,
                            author=request.user,
                        )
                        if create_from_deal.primary_reservation_id is None:
                            create_from_deal.primary_reservation = reservation
                            create_from_deal.reserve_created_at = timezone.now()
                            create_from_deal.save(update_fields=['primary_reservation', 'reserve_created_at', 'updated_at'])
                        record_deal_activity(
                            create_from_deal,
                            event_type='reservation.created',
                            source=DealActivity.SOURCE_USER,
                            actor=request.user,
                            payload={'reservation_id': reservation.id, 'items_autofilled': len(autofilled_items)},
                        )
                        recompute_deal_workflow(create_from_deal, actor=request.user)
                if create_from_deal is not None and autofilled_items:
                    messages.success(request, f'Бронирование создано. {len(autofilled_items)} позиций добавлены автоматически.')
                else:
                    messages.success(request, 'Бронирование создано. Добавьте позиции.')
                return _redirect_back_to_deal(
                    request,
                    fallback=redirect('manager_portal:reservation_detail', pk=reservation.pk),
                    anchor='reservation',
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        form = ReservationForm(initial=initial)
    return _render(
        request,
        'manager_portal/reservations.html',
        active_tab='reservations',
        reservations=reservations,
        form=form,
        filter_form=filter_form,
        reservation_prefill_deal=create_from_deal,
        reservation_prefill_note=reservation_prefill_note,
        reservation_prefill_items=reservation_prefill_items,
        reservation_open_drawer=(request.GET.get('openDrawer') == 'reservation-create-drawer'),
    )


@staff_required
def reservation_detail_view(request, pk):
    reservation = get_object_or_404(
        Reservation.objects.select_related('client', 'linked_order', 'source_warehouse', 'source_cargo', 'target_warehouse').prefetch_related(
            'items__product',
            'items__variant',
            'items__order_item__order',
            'shipments',
        ),
        pk=pk,
    )
    if request.method == 'POST':
        form = ReservationForm(request.POST, instance=reservation)
        if form.is_valid():
            try:
                previous_warehouse = _reservation_effective_warehouse(reservation)
                reservation = form.save(commit=False)
                reservation.full_clean()
                validate_reservation_availability(reservation, items=reservation.items.all())
                reservation.save()
                current_warehouse = _reservation_effective_warehouse(reservation)
                if previous_warehouse:
                    sync_public_stock_for_warehouse(previous_warehouse)
                if current_warehouse and (not previous_warehouse or current_warehouse.pk != previous_warehouse.pk):
                    sync_public_stock_for_warehouse(current_warehouse)
                if reservation.manager_deal_id:
                    recompute_deal_workflow(reservation.manager_deal, actor=request.user)
                messages.success(request, 'Бронирование обновлено.')
                return _redirect_back_to_deal(
                    request,
                    fallback=redirect('manager_portal:reservation_detail', pk=reservation.pk),
                    anchor='reservation',
                )
            except ValueError as exc:
                messages.error(request, str(exc))
    else:
        form = ReservationForm(instance=reservation)
    return _render(
        request,
        'manager_portal/reservation_detail.html',
        active_tab='reservations',
        reservation=reservation,
        form=form,
        item_form=ReservationItemForm(),
        status_form=ReservationStatusForm(initial={'status': reservation.status}),
    )


@staff_required
def reservation_add_item_view(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    form = ReservationItemForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.reservation = reservation
        try:
            validate_reservation_availability(reservation, items=[item])
            item.save()
            create_or_update_reservation_movements(
                reservation,
                movement_type='reserve',
                author=request.user,
                comment='Создание/расширение брони',
                items=[item],
            )
            effective_warehouse = _reservation_effective_warehouse(reservation)
            if effective_warehouse:
                sync_public_stock_for_warehouse(effective_warehouse)
            if reservation.manager_deal_id:
                recompute_deal_workflow(reservation.manager_deal, actor=request.user)
            messages.success(request, 'Позиция бронирования добавлена.')
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, 'Не удалось добавить позицию брони.')
    return _redirect_back_to_deal(
        request,
        fallback=redirect('manager_portal:reservation_detail', pk=reservation.pk),
        anchor='reservation',
    )


@staff_required
def reservation_status_update_view(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    form = ReservationStatusForm(request.POST)
    if form.is_valid():
        old_status = reservation.status
        reservation.status = form.cleaned_data['status']
        reservation.save(update_fields=['status', 'updated_at'])
        effective_warehouse = _reservation_effective_warehouse(reservation)
        if old_status in ACTIVE_RESERVATION_STATUSES and reservation.status not in ACTIVE_RESERVATION_STATUSES:
            create_or_update_reservation_movements(
                reservation,
                movement_type='release',
                author=request.user,
                comment='Снятие резерва по смене статуса',
            )
        elif old_status not in ACTIVE_RESERVATION_STATUSES and reservation.status in ACTIVE_RESERVATION_STATUSES:
            create_or_update_reservation_movements(
                reservation,
                movement_type='reserve',
                author=request.user,
                comment='Повторная активация брони',
            )
        if effective_warehouse:
            sync_public_stock_for_warehouse(effective_warehouse)
        if reservation.manager_deal_id:
            recompute_deal_workflow(reservation.manager_deal, actor=request.user)
        messages.success(request, 'Статус брони обновлен.')
    else:
        messages.error(request, 'Не удалось обновить статус брони.')
    return _redirect_back_to_deal(
        request,
        fallback=redirect('manager_portal:reservation_detail', pk=reservation.pk),
        anchor='reservation',
    )


@staff_required
def shipment_detail_view(request, pk):
    shipment = get_object_or_404(
        Shipment.objects.select_related(
            'order',
            'client',
            'manager_deal',
            'reservation',
            'source_warehouse',
            'target_warehouse',
        ).prefetch_related('items__product', 'items__variant', 'items__order_item__order'),
        pk=pk,
    )
    return _render(
        request,
        'manager_portal/shipment_detail.html',
        active_tab='shipments',
        shipment=shipment,
        shipment_checklist=shipment_checklist(shipment),
        shipment_missing_fields=shipment_missing_fields(shipment),
    )


@staff_required
def shipments_view(request):
    filter_form = ShipmentFilterForm(request.GET or None)
    rows = shipments_rows()
    shipments = Shipment.objects.select_related(
        'order',
        'client',
        'reservation',
        'source_warehouse',
        'target_warehouse',
    ).prefetch_related('items__product', 'items__variant').order_by('-created_at')
    if filter_form.is_valid():
        warehouse = filter_form.cleaned_data.get('warehouse')
        target_warehouse = filter_form.cleaned_data.get('target_warehouse')
        client = filter_form.cleaned_data.get('client')
        if warehouse:
            rows = [row for row in rows if row['reservation'].source_warehouse_id == warehouse.id or (row['reservation'].source_cargo_id and row['reservation'].source_cargo.destination_warehouse_id == warehouse.id)]
            shipments = shipments.filter(source_warehouse=warehouse)
        if target_warehouse:
            rows = [row for row in rows if row['target_warehouse'] and row['target_warehouse'].id == target_warehouse.id]
            shipments = shipments.filter(target_warehouse=target_warehouse)
        if client:
            rows = [row for row in rows if row['client'].id == client.id]
            shipments = shipments.filter(client=client)
        view_mode = filter_form.cleaned_data.get('view_mode') or 'reservation'
    else:
        view_mode = 'reservation'
    return _render(
        request,
        'manager_portal/shipments.html',
        active_tab='shipments',
        shipments=shipments,
        rows=rows,
        grouped_rows=shipments_grouped_by_reservation(rows),
        filter_form=filter_form,
        view_mode=view_mode,
    )
