import csv
import json
import zipfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db import models
from django.utils import timezone

from accounts.services import normalize_email, normalize_phone
from catalog.models import Product, ProductStock, ProductVariant
from orders.models import Order
from orders.services import sync_order_state_side_effects
from .status_system import (
    SEMANTIC_TONE_ACTIVE,
    SEMANTIC_TONE_ATTENTION,
    SEMANTIC_TONE_COMPLETE,
    SEMANTIC_TONE_CRITICAL,
    SEMANTIC_TONE_UNKNOWN,
    build_semantic_status,
)

from .models import (
    Cargo,
    CargoItem,
    ContractCompanyProfile,
    ContractDocument,
    ContractTemplate,
    DealActivity,
    DealSavedView,
    FinanceDeal,
    FinanceDealType,
    FinanceExpense,
    FinancePayout,
    InventoryBalance,
    InventoryMovement,
    ManagerClient,
    ManagerDeal,
    PurchaseItem,
    Reservation,
    ReservationItem,
    Shipment,
    ShipmentItem,
    Warehouse,
)


ACTIVE_RESERVATION_STATUSES = {
    Reservation.STATUS_DRAFT,
    Reservation.STATUS_ACTIVE,
    Reservation.STATUS_PARTIAL,
}
INBOUND_CARGO_STATUSES = {
    Cargo.STATUS_IN_TRANSIT,
    Cargo.STATUS_ARRIVED_RF,
    Cargo.STATUS_DELIVERY_RF,
    Cargo.STATUS_AWAITING_RECEIPT,
}
INVENTORY_PUBLIC_SYNC_STATUS_SYNCED = 'synced'
INVENTORY_PUBLIC_SYNC_STATUS_MISMATCH = 'mismatch'
INVENTORY_PUBLIC_SYNC_STATUS_UNLINKED = 'unlinked'
INVENTORY_PUBLIC_SYNC_STATUS_LABELS = {
    INVENTORY_PUBLIC_SYNC_STATUS_SYNCED: 'Совпадает с сайтом',
    INVENTORY_PUBLIC_SYNC_STATUS_MISMATCH: 'Нужно сверить с сайтом',
    INVENTORY_PUBLIC_SYNC_STATUS_UNLINKED: 'Не связан с сайтом',
}
INVENTORY_PROBLEM_LABELS = {
    'below_min_stock': 'Ниже минимального остатка',
    'negative_available': 'Отрицательный доступный остаток',
    'reserved_gt_on_hand': 'Резерв превышает остаток',
    'inbound_fully_allocated': 'Весь входящий остаток уже распределен',
    'public_mismatch': 'Остаток на сайте не совпадает',
}
INVENTORY_ROW_STATUS_NORMAL = 'normal'
INVENTORY_ROW_STATUS_LOW_STOCK = 'low_stock'
INVENTORY_ROW_STATUS_PROMISE_RISK = 'promise_risk'
INVENTORY_ROW_STATUS_SITE_MISMATCH = 'site_mismatch'
INVENTORY_ROW_STATUS_WAITING_INBOUND = 'waiting_inbound'
INVENTORY_ROW_STATUS_META = {
    INVENTORY_ROW_STATUS_NORMAL: {
        'label': 'Норма',
        'tone': SEMANTIC_TONE_COMPLETE,
    },
    INVENTORY_ROW_STATUS_LOW_STOCK: {
        'label': 'Мало остатков',
        'tone': SEMANTIC_TONE_ATTENTION,
    },
    INVENTORY_ROW_STATUS_PROMISE_RISK: {
        'label': 'Риск обещания',
        'tone': SEMANTIC_TONE_CRITICAL,
    },
    INVENTORY_ROW_STATUS_SITE_MISMATCH: {
        'label': 'Сайт не совпадает',
        'tone': SEMANTIC_TONE_ATTENTION,
    },
    INVENTORY_ROW_STATUS_WAITING_INBOUND: {
        'label': 'Ждем приход',
        'tone': SEMANTIC_TONE_ACTIVE,
    },
}
INVENTORY_PROBLEM_PRIORITY = (
    'reserved_gt_on_hand',
    'negative_available',
    'below_min_stock',
    'inbound_fully_allocated',
    'public_mismatch',
)
INVENTORY_PROBLEM_FILTERS = (
    {'param': 'below_min_stock', 'label': 'Ниже минимального остатка'},
    {'param': 'negative_available', 'label': 'Отрицательный доступный остаток'},
    {'param': 'reserved_gt_on_hand', 'label': 'Резерв превышает остаток'},
    {'param': 'inbound_fully_allocated', 'label': 'Весь входящий остаток уже распределен'},
    {'param': 'public_mismatch', 'label': 'Остаток на сайте не совпадает'},
)
MANAGER_PORTAL_DEFAULT_WORKFLOW_SETTINGS = {
    'timezone': 'Asia/Yekaterinburg',
    'business_hours': {'start': '10:00', 'end': '19:00'},
    'weekdays': [0, 1, 2, 3, 4],
    'stale_after_hours': 48,
    'sla_map': {
        ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION: 'created_plus_30m',
        ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION: 'current_business_day_end',
        ManagerDeal.NEXT_STEP_NEEDS_PAYMENT: 'next_business_day_end',
        ManagerDeal.NEXT_STEP_NEEDS_RESERVATION: 'current_business_day_end',
        ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT: 'next_business_day_end',
        ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS: 'current_business_day_end',
        ManagerDeal.NEXT_STEP_NEEDS_DOCUMENT_DISPATCH: 'current_business_day_end',
        ManagerDeal.NEXT_STEP_READY_TO_SHIP: 'current_business_day_end',
        ManagerDeal.NEXT_STEP_SHIPPED: None,
        ManagerDeal.NEXT_STEP_RETURN_TO_STOCK: 'current_business_day_end',
        ManagerDeal.NEXT_STEP_COMPLETED: None,
    },
}
SYSTEM_DEAL_QUEUE_PRESETS = (
    {
        'key': ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION,
        'label': 'Нужно подтвердить',
        'params': {'queue': ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION},
    },
    {
        'key': ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION,
        'label': 'Ждут наличие',
        'params': {'queue': ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION},
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
        'key': ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT,
        'label': 'Ждут закупку',
        'params': {'queue': ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT},
    },
    {
        'key': ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS,
        'label': 'Ждут документы',
        'params': {'queue': ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS},
    },
    {
        'key': ManagerDeal.NEXT_STEP_READY_TO_SHIP,
        'label': 'Готовы к отгрузке',
        'params': {'queue': ManagerDeal.NEXT_STEP_READY_TO_SHIP},
    },
)
MANUAL_EDITABLE_CASE_STATUSES = {
    ManagerDeal.CASE_STATUS_NEW,
    ManagerDeal.CASE_STATUS_CONFIRMED,
    ManagerDeal.CASE_STATUS_IN_PROGRESS,
    ManagerDeal.CASE_STATUS_WAITING_CLIENT,
    ManagerDeal.CASE_STATUS_READY_TO_SHIP,
}


def manager_portal_workflow_settings():
    config = dict(MANAGER_PORTAL_DEFAULT_WORKFLOW_SETTINGS)
    custom = getattr(settings, 'MANAGER_PORTAL_WORKFLOW', {}) or {}
    business_hours = dict(config['business_hours'])
    business_hours.update(custom.get('business_hours', {}) or {})
    sla_map = dict(config['sla_map'])
    sla_map.update(custom.get('sla_map', {}) or {})
    config.update(custom)
    config['business_hours'] = business_hours
    config['sla_map'] = sla_map
    config['weekdays'] = tuple(config.get('weekdays') or MANAGER_PORTAL_DEFAULT_WORKFLOW_SETTINGS['weekdays'])
    return config


def manager_portal_zoneinfo():
    return ZoneInfo(manager_portal_workflow_settings()['timezone'])


def manager_portal_stale_after():
    return timedelta(hours=int(manager_portal_workflow_settings().get('stale_after_hours') or 48))


def _portal_business_time(raw_value, *, fallback):
    if isinstance(raw_value, time):
        return raw_value
    value = raw_value or fallback
    if isinstance(value, str):
        parsed = datetime.strptime(value, '%H:%M').time()
        return parsed.replace(second=0, microsecond=0)
    return fallback


def _portal_business_window():
    config = manager_portal_workflow_settings()
    return (
        _portal_business_time(config['business_hours'].get('start'), fallback=time(10, 0)),
        _portal_business_time(config['business_hours'].get('end'), fallback=time(19, 0)),
    )


def manager_portal_now():
    return timezone.now().astimezone(manager_portal_zoneinfo())


def _portal_localize(value):
    if timezone.is_naive(value):
        return timezone.make_aware(value, manager_portal_zoneinfo())
    return value.astimezone(manager_portal_zoneinfo())


def _portal_business_datetime(day_value, clock_value):
    return _portal_localize(datetime.combine(day_value, clock_value))


def _portal_is_business_day(day_value):
    return day_value.weekday() in manager_portal_workflow_settings()['weekdays']


def _portal_next_business_day(day_value):
    current = day_value
    while not _portal_is_business_day(current):
        current += timedelta(days=1)
    return current


def _portal_shift_business_days(day_value, *, days):
    current = day_value
    remaining = max(int(days), 0)
    while remaining:
        current += timedelta(days=1)
        if _portal_is_business_day(current):
            remaining -= 1
    return _portal_next_business_day(current)


def _portal_current_business_day_end(reference_dt):
    _, end_time = _portal_business_window()
    local_reference = _portal_localize(reference_dt)
    business_day = _portal_next_business_day(local_reference.date())
    if business_day == local_reference.date():
        due_at = _portal_business_datetime(business_day, end_time)
        if local_reference <= due_at:
            return due_at
    business_day = _portal_shift_business_days(local_reference.date(), days=1)
    return _portal_business_datetime(business_day, end_time)


def _portal_next_business_day_end(reference_dt):
    _, end_time = _portal_business_window()
    local_reference = _portal_localize(reference_dt)
    business_day = _portal_shift_business_days(local_reference.date(), days=1)
    return _portal_business_datetime(business_day, end_time)


def compute_deal_sla_due_at(*, deal, next_step_code):
    policy = manager_portal_workflow_settings()['sla_map'].get(next_step_code)
    if not policy:
        return None
    local_created = _portal_localize(deal.created_at or timezone.now())
    if policy == 'created_plus_30m':
        return local_created + timedelta(minutes=30)
    if policy == 'current_business_day_end':
        return _portal_current_business_day_end(manager_portal_now())
    if policy == 'next_business_day_end':
        return _portal_next_business_day_end(manager_portal_now())
    if policy == 'ready_today_end':
        return _portal_current_business_day_end(manager_portal_now())
    return None


def deal_system_queue_presets():
    return SYSTEM_DEAL_QUEUE_PRESETS


def record_deal_activity(manager_deal, *, event_type, source=DealActivity.SOURCE_SYSTEM, actor=None, payload=None, created_at=None):
    if manager_deal is None:
        return None
    created_at = created_at or timezone.now()
    safe_payload = json.loads(json.dumps(payload or {}, cls=DjangoJSONEncoder))
    activity = DealActivity.objects.create(
        manager_deal=manager_deal,
        event_type=event_type,
        source=source,
        actor=actor,
        payload=safe_payload,
    )
    if manager_deal.last_activity_at is None or created_at > manager_deal.last_activity_at:
        manager_deal.last_activity_at = created_at
        manager_deal.save(update_fields=['last_activity_at', 'updated_at'])
    return activity


def ensure_initial_deal_activity(manager_deal, *, actor=None):
    if manager_deal is None or manager_deal.activities.exists():
        return
    record_deal_activity(
        manager_deal,
        event_type='deal.created',
        source=DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={'order_id': manager_deal.order_id},
        created_at=manager_deal.created_at,
    )


def deal_manager_client(manager_deal):
    if manager_deal is None:
        return None
    client = ManagerClient.objects.filter(orders=manager_deal.order).order_by('id').first()
    if client:
        return client
    reservation_client = manager_deal.reservations.select_related('client').order_by('id').values_list('client_id', flat=True).first()
    if reservation_client:
        return ManagerClient.objects.filter(pk=reservation_client).first()
    document_client = manager_deal.contract_documents.exclude(manager_client__isnull=True).select_related('manager_client').first()
    if document_client:
        return document_client.manager_client
    shipment_client = manager_deal.shipments.exclude(client__isnull=True).select_related('client').first()
    if shipment_client:
        return shipment_client.client
    return None


def _normalized_phone(value):
    raw_value = (value or '').strip()
    if not raw_value:
        return ''
    return normalize_phone(raw_value)


def _normalized_email(value):
    raw_value = (value or '').strip()
    if not raw_value:
        return ''
    return normalize_email(raw_value)


def match_manager_client(*, user=None, phone='', email=''):
    if user is not None:
        client = ManagerClient.objects.filter(user=user).order_by('id').first()
        if client is not None:
            return client, 'user'

    normalized_phone = _normalized_phone(phone)
    if normalized_phone:
        for candidate in ManagerClient.objects.exclude(phone='').order_by('id'):
            if _normalized_phone(candidate.phone) == normalized_phone:
                return candidate, 'phone'

    normalized_email = _normalized_email(email)
    if normalized_email:
        client = ManagerClient.objects.filter(email__iexact=normalized_email).order_by('id').first()
        if client is not None:
            return client, 'email'

    return None, ''


def _update_manager_client_snapshot(
    client,
    *,
    user=None,
    name='',
    phone='',
    email='',
    address='',
    telegram='',
    comments='',
):
    update_fields = []
    candidate_name = (name or '').strip()
    candidate_phone = (phone or '').strip()
    candidate_email = _normalized_email(email)
    candidate_address = (address or '').strip()
    candidate_telegram = (telegram or '').strip()
    candidate_comments = (comments or '').strip()

    if user is not None and client.user_id != user.id:
        client.user = user
        update_fields.append('user')
    if candidate_name and (not client.name or client.name.startswith('Клиент по заказу #')):
        client.name = candidate_name
        update_fields.append('name')
    if candidate_phone and not client.phone:
        client.phone = candidate_phone
        update_fields.append('phone')
    if candidate_email and not client.email:
        client.email = candidate_email
        update_fields.append('email')
    if candidate_address and not client.address:
        client.address = candidate_address
        update_fields.append('address')
    if candidate_telegram and not client.telegram:
        client.telegram = candidate_telegram
        update_fields.append('telegram')
    if candidate_comments and not client.comments:
        client.comments = candidate_comments
        update_fields.append('comments')
    if update_fields:
        update_fields.append('updated_at')
        client.save(update_fields=update_fields)
    return client


def resolve_manager_client(
    *,
    user=None,
    name='',
    phone='',
    email='',
    address='',
    telegram='',
    comments='',
    order=None,
):
    client, match_source = match_manager_client(user=user, phone=phone, email=email)
    created = False
    if client is None:
        client = ManagerClient.objects.create(
            user=user,
            name=(name or '').strip() or (f'Клиент по заказу #{order.pk}' if order is not None else 'Клиент'),
            phone=(phone or '').strip(),
            email=_normalized_email(email),
            address=(address or '').strip(),
            telegram=(telegram or '').strip(),
            comments=(comments or '').strip(),
        )
        created = True
        match_source = 'created'
    else:
        _update_manager_client_snapshot(
            client,
            user=user,
            name=name,
            phone=phone,
            email=email,
            address=address,
            telegram=telegram,
            comments=comments,
        )
    if order is not None:
        client.orders.add(order)
    return {
        'client': client,
        'created': created,
        'match_source': match_source,
    }


def order_items_snapshot(order):
    snapshot = []
    for item in order.items.select_related('product', 'variant').all():
        snapshot.append(
            {
                'order_item_id': item.id,
                'product_id': item.product_id,
                'variant_id': item.variant_id,
                'sku': item.sku,
                'name': item.display_name,
                'quantity': int(item.quantity or 0),
                'unit': 'шт.',
                'price': str(item.unit_price),
                'line_total': str(item.subtotal),
                'purchase_price': str(item.purchase_price),
                'is_on_request': bool(item.is_on_request),
            }
        )
    return snapshot


def reservation_coverage_snapshot(order):
    reserved_by_item = defaultdict(int)
    for reservation_item in ReservationItem.objects.filter(
        reservation__linked_order=order,
        reservation__status__in=ACTIVE_RESERVATION_STATUSES,
        order_item__isnull=False,
    ):
        reserved_by_item[reservation_item.order_item_id] += reservation_item.quantity
    lines = []
    for item in order.items.select_related('product', 'variant').all():
        reserved_quantity = reserved_by_item.get(item.id, 0)
        missing_quantity = max(item.quantity - reserved_quantity, 0)
        lines.append(
            {
                'order_item_id': item.id,
                'product_name': item.resolved_product_name,
                'variant_name': item.resolved_variant_name,
                'ordered_quantity': item.quantity,
                'reserved_quantity': reserved_quantity,
                'missing_quantity': missing_quantity,
                'is_fully_reserved': missing_quantity == 0 or item.is_on_request or not item.product_id,
            }
        )
    return {
        'lines': lines,
        'is_complete': all(line['is_fully_reserved'] for line in lines),
        'missing_lines': [line for line in lines if line['missing_quantity'] > 0],
    }


def contract_document_missing_fields(document):
    missing = []
    if not document.template_id:
        missing.append('Шаблон документа')
    if not document.company_profile_id:
        missing.append('Профиль компании')
    if not document.counterparty_name:
        missing.append('Контрагент')
    if not document.counterparty_phone:
        missing.append('Телефон контрагента')
    if not document.counterparty_address:
        missing.append('Адрес контрагента')
    if document.manager_deal_id and document.manager_deal.buyer_type == ManagerDeal.BUYER_BUSINESS:
        if not document.counterparty_inn:
            missing.append('ИНН контрагента')
        if not (document.counterparty_ogrn or document.counterparty_ogrnip):
            missing.append('ОГРН / ОГРНИП контрагента')
    return missing


def shipment_checklist(shipment):
    return [
        {'label': 'Получатель', 'value': shipment.recipient_name, 'is_ready': bool(shipment.recipient_name)},
        {'label': 'Телефон', 'value': shipment.recipient_phone, 'is_ready': bool(shipment.recipient_phone)},
        {'label': 'Адрес', 'value': shipment.delivery_address, 'is_ready': bool(shipment.delivery_address)},
        {'label': 'Склад-источник', 'value': getattr(shipment.source_warehouse, 'name', ''), 'is_ready': bool(shipment.source_warehouse_id)},
        {'label': 'Резерв', 'value': f'#{shipment.reservation_id}' if shipment.reservation_id else '', 'is_ready': bool(shipment.reservation_id)},
        {'label': 'Способ доставки', 'value': shipment.delivery_method, 'is_ready': bool(shipment.delivery_method)},
        {'label': 'Плановое получение', 'value': shipment.planned_receipt_at, 'is_ready': bool(shipment.planned_receipt_at)},
        {'label': 'Плательщик доставки', 'value': shipment.delivery_payer, 'is_ready': bool(shipment.delivery_payer)},
    ]


def shipment_missing_fields(shipment):
    return [entry['label'] for entry in shipment_checklist(shipment) if not entry['is_ready']]


def _deal_linked_document(deal):
    return (
        deal.contract_documents.exclude(status=ContractDocument.STATUS_ARCHIVED)
        .order_by(
            models.Case(
                models.When(document_type=ContractTemplate.DOC_TYPE_INVOICE, then=models.Value(0)),
                models.When(document_type=ContractTemplate.DOC_TYPE_CONTRACT, then=models.Value(1)),
                default=models.Value(2),
                output_field=models.IntegerField(),
            ),
            '-issue_date',
            '-id',
        )
        .first()
    )


def finance_case_expense_hints(deal):
    hints = []
    if deal.order.delivery_cost > 0 and deal.delivery_payer in {
        ManagerDeal.DELIVERY_PAYER_SELLER,
        ManagerDeal.DELIVERY_PAYER_INCLUDED,
    }:
        hints.append('Проверь расход на доставку')
    if deal.avito_commission > 0:
        hints.append('Проверь комиссию Avito')
    if deal.order.payment_status != Order.PAYMENT_STATUS_PAID:
        hints.append('Контроль оплаты до закрытия кейса')
    if deal.expected_margin <= 0:
        hints.append('Маржа не положительная, проверь себестоимость и скидки')
    return hints


def build_finance_case_snapshot(deal, *, linked_document=None):
    linked_document = linked_document or _deal_linked_document(deal)
    return {
        'linked_order_id': deal.order_id,
        'linked_document_id': linked_document.id if linked_document else None,
        'buyer_type': deal.buyer_type,
        'customer_source': deal.customer_source,
        'goods_total': str(deal.goods_total),
        'delivery_cost': str(deal.order.delivery_cost),
        'expected_margin': str(deal.expected_margin),
        'payment_method': deal.order.payment_method,
        'payment_status': deal.order.payment_status,
        'delivery_method': deal.delivery_method,
        'delivery_payer': deal.delivery_payer,
        'expense_hints': finance_case_expense_hints(deal),
        'items': order_items_snapshot(deal.order),
    }


def finance_case_missing_fields(finance_deal):
    missing = []
    if not finance_deal.responsible_manager_id:
        missing.append('Ответственный менеджер')
    if not finance_deal.linked_document_id:
        missing.append('Связанный договор / счет')
    if not finance_deal.payment_method:
        missing.append('Способ оплаты')
    if not finance_deal.payment_state:
        missing.append('Платежный статус')
    if not finance_deal.snapshot_data.get('items'):
        missing.append('Позиции сделки')
    return missing


def reservation_prefill_lines_for_deal(deal, *, exclude_reservation=None):
    existing_reserved = defaultdict(int)
    reservation_items = ReservationItem.objects.filter(
        reservation__linked_order=deal.order,
        reservation__status__in=ACTIVE_RESERVATION_STATUSES,
        order_item__isnull=False,
    )
    if exclude_reservation is not None and exclude_reservation.pk:
        reservation_items = reservation_items.exclude(reservation=exclude_reservation)
    for item in reservation_items:
        existing_reserved[item.order_item_id] += item.quantity

    lines = []
    for order_item in deal.order.items.select_related('product', 'variant').all():
        if not order_item.product_id:
            continue
        reserved_quantity = existing_reserved.get(order_item.id, 0)
        missing_quantity = max(int(order_item.quantity or 0) - reserved_quantity, 0)
        if missing_quantity <= 0:
            continue
        lines.append(
            {
                'order_item': order_item,
                'product': order_item.product,
                'variant': order_item.variant,
                'product_name': order_item.resolved_product_name,
                'variant_name': order_item.resolved_variant_name,
                'ordered_quantity': int(order_item.quantity or 0),
                'reserved_quantity': reserved_quantity,
                'missing_quantity': missing_quantity,
                'is_on_request': bool(order_item.is_on_request),
            }
        )
    return lines


def autofill_reservation_items_from_deal(reservation, deal, *, author=None):
    created_items = []
    for line in reservation_prefill_lines_for_deal(deal, exclude_reservation=reservation):
        created_items.append(
            ReservationItem.objects.create(
                reservation=reservation,
                order_item=line['order_item'],
                product=line['product'],
                variant=line['variant'],
                quantity=line['missing_quantity'],
            )
        )
    effective_warehouse = reservation_effective_warehouse(reservation)
    if created_items and reservation.status in {Reservation.STATUS_ACTIVE, Reservation.STATUS_PARTIAL} and effective_warehouse:
        validate_reservation_availability(reservation, items=created_items)
        create_or_update_reservation_movements(
            reservation,
            movement_type=InventoryMovement.TYPE_RESERVE,
            author=author,
            comment=reservation.comments or 'Автоматическое заполнение позиций по сделке.',
            items=created_items,
        )
        sync_public_stock_for_warehouse(effective_warehouse)
    return created_items


def _manager_delivery_method_for_order(order):
    return {
        Order.DELIVERY_CDEK_PVZ: ManagerDeal.DELIVERY_CDEK_PVZ,
        Order.DELIVERY_CDEK_COURIER: ManagerDeal.DELIVERY_CDEK_COURIER,
        Order.DELIVERY_PICKUP: ManagerDeal.DELIVERY_PICKUP,
        Order.DELIVERY_CITY: ManagerDeal.DELIVERY_CITY,
        Order.DELIVERY_COURIER: ManagerDeal.DELIVERY_CITY,
        Order.DELIVERY_OTHER_TRANSPORT: ManagerDeal.DELIVERY_OTHER_TRANSPORT,
        Order.DELIVERY_POST: ManagerDeal.DELIVERY_OTHER_TRANSPORT,
        Order.DELIVERY_NEGOTIABLE: ManagerDeal.DELIVERY_OTHER_TRANSPORT,
    }.get(order.delivery_type, ManagerDeal.DELIVERY_CDEK_PVZ)


def _case_status_for_order(order):
    if order.status == Order.STATUS_CANCELLED:
        return ManagerDeal.CASE_STATUS_CANCELLED
    if order.status == Order.STATUS_DONE:
        return ManagerDeal.CASE_STATUS_COMPLETED
    if order.status in {Order.STATUS_SHIPPING, Order.STATUS_READY_FOR_PICKUP}:
        return ManagerDeal.CASE_STATUS_READY_TO_SHIP
    if order.status == Order.STATUS_CONFIRMED:
        return ManagerDeal.CASE_STATUS_CONFIRMED
    return ManagerDeal.CASE_STATUS_NEW


def _order_status_for_case_status(case_status):
    if case_status == ManagerDeal.CASE_STATUS_CANCELLED:
        return Order.STATUS_CANCELLED
    if case_status == ManagerDeal.CASE_STATUS_COMPLETED:
        return Order.STATUS_DONE
    if case_status in {
        ManagerDeal.CASE_STATUS_CONFIRMED,
        ManagerDeal.CASE_STATUS_IN_PROGRESS,
        ManagerDeal.CASE_STATUS_WAITING_CLIENT,
        ManagerDeal.CASE_STATUS_READY_TO_SHIP,
    }:
        return Order.STATUS_CONFIRMED
    return Order.STATUS_NEW


def _payment_state_for_deal(deal):
    if deal.order.payment_status == Order.PAYMENT_STATUS_PAID:
        return ManagerDeal.PAYMENT_STATE_PAID
    if deal.order.payment_status == Order.PAYMENT_STATUS_REFUNDED:
        return ManagerDeal.PAYMENT_STATE_REFUNDED
    if Decimal(deal.prepayment_amount or 0) > 0:
        return ManagerDeal.PAYMENT_STATE_PARTIAL
    return ManagerDeal.PAYMENT_STATE_UNPAID


def _inventory_totals_map():
    totals = defaultdict(int)
    for row in inventory_snapshot():
        totals[(row['product_id'], row['variant_id'] or 0)] += int(row['available'] or 0)
    return totals


def _deal_requires_documents(deal):
    return deal.requires_documents


def _deal_documents_status(deal):
    if not _deal_requires_documents(deal):
        return ManagerDeal.DOCUMENTS_STATUS_NOT_REQUIRED
    documents = deal.contract_documents.exclude(status=ContractDocument.STATUS_ARCHIVED).order_by('-issue_date', '-id')
    if not documents.exists():
        return ManagerDeal.DOCUMENTS_STATUS_DRAFT
    if documents.filter(status__in=[ContractDocument.STATUS_SIGNED, ContractDocument.STATUS_PAID]).exists():
        return ManagerDeal.DOCUMENTS_STATUS_SIGNED
    if documents.filter(status__in=[ContractDocument.STATUS_SENT, ContractDocument.STATUS_REVIEW]).exists():
        return ManagerDeal.DOCUMENTS_STATUS_SENT
    return ManagerDeal.DOCUMENTS_STATUS_DRAFT


def _deal_primary_reservation(deal):
    reservation = deal.primary_reservation
    if reservation and reservation.status in ACTIVE_RESERVATION_STATUSES:
        return reservation
    reservation = (
        deal.reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES)
        .select_related('source_warehouse', 'source_cargo__destination_warehouse', 'target_warehouse')
        .order_by('id')
        .first()
    )
    return reservation


def _deal_fulfillment_status(deal):
    reservation = _deal_primary_reservation(deal)
    if reservation and deal.primary_reservation_id != reservation.id:
        deal.primary_reservation = reservation
        deal.save(update_fields=['primary_reservation', 'updated_at'])
    if deal.order.status in {Order.STATUS_SHIPPING, Order.STATUS_DONE} and reservation:
        return ManagerDeal.FULFILLMENT_STATUS_FULFILLED
    if reservation:
        if reservation.source_type == Reservation.SOURCE_CARGO:
            return ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING
        return ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK
    if deal.order.items.filter(is_on_request=True).exists():
        linked_purchase_items = PurchaseItem.objects.filter(order_item__order=deal.order)
        if not linked_purchase_items.exists() or linked_purchase_items.filter(received_quantity__lt=models.F('quantity')).exists():
            return ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED
    return ManagerDeal.FULFILLMENT_STATUS_NOT_RESERVED


def _deal_delivery_required(deal):
    return deal.requires_delivery_workflow


def _deal_delivery_status(deal):
    shipments = deal.shipments.exclude(status=Shipment.STATUS_CANCELLED)
    if not _deal_delivery_required(deal) and not shipments.exists():
        return ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED
    if deal.order.status == Order.STATUS_DONE or shipments.filter(status=Shipment.STATUS_DELIVERED).exists():
        return ManagerDeal.DELIVERY_STATUS_DELIVERED
    if deal.order.status == Order.STATUS_SHIPPING or shipments.filter(status=Shipment.STATUS_SHIPPED).exists():
        return ManagerDeal.DELIVERY_STATUS_SHIPPED
    if shipments.exists():
        return ManagerDeal.DELIVERY_STATUS_PREPARING
    if _deal_delivery_required(deal):
        return ManagerDeal.DELIVERY_STATUS_READY
    return ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED


def _deal_stock_conflict(deal):
    if deal.order.items.filter(is_on_request=True).exists():
        return False
    if _deal_primary_reservation(deal):
        return False
    inventory_totals = _inventory_totals_map()
    for item in deal.order.items.select_related('product', 'variant'):
        if not item.product_id:
            continue
        available = inventory_totals.get((item.product_id, item.variant_id or 0), 0)
        if available < item.quantity:
            return True
    return False


def _deal_has_reachable_contacts(deal):
    if deal.buyer_type == ManagerDeal.BUYER_BUSINESS:
        contact_values = [
            deal.business_phone,
            deal.business_email,
            deal.order.phone,
            deal.order.email,
        ]
    else:
        contact_values = [
            deal.individual_phone,
            deal.order.phone,
            deal.order.email,
            deal.individual_messenger,
        ]
    return any((value or '').strip() for value in contact_values)


def _deal_latest_document(deal):
    return _deal_linked_document(deal)


def _deal_document_needs_preparation(deal):
    if not _deal_requires_documents(deal):
        return False
    document = _deal_latest_document(deal)
    if document is None:
        return True
    return bool(contract_document_missing_fields(document))


def _deal_document_ready_for_dispatch(deal):
    if not _deal_requires_documents(deal):
        return False
    document = _deal_latest_document(deal)
    if document is None:
        return False
    if contract_document_missing_fields(document):
        return False
    return document.status not in {
        ContractDocument.STATUS_SENT,
        ContractDocument.STATUS_SIGNED,
        ContractDocument.STATUS_PAID,
    }


def _deal_can_confirm_availability(deal):
    if deal.deal_type != ManagerDeal.DEAL_SALE_FROM_STOCK:
        return False
    if deal.stock_warehouse_id or _deal_primary_reservation(deal):
        return False
    inventory_totals = _inventory_totals_map()
    has_catalog_items = False
    for item in deal.order.items.select_related('product', 'variant'):
        if item.is_on_request or not item.product_id:
            continue
        has_catalog_items = True
        available = inventory_totals.get((item.product_id, item.variant_id or 0), 0)
        if available < item.quantity:
            return False
    return has_catalog_items


def _compute_next_step_for_deal(deal, *, case_status, payment_state, fulfillment_status, delivery_status, documents_status):
    if deal.avito_return_pending:
        return ManagerDeal.NEXT_STEP_RETURN_TO_STOCK, 'По сделке оформлен возврат. Заберите товар у Avito и верните его на склад.'
    if case_status in {ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED} or deal.order.status == Order.STATUS_DONE:
        return ManagerDeal.NEXT_STEP_COMPLETED, 'Заказ завершен.'
    if delivery_status in {ManagerDeal.DELIVERY_STATUS_SHIPPED, ManagerDeal.DELIVERY_STATUS_DELIVERED} or deal.order.status == Order.STATUS_SHIPPING:
        return ManagerDeal.NEXT_STEP_SHIPPED, 'Заказ уже отправлен и находится в доставке.'
    if case_status == ManagerDeal.CASE_STATUS_NEW or deal.order.status == Order.STATUS_NEW:
        return ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION, 'Новый заказ без подтверждения менеджером.'
    if fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED:
        return ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT, 'Товара нет в доступном остатке, требуется закупка.'
    if _deal_can_confirm_availability(deal):
        return ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION, 'Нужно подтвердить доступный склад и наличие до создания брони.'
    if _deal_document_needs_preparation(deal):
        return ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS, 'Для сделки нужен документ, но он еще не готов к отправке клиенту.'
    if _deal_document_ready_for_dispatch(deal):
        return ManagerDeal.NEXT_STEP_NEEDS_DOCUMENT_DISPATCH, 'Документы готовы. Отправьте клиенту договорный пакет.'
    if payment_state in {ManagerDeal.PAYMENT_STATE_UNPAID, ManagerDeal.PAYMENT_STATE_PARTIAL}:
        return ManagerDeal.NEXT_STEP_NEEDS_PAYMENT, 'Оплата не закрыта полностью.'
    if fulfillment_status == ManagerDeal.FULFILLMENT_STATUS_NOT_RESERVED:
        return ManagerDeal.NEXT_STEP_NEEDS_RESERVATION, 'Склад подтвержден, но резерв по позициям еще не создан.'
    return ManagerDeal.NEXT_STEP_READY_TO_SHIP, 'Заказ готов к подготовке отправления.'


def _problem_flags_for_deal(*, deal, documents_status, next_step_code, sla_due_at, payment_state):
    flags = []
    if not deal.responsible_manager_id:
        flags.append(ManagerDeal.PROBLEM_FLAG_NO_ASSIGNEE)
    if not _deal_has_reachable_contacts(deal):
        flags.append(ManagerDeal.PROBLEM_FLAG_MISSING_CONTACTS)
    if _deal_stock_conflict(deal):
        flags.append(ManagerDeal.PROBLEM_FLAG_STOCK_CONFLICT)
    if _deal_document_needs_preparation(deal):
        flags.append(ManagerDeal.PROBLEM_FLAG_MISSING_DOCUMENTS)
    if payment_state in {
        ManagerDeal.PAYMENT_STATE_UNPAID,
        ManagerDeal.PAYMENT_STATE_PARTIAL,
    } and deal.case_status not in {
        ManagerDeal.CASE_STATUS_COMPLETED,
        ManagerDeal.CASE_STATUS_CANCELLED,
    }:
        flags.append(ManagerDeal.PROBLEM_FLAG_MISSING_PAYMENT)
    if sla_due_at and manager_portal_now() > _portal_localize(sla_due_at):
        flags.append(ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE)
    last_activity_at = deal.last_activity_at or deal.created_at
    if last_activity_at and deal.case_status not in {
        ManagerDeal.CASE_STATUS_COMPLETED,
        ManagerDeal.CASE_STATUS_CANCELLED,
    } and timezone.now() - last_activity_at >= manager_portal_stale_after():
        flags.append(ManagerDeal.PROBLEM_FLAG_STALE_UPDATES)
    return flags


def sync_child_entities_to_manager_deal(deal):
    if deal is None:
        return
    Reservation.objects.filter(linked_order=deal.order, manager_deal__isnull=True).update(manager_deal=deal)
    Shipment.objects.filter(order=deal.order, manager_deal__isnull=True).update(manager_deal=deal)
    ContractDocument.objects.filter(linked_order=deal.order, manager_deal__isnull=True).update(manager_deal=deal)
    FinanceExpense.objects.filter(deal__manager_deal=deal, manager_deal__isnull=True).update(manager_deal=deal)
    try:
        finance_deal = deal.finance_deal
    except FinanceDeal.DoesNotExist:
        finance_deal = None
    if finance_deal is not None:
        FinanceExpense.objects.filter(deal=finance_deal, manager_deal__isnull=True).update(manager_deal=deal)


def recompute_deal_workflow(deal, *, actor=None):
    if deal is None:
        return None
    sync_child_entities_to_manager_deal(deal)
    changed = {}
    old_values = {
        'payment_state': deal.payment_state,
        'fulfillment_status': deal.fulfillment_status,
        'delivery_status': deal.delivery_status,
        'documents_status': deal.documents_status,
        'next_step_code': deal.next_step_code,
        'next_step_reason_snapshot': deal.next_step_reason_snapshot,
        'next_step_source': deal.next_step_source,
        'sla_due_at': deal.sla_due_at,
        'sla_breached_at': deal.sla_breached_at,
        'problem_flags': list(deal.problem_flags or []),
        'case_status': deal.case_status,
    }

    if deal.case_status in MANUAL_EDITABLE_CASE_STATUSES:
        suggested_case_status = _case_status_for_order(deal.order)
        if deal.case_status == ManagerDeal.CASE_STATUS_NEW and suggested_case_status != ManagerDeal.CASE_STATUS_NEW:
            changed['case_status'] = suggested_case_status
    elif deal.case_status not in {ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED}:
        changed['case_status'] = _case_status_for_order(deal.order)
    elif deal.order.status == Order.STATUS_CANCELLED and deal.case_status != ManagerDeal.CASE_STATUS_CANCELLED:
        changed['case_status'] = ManagerDeal.CASE_STATUS_CANCELLED
    elif deal.order.status == Order.STATUS_DONE and deal.case_status != ManagerDeal.CASE_STATUS_COMPLETED:
        changed['case_status'] = ManagerDeal.CASE_STATUS_COMPLETED

    payment_state = _payment_state_for_deal(deal)
    fulfillment_status = _deal_fulfillment_status(deal)
    documents_status = _deal_documents_status(deal)
    delivery_status = _deal_delivery_status(deal)

    changed['payment_state'] = payment_state
    changed['fulfillment_status'] = fulfillment_status
    changed['documents_status'] = documents_status
    changed['delivery_status'] = delivery_status

    computed_next_step_code, computed_reason = _compute_next_step_for_deal(
        deal,
        case_status=changed.get('case_status', deal.case_status),
        payment_state=payment_state,
        fulfillment_status=fulfillment_status,
        delivery_status=delivery_status,
        documents_status=documents_status,
    )
    effective_next_step_code = computed_next_step_code
    effective_reason = computed_reason
    next_step_source = deal.next_step_source
    if deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL and deal.next_step_code:
        effective_next_step_code = deal.next_step_code
        effective_reason = deal.next_step_reason_snapshot
        next_step_source = ManagerDeal.NEXT_STEP_SOURCE_MANUAL
    else:
        next_step_source = ManagerDeal.NEXT_STEP_SOURCE_SYSTEM

    changed['next_step_source'] = next_step_source
    changed['next_step_code'] = effective_next_step_code
    changed['next_step_reason_snapshot'] = effective_reason or ''

    sla_due_at = compute_deal_sla_due_at(deal=deal, next_step_code=effective_next_step_code)
    changed['sla_due_at'] = sla_due_at
    problem_flags = _problem_flags_for_deal(
        deal=deal,
        documents_status=documents_status,
        next_step_code=effective_next_step_code,
        sla_due_at=sla_due_at,
        payment_state=payment_state,
    )
    changed['problem_flags'] = problem_flags
    if ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE in problem_flags:
        changed['sla_breached_at'] = deal.sla_breached_at or timezone.now()
    else:
        changed['sla_breached_at'] = None
    if deal.last_activity_at is None:
        changed['last_activity_at'] = deal.created_at
    update_fields = []
    for field_name, new_value in changed.items():
        current_value = getattr(deal, field_name)
        if current_value != new_value:
            setattr(deal, field_name, new_value)
            update_fields.append(field_name)
    legacy_status = _website_deal_status_for_order(
        deal.order,
        deal_type=deal.deal_type,
        customer_source=deal.customer_source,
    )
    if deal.deal_status != legacy_status:
        deal.deal_status = legacy_status
        update_fields.append('deal_status')
    if update_fields:
        update_fields.append('updated_at')
        deal.save(update_fields=update_fields)
        diff_payload = {}
        for field_name in (
            'case_status',
            'payment_state',
            'fulfillment_status',
            'delivery_status',
            'documents_status',
            'next_step_code',
            'problem_flags',
            'sla_due_at',
        ):
            if old_values.get(field_name) != getattr(deal, field_name):
                diff_payload[field_name] = {
                    'old': old_values.get(field_name),
                    'new': getattr(deal, field_name),
                }
        if diff_payload:
            record_deal_activity(
                deal,
                event_type='workflow.recomputed',
                source=DealActivity.SOURCE_SYSTEM,
                actor=actor,
                payload=diff_payload,
            )
    return deal


def _hydrate_finance_deal_from_manager_deal(finance_deal, deal, *, actor=None):
    linked_document = _deal_linked_document(deal)
    snapshot_data = build_finance_case_snapshot(deal, linked_document=linked_document)
    finance_type = finance_deal.deal_type if finance_deal.deal_type_id else None
    if finance_type is None:
        finance_type = FinanceDealType.objects.filter(is_active=True).order_by('name', 'id').first()
    update_fields = []
    updates = {
        'manager_deal': deal,
        'responsible_manager': deal.responsible_manager or actor,
        'linked_document': linked_document,
        'date': (deal.order.created_at or timezone.now()).date(),
        'deal_type': finance_type,
        'payment_method': deal.order.payment_method,
        'payment_state': deal.order.payment_status,
        'revenue': deal.grand_total,
        'cost_price': deal.outgoing_cost_total,
        'expected_margin_snapshot': deal.expected_margin,
        'snapshot_data': snapshot_data,
        'comment': finance_deal.comment or 'Подготовлено из карточки сделки.',
    }
    contract_number = ''
    if linked_document is not None:
        contract_number = linked_document.number or linked_document.title or ''
    if not contract_number:
        contract_number = deal_manager_client(deal).name if deal_manager_client(deal) else f'Сделка #{deal.order_id}'
    updates['contract_number'] = contract_number
    relation_fields = {'manager_deal', 'responsible_manager', 'linked_document', 'deal_type'}
    for field_name, value in updates.items():
        current_value = getattr(finance_deal, f'{field_name}_id') if field_name in relation_fields else getattr(finance_deal, field_name)
        expected_value = value.pk if field_name in relation_fields and value is not None else value
        if current_value != expected_value:
            setattr(finance_deal, field_name, value)
            update_fields.append(field_name)
    if update_fields and finance_deal.pk:
        finance_deal.save(update_fields=update_fields + ['updated_at'])
    return finance_deal


def prefill_finance_deal_from_manager_deal(finance_deal, deal, *, actor=None):
    return _hydrate_finance_deal_from_manager_deal(finance_deal, deal, actor=actor)


def ensure_finance_deal_for_manager_deal(deal, *, actor=None):
    try:
        finance_deal = deal.finance_deal
    except FinanceDeal.DoesNotExist:
        finance_deal = None
    if finance_deal:
        finance_deal = _hydrate_finance_deal_from_manager_deal(finance_deal, deal, actor=actor)
        return finance_deal
    finance_type = FinanceDealType.objects.filter(is_active=True).order_by('name', 'id').first()
    if finance_type is None:
        finance_type = FinanceDealType.objects.create(name='Операционная сделка', partner_share=Decimal('0'))
    finance_deal = FinanceDeal.objects.create(
        manager_deal=deal,
        responsible_manager=deal.responsible_manager or actor,
        linked_document=_deal_linked_document(deal),
        date=(deal.order.created_at or timezone.now()).date(),
        contract_number='',
        deal_type=finance_type,
        payment_method=deal.order.payment_method,
        payment_state=deal.order.payment_status,
        revenue=deal.grand_total,
        cost_price=deal.outgoing_cost_total,
        expected_margin_snapshot=deal.expected_margin,
        snapshot_data=build_finance_case_snapshot(deal),
        comment='Создано из карточки сделки.',
        created_by=actor,
    )
    finance_deal = _hydrate_finance_deal_from_manager_deal(finance_deal, deal, actor=actor)
    record_deal_activity(
        deal,
        event_type='finance.created',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={'finance_deal_id': finance_deal.id},
    )
    recompute_deal_workflow(deal, actor=actor)
    return finance_deal


def ensure_reservations_for_manager_deal(deal, *, actor=None):
    active_reservations = list(
        deal.reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES)
        .select_related('source_warehouse', 'target_warehouse', 'client')
        .order_by('id')
    )
    coverage = reservation_coverage_snapshot(deal.order)
    if active_reservations and coverage['is_complete']:
        primary = _deal_primary_reservation(deal) or active_reservations[0]
        if primary and deal.primary_reservation_id != primary.id:
            deal.primary_reservation = primary
            deal.save(update_fields=['primary_reservation', 'updated_at'])
        return {
            'reservations': active_reservations,
            'primary': primary,
            'created': False,
            'split': len(active_reservations) > 1,
            'client_resolution': None,
            'coverage': coverage,
        }

    client_resolution = ensure_manager_client_for_order(deal.order)
    created_reservations = ensure_order_reservations(
        deal.order,
        client_resolution['client'],
        warehouse=deal.stock_warehouse,
        author=actor,
        strict=True,
        comment='Автоматический резерв по сделке.',
    )
    active_reservations = list(
        deal.reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES)
        .select_related('source_warehouse', 'target_warehouse', 'client')
        .order_by('id')
    )
    if not active_reservations:
        raise ValueError('Не удалось подготовить резерв по строкам заказа. Проверьте остатки и склад-источник.')

    unique_warehouse_ids = {
        reservation.source_warehouse_id for reservation in active_reservations if reservation.source_warehouse_id
    }
    update_fields = []
    primary = _deal_primary_reservation(deal) or active_reservations[0]
    if primary and deal.primary_reservation_id != primary.id:
        deal.primary_reservation = primary
        update_fields.append('primary_reservation')
    if created_reservations and deal.reserve_created_at is None:
        deal.reserve_created_at = timezone.now()
        update_fields.append('reserve_created_at')
    if len(unique_warehouse_ids) == 1:
        warehouse_id = next(iter(unique_warehouse_ids))
        if deal.stock_warehouse_id != warehouse_id:
            deal.stock_warehouse_id = warehouse_id
            update_fields.append('stock_warehouse')
    if update_fields:
        deal.save(update_fields=update_fields + ['updated_at'])

    if created_reservations:
        record_deal_activity(
            deal,
            event_type='reservation.created',
            source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
            actor=actor,
            payload={
                'reservation_ids': [reservation.id for reservation in created_reservations],
                'split': len(active_reservations) > 1,
            },
        )
    recompute_deal_workflow(deal, actor=actor)
    return {
        'reservations': active_reservations,
        'primary': primary,
        'created': bool(created_reservations),
        'split': len(active_reservations) > 1,
        'client_resolution': client_resolution,
        'coverage': reservation_coverage_snapshot(deal.order),
    }


def ensure_primary_reservation_for_manager_deal(deal, *, actor=None):
    result = ensure_reservations_for_manager_deal(deal, actor=actor)
    return result['primary']


def ensure_shipment_for_manager_deal(deal, *, actor=None):
    shipments = list(deal.shipments.exclude(status=Shipment.STATUS_CANCELLED).order_by('id'))
    if shipments:
        if len(shipments) == 1:
            return create_or_update_shipment_for_order(shipments[0].order, author=actor, shipment=shipments[0])
        return shipments
    reservation = None
    try:
        reservation_result = ensure_reservations_for_manager_deal(deal, actor=actor)
        if len(reservation_result['reservations']) == 1:
            reservation = reservation_result['primary']
    except ValueError:
        reservation = _deal_primary_reservation(deal)
    shipment = create_or_update_shipment_for_order(deal.order, author=actor, reservation=reservation)
    if shipment.manager_deal_id != deal.id:
        shipment.manager_deal = deal
        shipment.save(update_fields=['manager_deal', 'updated_at'])
    record_deal_activity(
        deal,
        event_type='shipment.created',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={'shipment_id': shipment.id},
    )
    recompute_deal_workflow(deal, actor=actor)
    return shipment


def restore_avito_return_to_stock(deal, *, actor=None):
    if deal is None or not deal.is_avito:
        raise ValueError('Возврат на склад доступен только для сделок Avito.')
    if deal.deal_status != ManagerDeal.DEAL_STATUS_RETURNED:
        raise ValueError('Вернуть товар на склад можно только после перевода сделки в этап "Возврат".')
    if deal.returned_to_stock_at is not None:
        raise ValueError('Возврат на склад по этой сделке уже подтвержден.')

    reservations = list(
        Reservation.objects.filter(linked_order=deal.order)
        .select_related('source_warehouse', 'source_cargo__destination_warehouse')
        .prefetch_related('items__product', 'items__variant')
        .order_by('id')
    )
    restored_positions = []
    released_reservations = []
    receipt_total = 0

    with transaction.atomic():
        for reservation in reservations:
            warehouse = reservation_effective_warehouse(reservation) or deal.stock_warehouse
            if reservation.status in ACTIVE_RESERVATION_STATUSES:
                create_or_update_reservation_movements(
                    reservation,
                    movement_type=InventoryMovement.TYPE_RELEASE,
                    author=actor,
                    comment='Снятие резерва после возврата Avito.',
                )
                reservation.status = Reservation.STATUS_CANCELLED
                reservation.save(update_fields=['status', 'updated_at'])
                if warehouse is not None:
                    sync_public_stock_for_warehouse(warehouse)
                released_reservations.append(reservation.id)
                continue
            if reservation.status != Reservation.STATUS_FULFILLED:
                continue
            if warehouse is None:
                raise ValueError('Не удалось определить склад для возврата товара.')
            for item in reservation.items.select_related('product', 'variant'):
                receipt_inventory(
                    warehouse=warehouse,
                    product=item.product,
                    variant=item.variant,
                    quantity=item.quantity,
                    author=actor,
                    comment='Возврат по Avito-сделке.',
                    reference_type='avito_return',
                    reference_id=deal.pk,
                )
                restored_positions.append(
                    {
                        'product_id': item.product_id,
                        'variant_id': item.variant_id,
                        'quantity': item.quantity,
                        'warehouse_id': warehouse.id,
                    }
                )
                receipt_total += item.quantity

        if not reservations:
            warehouse = deal.stock_warehouse
            if warehouse is None:
                raise ValueError('Для возврата без резерва сначала укажите склад в сделке.')
            for order_item in deal.order.items.select_related('product', 'variant'):
                if not order_item.product_id:
                    continue
                receipt_inventory(
                    warehouse=warehouse,
                    product=order_item.product,
                    variant=order_item.variant,
                    quantity=order_item.quantity,
                    author=actor,
                    comment='Возврат по Avito-сделке.',
                    reference_type='avito_return',
                    reference_id=deal.pk,
                )
                restored_positions.append(
                    {
                        'product_id': order_item.product_id,
                        'variant_id': order_item.variant_id,
                        'quantity': order_item.quantity,
                        'warehouse_id': warehouse.id,
                    }
                )
                receipt_total += order_item.quantity

        if not released_reservations and receipt_total <= 0:
            raise ValueError('Не найдено складских движений для возврата по этой сделке.')

        deal.returned_to_stock_at = timezone.now()
        update_fields = ['returned_to_stock_at']
        if deal.primary_reservation_id and deal.primary_reservation.status not in ACTIVE_RESERVATION_STATUSES:
            deal.primary_reservation = None
            update_fields.append('primary_reservation')
        deal.save(update_fields=update_fields + ['updated_at'])

    record_deal_activity(
        deal,
        event_type='inventory.returned_to_stock',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'released_reservation_ids': released_reservations,
            'receipts_total': receipt_total,
            'positions': restored_positions,
        },
    )
    recompute_deal_workflow(deal, actor=actor)
    return {
        'released_reservation_ids': released_reservations,
        'receipts_total': receipt_total,
        'positions': restored_positions,
    }


def _document_counterparty_snapshot(*, deal, client):
    if deal.buyer_type == ManagerDeal.BUYER_BUSINESS:
        return {
            'name': deal.business_company_name or (client.name if client else '') or deal.customer_name,
            'email': deal.business_email or (client.email if client else ''),
            'phone': deal.business_phone or (client.phone if client else ''),
            'telegram': deal.business_telegram or (client.telegram if client else ''),
            'whatsapp': deal.business_whatsapp,
            'inn': deal.business_inn,
            'kpp': deal.business_kpp,
            'ogrn': deal.business_ogrn,
            'ogrnip': '',
            'address': deal.business_legal_address or deal.business_delivery_address or (client.address if client else ''),
            'checking_account': deal.business_checking_account,
            'bank_name': deal.business_bank_name,
            'bik': deal.business_bik,
            'correspondent_account': deal.business_correspondent_account,
        }
    return {
        'name': (client.name if client else '') or deal.customer_name,
        'email': (client.email if client else '') or deal.order.email,
        'phone': (client.phone if client else '') or deal.customer_phone,
        'inn': '',
        'kpp': '',
        'ogrn': '',
        'ogrnip': '',
        'address': deal.delivery_full_address or deal.delivery_pickup_address or (client.address if client else ''),
    }


def _hydrate_contract_document_from_manager_deal(document, deal, *, actor=None, document_type=None):
    client = deal_manager_client(deal) or ensure_manager_client_for_order(deal.order)['client']
    counterparty = _document_counterparty_snapshot(deal=deal, client=client)
    target_document_type = document_type or document.document_type
    template = None
    if (
        document.template_id
        and document.template is not None
        and document.template.is_active
        and document.template.document_type == target_document_type
    ):
        template = document.template
    if template is None:
        template = ContractTemplate.objects.filter(
            document_type=target_document_type,
            is_active=True,
        ).order_by('sort_order', 'name').first()
    company_profile = ContractCompanyProfile.objects.filter(is_active=True).order_by('-updated_at', '-id').first()
    snapshot_items = order_items_snapshot(deal.order)
    snapshot_data = {
        'manager_deal_id': deal.id,
        'linked_order_id': deal.order_id,
        'buyer_type': deal.buyer_type,
        'customer_source': deal.customer_source,
        'manager': {
            'id': deal.responsible_manager_id,
            'username': deal.responsible_manager.get_username() if deal.responsible_manager_id else '',
        },
        'delivery': {
            'method': deal.delivery_method,
            'payer': deal.delivery_payer,
            'to_city': deal.delivery_to_city,
            'address': deal.delivery_full_address or deal.delivery_pickup_address,
            'planned_receipt_at': str(deal.planned_receipt_at or ''),
        },
        'payment': {
            'method': deal.order.payment_method,
            'status': deal.order.payment_status,
            'amount': str(deal.grand_total),
            'payment_terms': 0 if deal.order.payment_status == Order.PAYMENT_STATUS_PAID else 5,
        },
        'positions': snapshot_items,
    }
    invoice_data = {
        'items': snapshot_items,
        'delivery_cost': str(deal.order.delivery_cost),
        'grand_total': str(deal.grand_total),
    }
    updates = {
        'manager_deal': deal,
        'linked_order': deal.order,
        'manager_client': client,
        'responsible_manager': deal.responsible_manager or actor,
        'created_by': document.created_by or actor,
        'document_type': target_document_type,
        'template': template or document.template,
        'company_profile': company_profile or document.company_profile,
        'issue_date': document.issue_date or timezone.localdate(),
        'amount': deal.grand_total,
        'payment_terms': 0 if deal.order.payment_status == Order.PAYMENT_STATUS_PAID else 5,
        'include_delivery': bool(deal.order.delivery_cost > 0),
        'delivery_date': deal.expected_customer_ship_date or deal.planned_receipt_at,
        'subject': deal.customer_request or f'Поставка товаров по заказу #{deal.order_id}',
        'counterparty_name': counterparty['name'],
        'counterparty_email': counterparty['email'],
        'counterparty_phone': counterparty['phone'],
        'counterparty_inn': counterparty['inn'],
        'counterparty_kpp': counterparty['kpp'],
        'counterparty_ogrn': counterparty['ogrn'],
        'counterparty_ogrnip': counterparty['ogrnip'],
        'counterparty_address': counterparty['address'],
        'counterparty_data': counterparty,
        'document_data': snapshot_data,
        'invoice_data': invoice_data,
        'notes': document.notes or 'Подготовлено из карточки сделки.',
    }
    update_fields = []
    relation_fields = {
        'manager_deal',
        'linked_order',
        'manager_client',
        'responsible_manager',
        'created_by',
        'template',
        'company_profile',
    }
    for field_name, value in updates.items():
        current_value = getattr(document, f'{field_name}_id') if field_name in relation_fields else getattr(document, field_name)
        expected_value = value.pk if field_name in relation_fields and value is not None else value
        if current_value != expected_value:
            setattr(document, field_name, value)
            update_fields.append(field_name)
    if update_fields and document.pk:
        document.save(update_fields=update_fields + ['updated_at'])
    return document


def prefill_contract_document_from_manager_deal(document, deal, *, actor=None, document_type=None):
    return _hydrate_contract_document_from_manager_deal(document, deal, actor=actor, document_type=document_type)


def ensure_current_document_for_manager_deal(deal, *, document_type, actor=None):
    document = (
        deal.contract_documents.filter(document_type=document_type)
        .exclude(status=ContractDocument.STATUS_ARCHIVED)
        .order_by('-issue_date', '-id')
        .first()
    )
    if document:
        document = _hydrate_contract_document_from_manager_deal(document, deal, actor=actor, document_type=document_type)
        return document
    client = deal_manager_client(deal)
    document = ContractDocument.objects.create(
        manager_deal=deal,
        linked_order=deal.order,
        manager_client=client,
        responsible_manager=deal.responsible_manager or actor,
        created_by=actor,
        document_type=document_type,
        status=ContractDocument.STATUS_DRAFT,
        title=f'{dict(ContractTemplate.DOCUMENT_TYPE_CHOICES).get(document_type, "Документ")} по сделке #{deal.order_id}',
    )
    document = _hydrate_contract_document_from_manager_deal(document, deal, actor=actor, document_type=document_type)
    record_deal_activity(
        deal,
        event_type='document.created',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={'document_id': document.id, 'document_type': document_type},
    )
    recompute_deal_workflow(deal, actor=actor)
    return document


def apply_deal_case_status_change(deal, *, case_status, actor=None):
    changed_fields = []
    if deal.case_status != case_status:
        deal.case_status = case_status
        changed_fields.append('case_status')
    mapped_order_status = _order_status_for_case_status(case_status)
    if deal.order.status != mapped_order_status:
        deal.order.status = mapped_order_status
        deal.order.save(update_fields=['status', 'updated_at'])
    if changed_fields:
        changed_fields.append('updated_at')
        deal.save(update_fields=changed_fields)
        record_deal_activity(
            deal,
            event_type='case_status.changed',
            source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
            actor=actor,
            payload={'case_status': case_status},
        )
    recompute_deal_workflow(deal, actor=actor)
    return deal


def apply_deal_assignment(deal, *, responsible_manager, actor=None):
    update_fields = []
    if deal.responsible_manager_id != getattr(responsible_manager, 'id', None):
        deal.responsible_manager = responsible_manager
        update_fields.append('responsible_manager')
        deal.assigned_at = timezone.now() if responsible_manager else None
        deal.assigned_by = actor if responsible_manager else None
        update_fields.extend(['assigned_at', 'assigned_by'])
    if update_fields:
        update_fields.append('updated_at')
        deal.save(update_fields=update_fields)
        record_deal_activity(
            deal,
            event_type='assignment.changed',
            source=DealActivity.SOURCE_USER,
            actor=actor,
            payload={'responsible_manager_id': deal.responsible_manager_id},
        )
    recompute_deal_workflow(deal, actor=actor)
    return deal


def apply_deal_next_step_override(deal, *, next_step_code, reason, actor=None):
    deal.next_step_code = next_step_code
    deal.next_step_reason_snapshot = reason or ''
    deal.next_step_source = ManagerDeal.NEXT_STEP_SOURCE_MANUAL
    deal.next_step_overridden_at = timezone.now()
    deal.next_step_overridden_by = actor
    deal.save(
        update_fields=[
            'next_step_code',
            'next_step_reason_snapshot',
            'next_step_source',
            'next_step_overridden_at',
            'next_step_overridden_by',
            'updated_at',
        ]
    )
    record_deal_activity(
        deal,
        event_type='next_step.overridden',
        source=DealActivity.SOURCE_USER,
        actor=actor,
        payload={'next_step_code': next_step_code, 'reason': reason or ''},
    )
    recompute_deal_workflow(deal, actor=actor)
    return deal


def clear_deal_next_step_override(deal, *, actor=None):
    deal.next_step_source = ManagerDeal.NEXT_STEP_SOURCE_SYSTEM
    deal.next_step_overridden_at = None
    deal.next_step_overridden_by = None
    deal.save(
        update_fields=[
            'next_step_source',
            'next_step_overridden_at',
            'next_step_overridden_by',
            'updated_at',
        ]
    )
    record_deal_activity(
        deal,
        event_type='next_step.override_cleared',
        source=DealActivity.SOURCE_USER,
        actor=actor,
    )
    recompute_deal_workflow(deal, actor=actor)
    return deal


def deal_search_groups(query):
    query = (query or '').strip()
    if len(query) < 2 and not query.isdigit():
        return []
    order_query = (
        models.Q(order__phone__icontains=query)
        | models.Q(order__email__icontains=query)
        | models.Q(order__first_name__icontains=query)
        | models.Q(order__last_name__icontains=query)
        | models.Q(individual_full_name__icontains=query)
        | models.Q(individual_phone__icontains=query)
        | models.Q(individual_additional_phone__icontains=query)
        | models.Q(individual_messenger__icontains=query)
        | models.Q(business_company_name__icontains=query)
        | models.Q(business_contact_person__icontains=query)
        | models.Q(business_phone__icontains=query)
        | models.Q(business_email__icontains=query)
        | models.Q(customer_request__icontains=query)
        | models.Q(tracking_number__icontains=query)
        | models.Q(next_step_reason_snapshot__icontains=query)
        | models.Q(order__items__product__sku__icontains=query)
        | models.Q(order__items__variant__sku__icontains=query)
        | models.Q(order__items__product__name__icontains=query)
        | models.Q(order__items__variant__name__icontains=query)
    )
    if query.isdigit():
        order_query |= models.Q(order_id=int(query))
    deals = ManagerDeal.objects.select_related('order', 'responsible_manager').filter(order_query).distinct().order_by('-deal_created_at')[:10]
    clients = ManagerClient.objects.filter(
        models.Q(name__icontains=query)
        | models.Q(phone__icontains=query)
        | models.Q(email__icontains=query)
        | models.Q(telegram__icontains=query)
    ).order_by('name')[:10]
    documents = ContractDocument.objects.filter(
        models.Q(number__icontains=query)
        | models.Q(title__icontains=query)
        | models.Q(counterparty_name__icontains=query)
        | models.Q(counterparty_email__icontains=query)
        | models.Q(counterparty_phone__icontains=query)
        | models.Q(subject__icontains=query)
    ).select_related('manager_deal', 'linked_order').order_by('-issue_date', '-id')[:10]
    shipments = Shipment.objects.filter(
        models.Q(tracking_number__icontains=query)
        | models.Q(order__phone__icontains=query)
        | models.Q(order__email__icontains=query)
        | models.Q(order__first_name__icontains=query)
        | models.Q(order__last_name__icontains=query)
        | models.Q(client__name__icontains=query)
        | models.Q(comments__icontains=query)
    ).select_related('manager_deal', 'order', 'client').order_by('-created_at')[:10]
    cargos = Cargo.objects.filter(
        models.Q(cargo_number__icontains=query)
        | models.Q(comments__icontains=query)
    ).order_by('-created_at')[:10]
    variant_query = ProductVariant.objects.filter(
        models.Q(sku__icontains=query) | models.Q(name__icontains=query) | models.Q(product__name__icontains=query)
    ).select_related('product').order_by('product__name', 'name')[:10]
    product_query = Product.objects.filter(
        models.Q(sku__icontains=query) | models.Q(name__icontains=query) | models.Q(description__icontains=query)
    ).order_by('name')[:10]
    return [
        {'key': 'deals', 'label': 'Заказы', 'items': list(deals)},
        {'key': 'clients', 'label': 'Клиенты', 'items': list(clients)},
        {'key': 'documents', 'label': 'Документы', 'items': list(documents)},
        {'key': 'shipments', 'label': 'Отгрузки', 'items': list(shipments)},
        {'key': 'cargos', 'label': 'Грузы', 'items': list(cargos)},
        {'key': 'variants', 'label': 'SKU / варианты', 'items': list(variant_query)},
        {'key': 'products', 'label': 'Товары', 'items': list(product_query)},
    ]


def _get_or_create_balance(warehouse, product, variant=None):
    if variant is None:
        balance = InventoryBalance.objects.filter(
            warehouse=warehouse,
            product=product,
            variant__isnull=True,
        ).first()
        if balance:
            return balance
        return InventoryBalance.objects.create(warehouse=warehouse, product=product, quantity=0)
    balance, _ = InventoryBalance.objects.get_or_create(
        warehouse=warehouse,
        product=product,
        variant=variant,
        defaults={'quantity': 0},
    )
    return balance


def _inventory_row_key(warehouse_id, product_id, variant_id=None):
    return (warehouse_id, product_id, variant_id or 0)


def _inventory_sku(*, product, variant=None):
    return ((variant.sku if variant else '') or (product.sku or '')).strip()


def _inventory_public_stock_map(rows, warehouse_pickup_map):
    pickup_ids = {pickup_id for pickup_id in warehouse_pickup_map.values() if pickup_id}
    if not pickup_ids or not rows:
        return {}
    product_ids = {row['product_id'] for row in rows}
    has_without_variant = any(not row['variant_id'] for row in rows)
    variant_ids = {row['variant_id'] for row in rows if row['variant_id']}
    public_stocks = ProductStock.objects.filter(
        pickup_point_id__in=pickup_ids,
        product_id__in=product_ids,
    )
    if variant_ids and has_without_variant:
        public_stocks = public_stocks.filter(models.Q(variant_id__in=variant_ids) | models.Q(variant__isnull=True))
    elif variant_ids:
        public_stocks = public_stocks.filter(variant_id__in=variant_ids)
    elif has_without_variant:
        public_stocks = public_stocks.filter(variant__isnull=True)
    else:
        return {}
    return {
        _inventory_row_key(stock.pickup_point_id, stock.product_id, stock.variant_id): int(stock.quantity or 0)
        for stock in public_stocks
    }


def _inventory_problem_entries(row):
    problems = []
    available = int(row['available'] or 0)
    on_hand = int(row['on_hand'] or 0)
    reserved_on_hand = int(row['reserved_on_hand'] or 0)
    inbound = int(row['inbound'] or 0)
    inbound_available = int(row['inbound_available'] or 0)
    min_stock = int(row['min_stock'] or 0)
    public_mismatch = row.get('public_sync_status_code') == INVENTORY_PUBLIC_SYNC_STATUS_MISMATCH
    if min_stock > 0 and available < min_stock:
        problems.append({'code': 'below_min_stock', 'label': INVENTORY_PROBLEM_LABELS['below_min_stock']})
    if available < 0:
        problems.append({'code': 'negative_available', 'label': INVENTORY_PROBLEM_LABELS['negative_available']})
    if reserved_on_hand > on_hand:
        problems.append({'code': 'reserved_gt_on_hand', 'label': INVENTORY_PROBLEM_LABELS['reserved_gt_on_hand']})
    if inbound > 0 and inbound_available <= 0:
        problems.append({'code': 'inbound_fully_allocated', 'label': INVENTORY_PROBLEM_LABELS['inbound_fully_allocated']})
    if public_mismatch:
        problems.append({'code': 'public_mismatch', 'label': INVENTORY_PROBLEM_LABELS['public_mismatch']})
    ordered = []
    for code in INVENTORY_PROBLEM_PRIORITY:
        ordered.extend(problem for problem in problems if problem['code'] == code)
    return ordered


def inventory_summary(rows):
    problem_sku_keys = {row['sku_key'] for row in rows if row.get('has_problem')}
    return {
        'problem_sku_count': len(problem_sku_keys),
        'sellable_sku_count': sum(1 for row in rows if int(row.get('available') or 0) > 0),
        'negative_available_count': sum(1 for row in rows if 'negative_available' in row.get('problem_codes', [])),
        'below_min_stock_count': sum(1 for row in rows if 'below_min_stock' in row.get('problem_codes', [])),
        'public_mismatch_count': sum(1 for row in rows if 'public_mismatch' in row.get('problem_codes', [])),
        'waiting_inbound_count': sum(
            1
            for row in rows
            if int(row.get('available') or 0) <= 0 and int(row.get('inbound_available') or 0) > 0
        ),
        'total_available': sum(int(row['available'] or 0) for row in rows),
        'total_inbound': sum(int(row['inbound'] or 0) for row in rows),
        'total_inbound_reserved': sum(int(row['inbound_reserved'] or 0) for row in rows),
    }


def _inventory_build_row_status(row):
    problem_codes = set(row.get('problem_codes') or [])
    available = int(row.get('available') or 0)
    inbound_available = int(row.get('inbound_available') or 0)
    reserved_on_hand = int(row.get('reserved_on_hand') or 0)
    on_hand = int(row.get('on_hand') or 0)
    public_published_qty = row.get('public_published_qty')
    public_expected_qty = int(row.get('public_expected_qty') or 0)
    linked_deals = row.get('linked_deals') or []

    if {'reserved_gt_on_hand', 'negative_available'} & problem_codes:
        detail = f'Свободный остаток ушел в минус: {available} шт.'
        if linked_deals:
            detail = f'{detail} Под риском {len(linked_deals)} сделок.'
        status_code = INVENTORY_ROW_STATUS_PROMISE_RISK
    elif 'public_mismatch' in problem_codes:
        published = '—' if public_published_qty is None else public_published_qty
        detail = f'На сайте {published}, менеджеру нужно обещать {max(available, 0)} шт.'
        if public_expected_qty != max(available, 0):
            detail = f'На сайте {published}, ожидается {public_expected_qty} шт.'
        status_code = INVENTORY_ROW_STATUS_SITE_MISMATCH
    elif 'below_min_stock' in problem_codes:
        detail = f'Свободно {available} шт. при минимуме {int(row.get("min_stock") or 0)} шт.'
        status_code = INVENTORY_ROW_STATUS_LOW_STOCK
    elif available <= 0 and inbound_available > 0:
        eta = _inventory_earliest_incoming_eta(row)
        detail = f'Сейчас свободного остатка нет, в пути {inbound_available} шт.'
        if eta:
            detail = f'{detail} ETA {eta:%d.%m.%Y}.'
        status_code = INVENTORY_ROW_STATUS_WAITING_INBOUND
    else:
        detail = f'На руках {on_hand} шт., в резерве {reserved_on_hand} шт., свободно {available} шт.'
        status_code = INVENTORY_ROW_STATUS_NORMAL

    meta = INVENTORY_ROW_STATUS_META[status_code]
    return {
        'code': status_code,
        'label': meta['label'],
        'tone': meta['tone'],
        'detail': detail,
    }


def _inventory_problem_tone(problem_code):
    if problem_code in {'negative_available', 'reserved_gt_on_hand'}:
        return SEMANTIC_TONE_CRITICAL
    if problem_code in {'below_min_stock', 'inbound_fully_allocated', 'public_mismatch'}:
        return SEMANTIC_TONE_ATTENTION
    return SEMANTIC_TONE_UNKNOWN


def _inventory_build_sync_status(row):
    status_code = row.get('public_sync_status_code')
    tone_map = {
        INVENTORY_PUBLIC_SYNC_STATUS_SYNCED: SEMANTIC_TONE_COMPLETE,
        INVENTORY_PUBLIC_SYNC_STATUS_MISMATCH: SEMANTIC_TONE_ATTENTION,
        INVENTORY_PUBLIC_SYNC_STATUS_UNLINKED: SEMANTIC_TONE_UNKNOWN,
    }
    detail = ''
    if status_code == INVENTORY_PUBLIC_SYNC_STATUS_MISMATCH:
        published = '—' if row.get('public_published_qty') is None else row.get('public_published_qty')
        detail = f'На сайте {published}, ожидается {row.get("public_expected_qty")}.'
    elif status_code == INVENTORY_PUBLIC_SYNC_STATUS_UNLINKED:
        detail = 'Позиция не связана с публичным остатком.'
    return build_semantic_status(
        row.get('public_sync_status_label') or 'Нет данных',
        tone=tone_map.get(status_code, SEMANTIC_TONE_UNKNOWN),
        detail=detail,
    )


def _inventory_build_risk_summary(row):
    problems = row.get('problem_types') or []
    if problems:
        primary = problems[0]
        tone = _inventory_problem_tone(primary.get('code'))
        detail_parts = []
        if len(problems) > 1:
            detail_parts.append(f'Еще {len(problems) - 1}.')
        linked_deals = row.get('linked_deals') or []
        if linked_deals:
            detail_parts.append(f'Связано сделок: {len(linked_deals)}.')
        return build_semantic_status(
            primary.get('label') or 'Нужна проверка',
            tone=tone,
            detail=' '.join(detail_parts).strip(),
        )

    if row.get('linked_deals'):
        return build_semantic_status('Рисков нет', tone=SEMANTIC_TONE_COMPLETE, detail='Есть связанные сделки.')

    return build_semantic_status('Рисков нет', tone=SEMANTIC_TONE_COMPLETE, detail='Критичных сигналов нет.')


def _inventory_earliest_incoming_eta(row):
    incoming_cargos = row.get('incoming_cargos') or []
    eta_values = [item['cargo'].eta for item in incoming_cargos if item['cargo'].eta]
    return min(eta_values) if eta_values else None


def _inventory_build_detail_reasons(row):
    reasons = []
    available = int(row.get('available') or 0)
    reserved_on_hand = int(row.get('reserved_on_hand') or 0)
    on_hand = int(row.get('on_hand') or 0)
    inbound_available = int(row.get('inbound_available') or 0)
    linked_deals = row.get('linked_deals') or []
    active_reservations = row.get('active_reservations') or []
    incoming_cargos = row.get('incoming_cargos') or []

    if reserved_on_hand:
        reasons.append(f'В резерве {reserved_on_hand} из {on_hand} шт.; свободно сейчас {available} шт.')
    else:
        reasons.append(f'На складе {on_hand} шт. без активного резерва; свободно {available} шт.')
    if linked_deals:
        reasons.append(f'С позицией связаны сделки: {len(linked_deals)}.')
    if active_reservations:
        reasons.append(f'Активных броней по позиции: {len(active_reservations)}.')
    if incoming_cargos:
        eta = _inventory_earliest_incoming_eta(row)
        if eta:
            reasons.append(f'Свободный приход {max(inbound_available, 0)} шт. ожидается к {eta:%d.%m.%Y}.')
        else:
            reasons.append(f'В пути остается {max(inbound_available, 0)} шт., дата прихода пока не указана.')
    if row.get('public_sync_status_code') == INVENTORY_PUBLIC_SYNC_STATUS_MISMATCH:
        published = '—' if row.get('public_published_qty') is None else row.get('public_published_qty')
        reasons.append(f'На сайте опубликовано {published} шт., ожидается {row.get("public_expected_qty")}.')
    return reasons[:4]


def enrich_inventory_rows(rows):
    if not rows:
        return rows

    row_map = {}
    warehouse_ids = set()
    product_ids = set()
    for row in rows:
        row['row_key'] = f"{row['warehouse_id']}-{row['product_id']}-{row['variant_id'] or 0}"
        row['active_reservations'] = []
        row['recent_movements'] = []
        row['incoming_cargos'] = []
        row['linked_deals'] = []
        row['last_change'] = None
        row['_linked_deal_ids'] = set()
        row_map[_inventory_row_key(row['warehouse_id'], row['product_id'], row['variant_id'])] = row
        warehouse_ids.add(row['warehouse_id'])
        product_ids.add(row['product_id'])

    def append_deal(row, deal, *, source_label):
        if not deal or deal.pk in row['_linked_deal_ids']:
            return
        row['_linked_deal_ids'].add(deal.pk)
        row['linked_deals'].append({'deal': deal, 'source_label': source_label})

    reservation_items = (
        ReservationItem.objects.filter(
            reservation__status__in=ACTIVE_RESERVATION_STATUSES,
            product_id__in=product_ids,
        )
        .filter(
            models.Q(reservation__source_warehouse_id__in=warehouse_ids)
            | models.Q(reservation__source_cargo__destination_warehouse_id__in=warehouse_ids)
        )
        .select_related(
            'product',
            'variant',
            'reservation',
            'reservation__client',
            'reservation__manager_deal',
            'reservation__manager_deal__order',
            'reservation__source_warehouse',
            'reservation__source_cargo',
            'reservation__source_cargo__destination_warehouse',
            'reservation__target_warehouse',
        )
        .order_by('-reservation__created_at', '-reservation__id', 'id')
    )
    for item in reservation_items:
        effective_warehouse = reservation_effective_warehouse(item.reservation)
        if not effective_warehouse:
            continue
        row = row_map.get(_inventory_row_key(effective_warehouse.id, item.product_id, item.variant_id))
        if not row:
            continue
        if len(row['active_reservations']) < 5:
            row['active_reservations'].append(
                {
                    'reservation': item.reservation,
                    'quantity': item.quantity,
                    'source_label': (
                        item.reservation.source_warehouse.name
                        if item.reservation.source_type == Reservation.SOURCE_WAREHOUSE and item.reservation.source_warehouse_id
                        else item.reservation.source_cargo.cargo_number
                    ),
                    'source_type_label': (
                        'warehouse' if item.reservation.source_type == Reservation.SOURCE_WAREHOUSE else 'incoming'
                    ),
                }
            )
        append_deal(row, item.reservation.manager_deal, source_label='reservation')

    movements = (
        InventoryMovement.objects.filter(
            warehouse_id__in=warehouse_ids,
            product_id__in=product_ids,
        )
        .select_related('author')
        .order_by('-created_at', '-id')
    )
    for movement in movements:
        row = row_map.get(_inventory_row_key(movement.warehouse_id, movement.product_id, movement.variant_id))
        if not row:
            continue
        if len(row['recent_movements']) < 5:
            row['recent_movements'].append(movement)
        if row['last_change'] is None:
            row['last_change'] = {
                'author_name': movement.author.get_username() if movement.author_id else 'Система',
                'created_at': movement.created_at,
                'comment': movement.comment,
                'movement_type_label': movement.get_movement_type_display(),
            }

    cargo_items = (
        CargoItem.objects.filter(
            cargo__status__in=INBOUND_CARGO_STATUSES,
            cargo__destination_warehouse_id__in=warehouse_ids,
            product_id__in=product_ids,
        )
        .select_related(
            'cargo',
            'purchase_item',
            'purchase_item__purchase',
            'purchase_item__order_item__order',
            'purchase_item__order_item__order__manager_deal',
        )
        .order_by('cargo__eta', '-cargo__created_at', 'id')
    )
    for item in cargo_items:
        remaining = item.remaining_quantity
        if remaining <= 0:
            continue
        row = row_map.get(_inventory_row_key(item.cargo.destination_warehouse_id, item.product_id, item.variant_id))
        if not row:
            continue
        if len(row['incoming_cargos']) < 5:
            row['incoming_cargos'].append(
                {
                    'cargo': item.cargo,
                    'cargo_item': item,
                    'remaining_quantity': remaining,
                    'purchase': item.purchase_item.purchase if item.purchase_item_id else None,
                    'linked_order': item.linked_order,
                }
            )
        linked_order = item.linked_order
        if linked_order and hasattr(linked_order, 'manager_deal'):
            append_deal(row, linked_order.manager_deal, source_label='incoming')

    stock_deals = (
        ManagerDeal.objects.filter(stock_warehouse_id__in=warehouse_ids)
        .exclude(case_status__in=[ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED])
        .select_related('order')
        .prefetch_related('order__items')
        .distinct()
    )
    for deal in stock_deals:
        for order_item in deal.order.items.all():
            row = row_map.get(_inventory_row_key(deal.stock_warehouse_id, order_item.product_id, order_item.variant_id))
            if row:
                append_deal(row, deal, source_label='stock')

    for row in rows:
        row['linked_deals'] = sorted(
            row['linked_deals'],
            key=lambda item: item['deal'].order.created_at,
            reverse=True,
        )[:5]
        row['is_low_stock'] = (
            int(row.get('min_stock') or 0) > 0
            and int(row.get('available') or 0) < int(row.get('min_stock') or 0)
        )
        row['promise_capacity'] = max(int(row.get('available') or 0), 0) + max(int(row.get('inbound_available') or 0), 0)
        row['row_status'] = _inventory_build_row_status(row)
        row['public_sync_status'] = _inventory_build_sync_status(row)
        row['risk_summary'] = _inventory_build_risk_summary(row)
        row['detail_reasons'] = _inventory_build_detail_reasons(row)
        row['has_detail_data'] = bool(
            row['active_reservations']
            or row['recent_movements']
            or row['incoming_cargos']
            or row['linked_deals']
            or row['last_change']
        )
        row.pop('_linked_deal_ids', None)
    return rows


def inventory_snapshot(*, warehouse_ids=None):
    balances = InventoryBalance.objects.select_related('warehouse', 'product', 'variant')
    if warehouse_ids:
        balances = balances.filter(warehouse_id__in=warehouse_ids)
    rows = {}
    warehouse_pickup_map = {}

    def ensure_row(
        warehouse_id,
        warehouse_name,
        product_id,
        product_name,
        product_slug,
        variant_id=None,
        variant_name='',
        on_hand=0,
        sku='',
        min_stock=0,
    ):
        row_key = _inventory_row_key(warehouse_id, product_id, variant_id)
        if row_key not in rows:
            rows[row_key] = {
                'warehouse_id': warehouse_id,
                'warehouse_name': warehouse_name,
                'product_id': product_id,
                'product_name': product_name,
                'product_slug': product_slug,
                'variant_id': variant_id,
                'variant_name': variant_name or '',
                'on_hand': 0,
                'reserved_on_hand': 0,
                'available': 0,
                'inbound': 0,
                'inbound_reserved': 0,
                'inbound_available': 0,
                'sku': sku,
                'sku_key': sku or f'product-{product_id}-variant-{variant_id or 0}',
                'min_stock': int(min_stock or 0),
                'public_published_qty': None,
                'public_expected_qty': 0,
                'public_sync_status_code': INVENTORY_PUBLIC_SYNC_STATUS_UNLINKED,
                'public_sync_status_label': INVENTORY_PUBLIC_SYNC_STATUS_LABELS[INVENTORY_PUBLIC_SYNC_STATUS_UNLINKED],
                'problem_types': [],
                'problem_codes': [],
                'primary_problem_type': None,
                'has_problem': False,
                'problem_rank': len(INVENTORY_PROBLEM_PRIORITY),
            }
        if sku and not rows[row_key]['sku']:
            rows[row_key]['sku'] = sku
        rows[row_key]['sku_key'] = rows[row_key]['sku'] or f'product-{product_id}-variant-{variant_id or 0}'
        rows[row_key]['min_stock'] = max(int(rows[row_key]['min_stock'] or 0), int(min_stock or 0))
        rows[row_key]['on_hand'] += int(on_hand or 0)
        return rows[row_key]

    for balance in balances:
        warehouse_pickup_map[balance.warehouse_id] = balance.warehouse.pickup_point_id
        ensure_row(
            balance.warehouse_id,
            balance.warehouse.name,
            balance.product_id,
            balance.product.name,
            balance.product.slug,
            balance.variant_id,
            balance.variant.name if balance.variant_id else '',
            balance.quantity,
            _inventory_sku(product=balance.product, variant=balance.variant),
            balance.min_stock,
        )

    reservation_items = ReservationItem.objects.filter(
        reservation__status__in=ACTIVE_RESERVATION_STATUSES,
    ).select_related(
        'product',
        'variant',
        'reservation__source_warehouse',
        'reservation__source_cargo__destination_warehouse',
    )
    if warehouse_ids:
        reservation_items = reservation_items.filter(
            models.Q(reservation__source_warehouse_id__in=warehouse_ids)
            | models.Q(reservation__source_cargo__destination_warehouse_id__in=warehouse_ids)
        )
    for item in reservation_items:
        if item.reservation.source_type == Reservation.SOURCE_WAREHOUSE and item.reservation.source_warehouse_id:
            warehouse_pickup_map[item.reservation.source_warehouse_id] = item.reservation.source_warehouse.pickup_point_id
            row = ensure_row(
                item.reservation.source_warehouse_id,
                item.reservation.source_warehouse.name,
                item.product_id,
                item.product.name,
                item.product.slug,
                item.variant_id,
                item.variant.name if item.variant_id else '',
                sku=_inventory_sku(product=item.product, variant=item.variant),
            )
            row['reserved_on_hand'] += item.quantity
        elif item.reservation.source_type == Reservation.SOURCE_CARGO and item.reservation.source_cargo_id:
            cargo = item.reservation.source_cargo
            if cargo.destination_warehouse_id:
                warehouse_pickup_map[cargo.destination_warehouse_id] = cargo.destination_warehouse.pickup_point_id
                row = ensure_row(
                    cargo.destination_warehouse_id,
                    cargo.destination_warehouse.name,
                    item.product_id,
                    item.product.name,
                    item.product.slug,
                    item.variant_id,
                    item.variant.name if item.variant_id else '',
                    sku=_inventory_sku(product=item.product, variant=item.variant),
                )
                row['inbound_reserved'] += item.quantity

    cargo_items = CargoItem.objects.filter(
        cargo__status__in=INBOUND_CARGO_STATUSES,
        cargo__destination_warehouse__isnull=False,
    ).select_related('cargo__destination_warehouse', 'product', 'variant')
    if warehouse_ids:
        cargo_items = cargo_items.filter(cargo__destination_warehouse_id__in=warehouse_ids)
    for item in cargo_items:
        remaining = item.remaining_quantity
        if remaining <= 0:
            continue
        warehouse_pickup_map[item.cargo.destination_warehouse_id] = item.cargo.destination_warehouse.pickup_point_id
        row = ensure_row(
            item.cargo.destination_warehouse_id,
            item.cargo.destination_warehouse.name,
            item.product_id,
            item.product.name,
            item.product.slug,
            item.variant_id,
            item.variant.name if item.variant_id else '',
            sku=_inventory_sku(product=item.product, variant=item.variant),
        )
        row['inbound'] += remaining

    row_values = list(rows.values())
    public_stock_map = _inventory_public_stock_map(row_values, warehouse_pickup_map)
    for row in row_values:
        row['available'] = row['on_hand'] - row['reserved_on_hand']
        row['inbound_available'] = row['inbound'] - row['inbound_reserved']
        pickup_point_id = warehouse_pickup_map.get(row['warehouse_id'])
        if pickup_point_id:
            public_qty = int(public_stock_map.get(_inventory_row_key(pickup_point_id, row['product_id'], row['variant_id']), 0))
            expected_qty = max(int(row['available'] or 0), 0)
            status_code = (
                INVENTORY_PUBLIC_SYNC_STATUS_SYNCED
                if public_qty == expected_qty
                else INVENTORY_PUBLIC_SYNC_STATUS_MISMATCH
            )
            row['public_published_qty'] = public_qty
            row['public_expected_qty'] = expected_qty
            row['public_sync_status_code'] = status_code
            row['public_sync_status_label'] = INVENTORY_PUBLIC_SYNC_STATUS_LABELS[status_code]
        problem_types = _inventory_problem_entries(row)
        row['problem_types'] = problem_types
        row['problem_codes'] = [item['code'] for item in problem_types]
        row['primary_problem_type'] = problem_types[0] if problem_types else None
        row['has_problem'] = bool(problem_types)
        row['problem_rank'] = (
            INVENTORY_PROBLEM_PRIORITY.index(problem_types[0]['code'])
            if problem_types
            else len(INVENTORY_PROBLEM_PRIORITY)
        )

    return sorted(row_values, key=lambda value: (value['warehouse_name'], value['product_name'], value['variant_name']))


def inventory_snapshot_for_warehouse(warehouse):
    return inventory_snapshot(warehouse_ids=[warehouse.id])


def _available_map_for_source(source_type, source_warehouse=None, source_cargo=None):
    if source_type == Reservation.SOURCE_WAREHOUSE and source_warehouse:
        rows = inventory_snapshot_for_warehouse(source_warehouse)
        return {(row['product_id'], row['variant_id'] or 0): row['available'] for row in rows}
    if source_type == Reservation.SOURCE_CARGO and source_cargo and source_cargo.destination_warehouse_id:
        rows = inventory_snapshot_for_warehouse(source_cargo.destination_warehouse)
        return {(row['product_id'], row['variant_id'] or 0): row['inbound_available'] for row in rows}
    return {}


def receipt_inventory(*, warehouse, product, variant=None, quantity, author=None, comment='', reference_type='manual', reference_id=None):
    with transaction.atomic():
        balance = _get_or_create_balance(warehouse, product, variant)
        balance.quantity += int(quantity)
        balance.save(update_fields=['quantity', 'updated_at'])
        InventoryMovement.objects.create(
            warehouse=warehouse,
            product=product,
            variant=variant,
            movement_type=InventoryMovement.TYPE_RECEIPT,
            quantity=int(quantity),
            reference_type=reference_type,
            reference_id=reference_id,
            comment=comment,
            author=author,
        )
        sync_public_stock_for_warehouse(warehouse)
    return balance


def create_or_update_reservation_movements(reservation, *, movement_type, author=None, comment='', items=None):
    source_warehouse = reservation.source_warehouse
    if reservation.source_type == Reservation.SOURCE_CARGO and reservation.source_cargo_id:
        source_warehouse = reservation.source_cargo.destination_warehouse
    if not source_warehouse:
        return
    item_iterable = items if items is not None else reservation.items.select_related('product', 'variant').all()
    for item in item_iterable:
        InventoryMovement.objects.create(
            warehouse=source_warehouse,
            product=item.product,
            variant=item.variant,
            movement_type=movement_type,
            quantity=item.quantity,
            reference_type='reservation',
            reference_id=reservation.id,
            comment=comment,
            author=author,
        )


def validate_reservation_availability(reservation, *, items):
    available_map = _available_map_for_source(
        reservation.source_type,
        source_warehouse=reservation.source_warehouse,
        source_cargo=reservation.source_cargo,
    )
    for item in items:
        variant_id = item.variant_id or 0
        available = int(available_map.get((item.product_id, variant_id), 0))
        if item.quantity > available:
            raise ValueError(
                f'Недостаточно доступного остатка для "{item.product.name}". '
                f'Доступно: {available}, запрошено: {item.quantity}.'
            )


def sync_public_stock_for_warehouse(warehouse):
    if not warehouse.pickup_point_id:
        return
    rows = inventory_snapshot_for_warehouse(warehouse)
    target = warehouse.pickup_point
    ProductStock.objects.filter(pickup_point=target).update(quantity=0)
    for row in rows:
        quantity = max(int(row['available']), 0)
        variant_id = row['variant_id'] or None
        if variant_id is None:
            stock = ProductStock.objects.filter(
                product_id=row['product_id'],
                pickup_point=target,
                variant__isnull=True,
            ).first()
            if stock:
                stock.quantity = quantity
                stock.save(update_fields=['quantity'])
            else:
                ProductStock.objects.create(
                    product_id=row['product_id'],
                    pickup_point=target,
                    variant=None,
                    quantity=quantity,
                )
            continue
        ProductStock.objects.update_or_create(
            product_id=row['product_id'],
            pickup_point=target,
            variant_id=variant_id,
            defaults={'quantity': quantity},
        )
    warehouse.public_stock_synced_at = timezone.now()
    warehouse.save(update_fields=['public_stock_synced_at', 'updated_at'])


def sync_public_stock_all():
    for warehouse in Warehouse.objects.filter(pickup_point__isnull=False):
        sync_public_stock_for_warehouse(warehouse)


def reservation_effective_warehouse(reservation):
    if reservation.source_type == Reservation.SOURCE_WAREHOUSE:
        return reservation.source_warehouse
    if reservation.source_type == Reservation.SOURCE_CARGO and reservation.source_cargo_id:
        return reservation.source_cargo.destination_warehouse
    return None


def ensure_manager_client_for_order(order):
    business_name = (order.business_company_name or '').strip()
    business_phone = (order.business_phone or '').strip()
    telegram = ''
    if order.contact_channel == Order.CONTACT_CHANNEL_TELEGRAM:
        telegram = (order.contact_handle or '').strip()
    elif order.business_telegram:
        telegram = (order.business_telegram or '').strip()
    return resolve_manager_client(
        user=order.user,
        name=business_name or order.shipping_contact_name or f'Клиент по заказу #{order.pk}',
        phone=business_phone or order.shipping_phone or order.phone,
        email=order.email,
        address=order.display_address,
        telegram=telegram,
        order=order,
    )


def _website_deal_type_for_order(order):
    if order.items.filter(is_on_request=True).exists():
        return ManagerDeal.DEAL_SALE_ON_REQUEST
    return ManagerDeal.DEAL_SALE_FROM_STOCK


def _website_deal_status_for_order(order, *, deal_type, customer_source=''):
    is_avito_workflow = ManagerDeal.uses_avito_workflow(deal_type, customer_source)
    if order.status == Order.STATUS_CANCELLED:
        return ManagerDeal.DEAL_STATUS_RETURNED if is_avito_workflow else ManagerDeal.DEAL_STATUS_CANCELLED
    if order.status == Order.STATUS_DONE:
        return ManagerDeal.DEAL_STATUS_RECEIVED_BY_CUSTOMER if is_avito_workflow else ManagerDeal.DEAL_STATUS_COMPLETED
    if order.status == Order.STATUS_SHIPPING:
        return ManagerDeal.DEAL_STATUS_SHIPPED

    if deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST:
        linked_purchase_items = PurchaseItem.objects.filter(order_item__order=order)
        if linked_purchase_items.exists():
            if all(item.received_quantity >= item.quantity for item in linked_purchase_items):
                return ManagerDeal.DEAL_STATUS_RECEIVED
            return ManagerDeal.DEAL_STATUS_SUPPLIER_ORDERED
        if order.payment_status == Order.PAYMENT_STATUS_PAID:
            return ManagerDeal.DEAL_STATUS_PREPAYMENT_RECEIVED
        return ManagerDeal.DEAL_STATUS_NEW_REQUEST

    if is_avito_workflow:
        return ManagerDeal.DEAL_STATUS_NEW

    if order.payment_status == Order.PAYMENT_STATUS_PAID:
        return ManagerDeal.DEAL_STATUS_PAID
    if order.manager_reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES).exists():
        return ManagerDeal.DEAL_STATUS_RESERVED
    return ManagerDeal.DEAL_STATUS_AWAITING_PAYMENT


def _order_business_deal_defaults(order):
    return {
        'buyer_type': ManagerDeal.BUYER_BUSINESS,
        'business_company_name': (order.business_company_name or '').strip(),
        'business_inn': (order.business_inn or '').strip(),
        'business_kpp': (order.business_kpp or '').strip(),
        'business_contact_person': order.shipping_contact_name,
        'business_phone': (order.business_phone or order.shipping_phone or order.phone or '').strip(),
        'business_telegram': (
            (order.business_telegram or '').strip()
            or ((order.contact_handle or '').strip() if order.contact_channel == Order.CONTACT_CHANNEL_TELEGRAM else '')
        ),
        'business_whatsapp': (
            (order.business_whatsapp or '').strip()
            or ((order.contact_handle or '').strip() if order.contact_channel == Order.CONTACT_CHANNEL_WHATSAPP else '')
        ),
        'business_email': (order.email or '').strip(),
        'business_city': (order.city_text or '').strip(),
        'business_delivery_address': (order.display_address or '').strip(),
        'business_checking_account': (order.business_checking_account or '').strip(),
        'business_bank_name': (order.business_bank_name or '').strip(),
        'business_bik': (order.business_bik or '').strip(),
        'business_correspondent_account': (order.business_correspondent_account or '').strip(),
    }


def ensure_manager_deal_for_order(order, *, customer_source=ManagerDeal.SOURCE_WEBSITE, responsible_manager=None):
    deal_type = _website_deal_type_for_order(order)
    deal_status = _website_deal_status_for_order(order, deal_type=deal_type, customer_source=customer_source)
    initial_paid_amount = order.total_with_delivery if order.payment_status == Order.PAYMENT_STATUS_PAID else Decimal('0')
    defaults = {
        'responsible_manager': responsible_manager,
        'assigned_at': timezone.now() if responsible_manager else None,
        'deal_type': deal_type,
        'deal_status': deal_status,
        'case_status': _case_status_for_order(order),
        'payment_state': ManagerDeal.PAYMENT_STATE_PAID if order.payment_status == Order.PAYMENT_STATUS_PAID else ManagerDeal.PAYMENT_STATE_UNPAID,
        'buyer_type': ManagerDeal.BUYER_INDIVIDUAL,
        'customer_source': customer_source,
        'deal_created_at': order.created_at or timezone.now(),
        'individual_full_name': order.shipping_contact_name,
        'individual_phone': order.shipping_phone,
        'individual_city': order.city_text,
        'individual_delivery_address': order.display_address,
        'individual_messenger': (
            (order.contact_handle or '').strip()
            if order.contact_channel in {Order.CONTACT_CHANNEL_TELEGRAM, Order.CONTACT_CHANNEL_WHATSAPP}
            else ''
        ),
        'customer_request': ', '.join(
            item.display_name for item in order.items.select_related('product', 'variant').all()
        ),
        'delivery_method': _manager_delivery_method_for_order(order),
        'delivery_to_city': order.city_text,
        'delivery_full_address': order.display_address,
        'tracking_number': '',
        'shipment_status': ManagerDeal.SHIPMENT_DRAFT,
        'prepayment_amount': initial_paid_amount,
        'last_payment_at': order.updated_at if initial_paid_amount > MONEY_ZERO else None,
        'last_activity_at': order.created_at or timezone.now(),
    }
    if order.payment_method in {Order.PAYMENT_METHOD_MANAGER_PAYMENT, Order.PAYMENT_METHOD_INVOICE}:
        defaults.update(_order_business_deal_defaults(order))
    deal, created = ManagerDeal.objects.get_or_create(order=order, defaults=defaults)
    if created:
        ensure_initial_deal_activity(deal)
        recompute_deal_workflow(deal)
        return deal

    update_fields = []
    if order.payment_method not in {Order.PAYMENT_METHOD_MANAGER_PAYMENT, Order.PAYMENT_METHOD_INVOICE}:
        for field, value in (
            ('deal_type', deal_type),
            ('deal_status', deal_status),
            ('individual_full_name', order.shipping_contact_name),
            ('individual_phone', order.shipping_phone),
            ('individual_city', order.city_text),
            ('individual_delivery_address', order.display_address),
            (
                'individual_messenger',
                (order.contact_handle or '').strip()
                if order.contact_channel in {Order.CONTACT_CHANNEL_TELEGRAM, Order.CONTACT_CHANNEL_WHATSAPP}
                else '',
            ),
            ('customer_request', defaults['customer_request']),
            ('delivery_method', _manager_delivery_method_for_order(order)),
            ('delivery_to_city', order.city_text),
            ('delivery_full_address', order.display_address),
        ):
            if getattr(deal, field) != value:
                setattr(deal, field, value)
                update_fields.append(field)
        if responsible_manager is not None and deal.responsible_manager_id is None:
            deal.responsible_manager = responsible_manager
            deal.assigned_at = timezone.now()
            update_fields.extend(['responsible_manager', 'assigned_at'])
    else:
        business_defaults = _order_business_deal_defaults(order)
        if deal.buyer_type != ManagerDeal.BUYER_BUSINESS:
            deal.buyer_type = ManagerDeal.BUYER_BUSINESS
            update_fields.append('buyer_type')
        for field, value in business_defaults.items():
            if field == 'buyer_type' or not value:
                continue
            if getattr(deal, field) != value and not getattr(deal, field):
                setattr(deal, field, value)
                update_fields.append(field)
    if update_fields:
        update_fields.append('updated_at')
        deal.save(update_fields=update_fields)
    set_manager_deal_paid_amount(
        deal,
        paid_amount=initial_paid_amount,
        changed_at=order.updated_at,
    )
    ensure_initial_deal_activity(deal)
    recompute_deal_workflow(deal)
    return deal


def _get_or_create_order_reservation(*, order, client, warehouse, comment, manager_deal=None):
    reservation = Reservation.objects.filter(
        linked_order=order,
        client=client,
        source_type=Reservation.SOURCE_WAREHOUSE,
        source_warehouse=warehouse,
        status__in=ACTIVE_RESERVATION_STATUSES,
    ).first()
    if reservation:
        if manager_deal is not None and reservation.manager_deal_id is None:
            reservation.manager_deal = manager_deal
            reservation.save(update_fields=['manager_deal', 'updated_at'])
        return reservation, False
    return (
        Reservation.objects.create(
            manager_deal=manager_deal,
            client=client,
            linked_order=order,
            status=Reservation.STATUS_ACTIVE,
            source_type=Reservation.SOURCE_WAREHOUSE,
            source_warehouse=warehouse,
            target_warehouse=warehouse,
            comments=comment,
        ),
        True,
    )


def ensure_order_reservations(order, client, *, warehouse=None, author=None, strict=False, comment=''):
    try:
        deal = order.manager_deal
    except ManagerDeal.DoesNotExist:
        deal = None
    created_reservations = []
    created_items_by_reservation = defaultdict(list)
    existing_reserved = defaultdict(int)
    for item in ReservationItem.objects.filter(
        reservation__linked_order=order,
        reservation__status__in=ACTIVE_RESERVATION_STATUSES,
        order_item__isnull=False,
    ):
        existing_reserved[item.order_item_id] += item.quantity

    order_items = list(order.items.select_related('product', 'variant').all())
    if warehouse is not None:
        available_map = _available_map_for_source(Reservation.SOURCE_WAREHOUSE, source_warehouse=warehouse)
        reservation, created = _get_or_create_order_reservation(
            order=order,
            client=client,
            warehouse=warehouse,
            comment=comment,
            manager_deal=deal,
        )
        if created:
            created_reservations.append(reservation)
        for order_item in order_items:
            if order_item.is_on_request or not order_item.product_id:
                continue
            remaining = max(order_item.quantity - existing_reserved[order_item.id], 0)
            if remaining <= 0:
                continue
            available = int(available_map.get((order_item.product_id, order_item.variant_id or 0), 0))
            quantity_to_reserve = remaining if strict else min(remaining, max(available, 0))
            if strict and quantity_to_reserve < remaining:
                raise ValueError(
                    f'Недостаточно остатка на складе "{warehouse.name}" для "{order_item.display_name}".'
                )
            if quantity_to_reserve <= 0:
                continue
            reservation_item = ReservationItem.objects.create(
                reservation=reservation,
                order_item=order_item,
                product=order_item.product,
                variant=order_item.variant,
                quantity=quantity_to_reserve,
            )
            created_items_by_reservation[reservation.id].append(reservation_item)
        if created_items_by_reservation.get(reservation.id):
            create_or_update_reservation_movements(
                reservation,
                movement_type=InventoryMovement.TYPE_RESERVE,
                author=author,
                comment=comment or 'Автоматический резерв по заказу',
                items=created_items_by_reservation[reservation.id],
            )
            sync_public_stock_for_warehouse(warehouse)
        return [reservation] if created_items_by_reservation.get(reservation.id) else []

    rows = inventory_snapshot()
    rows_by_item = defaultdict(list)
    for row in rows:
        if row['available'] <= 0:
            continue
        rows_by_item[(row['product_id'], row['variant_id'] or 0)].append(row)
    for candidates in rows_by_item.values():
        candidates.sort(key=lambda value: (-value['available'], value['warehouse_name']))

    for order_item in order_items:
        if order_item.is_on_request or not order_item.product_id:
            continue
        remaining = max(order_item.quantity - existing_reserved[order_item.id], 0)
        if remaining <= 0:
            continue
        candidates = rows_by_item.get((order_item.product_id, order_item.variant_id or 0), [])
        total_available = sum(int(candidate['available']) for candidate in candidates)
        if strict and total_available < remaining:
            raise ValueError(f'Недостаточно доступного остатка для "{order_item.display_name}".')
        for candidate in candidates:
            if remaining <= 0:
                break
            quantity_to_reserve = min(remaining, int(candidate['available']))
            if quantity_to_reserve <= 0:
                continue
            candidate['available'] -= quantity_to_reserve
            warehouse_obj = Warehouse.objects.get(pk=candidate['warehouse_id'])
            reservation, created = _get_or_create_order_reservation(
                order=order,
                client=client,
                warehouse=warehouse_obj,
                comment=comment or 'Автоматический резерв по заказу сайта.',
                manager_deal=deal,
            )
            if created:
                created_reservations.append(reservation)
            reservation_item = ReservationItem.objects.create(
                reservation=reservation,
                order_item=order_item,
                product=order_item.product,
                variant=order_item.variant,
                quantity=quantity_to_reserve,
            )
            created_items_by_reservation[reservation.id].append(reservation_item)
            remaining -= quantity_to_reserve

    touched_warehouses = set()
    for reservation_id, items in created_items_by_reservation.items():
        reservation = items[0].reservation
        create_or_update_reservation_movements(
            reservation,
            movement_type=InventoryMovement.TYPE_RESERVE,
            author=author,
            comment=reservation.comments or 'Автоматический резерв по заказу',
            items=items,
        )
        effective_warehouse = reservation_effective_warehouse(reservation)
        if effective_warehouse:
            touched_warehouses.add(effective_warehouse.pk)
    for warehouse_id in touched_warehouses:
        sync_public_stock_for_warehouse(Warehouse.objects.get(pk=warehouse_id))
    if deal and len(created_reservations) == 1 and deal.primary_reservation_id != created_reservations[0].id:
        deal.primary_reservation = created_reservations[0]
        deal.reserve_created_at = timezone.now()
        deal.save(update_fields=['primary_reservation', 'reserve_created_at', 'updated_at'])
    return created_reservations


def ensure_website_order_workflow(order, *, author=None):
    client_resolution = ensure_manager_client_for_order(order)
    client = client_resolution['client']
    deal = ensure_manager_deal_for_order(order)
    reservations = ensure_order_reservations(
        order,
        client,
        author=author,
        strict=False,
        comment='Автоматический резерв по заказу сайта.',
    )
    if reservations:
        unique_warehouses = {reservation.source_warehouse_id for reservation in reservations if reservation.source_warehouse_id}
        update_fields = []
        if len(reservations) == 1 and deal.primary_reservation_id != reservations[0].id:
            deal.primary_reservation = reservations[0]
            deal.reserve_created_at = timezone.now()
            update_fields.extend(['primary_reservation', 'reserve_created_at'])
        if len(unique_warehouses) == 1:
            warehouse_id = next(iter(unique_warehouses))
            if deal.stock_warehouse_id != warehouse_id:
                deal.stock_warehouse_id = warehouse_id
                update_fields.append('stock_warehouse')
        if update_fields:
            update_fields.append('updated_at')
            deal.save(update_fields=update_fields)
    ensure_initial_deal_activity(deal, actor=author)
    if not deal.activities.filter(event_type='order.synced').exists():
        record_deal_activity(
            deal,
            event_type='order.synced',
            source=DealActivity.SOURCE_SYSTEM,
            actor=author,
            payload={'order_id': order.id},
        )
    recompute_deal_workflow(deal, actor=author)
    return {
        'client': client,
        'client_resolution': client_resolution,
        'deal': deal,
        'reservations': reservations,
    }


def fulfill_reservation(reservation, *, author=None, comment=''):
    source_warehouse = reservation_effective_warehouse(reservation)
    if not reservation or not source_warehouse:
        return False
    with transaction.atomic():
        for item in reservation.items.select_related('product', 'variant'):
            balance = InventoryBalance.objects.filter(
                warehouse=source_warehouse,
                product=item.product,
                variant=item.variant,
            ).first()
            if balance:
                balance.quantity = max(balance.quantity - item.quantity, 0)
                balance.save(update_fields=['quantity', 'updated_at'])
            InventoryMovement.objects.create(
                warehouse=source_warehouse,
                product=item.product,
                variant=item.variant,
                movement_type=InventoryMovement.TYPE_RELEASE,
                quantity=item.quantity,
                reference_type='deal_shipment',
                reference_id=reservation.linked_order_id,
                comment=comment or 'Списание после исполнения заказа',
                author=author,
            )
        reservation.status = Reservation.STATUS_FULFILLED
        reservation.save(update_fields=['status', 'updated_at'])
        sync_public_stock_for_warehouse(source_warehouse)
    return True


def consume_inventory_for_order(order, *, author=None):
    reservations = list(
        Reservation.objects.filter(
            linked_order=order,
            status__in=ACTIVE_RESERVATION_STATUSES,
        ).select_related('source_warehouse', 'source_cargo__destination_warehouse')
    )
    if not reservations:
        return False
    consumed_any = False
    for reservation in reservations:
        consumed_any = fulfill_reservation(reservation, author=author) or consumed_any
    return consumed_any


def create_or_update_shipment_for_order(order, *, author=None, reservation=None, tracking_number='', shipment=None):
    client_resolution = ensure_manager_client_for_order(order)
    client = client_resolution['client']
    try:
        deal = order.manager_deal
    except ManagerDeal.DoesNotExist:
        deal = None
    if reservation is None:
        reservation_candidates = list(
            order.manager_reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES)
            .select_related('source_warehouse', 'target_warehouse')
            .order_by('id')[:2]
        )
        if len(reservation_candidates) == 1:
            reservation = reservation_candidates[0]
    recipient_name = (
        order.recipient_name
        or order.shipping_contact_name
        or (deal.customer_name if deal is not None else '')
        or client.name
    )
    recipient_phone = (
        order.recipient_phone
        or order.shipping_phone
        or (deal.customer_phone if deal is not None else '')
        or client.phone
    )
    delivery_address = (
        order.display_address
        or (deal.delivery_full_address if deal is not None else '')
        or (deal.delivery_pickup_address if deal is not None else '')
        or client.address
    )
    source_warehouse = reservation_effective_warehouse(reservation) if reservation else (deal.stock_warehouse if deal is not None else None)
    target_warehouse = reservation.target_warehouse if reservation else (deal.stock_warehouse if deal is not None else None)
    defaults = {
        'manager_deal': deal,
        'client': client,
        'reservation': reservation,
        'source_warehouse': source_warehouse,
        'target_warehouse': target_warehouse,
        'delivery_method': _manager_delivery_method_for_order(order),
        'delivery_provider_name': deal.delivery_provider_name if deal is not None else '',
        'recipient_name': recipient_name,
        'recipient_phone': recipient_phone,
        'delivery_address': delivery_address,
        'planned_receipt_at': deal.planned_receipt_at if deal is not None else None,
        'delivery_payer': deal.delivery_payer if deal is not None else '',
        'tracking_number': tracking_number or '',
        'status': Shipment.STATUS_PENDING if order.status != Order.STATUS_DONE else Shipment.STATUS_DELIVERED,
        'comments': (deal.shipping_comment if deal is not None else '') or order.delivery_comment or '',
    }
    if shipment is None:
        shipment, _ = Shipment.objects.get_or_create(order=order, defaults=defaults)
    update_fields = []
    for field, value in defaults.items():
        if getattr(shipment, field) != value and value not in (None, ''):
            setattr(shipment, field, value)
            update_fields.append(field)
    if order.status == Order.STATUS_SHIPPING:
        shipped_at = timezone.now()
        if shipment.status != Shipment.STATUS_SHIPPED:
            shipment.status = Shipment.STATUS_SHIPPED
            update_fields.append('status')
        if not shipment.shipped_at:
            shipment.shipped_at = shipped_at
            update_fields.append('shipped_at')
    elif order.status == Order.STATUS_DONE:
        if shipment.status != Shipment.STATUS_DELIVERED:
            shipment.status = Shipment.STATUS_DELIVERED
            update_fields.append('status')
        if not shipment.delivered_at:
            shipment.delivered_at = timezone.now()
            update_fields.append('delivered_at')
    if tracking_number and shipment.tracking_number != tracking_number:
        shipment.tracking_number = tracking_number
        update_fields.append('tracking_number')
    if update_fields:
        update_fields.append('updated_at')
        shipment.save(update_fields=update_fields)

    ShipmentItem.objects.filter(shipment=shipment).delete()
    if reservation:
        for reservation_item in reservation.items.select_related('product', 'variant', 'order_item'):
            ShipmentItem.objects.create(
                shipment=shipment,
                order_item=reservation_item.order_item,
                reservation_item=reservation_item,
                product=reservation_item.product,
                variant=reservation_item.variant,
                quantity=reservation_item.quantity,
            )
    else:
        for order_item in order.items.select_related('product', 'variant'):
            if not order_item.product_id:
                continue
            ShipmentItem.objects.create(
                shipment=shipment,
                order_item=order_item,
                product=order_item.product,
                variant=order_item.variant,
                quantity=order_item.quantity,
            )
    if deal is not None:
        recompute_deal_workflow(deal, actor=author)
    return shipment


def sync_order_workflow_state(order, *, author=None):
    deal = ensure_manager_deal_for_order(order)
    if order.status in {Order.STATUS_SHIPPING, Order.STATUS_DONE}:
        create_or_update_shipment_for_order(order, author=author)
    recompute_deal_workflow(deal, actor=author)


def receive_cargo_item(cargo_item, *, quantity, author=None, comment=''):
    if not cargo_item.cargo.destination_warehouse_id:
        raise ValueError('У груза не указан склад назначения.')
    if quantity > cargo_item.remaining_quantity:
        raise ValueError('Нельзя принять больше, чем осталось в грузе.')
    with transaction.atomic():
        cargo_item.received_quantity += int(quantity)
        cargo_item.save(update_fields=['received_quantity'])
        if cargo_item.purchase_item_id:
            purchase_item = cargo_item.purchase_item
            purchase_item.received_quantity = min(
                purchase_item.received_quantity + int(quantity),
                purchase_item.quantity,
            )
            purchase_item.received_at = timezone.now()
            purchase_item.save(update_fields=['received_quantity', 'received_at'])
        receipt_inventory(
            warehouse=cargo_item.cargo.destination_warehouse,
            product=cargo_item.product,
            variant=cargo_item.variant,
            quantity=int(quantity),
            author=author,
            comment=comment or f'Приемка по грузу {cargo_item.cargo.cargo_number}',
            reference_type='cargo',
            reference_id=cargo_item.cargo_id,
        )
        if all(item.remaining_quantity == 0 for item in cargo_item.cargo.items.all()):
            cargo_item.cargo.status = Cargo.STATUS_RECEIVED
            cargo_item.cargo.save(update_fields=['status', 'updated_at'])
    if cargo_item.purchase_item_id and cargo_item.purchase_item.order_item_id:
        sync_order_workflow_state(cargo_item.purchase_item.order_item.order, author=author)


def split_cargo(cargo, *, cargo_number, cargo_item, quantity):
    if quantity >= cargo_item.remaining_quantity:
        raise ValueError('Для split количество должно быть меньше остатка по позиции.')
    with transaction.atomic():
        new_cargo = Cargo.objects.create(
            cargo_number=cargo_number,
            purchase=cargo.purchase,
            status=cargo.status,
            eta=cargo.eta,
            destination_warehouse=cargo.destination_warehouse,
            comments=f'Создано через split из {cargo.cargo_number}',
        )
        CargoItem.objects.create(
            cargo=new_cargo,
            product=cargo_item.product,
            variant=cargo_item.variant,
            purchase_item=cargo_item.purchase_item,
            quantity=quantity,
        )
        cargo_item.quantity -= quantity
        cargo_item.save(update_fields=['quantity'])
    return new_cargo


def dashboard_stats():
    inventory_rows = inventory_snapshot()
    overdue_cargos = Cargo.objects.filter(
        status__in=INBOUND_CARGO_STATUSES,
        eta__lt=timezone.localdate(),
    ).count()
    cargo_status_rows = list(
        Cargo.objects.values('status').annotate(total=models.Count('id')).order_by('status')
    )
    order_status_rows = list(
        Order.objects.values('status').annotate(total=models.Count('id')).order_by('status')
    )
    return {
        'new_orders': Order.objects.filter(status=Order.STATUS_NEW).count(),
        'cargos_in_transit': Cargo.objects.filter(status__in=INBOUND_CARGO_STATUSES).count(),
        'overdue_cargos': overdue_cargos,
        'active_reservations': Reservation.objects.filter(status__in=ACTIVE_RESERVATION_STATUSES).count(),
        'inventory_problem_rows': sum(1 for row in inventory_rows if row['has_problem']),
        'inventory_rows': inventory_rows[:8],
        'cargo_status_rows': cargo_status_rows,
        'order_status_rows': order_status_rows,
    }


def shipments_rows():
    rows = []
    reservations = Reservation.objects.filter(status__in=ACTIVE_RESERVATION_STATUSES).select_related(
        'client',
        'source_warehouse',
        'source_cargo',
        'target_warehouse',
    ).prefetch_related('items__product', 'items__variant')
    for reservation in reservations:
        for item in reservation.items.all():
            rows.append(
                {
                    'reservation': reservation,
                    'client': reservation.client,
                    'product': item.product,
                    'variant': item.variant,
                    'quantity': item.quantity,
                    'source_label': reservation.source_warehouse.name if reservation.source_type == Reservation.SOURCE_WAREHOUSE else reservation.source_cargo.cargo_number,
                    'target_warehouse': reservation.target_warehouse,
                }
            )
    return rows


def shipments_grouped_by_reservation(rows):
    grouped = []
    bucket = {}
    for row in rows:
        reservation_id = row['reservation'].pk
        if reservation_id not in bucket:
            bucket[reservation_id] = {
                'reservation': row['reservation'],
                'client': row['client'],
                'source_label': row['source_label'],
                'target_warehouse': row['target_warehouse'],
                'items': [],
                'items_total': 0,
            }
            grouped.append(bucket[reservation_id])
        bucket[reservation_id]['items'].append(row)
        bucket[reservation_id]['items_total'] += row['quantity']
    return grouped


def update_order_state(order, *, status, payment_status, request=None):
    previous_status = order.status
    previous_payment_status = order.payment_status
    changed_fields = []
    if order.status != status:
        order.status = status
        changed_fields.append('status')
    if order.payment_status != payment_status:
        order.payment_status = payment_status
        changed_fields.append('payment_status')
    if changed_fields:
        changed_fields.append('updated_at')
        order.save(update_fields=changed_fields)
        sync_order_state_side_effects(
            order,
            previous_status=previous_status,
            previous_payment_status=previous_payment_status,
            request=request,
        )


MONEY_ZERO = Decimal('0.00')
MONEY_QUANT = Decimal('0.01')
PERCENT_QUANT = Decimal('0.0001')


def _sum_decimal(queryset, field_name):
    value = queryset.aggregate(total=models.Sum(field_name)).get('total')
    return value if value is not None else MONEY_ZERO


def _quantize_money(value):
    return Decimal(value or 0).quantize(MONEY_QUANT)


def set_manager_deal_paid_amount(deal, *, paid_amount, changed_at=None, save=True):
    normalized_amount = _quantize_money(paid_amount)
    current_amount = _quantize_money(deal.prepayment_amount)
    amount_changed = current_amount != normalized_amount
    update_fields = []

    if amount_changed:
        deal.prepayment_amount = normalized_amount
        update_fields.append('prepayment_amount')

    if normalized_amount > MONEY_ZERO:
        if amount_changed or deal.last_payment_at is None:
            payment_time = changed_at or timezone.now()
            if deal.last_payment_at != payment_time:
                deal.last_payment_at = payment_time
                update_fields.append('last_payment_at')
    elif deal.last_payment_at is not None:
        deal.last_payment_at = None
        update_fields.append('last_payment_at')

    if save and update_fields:
        deal.save(update_fields=[*update_fields, 'updated_at'])
    return bool(update_fields)


def _quantize_percent(value):
    return Decimal(value or 0).quantize(PERCENT_QUANT)


def finance_period_bounds(*, year, month):
    year = int(year)
    month = int(month)
    start = date(year, 1, 1) if month == 0 else date(year, month, 1)
    if month == 0 or month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def finance_month_label(*, year, month):
    year = int(year)
    month = int(month)
    month_names = (
        'январь',
        'февраль',
        'март',
        'апрель',
        'май',
        'июнь',
        'июль',
        'август',
        'сентябрь',
        'октябрь',
        'ноябрь',
        'декабрь',
    )
    if month == 0:
        return f'{year} год'
    return f'{month_names[month - 1]} {year}'


def _normalize_finance_payment_state(value):
    return str(value or '').strip().lower()


def _finance_cash_metrics_for_deal(deal):
    revenue = Decimal(deal.revenue or 0)
    paid_amount = MONEY_ZERO
    debt_amount = MONEY_ZERO
    overdue_amount = MONEY_ZERO

    if deal.manager_deal_id:
        paid_amount = Decimal(deal.manager_deal.prepayment_amount or 0)
        debt_amount = revenue - paid_amount
        if debt_amount < 0:
            debt_amount = MONEY_ZERO
        problem_flags = set(deal.manager_deal.problem_flags or [])
        is_payment_open = deal.manager_deal.payment_state in {
            ManagerDeal.PAYMENT_STATE_UNPAID,
            ManagerDeal.PAYMENT_STATE_PARTIAL,
        }
        if (
            debt_amount > 0
            and ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE in problem_flags
            and (
                deal.manager_deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PAYMENT
                or is_payment_open
            )
        ):
            overdue_amount = debt_amount
        return paid_amount, debt_amount, overdue_amount

    payment_state = _normalize_finance_payment_state(deal.payment_state)
    if payment_state in {Order.PAYMENT_STATUS_PAID, 'finished'}:
        paid_amount = revenue
    elif payment_state not in {Order.PAYMENT_STATUS_REFUNDED, 'refunded'}:
        debt_amount = revenue
    return paid_amount, debt_amount, overdue_amount


def finance_dashboard_data(*, year, month):
    start, end = finance_period_bounds(year=year, month=month)
    deals = FinanceDeal.objects.filter(date__gte=start, date__lt=end).select_related(
        'deal_type',
        'created_by',
        'manager_deal',
    )
    expenses = FinanceExpense.objects.filter(date__gte=start, date__lt=end).select_related('category', 'deal', 'created_by')
    payouts = FinancePayout.objects.filter(date__gte=start, date__lt=end).select_related('created_by')

    turnover = _sum_decimal(deals, 'revenue')
    cost_of_goods = _sum_decimal(deals, 'cost_price')
    company_profit = _sum_decimal(deals, 'margin')
    total_opex = _sum_decimal(expenses.filter(deal__isnull=True, expense_side=FinanceExpense.SIDE_OURS), 'amount')
    partner_paid_physically = _sum_decimal(
        expenses.filter(deal__isnull=True, expense_side=FinanceExpense.SIDE_PARTNER),
        'amount',
    )
    total_opex_both = total_opex + partner_paid_physically
    total_opex_display = _sum_decimal(expenses.filter(expense_side=FinanceExpense.SIDE_OURS), 'amount')
    already_paid = _sum_decimal(payouts, 'amount')
    partner_rows, partner_profit = finance_partner_profit_by_direction(
        deals=deals,
        total_opex=total_opex_both,
    )
    net_profit = company_profit - total_opex_display
    final_payout = partner_profit - already_paid

    income_map = defaultdict(lambda: MONEY_ZERO)
    expense_map = defaultdict(lambda: MONEY_ZERO)
    cash_income_map = defaultdict(lambda: MONEY_ZERO)
    operating_expense_map = defaultdict(lambda: MONEY_ZERO)
    payout_map = defaultdict(lambda: MONEY_ZERO)
    paid_total = MONEY_ZERO
    receivables_total = MONEY_ZERO
    overdue_total = MONEY_ZERO
    paid_case_count = 0
    receivables_case_count = 0
    overdue_case_count = 0
    for deal in deals:
        income_map[deal.date] += deal.revenue
        paid_amount, debt_amount, overdue_amount = _finance_cash_metrics_for_deal(deal)
        cash_income_map[deal.date] += paid_amount
        paid_total += paid_amount
        receivables_total += debt_amount
        overdue_total += overdue_amount
        if paid_amount > 0:
            paid_case_count += 1
        if debt_amount > 0:
            receivables_case_count += 1
        if overdue_amount > 0:
            overdue_case_count += 1
    for expense in expenses:
        expense_map[expense.date] += expense.amount
        if expense.expense_side == FinanceExpense.SIDE_OURS:
            operating_expense_map[expense.date] += expense.amount
    for payout in payouts:
        payout_map[payout.date] += payout.amount

    daily_rows = []
    cashflow_rows = []
    cashflow_chart = {
        'labels': [],
        'income': [],
        'operating_expense': [],
        'payout': [],
        'balance': [],
    }
    running_balance = MONEY_ZERO
    current = start
    while current < end:
        income = _quantize_money(cash_income_map[current])
        operating_expense = _quantize_money(operating_expense_map[current])
        payout = _quantize_money(payout_map[current])
        outflow = operating_expense + payout
        net = income - outflow
        running_balance = _quantize_money(running_balance + net)
        daily_rows.append(
            {
                'date': current,
                'income': _quantize_money(income_map[current]),
                'expense': _quantize_money(expense_map[current]),
            }
        )
        cashflow_rows.append(
            {
                'date': current,
                'income': income,
                'operating_expense': operating_expense,
                'payout': payout,
                'outflow': _quantize_money(outflow),
                'net': _quantize_money(net),
                'balance': running_balance,
            }
        )
        cashflow_chart['labels'].append(current.strftime('%d.%m'))
        cashflow_chart['income'].append(str(income))
        cashflow_chart['operating_expense'].append(str(operating_expense))
        cashflow_chart['payout'].append(str(payout))
        cashflow_chart['balance'].append(str(running_balance))
        current += timedelta(days=1)

    cash_outflow_total = total_opex_display + already_paid
    cash_balance = paid_total - cash_outflow_total
    cashflow_activity_rows = [
        row for row in cashflow_rows
        if row['income'] or row['operating_expense'] or row['payout'] or row['net']
    ]

    return {
        'year': int(year),
        'month': int(month),
        'start': start,
        'end': end,
        'period_label': finance_month_label(year=year, month=month),
        'deals': list(deals),
        'expenses': list(expenses),
        'payouts': list(payouts),
        'turnover': _quantize_money(turnover),
        'cost_of_goods': _quantize_money(cost_of_goods),
        'company_profit': _quantize_money(company_profit),
        'net_profit': _quantize_money(net_profit),
        'total_opex': _quantize_money(total_opex),
        'partner_paid_physically': _quantize_money(partner_paid_physically),
        'total_opex_both': _quantize_money(total_opex_both),
        'total_opex_display': _quantize_money(total_opex_display),
        'partner_profit': _quantize_money(partner_profit),
        'already_paid': _quantize_money(already_paid),
        'final_payout': _quantize_money(final_payout),
        'cash_balance': _quantize_money(cash_balance),
        'cash_outflow_total': _quantize_money(cash_outflow_total),
        'paid_total': _quantize_money(paid_total),
        'receivables_total': _quantize_money(receivables_total),
        'overdue_total': _quantize_money(overdue_total),
        'paid_case_count': int(paid_case_count),
        'receivables_case_count': int(receivables_case_count),
        'overdue_case_count': int(overdue_case_count),
        'partner_rows': partner_rows,
        'daily_rows': daily_rows,
        'cashflow_rows': cashflow_rows,
        'cashflow_activity_rows': cashflow_activity_rows,
        'cashflow_chart': cashflow_chart,
        'has_cashflow_activity': bool(cashflow_activity_rows),
    }


def finance_partner_profit_by_direction(*, deals, total_opex):
    groups = {}
    for deal in deals:
        share = Decimal(deal.deal_type.partner_share or 0)
        group = groups.setdefault(
            share,
            {
                'share': share,
                'deal_types': set(),
                'margin': MONEY_ZERO,
            },
        )
        group['deal_types'].add(deal.deal_type.name)
        group['margin'] += Decimal(deal.margin or 0)

    rows = []
    total_margin = sum((group['margin'] for group in groups.values()), MONEY_ZERO)
    total_opex = Decimal(total_opex or 0)
    total_net = total_margin - total_opex
    weight_sum = sum((group['margin'] * group['share'] for group in groups.values()), MONEY_ZERO)

    for share, group in sorted(groups.items(), key=lambda item: (item[0], sorted(item[1]['deal_types']))):
        margin = group['margin']
        weight = margin * share
        if total_margin <= 0:
            net_profit = MONEY_ZERO
        elif weight_sum <= 0:
            net_profit = total_net * (margin / total_margin)
        else:
            net_profit = total_net * (weight / weight_sum)
        partner_profit = net_profit * share if net_profit > 0 else MONEY_ZERO
        opex_allocated = margin - net_profit
        rows.append(
            {
                'deal_type': ' + '.join(sorted(group['deal_types'])),
                'share': _quantize_percent(share),
                'margin': _quantize_money(margin),
                'weight': _quantize_money(weight),
                'weight_percent': _quantize_percent((weight / weight_sum * Decimal('100')) if weight_sum > 0 else MONEY_ZERO),
                'net_profit': _quantize_money(net_profit),
                'opex_allocated': _quantize_money(opex_allocated),
                'partner_profit': _quantize_money(partner_profit),
            }
        )
    return rows, _quantize_money(sum((row['partner_profit'] for row in rows), MONEY_ZERO))


def finance_report_archive():
    return {
        'deals': list(FinanceDeal.objects.select_related('deal_type', 'created_by').order_by('-date', '-id')),
        'expenses': list(FinanceExpense.objects.select_related('category', 'deal', 'created_by').order_by('-date', '-id')),
        'payouts': list(FinancePayout.objects.select_related('created_by').order_by('-date', '-id')),
    }


def _csv_bytes(fieldnames, rows):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode('utf-8-sig')


def build_finance_report_zip(*, year, month):
    data = finance_dashboard_data(year=year, month=month)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            'summary.csv',
            _csv_bytes(
                ['metric', 'value'],
                [
                    {'metric': 'period', 'value': data['period_label']},
                    {'metric': 'turnover', 'value': data['turnover']},
                    {'metric': 'cost_of_goods', 'value': data['cost_of_goods']},
                    {'metric': 'company_profit', 'value': data['company_profit']},
                    {'metric': 'net_profit', 'value': data['net_profit']},
                    {'metric': 'cash_balance', 'value': data['cash_balance']},
                    {'metric': 'receivables_total', 'value': data['receivables_total']},
                    {'metric': 'paid_total', 'value': data['paid_total']},
                    {'metric': 'overdue_total', 'value': data['overdue_total']},
                    {'metric': 'our_opex', 'value': data['total_opex']},
                    {'metric': 'partner_opex', 'value': data['partner_paid_physically']},
                    {'metric': 'partner_profit', 'value': data['partner_profit']},
                    {'metric': 'already_paid', 'value': data['already_paid']},
                    {'metric': 'final_payout', 'value': data['final_payout']},
                ],
            ),
        )
        archive.writestr(
            'deals.csv',
            _csv_bytes(
                ['id', 'date', 'contract_number', 'deal_type', 'revenue', 'cost_price', 'direct_expenses', 'manager_bonus', 'margin', 'partner_share_amount', 'comment'],
                [
                    {
                        'id': deal.id,
                        'date': deal.date,
                        'contract_number': deal.contract_number,
                        'deal_type': deal.deal_type.name,
                        'revenue': deal.revenue,
                        'cost_price': deal.cost_price,
                        'direct_expenses': deal.direct_expenses,
                        'manager_bonus': deal.manager_bonus,
                        'margin': deal.margin,
                        'partner_share_amount': deal.partner_share_amount,
                        'comment': deal.comment,
                    }
                    for deal in data['deals']
                ],
            ),
        )
        archive.writestr(
            'expenses.csv',
            _csv_bytes(
                ['id', 'side', 'date', 'category', 'amount', 'deal_id', 'who_paid', 'comment'],
                [
                    {
                        'id': expense.id,
                        'side': expense.expense_side,
                        'date': expense.date,
                        'category': expense.category.name,
                        'amount': expense.amount,
                        'deal_id': expense.deal_id or '',
                        'who_paid': expense.who_paid,
                        'comment': expense.comment,
                    }
                    for expense in data['expenses']
                ],
            ),
        )
        archive.writestr(
            'payouts.csv',
            _csv_bytes(
                ['id', 'date', 'amount', 'comment'],
                [
                    {
                        'id': payout.id,
                        'date': payout.date,
                        'amount': payout.amount,
                        'comment': payout.comment,
                    }
                    for payout in data['payouts']
                ],
            ),
        )
    buffer.seek(0)
    return buffer.getvalue()
