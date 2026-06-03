from collections import OrderedDict, defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from manager_portal.models import (
    Cargo,
    CargoItem,
    DealActivity,
    FinanceDeal,
    ManagerDeal,
    Purchase,
    PurchaseItem,
    Reservation,
    Shipment,
)
from manager_portal.services import (
    ACTIVE_RESERVATION_STATUSES,
    _manager_delivery_method_for_order,
    deal_manager_client,
    inventory_snapshot,
    order_supply_state_snapshot,
    recompute_deal_workflow,
    record_deal_activity,
    sync_order_item_planned_cost,
)
from orders.models import Order, OrderItem


OP_STATUS_NEEDS_REVIEW = 'needs_review'
OP_STATUS_NEEDS_LINK_PRODUCTS = 'needs_link_products'
OP_STATUS_NEEDS_SHIPPING_DATA = 'needs_shipping_data'
OP_STATUS_NEEDS_AVAILABILITY_CHECK = 'needs_availability_check'
OP_STATUS_NEEDS_PROCUREMENT = 'needs_procurement'
OP_STATUS_PARTIALLY_SECURED = 'partially_secured'
OP_STATUS_IN_TRANSIT = 'in_transit'
OP_STATUS_PARTIALLY_ARRIVED = 'partially_arrived'
OP_STATUS_READY_TO_SHIP = 'ready_to_ship'
OP_STATUS_IN_DELIVERY = 'in_delivery'
OP_STATUS_PROBLEMS = 'problems'
OP_STATUS_COMPLETED = 'completed'

OPS_TONE_CRITICAL = 'critical'
OPS_TONE_ATTENTION = 'attention'
OPS_TONE_WORKING = 'working'
OPS_TONE_INFO = 'info'
OPS_TONE_SUCCESS = 'success'
OPS_TONE_NEUTRAL = 'neutral'

HISTORY_FILTER_ALL = 'all'
HISTORY_FILTER_SYSTEM = 'system'
HISTORY_FILTER_USER = 'user'
HISTORY_FILTER_PURCHASES = 'purchases'
HISTORY_FILTER_CARGOS = 'cargos'
HISTORY_FILTER_SHIPMENTS = 'shipments'
HISTORY_FILTER_FINANCE = 'finance'

HISTORY_FILTER_DEFINITIONS = OrderedDict(
    [
        (HISTORY_FILTER_ALL, {'label': 'Все'}),
        (HISTORY_FILTER_SYSTEM, {'label': 'Система'}),
        (HISTORY_FILTER_USER, {'label': 'Пользователь'}),
        (HISTORY_FILTER_PURCHASES, {'label': 'Закупки'}),
        (HISTORY_FILTER_CARGOS, {'label': 'Грузы'}),
        (HISTORY_FILTER_SHIPMENTS, {'label': 'Отгрузки'}),
        (HISTORY_FILTER_FINANCE, {'label': 'Финансы'}),
    ]
)

OPERATION_STATUS_DEFINITIONS = OrderedDict(
    [
        (
            OP_STATUS_NEEDS_REVIEW,
            {
                'label': 'Нужно разобрать',
                'description': 'Сделка только пришла в операционный контур и требует первичного разбора.',
            },
        ),
        (
            OP_STATUS_NEEDS_LINK_PRODUCTS,
            {
                'label': 'Нужно связать товары',
                'description': 'Есть произвольные позиции без связи с каталогом сайта.',
            },
        ),
        (
            OP_STATUS_NEEDS_SHIPPING_DATA,
            {
                'label': 'Нужно запросить данные доставки',
                'description': 'Для отгрузки не хватает данных получателя или адреса.',
            },
        ),
        (
            OP_STATUS_NEEDS_AVAILABILITY_CHECK,
            {
                'label': 'Нужно проверить наличие',
                'description': 'Нужно подтвердить склад и доступный остаток до резервирования.',
            },
        ),
        (
            OP_STATUS_NEEDS_PROCUREMENT,
            {
                'label': 'Нужно закупить',
                'description': 'По сделке нет покрытия и нужно запустить закупку.',
            },
        ),
        (
            OP_STATUS_PARTIALLY_SECURED,
            {
                'label': 'Частично обеспечено',
                'description': 'Часть позиций уже закрыта, часть ещё ждёт обеспечение.',
            },
        ),
        (
            OP_STATUS_IN_TRANSIT,
            {
                'label': 'В пути',
                'description': 'Товар уже едет по связанным грузам.',
            },
        ),
        (
            OP_STATUS_PARTIALLY_ARRIVED,
            {
                'label': 'Частично приехало',
                'description': 'По закупке или грузу уже есть частичная приёмка.',
            },
        ),
        (
            OP_STATUS_READY_TO_SHIP,
            {
                'label': 'Готово к отправке',
                'description': 'Сделка обеспечена и может переходить в отгрузку.',
            },
        ),
        (
            OP_STATUS_IN_DELIVERY,
            {
                'label': 'В доставке',
                'description': 'Отгрузка уже создана и отправлена клиенту.',
            },
        ),
        (
            OP_STATUS_PROBLEMS,
            {
                'label': 'Проблемы',
                'description': 'Есть операционные блокеры, которые не стоит терять из виду.',
            },
        ),
        (
            OP_STATUS_COMPLETED,
            {
                'label': 'Сделка исполнена',
                'description': 'Все релевантные позиции закрыты, а доставка подтверждена.',
            },
        ),
    ]
)

SEVERE_PROBLEM_FLAGS = {
    ManagerDeal.PROBLEM_FLAG_NO_ASSIGNEE,
    ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE,
    ManagerDeal.PROBLEM_FLAG_STALE_UPDATES,
    ManagerDeal.PROBLEM_FLAG_PAYMENT_BLOCKED,
    ManagerDeal.PROBLEM_FLAG_SHIPMENT_BLOCKED,
}
IN_TRANSIT_CARGO_STATUSES = {
    Cargo.STATUS_IN_TRANSIT,
    Cargo.STATUS_ARRIVED_RF,
    Cargo.STATUS_DELIVERY_RF,
    Cargo.STATUS_AWAITING_RECEIPT,
}


def history_filter_choices():
    return [(code, meta['label']) for code, meta in HISTORY_FILTER_DEFINITIONS.items()]


def ops_tone_for_operation_status(code):
    return {
        OP_STATUS_NEEDS_REVIEW: OPS_TONE_NEUTRAL,
        OP_STATUS_NEEDS_LINK_PRODUCTS: OPS_TONE_ATTENTION,
        OP_STATUS_NEEDS_SHIPPING_DATA: OPS_TONE_ATTENTION,
        OP_STATUS_NEEDS_AVAILABILITY_CHECK: OPS_TONE_INFO,
        OP_STATUS_NEEDS_PROCUREMENT: OPS_TONE_WORKING,
        OP_STATUS_PARTIALLY_SECURED: OPS_TONE_WORKING,
        OP_STATUS_IN_TRANSIT: OPS_TONE_INFO,
        OP_STATUS_PARTIALLY_ARRIVED: OPS_TONE_WORKING,
        OP_STATUS_READY_TO_SHIP: OPS_TONE_SUCCESS,
        OP_STATUS_IN_DELIVERY: OPS_TONE_INFO,
        OP_STATUS_PROBLEMS: OPS_TONE_CRITICAL,
        OP_STATUS_COMPLETED: OPS_TONE_SUCCESS,
    }.get(code, OPS_TONE_NEUTRAL)


def ops_tone_for_fulfillment_status(status):
    return {
        ManagerDeal.FULFILLMENT_STATUS_NOT_RESERVED: OPS_TONE_NEUTRAL,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK: OPS_TONE_SUCCESS,
        ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING: OPS_TONE_INFO,
        ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED: OPS_TONE_WORKING,
        ManagerDeal.FULFILLMENT_STATUS_FULFILLED: OPS_TONE_SUCCESS,
    }.get(status, OPS_TONE_NEUTRAL)


def ops_tone_for_delivery_status(status):
    return {
        ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED: OPS_TONE_NEUTRAL,
        ManagerDeal.DELIVERY_STATUS_PREPARING: OPS_TONE_WORKING,
        ManagerDeal.DELIVERY_STATUS_READY: OPS_TONE_SUCCESS,
        ManagerDeal.DELIVERY_STATUS_SHIPPED: OPS_TONE_INFO,
        ManagerDeal.DELIVERY_STATUS_DELIVERED: OPS_TONE_SUCCESS,
    }.get(status, OPS_TONE_NEUTRAL)


def ops_tone_for_purchase_status(status):
    return {
        Purchase.STATUS_DRAFT: OPS_TONE_NEUTRAL,
        Purchase.STATUS_ORDERED: OPS_TONE_WORKING,
        Purchase.STATUS_PARTIAL: OPS_TONE_WORKING,
        Purchase.STATUS_RECEIVED: OPS_TONE_SUCCESS,
        Purchase.STATUS_CANCELLED: OPS_TONE_CRITICAL,
    }.get(status, OPS_TONE_NEUTRAL)


def ops_tone_for_cargo_status(status):
    return {
        Cargo.STATUS_CREATED: OPS_TONE_NEUTRAL,
        Cargo.STATUS_IN_TRANSIT: OPS_TONE_INFO,
        Cargo.STATUS_ARRIVED_RF: OPS_TONE_INFO,
        Cargo.STATUS_DELIVERY_RF: OPS_TONE_WORKING,
        Cargo.STATUS_AWAITING_RECEIPT: OPS_TONE_ATTENTION,
        Cargo.STATUS_RECEIVED: OPS_TONE_SUCCESS,
        Cargo.STATUS_CANCELLED: OPS_TONE_CRITICAL,
    }.get(status, OPS_TONE_NEUTRAL)


def ops_tone_for_shipment_status(status):
    return {
        Shipment.STATUS_DRAFT: OPS_TONE_NEUTRAL,
        Shipment.STATUS_PENDING: OPS_TONE_WORKING,
        Shipment.STATUS_SHIPPED: OPS_TONE_INFO,
        Shipment.STATUS_DELIVERED: OPS_TONE_SUCCESS,
        Shipment.STATUS_CANCELLED: OPS_TONE_CRITICAL,
    }.get(status, OPS_TONE_NEUTRAL)


def ops_tone_for_reservation_status(status):
    return {
        Reservation.STATUS_DRAFT: OPS_TONE_NEUTRAL,
        Reservation.STATUS_ACTIVE: OPS_TONE_INFO,
        Reservation.STATUS_PARTIAL: OPS_TONE_WORKING,
        Reservation.STATUS_RELEASED: OPS_TONE_NEUTRAL,
        Reservation.STATUS_FULFILLED: OPS_TONE_SUCCESS,
        Reservation.STATUS_CANCELLED: OPS_TONE_CRITICAL,
        Reservation.STATUS_EXPIRED: OPS_TONE_ATTENTION,
    }.get(status, OPS_TONE_NEUTRAL)


def operation_status_choices():
    return [(code, meta['label']) for code, meta in OPERATION_STATUS_DEFINITIONS.items()]


def operation_status_label(code):
    return OPERATION_STATUS_DEFINITIONS.get(code, {}).get('label', code)


def operations_deals_queryset():
    return (
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse')
        .prefetch_related('order__items__product', 'order__items__variant')
        .exclude(case_status__in=[ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED])
        .order_by('sla_due_at', '-last_activity_at', '-deal_created_at', '-id')
    )


def related_purchases_queryset(deal):
    return (
        Purchase.objects.filter(items__order_item__order=deal.order)
        .prefetch_related('items__product', 'items__variant', 'items__order_item')
        .distinct()
        .order_by('-date', '-id')
    )


def latest_purchase_item_for_order_item(order_item):
    return (
        PurchaseItem.objects.select_related('purchase', 'product', 'variant', 'order_item')
        .filter(order_item=order_item)
        .exclude(purchase__status=Purchase.STATUS_CANCELLED)
        .order_by('-purchase__date', '-purchase_id', '-id')
        .first()
    )


def related_cargos_queryset(deal):
    return (
        Cargo.objects.filter(
            Q(items__purchase_item__order_item__order=deal.order)
            | Q(cargo_reservations__linked_order=deal.order)
        )
        .select_related('purchase', 'destination_warehouse')
        .prefetch_related('items__product', 'items__variant', 'items__purchase_item', 'items__purchase_item__order_item')
        .distinct()
        .order_by('-created_at', '-id')
    )


def related_reservations_queryset(deal):
    return (
        deal.reservations.select_related('source_warehouse', 'source_cargo', 'target_warehouse')
        .prefetch_related('items__product', 'items__variant', 'items__order_item')
        .order_by('-created_at', '-id')
    )


def related_shipments_queryset(deal):
    return (
        deal.shipments.select_related('reservation', 'source_warehouse', 'target_warehouse')
        .prefetch_related('items__product', 'items__variant', 'items__order_item')
        .exclude(status=Shipment.STATUS_CANCELLED)
        .order_by('-created_at', '-id')
    )


def operation_detail_relations(deal):
    purchases = list(related_purchases_queryset(deal))
    cargos = list(related_cargos_queryset(deal))
    reservations = list(related_reservations_queryset(deal))
    shipments = list(related_shipments_queryset(deal))
    activities = list(deal.activities.select_related('actor', 'manager_deal').order_by('-created_at', '-id')[:120])
    finance_deal = FinanceDeal.objects.filter(manager_deal=deal).first()
    return {
        'purchases': purchases,
        'cargos': cargos,
        'reservations': reservations,
        'shipments': shipments,
        'activities': activities,
        'finance_deal': finance_deal,
    }


def reservation_candidates_for_deal(deal):
    supply_snapshot = order_supply_state_snapshot(deal.order)
    inventory_rows = inventory_snapshot()
    rows_by_product = OrderedDict()
    for row in inventory_rows:
        available = max(int(row['available'] or 0), 0)
        if available <= 0:
            continue
        key = (row['product_id'], row['variant_id'] or 0)
        rows_by_product.setdefault(key, []).append(
            {
                'warehouse_id': row['warehouse_id'],
                'warehouse_name': row['warehouse_name'],
                'available': available,
            }
        )

    received_warehouses_by_order_item = defaultdict(lambda: defaultdict(int))
    for cargo_item in (
        CargoItem.objects.filter(
            purchase_item__order_item__order=deal.order,
            received_quantity__gt=0,
            cargo__destination_warehouse__isnull=False,
        )
        .select_related('cargo__destination_warehouse', 'purchase_item__order_item')
        .order_by('cargo__destination_warehouse__name', 'cargo_id', 'id')
    ):
        order_item = cargo_item.purchase_item.order_item if cargo_item.purchase_item_id else None
        if order_item is None:
            continue
        received_warehouses_by_order_item[order_item.id][
            (cargo_item.cargo.destination_warehouse_id, cargo_item.cargo.destination_warehouse.name)
        ] += int(cargo_item.received_quantity or 0)

    candidates = OrderedDict()
    for line in supply_snapshot['lines']:
        item = line['item']
        if not line['is_supply_tracked'] or not item.product_id:
            continue
        missing_quantity = _line_reservation_outstanding_quantity(line)
        if missing_quantity <= 0:
            continue
        warehouses = list(rows_by_product.get((item.product_id, item.variant_id or 0), []))
        if not warehouses and int(line['cargo_received_quantity'] or 0) > 0:
            fallback_rows = received_warehouses_by_order_item.get(item.id, {})
            fallback_total = min(
                max(
                    int(line['cargo_received_quantity'] or 0)
                    - int(line['reserved_quantity'] or 0)
                    - int(line['shipment_quantity'] or 0),
                    0,
                ),
                missing_quantity,
            )
            normalized_fallback_rows = []
            remaining_fallback = fallback_total
            for (warehouse_id, warehouse_name), warehouse_available in fallback_rows.items():
                if remaining_fallback <= 0:
                    break
                take = min(int(warehouse_available or 0), remaining_fallback)
                if take <= 0:
                    continue
                normalized_fallback_rows.append(
                    {
                        'warehouse_id': warehouse_id,
                        'warehouse_name': warehouse_name,
                        'available': take,
                    }
                )
                remaining_fallback -= take
            warehouses = normalized_fallback_rows
        if not warehouses:
            continue
        total_available = sum(int(entry['available'] or 0) for entry in warehouses)
        candidates[item.id] = {
            'order_item': item,
            'product': item.product,
            'variant': item.variant,
            'ordered_quantity': int(line['ordered_quantity'] or 0),
            'reserved_quantity': int(line['reserved_quantity'] or 0),
            'missing_quantity': missing_quantity,
            'warehouses': warehouses,
            'total_available': min(total_available, missing_quantity),
        }
    return candidates


def _purchase_total_amount(purchase):
    return sum(
        (Decimal(item.unit_cost or 0) * Decimal(item.active_quantity or 0) for item in purchase.items.all()),
        Decimal('0'),
    )


def purchase_initial_data_for_order_item(deal, order_item):
    existing_purchase_item = latest_purchase_item_for_order_item(order_item)
    default_currency = Purchase._meta.get_field('currency').default
    default_status = Purchase.STATUS_DRAFT
    missing_quantity = int(order_item.active_quantity or order_item.quantity or 1)
    supply_snapshot = order_supply_state_snapshot(deal.order)
    for line in supply_snapshot['lines']:
        if line['item'].pk != order_item.pk:
            continue
        ordered = int(line['ordered_quantity'] or 0)
        progress = _line_supply_progress(line)
        missing_quantity = max(ordered - progress, 0) or ordered or missing_quantity
        break

    if existing_purchase_item is not None:
        purchase = existing_purchase_item.purchase
        return {
            'supplier_name': purchase.supplier_name,
            'quantity': existing_purchase_item.quantity,
            'unit_cost': existing_purchase_item.unit_cost,
            'currency': purchase.currency or default_currency,
            'status': purchase.status or default_status,
            'comments': purchase.comments,
        }, existing_purchase_item

    unit_cost = order_item.planned_unit_cost or order_item.effective_unit_cost or Decimal('0')
    return {
        'supplier_name': deal.supplier_name or '',
        'quantity': max(missing_quantity, 1),
        'unit_cost': unit_cost,
        'currency': default_currency,
        'status': default_status,
        'comments': '',
    }, None


@transaction.atomic
def upsert_purchase_for_order_item(
    deal,
    order_item,
    *,
    supplier_name,
    quantity,
    unit_cost,
    currency,
    status,
    comments,
    actor=None,
):
    existing_purchase_item = latest_purchase_item_for_order_item(order_item)
    created = existing_purchase_item is None
    supplier_name = (supplier_name or '').strip()
    currency = (currency or Purchase._meta.get_field('currency').default).strip()
    status = (status or Purchase.STATUS_DRAFT).strip() or Purchase.STATUS_DRAFT
    comments = (comments or '').strip()
    if not supplier_name:
        raise ValueError('Укажите поставщика.')
    if quantity is None or int(quantity) <= 0:
        raise ValueError('Количество в закупке должно быть больше нуля.')
    if unit_cost is None or Decimal(unit_cost) < 0:
        raise ValueError('Цена закупки не может быть отрицательной.')

    purchase = existing_purchase_item.purchase if existing_purchase_item is not None else Purchase(
        date=timezone.localdate(),
    )
    purchase.supplier_name = supplier_name
    purchase.agent = deal.supplier_agent or purchase.agent or ''
    purchase.currency = currency
    purchase.status = status
    purchase.comments = comments
    if not purchase.date:
        purchase.date = timezone.localdate()
    purchase.save()

    purchase_item = existing_purchase_item or PurchaseItem(
        purchase=purchase,
        product=order_item.product,
        variant=order_item.variant,
        order_item=order_item,
    )
    purchase_item.purchase = purchase
    purchase_item.product = order_item.product
    purchase_item.variant = order_item.variant
    purchase_item.order_item = order_item
    purchase_item.quantity = quantity
    purchase_item.unit_cost = unit_cost
    purchase_item.save()

    purchase.total_amount = _purchase_total_amount(purchase)
    purchase.save(update_fields=['total_amount', 'updated_at'])
    sync_order_item_planned_cost(order_item)

    record_deal_activity(
        deal,
        event_type='operations.purchase_created' if created else 'operations.purchase_updated',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'purchase_id': purchase.id,
            'purchase_item_id': purchase_item.id,
            'order_item_id': order_item.id,
        },
    )
    recompute_deal_workflow(deal, actor=actor)
    return purchase, purchase_item, created


def _delivery_field_issues(deal):
    if not deal.requires_delivery_workflow:
        return []
    order = deal.order
    missing = []
    if not _is_present(order.recipient_name or order.shipping_contact_name or deal.customer_name):
        missing.append('Не указано имя получателя')
    if not _is_present(order.recipient_phone or order.shipping_phone or deal.customer_phone):
        missing.append('Не указан телефон получателя')
    if not _is_present(order.display_address or deal.delivery_full_address or deal.delivery_pickup_address):
        missing.append('Не указан адрес доставки')
    return missing


def _line_supply_progress(line):
    return max(
        int(line['reserved_quantity'] or 0),
        int(line['purchase_quantity'] or 0),
        int(line['cargo_quantity'] or 0),
        int(line['shipment_quantity'] or 0),
    )


def _line_reservation_outstanding_quantity(line):
    ordered_quantity = int(line['ordered_quantity'] or 0)
    reserved_quantity = int(line['reserved_quantity'] or 0)
    shipped_quantity = int(line['shipment_quantity'] or 0)
    return max(ordered_quantity - shipped_quantity - reserved_quantity, 0)


def _line_reservation_satisfied(line):
    ordered_quantity = int(line['ordered_quantity'] or 0)
    if ordered_quantity <= 0:
        return True
    return _line_reservation_outstanding_quantity(line) <= 0


def _supply_flags(supply_snapshot):
    tracked_lines = [line for line in supply_snapshot['lines'] if line['is_supply_tracked']]
    custom_lines = [line for line in supply_snapshot['lines'] if not line['is_supply_tracked']]
    has_uncovered = False
    has_partial_supply = False
    for line in tracked_lines:
        ordered = int(line['ordered_quantity'] or 0)
        progress = _line_supply_progress(line)
        if ordered > 0 and progress <= 0:
            has_uncovered = True
        elif 0 < progress < ordered:
            has_partial_supply = True
    return {
        'tracked_lines': tracked_lines,
        'custom_lines': custom_lines,
        'has_uncovered': has_uncovered,
        'has_partial_supply': has_partial_supply,
    }


def _format_count(value, one, few, many):
    value = abs(int(value or 0))
    tail = value % 100
    if 11 <= tail <= 14:
        return many
    tail = value % 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _has_recipient(deal):
    order = deal.order
    return _is_present(order.recipient_name or order.shipping_contact_name or deal.customer_name or order.first_name)


def _has_recipient_phone(deal):
    order = deal.order
    return _is_present(order.recipient_phone or order.shipping_phone or deal.customer_phone or order.phone)


def _has_delivery_address(deal):
    if not deal.requires_delivery_workflow:
        return True
    order = deal.order
    return _is_present(order.display_address or deal.delivery_full_address or deal.delivery_pickup_address)


def _is_present(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _finance_is_filled(finance_deal):
    if finance_deal is None:
        return False
    return any(
        Decimal(value or 0) > 0
        for value in (finance_deal.revenue, finance_deal.cost_of_goods, finance_deal.direct_expenses)
    )


CHECK_STATE_OK = 'ok'
CHECK_STATE_ATTENTION = 'attention'
CHECK_STATE_NOT_REQUIRED = 'not_required'


def _checklist_item(code, label, *, state, ok_detail, attention_detail, not_required_detail='Не требуется для этой сделки.'):
    is_ok = state != CHECK_STATE_ATTENTION
    status_labels = {
        CHECK_STATE_OK: 'OK',
        CHECK_STATE_ATTENTION: 'Требует внимания',
        CHECK_STATE_NOT_REQUIRED: 'Не требуется',
    }
    tones = {
        CHECK_STATE_OK: OPS_TONE_SUCCESS,
        CHECK_STATE_ATTENTION: OPS_TONE_ATTENTION,
        CHECK_STATE_NOT_REQUIRED: OPS_TONE_NEUTRAL,
    }
    details = {
        CHECK_STATE_OK: ok_detail,
        CHECK_STATE_ATTENTION: attention_detail,
        CHECK_STATE_NOT_REQUIRED: not_required_detail,
    }
    return {
        'code': code,
        'label': label,
        'state': state,
        'is_ok': bool(is_ok),
        'needs_attention': state == CHECK_STATE_ATTENTION,
        'status_label': status_labels[state],
        'tone': tones[state],
        'detail': details[state],
    }


def _pending_cargo_receipt_groups(cargos, *, order_id):
    groups = []
    for cargo in cargos:
        items = []
        for cargo_item in cargo.items.all():
            purchase_item = cargo_item.purchase_item
            order_item = purchase_item.order_item if purchase_item and purchase_item.order_item_id else None
            if order_item is not None and order_item.order_id != order_id:
                continue
            if cargo_item.remaining_quantity <= 0:
                continue
            items.append(cargo_item)
        if items:
            groups.append({'cargo': cargo, 'items': items})
    groups.sort(
        key=lambda row: (
            0 if row['cargo'].status == Cargo.STATUS_AWAITING_RECEIPT else 1,
            row['cargo'].eta or timezone.localdate(),
            row['cargo'].id,
        )
    )
    return groups


def _ops_progress_detail(done, total, noun):
    return f'{done}/{total} {noun}.'


def _ops_deal_completed(deal, *, relations, supply_flags):
    shipments = [shipment for shipment in relations['shipments'] if shipment.status != Shipment.STATUS_CANCELLED]
    all_shipments_delivered = bool(shipments) and all(shipment.status == Shipment.STATUS_DELIVERED for shipment in shipments)
    tracked_lines = supply_flags['tracked_lines']
    tracked_lines_fully_shipped = all(
        int(line['shipment_quantity'] or 0) >= int(line['ordered_quantity'] or 0)
        for line in tracked_lines
    ) if tracked_lines else True
    return bool(
        deal.case_status == ManagerDeal.CASE_STATUS_COMPLETED
        or deal.next_step_code == ManagerDeal.NEXT_STEP_COMPLETED
        or (
            deal.delivery_status == ManagerDeal.DELIVERY_STATUS_DELIVERED
            and all_shipments_delivered
            and tracked_lines_fully_shipped
        )
    )


def _operation_checklist(deal, *, relations, supply_flags, all_tracked_fully_covered):
    finance_deal = relations['finance_deal']
    total_lines = len(supply_flags['tracked_lines']) + len(supply_flags['custom_lines'])
    custom_count = len(supply_flags['custom_lines'])
    catalog_linked = custom_count == 0
    catalog_linked_count = max(total_lines - custom_count, 0)
    delivery_ready = _has_recipient(deal) and _has_recipient_phone(deal) and _has_delivery_address(deal)
    tracked_lines = supply_flags['tracked_lines']
    tracked_line_count = len(tracked_lines)
    secured_count = sum(
        1 for line in tracked_lines
        if int(line['ordered_quantity'] or 0) <= 0 or _line_supply_progress(line) >= int(line['ordered_quantity'] or 0)
    )
    reserved_count = sum(
        1 for line in tracked_lines
        if _line_reservation_satisfied(line)
    )
    shipped_count = sum(
        1 for line in tracked_lines
        if int(line['ordered_quantity'] or 0) <= 0 or int(line['shipment_quantity'] or 0) >= int(line['ordered_quantity'] or 0)
    )
    purchase_items = [
        purchase_item
        for purchase in relations['purchases']
        for purchase_item in purchase.items.all()
        if purchase_item.order_item_id and purchase_item.order_item.order_id == deal.order_id
    ]
    purchase_lines_without_cargo = [
        purchase_item
        for purchase_item in purchase_items
        if purchase_item.remaining_quantity > 0 and purchase_item_cargo_allocated_quantity(purchase_item) <= 0
    ]
    cargo_items = [
        cargo_item
        for cargo in relations['cargos']
        for cargo_item in cargo.items.all()
        if cargo_item.purchase_item_id and cargo_item.purchase_item.order_item_id and cargo_item.purchase_item.order_item.order_id == deal.order_id
    ]
    secured = catalog_linked and all_tracked_fully_covered
    shipment_created = bool(relations['shipments'])
    finance_filled = _finance_is_filled(finance_deal)
    purchases_required = any(
        int(line['ordered_quantity'] or 0) > _line_supply_progress(line)
        and int(line['free_stock'] or 0) <= int(line['reserved_quantity'] or 0)
        for line in tracked_lines
    )
    purchases_created = bool(purchase_items)
    cargos_required = purchases_created
    cargos_ready = not purchase_lines_without_cargo
    cargos_have_progress = bool(cargo_items)
    purchases_state = (
        CHECK_STATE_OK
        if purchases_created and not purchases_required
        else CHECK_STATE_ATTENTION
        if purchases_required and not purchases_created
        else CHECK_STATE_NOT_REQUIRED
    )
    if purchases_created and purchases_required:
        purchases_state = CHECK_STATE_OK
    cargos_state = (
        CHECK_STATE_OK
        if cargos_required and (cargos_ready or cargos_have_progress)
        else CHECK_STATE_ATTENTION
        if cargos_required
        else CHECK_STATE_NOT_REQUIRED
    )
    reservation_state = (
        CHECK_STATE_NOT_REQUIRED
        if tracked_line_count == 0
        else CHECK_STATE_OK
        if reserved_count >= tracked_line_count
        else CHECK_STATE_ATTENTION
    )
    shipment_state = (
        CHECK_STATE_NOT_REQUIRED
        if tracked_line_count == 0 and not shipment_created
        else CHECK_STATE_OK
        if shipment_created and shipped_count >= tracked_line_count
        else CHECK_STATE_ATTENTION
        if secured
        else CHECK_STATE_NOT_REQUIRED
    )

    return [
        _checklist_item(
            'assignee',
            'Ответственный назначен',
            state=CHECK_STATE_OK if deal.responsible_manager_id else CHECK_STATE_ATTENTION,
            ok_detail=f'Сделка закреплена за {deal.responsible_manager}.',
            attention_detail='Назначьте ответственного, чтобы сделка не зависла без владельца.',
        ),
        _checklist_item(
            'catalog_links',
            'Все товары связаны с каталогом',
            state=CHECK_STATE_OK if catalog_linked else CHECK_STATE_ATTENTION,
            ok_detail=_ops_progress_detail(catalog_linked_count, total_lines, 'товарных строк связаны с каталогом'),
            attention_detail=(
                f'{_ops_progress_detail(catalog_linked_count, total_lines, "товарных строк связаны с каталогом")} '
                f'Нужно связать ещё {custom_count} '
                f'{_format_count(custom_count, "товар", "товара", "товаров")} с каталогом сайта.'
            ),
        ),
        _checklist_item(
            'delivery',
            'Данные доставки заполнены',
            state=(
                CHECK_STATE_NOT_REQUIRED
                if not deal.requires_delivery_workflow
                else CHECK_STATE_OK
                if delivery_ready
                else CHECK_STATE_ATTENTION
            ),
            ok_detail='Получатель, телефон и адрес готовы для отгрузки.',
            attention_detail='Заполните получателя, телефон и адрес доставки.',
            not_required_detail='Для этой сделки доставка не требуется.',
        ),
        _checklist_item(
            'secured',
            'Все позиции обеспечены',
            state=CHECK_STATE_OK if secured else CHECK_STATE_ATTENTION,
            ok_detail=_ops_progress_detail(secured_count, total_lines, 'позиций обеспечено'),
            attention_detail=(
                f'{_ops_progress_detail(secured_count, total_lines, "позиций обеспечено")} '
                'Есть позиции без резерва, закупки, груза или отгрузки.'
            ),
            not_required_detail='В сделке нет supply-позиций.',
        ),
        _checklist_item(
            'purchases',
            'Закупки созданы',
            state=purchases_state,
            ok_detail='Для нужных позиций закупки уже заведены.',
            attention_detail='Есть позиции, которым нужна закупка.',
            not_required_detail='Сделка закрывается без закупки: хватает складского остатка или это не supply-позиции.',
        ),
        _checklist_item(
            'cargos',
            'Грузы созданы / в пути / приняты',
            state=cargos_state,
            ok_detail='По закупке уже есть грузовой контур или приемка.',
            attention_detail='По закупке еще не создан груз или не начато движение.',
            not_required_detail='Грузы не нужны, потому что закупка по сделке не требуется.',
        ),
        _checklist_item(
            'reservation',
            'Резерв создан',
            state=reservation_state,
            ok_detail=_ops_progress_detail(reserved_count, total_lines, 'позиций зарезервировано'),
            attention_detail=(
                f'{_ops_progress_detail(reserved_count, total_lines, "позиций зарезервировано")} '
                'На складе есть остаток или incoming, который ещё не закреплён за сделкой.'
            ),
            not_required_detail='Резерв не требуется: в сделке нет складских позиций.',
        ),
        _checklist_item(
            'shipment',
            'Отгрузка создана',
            state=shipment_state,
            ok_detail=_ops_progress_detail(shipped_count, total_lines, 'позиций отгружено'),
            attention_detail=(
                f'{_ops_progress_detail(shipped_count, total_lines, "позиций отгружено")} '
                'Создайте или проведите отгрузку по оставшимся строкам.'
            ),
            not_required_detail='До отгрузки еще рано: сначала нужно обеспечить позиции.',
        ),
        _checklist_item(
            'finance',
            'Финансы заполнены',
            state=CHECK_STATE_OK if finance_filled else CHECK_STATE_ATTENTION,
            ok_detail='Финансовый кейс заведен.',
            attention_detail='Создайте или заполните финансовый кейс.',
        ),
    ]


def _action_candidate(
    code,
    priority,
    text,
    reason,
    *,
    blocker='',
    cta_label='',
    item_id=None,
    purchase_item_id=None,
    cargo_item_id=None,
    purchase_id=None,
    shipment_id=None,
):
    return {
        'code': code,
        'priority': int(priority),
        'text': text,
        'reason': reason,
        'blocker': blocker,
        'cta_label': cta_label or text,
        'item_id': item_id,
        'purchase_item_id': purchase_item_id,
        'cargo_item_id': cargo_item_id,
        'purchase_id': purchase_id,
        'shipment_id': shipment_id,
    }


def _operation_action_candidates(
    deal,
    *,
    relations,
    supply_flags,
    all_tracked_fully_covered,
    severe_problem_flags,
):
    missing_delivery_fields = _delivery_field_issues(deal)
    reservation_candidates = reservation_candidates_for_deal(deal)
    custom_count = len(supply_flags['custom_lines'])
    pending_cargo_groups = _pending_cargo_receipt_groups(relations['cargos'], order_id=deal.order_id)
    tracked_lines = supply_flags['tracked_lines']
    custom_items = [line['item'] for line in supply_flags['custom_lines']]
    uncovered_lines = [
        line
        for line in tracked_lines
        if int(line['ordered_quantity'] or 0) > _line_supply_progress(line)
    ]
    first_custom_item = custom_items[0] if custom_items else None
    reserve_ready_lines = list(reservation_candidates.values())
    first_reserve_ready_line = reserve_ready_lines[0] if reserve_ready_lines else None
    uncovered_purchase_lines = [
        line
        for line in uncovered_lines
        if int(line['free_stock'] or 0) <= int(line['reserved_quantity'] or 0)
    ]
    purchase_items = [
        purchase_item
        for purchase in relations['purchases']
        for purchase_item in purchase.items.all()
        if purchase_item.order_item_id and purchase_item.order_item.order_id == deal.order_id
    ]
    cargo_ready_purchase_items = [
        purchase_item
        for purchase_item in purchase_items
        if purchase_item_cargo_available_quantity(purchase_item) > 0
    ]
    shipments = relations['shipments']
    shipment_without_tracking = next(
        (
            shipment
            for shipment in shipments
            if shipment.status != Shipment.STATUS_CANCELLED and not (shipment.tracking_number or '').strip()
        ),
        None,
    )
    pending_shipment = next(
        (
            shipment
            for shipment in shipments
            if shipment.status in {Shipment.STATUS_DRAFT, Shipment.STATUS_PENDING}
            and shipment.inventory_consumed_at is None
        ),
        None,
    )
    shipped_shipment = next(
        (shipment for shipment in shipments if shipment.status == Shipment.STATUS_SHIPPED),
        None,
    )
    all_shipments_delivered = bool(shipments) and all(
        shipment.status == Shipment.STATUS_DELIVERED for shipment in shipments
    )
    checklist = _operation_checklist(
        deal,
        relations=relations,
        supply_flags=supply_flags,
        all_tracked_fully_covered=all_tracked_fully_covered,
    )
    checklist_map = {item['code']: item for item in checklist}
    missing_delivery_fields = _delivery_field_issues(deal)
    if _ops_deal_completed(deal, relations=relations, supply_flags=supply_flags):
        return [
            _action_candidate(
                'deal_completed',
                0,
                'Сделка исполнена',
                'Все релевантные позиции закрыты, а доставка подтверждена.',
                cta_label='Сделка исполнена',
            )
        ], checklist, pending_cargo_groups
    candidates = []

    if custom_count:
        candidates.append(
            _action_candidate(
                'link_products',
                10,
                f'Связать {custom_count} {_format_count(custom_count, "товар", "товара", "товаров")} с каталогом',
                'Пока позиция остается custom, складские действия, закупка и отгрузка по ней ограничены.',
                blocker='Не все товары связаны с каталогом сайта',
                cta_label='Связать товар',
                item_id=first_custom_item.id if first_custom_item else None,
            )
        )
    if deal.responsible_manager_id is None:
        candidates.append(
            _action_candidate(
                'assign_self',
                15,
                'Назначить себя ответственным',
                'У сделки должен быть владелец, иначе следующий шаг легко потерять.',
                blocker='Нет ответственного',
                cta_label='Назначить себя',
            )
        )
    if any('имя получателя' in issue.lower() or 'получатель' in issue.lower() for issue in missing_delivery_fields):
        candidates.append(
            _action_candidate(
                'fill_recipient',
                20,
                'Заполнить получателя',
                'Без имени получателя отгрузку и коммуникацию легко сорвать.',
                blocker='Не указан получатель',
                cta_label='Заполнить доставку',
            )
        )
    if any('телефон' in issue.lower() for issue in missing_delivery_fields):
        candidates.append(
            _action_candidate(
                'fill_phone',
                25,
                'Заполнить телефон получателя',
                'Телефон нужен для доставки, подтверждения и связи по отгрузке.',
                blocker='Не указан телефон получателя',
                cta_label='Заполнить доставку',
            )
        )
    if any('адрес' in issue.lower() for issue in missing_delivery_fields):
        candidates.append(
            _action_candidate(
                'fill_address',
                30,
                'Заполнить адрес доставки',
                'Без адреса нельзя корректно подготовить shipment.',
                blocker='Не указан адрес доставки',
                cta_label='Заполнить доставку',
            )
        )
    if severe_problem_flags:
        problem_label = deal.problem_flag_labels[0] if deal.problem_flag_labels else 'Есть системный блокер'
        candidates.append(
            _action_candidate(
                'resolve_problem',
                40,
                f'Разобрать блокер: {problem_label}',
                'Сделка уже помечена как проблемная и требует ручного внимания.',
                blocker=problem_label,
                cta_label='Открыть блокер',
            )
        )
    if pending_cargo_groups:
        cargo = pending_cargo_groups[0]['cargo']
        first_pending_item = pending_cargo_groups[0]['items'][0]
        candidates.append(
            _action_candidate(
                'receive_cargo',
                50,
                f'Принять груз {cargo.cargo_number or f"CG-{cargo.pk}"}',
                'По inbound-грузу есть непринятые позиции, их нужно провести в складской контур.',
                blocker=f'Груз {cargo.cargo_number or cargo.pk} ожидает приемки',
                cta_label='Принять груз',
                cargo_item_id=first_pending_item.id,
            )
        )
    if reserve_ready_lines:
        candidates.append(
            _action_candidate(
                'reserve_stock',
                55,
                f'Зарезервировать {len(reserve_ready_lines)} {_format_count(len(reserve_ready_lines), "позицию", "позиции", "позиций")}',
                'По части позиций уже есть принятый или свободный остаток, его можно сразу закрепить за сделкой.',
                blocker='Можно зарезервировать свободный остаток',
                cta_label='Зарезервировать',
                item_id=first_reserve_ready_line['order_item'].id if first_reserve_ready_line else None,
            )
        )
    if uncovered_purchase_lines:
        first_uncovered_line = uncovered_purchase_lines[0]
        uncovered_count = len(uncovered_purchase_lines)
        candidates.append(
            _action_candidate(
                'create_purchase',
                60,
                f'Создать закупку на {uncovered_count} {_format_count(uncovered_count, "позицию", "позиции", "позиций")}',
                'Часть товарных позиций пока не покрыта резервом, закупкой, грузом или отгрузкой.',
                blocker='Есть необеспеченные позиции',
                cta_label='Создать закупку',
                item_id=first_uncovered_line['item'].id,
            )
        )
    if cargo_ready_purchase_items:
        first_cargo_ready_item = cargo_ready_purchase_items[0]
        cargo_ready_count = len(cargo_ready_purchase_items)
        candidates.append(
            _action_candidate(
                'create_cargo',
                70,
                (
                    f'Добавить в груз {cargo_ready_count} '
                    f'{_format_count(cargo_ready_count, "позицию", "позиции", "позиций")}'
                ),
                'Закупка уже заведена, следующий шаг — распределить позиции по грузам.',
                blocker='Есть закупка без груза',
                cta_label='Добавить в груз',
                purchase_item_id=first_cargo_ready_item.id,
                purchase_id=first_cargo_ready_item.purchase_id,
            )
        )
    if all_tracked_fully_covered and not shipments and not reserve_ready_lines:
        candidates.append(
            _action_candidate(
                'create_shipment',
                80,
                'Создать отгрузку',
                'Сделка уже обеспечена и может переходить в shipment.',
                blocker='Отгрузка по сделке еще не создана',
                cta_label='Создать отгрузку',
            )
        )
    if pending_shipment is not None:
        candidates.append(
            _action_candidate(
                'ship_shipment',
                81,
                'Отправить отгрузку',
                'Товар уже собран в shipment и готов перейти из резерва в фактическое списание.',
                blocker='Отгрузка подготовлена, но еще не отправлена',
                cta_label='Отправить отгрузку',
                shipment_id=pending_shipment.id,
            )
        )
    if shipped_shipment is not None:
        candidates.append(
            _action_candidate(
                'deliver_shipment',
                82,
                'Отметить доставлено',
                'Клиент уже получил отправление или доставка подтверждена перевозчиком.',
                blocker='Отгрузка в пути и ждет подтверждения доставки',
                cta_label='Отметить доставлено',
                shipment_id=shipped_shipment.id,
            )
        )
    if not checklist_map['finance']['is_ok']:
        candidates.append(
            _action_candidate(
                'fill_finance',
                85,
                'Заполнить финансы сделки',
                'Операционке нужен заполненный финансовый кейс для контроля маржи и себестоимости.',
                blocker='Финансовый кейс не заполнен',
                cta_label='Открыть финансы',
            )
        )
    if shipment_without_tracking is not None:
        candidates.append(
            _action_candidate(
                'fill_tracking_number',
                90,
                'Указать трек-номер',
                'Отгрузка уже создана, но без трека ее сложно сопровождать.',
                blocker='У отгрузки нет трек-номера',
                cta_label='Открыть отгрузку',
            )
        )
    if all_shipments_delivered:
        candidates.append(
            _action_candidate(
                'shipment_delivered',
                83,
                'Доставлено',
                'Все активные отгрузки по сделке уже доставлены.',
                cta_label='Доставлено',
            )
        )
    if (
        not candidates
        and (
            deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION
            or deal.case_status == ManagerDeal.CASE_STATUS_NEW
        )
    ):
        candidates.append(
            _action_candidate(
                'review_deal',
                100,
                'Проверить состав сделки и взять в работу',
                'Сделка только попала в операционный контур и ждет первичного разбора.',
            )
        )
    if not candidates:
        candidates.append(
            _action_candidate(
                'review_deal',
                110,
                'Разобрать сделку',
                deal.next_step_reason_snapshot or 'Сделку стоит вручную проверить и выбрать следующий операционный шаг.',
            )
        )
    candidates.sort(key=lambda row: (row['priority'], row['text']))
    return candidates, checklist, pending_cargo_groups


def classify_operation_deal(deal, *, relations=None):
    relations = relations or operation_detail_relations(deal)
    supply_snapshot = order_supply_state_snapshot(deal.order)
    supply_flags = _supply_flags(supply_snapshot)
    missing_delivery_fields = _delivery_field_issues(deal)
    custom_items = [line['item'] for line in supply_flags['custom_lines']]

    purchase_items = [
        purchase_item
        for purchase in relations['purchases']
        for purchase_item in purchase.items.all()
        if purchase_item.order_item_id and purchase_item.order_item.order_id == deal.order_id
    ]
    cargo_items = [
        cargo_item
        for cargo in relations['cargos']
        for cargo_item in cargo.items.all()
        if cargo_item.purchase_item_id and cargo_item.purchase_item.order_item_id
    ]
    has_partial_arrival = any(
        0 < int(item.received_quantity or 0) < max(int(item.active_quantity or 0), 1)
        for item in purchase_items
    ) or any(
        0 < int(item.received_quantity or 0) < max(int(item.quantity or 0), 1)
        for item in cargo_items
    )
    has_in_transit = any(cargo.status in IN_TRANSIT_CARGO_STATUSES for cargo in relations['cargos'])
    has_shipment_in_delivery = any(
        shipment.status in {Shipment.STATUS_SHIPPED, Shipment.STATUS_DELIVERED}
        or shipment.inventory_consumed_at is not None
        for shipment in relations['shipments']
    ) or deal.order.status == deal.order.STATUS_SHIPPING
    has_ready_reservation = any(
        reservation.status in ACTIVE_RESERVATION_STATUSES for reservation in relations['reservations']
    )
    has_delivered_shipment = any(
        shipment.status == Shipment.STATUS_DELIVERED or shipment.delivered_at is not None
        for shipment in relations['shipments']
    )
    tracked_lines = supply_flags['tracked_lines']
    has_partial_supply = supply_flags['has_partial_supply']
    all_tracked_fully_covered = all(
        _line_supply_progress(line) >= int(line['ordered_quantity'] or 0)
        for line in tracked_lines
    ) if tracked_lines else True
    severe_problem_flags = [flag for flag in (deal.problem_flags or []) if flag in SEVERE_PROBLEM_FLAGS]
    action_candidates, checklist, pending_cargo_groups = _operation_action_candidates(
        deal,
        relations=relations,
        supply_flags=supply_flags,
        all_tracked_fully_covered=all_tracked_fully_covered,
        severe_problem_flags=severe_problem_flags,
    )
    primary_action = action_candidates[0]
    is_completed = _ops_deal_completed(deal, relations=relations, supply_flags=supply_flags)

    if is_completed:
        status_code = OP_STATUS_COMPLETED
    elif custom_items:
        status_code = OP_STATUS_NEEDS_LINK_PRODUCTS
    elif severe_problem_flags:
        status_code = OP_STATUS_PROBLEMS
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION or deal.case_status == ManagerDeal.CASE_STATUS_NEW:
        status_code = OP_STATUS_NEEDS_REVIEW
    elif missing_delivery_fields:
        status_code = OP_STATUS_NEEDS_SHIPPING_DATA
    elif deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION:
        status_code = OP_STATUS_NEEDS_AVAILABILITY_CHECK
    elif supply_flags['has_uncovered']:
        status_code = OP_STATUS_NEEDS_PROCUREMENT
    elif has_partial_arrival:
        status_code = OP_STATUS_PARTIALLY_ARRIVED
    elif has_partial_supply:
        status_code = OP_STATUS_PARTIALLY_SECURED
    elif has_shipment_in_delivery:
        status_code = OP_STATUS_IN_DELIVERY
    elif has_in_transit:
        status_code = OP_STATUS_IN_TRANSIT
    elif (
        all_tracked_fully_covered
        and has_ready_reservation
        and deal.payment_state == ManagerDeal.PAYMENT_STATE_PAID
    ):
        status_code = OP_STATUS_READY_TO_SHIP
    elif deal.problem_flags:
        status_code = OP_STATUS_PROBLEMS
    else:
        status_code = OP_STATUS_NEEDS_REVIEW

    blockers = [
        candidate['blocker']
        for candidate in action_candidates
        if candidate.get('blocker')
    ]
    blockers.extend(missing_delivery_fields)
    blockers.extend(deal.problem_flag_labels)
    blockers = list(OrderedDict.fromkeys(filter(None, blockers)))
    if is_completed:
        blockers = []

    return {
        'status_code': status_code,
        'status_label': operation_status_label(status_code),
        'status_description': OPERATION_STATUS_DEFINITIONS[status_code]['description'],
        'status_tone': ops_tone_for_operation_status(status_code),
        'action_text': primary_action['text'],
        'reason': primary_action['reason'],
        'primary_action': primary_action,
        'blockers': blockers,
        'primary_blocker': blockers[0] if blockers else '',
        'next_actions': action_candidates,
        'checklist': checklist,
        'missing_delivery_fields': missing_delivery_fields,
        'custom_items': custom_items,
        'needs_procurement': supply_flags['has_uncovered'],
        'has_problem': False if is_completed else (bool(blockers) or bool(deal.problem_flags)),
        'fulfillment_status_label': deal.get_fulfillment_status_display(),
        'fulfillment_tone': ops_tone_for_fulfillment_status(deal.fulfillment_status),
        'delivery_status_label': deal.get_delivery_status_display(),
        'delivery_tone': ops_tone_for_delivery_status(deal.delivery_status),
        'pending_cargo_receipts': pending_cargo_groups,
        'supply_snapshot': supply_snapshot,
        'relations': relations,
    }


def group_operation_deals(deals):
    grouped = OrderedDict(
        (
            code,
            {
                'code': code,
                'label': meta['label'],
                'description': meta['description'],
                'count': 0,
                'items': [],
            },
        )
        for code, meta in OPERATION_STATUS_DEFINITIONS.items()
    )
    for deal in deals:
        snapshot = classify_operation_deal(deal)
        deal.operation_snapshot = snapshot
        bucket = grouped[snapshot['status_code']]
        bucket['count'] += 1
        bucket['items'].append(deal)
    return list(grouped.values())


def sync_delivery_data_for_deal(deal, *, actor=None):
    order = deal.order
    address = (order.display_address or '').strip()
    updates = {
        'delivery_method': _manager_delivery_method_for_order(order),
        'delivery_to_city': (order.city_text or '').strip(),
        'delivery_pickup_address': (
            address if order.delivery_type in {Order.DELIVERY_CDEK_PVZ, Order.DELIVERY_PICKUP} else ''
        ),
        'delivery_full_address': (
            address if order.delivery_type not in {Order.DELIVERY_CDEK_PVZ, Order.DELIVERY_PICKUP} else ''
        ),
        'shipping_comment': (order.delivery_comment or '').strip(),
    }
    if deal.buyer_type == ManagerDeal.BUYER_BUSINESS:
        updates.update(
            {
                'business_contact_person': order.shipping_contact_name,
                'business_phone': (order.business_phone or order.shipping_phone or order.phone or '').strip(),
                'business_city': (order.city_text or '').strip(),
                'business_delivery_address': address,
            }
        )
    else:
        updates.update(
            {
                'individual_full_name': order.shipping_contact_name,
                'individual_phone': (order.shipping_phone or '').strip(),
                'individual_city': (order.city_text or '').strip(),
                'individual_delivery_address': address,
            }
        )

    update_fields = []
    for field_name, value in updates.items():
        if getattr(deal, field_name) != value:
            setattr(deal, field_name, value)
            update_fields.append(field_name)
    if update_fields:
        deal.save(update_fields=[*update_fields, 'updated_at'])
        record_deal_activity(
            deal,
            event_type='operations.delivery_updated',
            source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
            actor=actor,
            payload={'updated_fields': update_fields},
        )
    recompute_deal_workflow(deal, actor=actor)
    return deal


def create_purchase_for_deal(deal, *, actor=None):
    supply_snapshot = order_supply_state_snapshot(deal.order)
    candidate_lines = []
    total_amount = Decimal('0')
    for line in supply_snapshot['lines']:
        if not line['is_supply_tracked']:
            continue
        ordered = int(line['ordered_quantity'] or 0)
        progress = _line_supply_progress(line)
        missing_quantity = max(ordered - progress, 0)
        if missing_quantity <= 0:
            continue
        candidate_lines.append((line['item'], missing_quantity))

    if not candidate_lines:
        raise ValueError('По сделке нет позиций, для которых нужно создать закупку.')

    purchase = Purchase.objects.create(
        date=timezone.localdate(),
        supplier_name=deal.supplier_name or '',
        agent=deal.supplier_agent or '',
        status=Purchase.STATUS_DRAFT,
        comments=f'Создано из операторского портала по сделке {deal.code or deal.order_id}.',
    )
    for order_item, missing_quantity in candidate_lines:
        unit_cost = order_item.planned_unit_cost or order_item.effective_unit_cost or Decimal('0')
        PurchaseItem.objects.create(
            purchase=purchase,
            product=order_item.product,
            variant=order_item.variant,
            order_item=order_item,
            quantity=missing_quantity,
            unit_cost=unit_cost,
        )
        total_amount += unit_cost * Decimal(missing_quantity)
    purchase.total_amount = total_amount
    purchase.save(update_fields=['total_amount', 'updated_at'])

    record_deal_activity(
        deal,
        event_type='operations.purchase_created',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={'purchase_id': purchase.id, 'items_count': len(candidate_lines)},
    )
    recompute_deal_workflow(deal, actor=actor)
    return purchase


def create_or_link_cargo_for_deal(deal, *, actor=None):
    purchase = (
        related_purchases_queryset(deal)
        .exclude(status=Purchase.STATUS_CANCELLED)
        .first()
    )
    if purchase is None:
        raise ValueError('Сначала создайте закупку, а затем уже готовьте груз.')

    cargo = (
        Cargo.objects.filter(purchase=purchase)
        .exclude(status=Cargo.STATUS_CANCELLED)
        .order_by('-created_at', '-id')
        .first()
    )
    created = False
    if cargo is None:
        cargo = Cargo.objects.create(
            purchase=purchase,
            status=Cargo.STATUS_CREATED,
            eta=deal.expected_arrival_date or None,
            destination_warehouse=deal.stock_warehouse,
            comments=f'Создано из операторского портала по сделке {deal.code or deal.order_id}.',
        )
        created = True

    existing_purchase_item_ids = set(
        cargo.items.exclude(purchase_item__isnull=True).values_list('purchase_item_id', flat=True)
    )
    added_items = 0
    for purchase_item in purchase.items.filter(order_item__order=deal.order).select_related('product', 'variant'):
        if purchase_item.id in existing_purchase_item_ids:
            continue
        quantity = max(int(purchase_item.active_quantity or 0) - int(purchase_item.received_quantity or 0), 0)
        if quantity <= 0:
            continue
        CargoItem.objects.create(
            cargo=cargo,
            product=purchase_item.product,
            variant=purchase_item.variant,
            purchase_item=purchase_item,
            quantity=quantity,
        )
        added_items += 1

    if created or added_items:
        record_deal_activity(
            deal,
            event_type='operations.cargo_prepared',
            source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
            actor=actor,
            payload={'cargo_id': cargo.id, 'purchase_id': purchase.id, 'added_items': added_items},
        )
        recompute_deal_workflow(deal, actor=actor)
    return cargo, created, added_items


def purchase_item_cargo_allocated_quantity(purchase_item):
    prefetched_cargo_items = getattr(purchase_item, '_prefetched_objects_cache', {}).get('cargo_items')
    if prefetched_cargo_items is not None:
        return sum(
            int(cargo_item.quantity or 0)
            for cargo_item in prefetched_cargo_items
            if not cargo_item.cargo_id or cargo_item.cargo.status != Cargo.STATUS_CANCELLED
        )
    return sum(
        int(cargo_item.quantity or 0)
        for cargo_item in purchase_item.cargo_items.select_related('cargo').exclude(cargo__status=Cargo.STATUS_CANCELLED)
    )


def purchase_item_cargo_available_quantity(purchase_item):
    return max(int(purchase_item.active_quantity or 0) - purchase_item_cargo_allocated_quantity(purchase_item), 0)


def create_cargo_for_purchase_item(
    deal,
    *,
    purchase_item,
    quantity,
    destination_warehouse,
    eta=None,
    status=Cargo.STATUS_CREATED,
    comments='',
    cargo_number='',
    actor=None,
):
    if purchase_item.order_item_id is None or purchase_item.order_item.order_id != deal.order_id:
        raise ValueError('Позиция закупки не относится к этой сделке.')

    status = (status or Cargo.STATUS_CREATED).strip() or Cargo.STATUS_CREATED
    if destination_warehouse is None:
        raise ValueError('Укажите склад назначения.')
    if status != Cargo.STATUS_CREATED and eta is None:
        raise ValueError('Укажите ETA для груза, если он уже не в статусе "Создан".')

    available_quantity = purchase_item_cargo_available_quantity(purchase_item)
    if quantity <= 0:
        raise ValueError('Количество в грузе должно быть больше нуля.')
    if quantity > available_quantity:
        raise ValueError(f'В груз можно добавить не больше {available_quantity} шт. по выбранной позиции закупки.')

    cargo_comments = (comments or '').strip() or f'Создано из операторского портала по сделке {deal.code or deal.order_id}.'
    cargo_number = (cargo_number or '').strip()

    with transaction.atomic():
        cargo = Cargo(
            cargo_number=cargo_number,
            purchase=purchase_item.purchase,
            status=status,
            eta=eta,
            destination_warehouse=destination_warehouse,
            comments=cargo_comments,
        )
        cargo.full_clean()
        cargo.save()

        cargo_item = CargoItem(
            cargo=cargo,
            product=purchase_item.product,
            variant=purchase_item.variant,
            purchase_item=purchase_item,
            quantity=quantity,
        )
        cargo_item.full_clean()
        cargo_item.save()

    record_deal_activity(
        deal,
        event_type='operations.cargo_prepared',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'cargo_id': cargo.id,
            'purchase_id': purchase_item.purchase_id,
            'purchase_item_id': purchase_item.id,
            'quantity': quantity,
        },
    )
    recompute_deal_workflow(deal, actor=actor)
    return cargo, cargo_item


def finance_summary_for_detail(finance_deal):
    if finance_deal is None:
        return {
            'exists': False,
            'revenue': Decimal('0'),
            'cost_of_goods': Decimal('0'),
            'delivery_cost': Decimal('0'),
            'direct_expenses': Decimal('0'),
            'estimated_profit': Decimal('0'),
            'cost_status_label': 'Финансовый кейс не создан',
            'share_rows': [],
        }
    return {
        'exists': True,
        'revenue': finance_deal.revenue,
        'cost_of_goods': finance_deal.cost_of_goods,
        'delivery_cost': Decimal('0'),
        'direct_expenses': finance_deal.direct_expenses,
        'estimated_profit': finance_deal.distributable_profit,
        'cost_status_label': 'Себестоимость подтверждена' if Decimal(finance_deal.cost_of_goods or 0) > 0 else 'Себестоимость пока не заведена',
        'share_rows': list(finance_deal.shares.select_related('participant_alias').order_by('id')),
    }


def purchase_form_summary(order_item, *, quantity=None, unit_cost=None):
    sale_unit_price = Decimal(order_item.unit_price or 0)
    sale_total = Decimal(order_item.subtotal or 0)
    planned_cost_total = Decimal(order_item.planned_cost_total or 0)
    parsed_quantity = order_item.active_quantity or order_item.quantity or 0
    parsed_unit_cost = Decimal(order_item.planned_unit_cost or 0)

    try:
        if quantity not in (None, ''):
            parsed_quantity = max(int(quantity), 0)
    except (TypeError, ValueError):
        parsed_quantity = order_item.active_quantity or order_item.quantity or 0

    try:
        if unit_cost not in (None, ''):
            parsed_unit_cost = Decimal(str(unit_cost))
    except (InvalidOperation, TypeError, ValueError):
        parsed_unit_cost = Decimal(order_item.planned_unit_cost or 0)

    estimated_cost_total = parsed_unit_cost * Decimal(parsed_quantity)
    return {
        'sale_unit_price': sale_unit_price,
        'sale_total': sale_total,
        'planned_cost_total': planned_cost_total,
        'estimated_cost_total': estimated_cost_total,
        'estimated_margin_total': sale_total - estimated_cost_total,
    }


def client_summary_for_detail(deal):
    client = deal_manager_client(deal)
    order = deal.order
    recipient = order.recipient_name or order.shipping_contact_name or deal.customer_name or (client.name if client else '')
    phone = order.recipient_phone or order.shipping_phone or deal.customer_phone or order.phone or (client.phone if client else '')
    city = order.city_text or deal.delivery_to_city or deal.customer_city
    address = order.display_address or deal.delivery_full_address or deal.delivery_pickup_address or (client.address if client else '')
    manual_fields = [
        order.recipient_name,
        order.recipient_phone,
        order.city_text,
        order.address,
        order.address_line,
        order.delivery_comment,
    ]
    data_source = 'Вручную' if any(_is_present(value) for value in manual_fields) else 'Bitrix'
    return {
        'display_name': deal.customer_name or (client.name if client else 'Клиент не определён'),
        'recipient': recipient,
        'phone': phone,
        'email': deal.order.email or (client.email if client else ''),
        'city': city,
        'address': address,
        'delivery_comment': order.delivery_comment or deal.shipping_comment or '',
        'data_source': data_source,
    }


def delivery_summary_for_detail(deal):
    order = deal.order
    return {
        'recipient_name': order.recipient_name or order.shipping_contact_name or '',
        'recipient_phone': order.recipient_phone or order.shipping_phone or '',
        'delivery_type_label': order.get_delivery_type_display(),
        'city': order.city_text or deal.delivery_to_city or deal.customer_city,
        'address': order.display_address or deal.delivery_full_address or deal.delivery_pickup_address,
        'comment': order.delivery_comment or deal.shipping_comment or '',
    }


def bitrix_sync_meta_for_detail(deal, activities):
    latest_import = next((activity for activity in activities if activity.event_type == 'bitrix.imported'), None)
    return {
        'deal_id': deal.bitrix_deal_id,
        'deal_url': deal.bitrix_deal_url,
        'synced_at': latest_import.created_at if latest_import else None,
        'title': deal.title or deal.short_label or '',
        'amount': deal.grand_total,
    }


def build_purchase_rows(deal, purchases):
    rows = []
    for purchase in purchases:
        item_rows = []
        can_create_cargo = False
        for item in purchase.items.all():
            if not item.order_item_id or item.order_item.order_id != deal.order_id:
                continue
            available_for_cargo = purchase_item_cargo_available_quantity(item)
            cargo_action_enabled = available_for_cargo > 0
            can_create_cargo = can_create_cargo or cargo_action_enabled
            item_rows.append(
                {
                    'item': item,
                    'order_item': item.order_item,
                    'line_total': Decimal(item.unit_cost or 0) * Decimal(item.quantity or 0),
                    'available_for_cargo': available_for_cargo,
                    'cargo_action_enabled': cargo_action_enabled,
                    'cargo_action_note': '' if cargo_action_enabled else 'Весь объём уже распределён по грузам.',
                }
            )
        if item_rows:
            rows.append(
                {
                    'purchase': purchase,
                    'status_tone': ops_tone_for_purchase_status(purchase.status),
                    'items': item_rows,
                    'cargo_action_enabled': can_create_cargo,
                    'cargo_action_note': '' if can_create_cargo else 'По этой закупке уже нечего добавлять в грузы.',
                }
            )
    return rows


def build_position_rows(
    deal,
    *,
    supply_snapshot=None,
    purchase_items_by_order_item=None,
    pending_cargo_items_by_order_item=None,
    shipments=None,
):
    supply_snapshot = supply_snapshot or order_supply_state_snapshot(deal.order)
    purchase_items_by_order_item = purchase_items_by_order_item or {}
    pending_cargo_items_by_order_item = pending_cargo_items_by_order_item or {}
    shipments = shipments or []
    reservation_candidates = reservation_candidates_for_deal(deal)
    rows = []
    for line in supply_snapshot['lines']:
        item = line['item']
        reservation_candidate = reservation_candidates.get(item.id)
        linked_purchase_item = purchase_items_by_order_item.get(item.id)
        pending_cargo_item = pending_cargo_items_by_order_item.get(item.id)
        ordered = int(line['ordered_quantity'] or 0)
        reserved = int(line['reserved_quantity'] or 0)
        purchased = int(line['purchase_quantity'] or 0)
        cargo_quantity = int(line['cargo_quantity'] or 0)
        cargo_received = int(line['cargo_received_quantity'] or 0)
        purchase_received = int(line['purchase_received_quantity'] or 0)
        shipped = int(line['shipment_quantity'] or 0)
        in_transit = max(cargo_quantity - cargo_received, 0)
        received = max(cargo_received, purchase_received, 0)
        secured_progress = max(reserved, purchased, cargo_quantity, shipped)
        missing = max(ordered - secured_progress, 0)
        reserve_missing = max(ordered - reserved, 0)
        free_stock = int(line['free_stock'] or 0)
        available_to_reserve = int(reservation_candidate['total_available'] or 0) if reservation_candidate else 0
        reserve_available = available_to_reserve > 0 and reserve_missing > 0
        if not item.product_id:
            reserve_debug_reason = 'нет product'
        elif item.line_type == OrderItem.LINE_TYPE_CUSTOM:
            reserve_debug_reason = 'custom item'
        elif not line['is_supply_tracked']:
            reserve_debug_reason = 'нет свободного остатка'
        elif reserve_missing <= 0:
            reserve_debug_reason = 'всё уже зарезервировано'
        elif available_to_reserve <= 0:
            reserve_debug_reason = 'нет свободного остатка'
        else:
            reserve_debug_reason = ''
        can_create_purchase = bool(item.product_id and item.line_type == OrderItem.LINE_TYPE_CATALOG and missing > 0)
        can_add_to_cargo = bool(
            item.product_id
            and item.line_type == OrderItem.LINE_TYPE_CATALOG
            and linked_purchase_item
            and purchase_item_cargo_available_quantity(linked_purchase_item) > 0
        )
        ready_to_ship = shipped < ordered and reserved >= ordered and ordered > 0
        position_actions = []

        if not line['is_supply_tracked']:
            position_status = 'Не связано с каталогом'
            position_tone = OPS_TONE_ATTENTION
        elif shipped >= ordered and ordered > 0:
            position_status = 'Отгружено'
            position_tone = OPS_TONE_INFO
        elif reserved >= ordered and ordered > 0:
            position_status = 'Готово к отгрузке'
            position_tone = OPS_TONE_SUCCESS
        elif reserve_available:
            position_status = 'Нужно зарезервировать'
            position_tone = OPS_TONE_ATTENTION
        elif received >= ordered and ordered > 0:
            position_status = 'Принято на склад'
            position_tone = OPS_TONE_INFO
        elif cargo_received > 0 and cargo_received < ordered:
            position_status = 'Частично приехало'
            position_tone = OPS_TONE_WORKING
        elif in_transit > 0:
            position_status = 'В пути'
            position_tone = OPS_TONE_INFO
        elif 0 < secured_progress < ordered:
            position_status = 'Частично обеспечено'
            position_tone = OPS_TONE_WORKING
        elif missing > 0:
            position_status = 'Нужно закупить'
            position_tone = OPS_TONE_WORKING
        else:
            position_status = 'Нужно проверить наличие'
            position_tone = OPS_TONE_NEUTRAL

        if item.line_type == OrderItem.LINE_TYPE_CUSTOM or not item.product_id:
            position_actions.append(
                {
                    'code': 'link_product',
                    'label': 'Связать с товаром сайта',
                    'kind': 'anchor',
                    'url': f'#item-{item.id}',
                    'tone': 'attention',
                }
            )
        else:
            if pending_cargo_item is not None:
                position_actions.append(
                    {
                        'code': 'receive_cargo',
                        'label': 'Принять груз',
                        'kind': 'receive_cargo',
                        'cargo_item_id': pending_cargo_item.id,
                        'tone': 'primary',
                    }
                )
            else:
                if reserve_available:
                    position_actions.append(
                        {
                            'code': 'reserve_stock',
                            'label': 'Зарезервировать',
                            'kind': 'reserve',
                            'item_id': item.id,
                            'tone': 'secondary',
                        }
                    )
                if can_create_purchase and linked_purchase_item is None:
                    position_actions.append(
                        {
                            'code': 'create_purchase',
                            'label': 'Создать закупку',
                            'kind': 'purchase',
                            'item_id': item.id,
                            'tone': 'primary',
                        }
                    )
                if can_add_to_cargo:
                    position_actions.append(
                        {
                            'code': 'create_cargo',
                            'label': 'Добавить в груз',
                            'kind': 'cargo',
                            'purchase_id': linked_purchase_item.purchase_id,
                            'purchase_item_id': linked_purchase_item.id,
                            'tone': 'secondary',
                        }
                    )
                if ready_to_ship and not shipments:
                    position_actions.append(
                        {
                            'code': 'create_shipment',
                            'label': 'Создать отгрузку',
                            'kind': 'post',
                            'post_action': 'create_shipment',
                            'tone': 'secondary',
                        }
                    )

        rows.append(
            {
                'item': item,
                'is_link_required': item.line_type == OrderItem.LINE_TYPE_CUSTOM or not item.product_id,
                'catalog_mode_label': 'catalog' if item.product_id and item.line_type == OrderItem.LINE_TYPE_CATALOG else 'custom',
                'catalog_link_label': (
                    'Связан с каталогом'
                    if item.product_id and item.line_type == OrderItem.LINE_TYPE_CATALOG
                    else 'Не связан — складские действия ограничены'
                ),
                'catalog_link_tone': (
                    OPS_TONE_SUCCESS
                    if item.product_id and item.line_type == OrderItem.LINE_TYPE_CATALOG
                    else OPS_TONE_ATTENTION
                ),
                'warehouse_actions_enabled': bool(item.product_id and item.line_type == OrderItem.LINE_TYPE_CATALOG),
                'warehouse_actions_note': (
                    ''
                    if item.product_id and item.line_type == OrderItem.LINE_TYPE_CATALOG
                    else 'Сначала свяжите товар с каталогом сайта.'
                ),
                'cargo_actions_enabled': can_add_to_cargo,
                'cargo_actions_note': (
                    'Сначала свяжите товар с каталогом сайта.'
                    if not (item.product_id and item.line_type == OrderItem.LINE_TYPE_CATALOG)
                    else (
                        'Сначала создайте закупку.'
                        if not linked_purchase_item
                        else (
                            ''
                            if purchase_item_cargo_available_quantity(linked_purchase_item) > 0
                            else 'Весь объём уже распределён по грузам.'
                        )
                    )
                ),
                'ordered': ordered,
                'free_stock': free_stock,
                'available_to_reserve': available_to_reserve,
                'reserved': reserved,
                'purchased': purchased,
                'in_transit': in_transit,
                'received': received,
                'shipped': shipped,
                'missing': missing,
                'reserve_missing': reserve_missing,
                'reserve_debug_reason': reserve_debug_reason,
                'status_label': position_status,
                'status_tone': position_tone,
                'coverage_label': line['coverage_label'],
                'coverage_summary': line['coverage_summary'],
                'purchase_item': linked_purchase_item,
                'pending_cargo_item': pending_cargo_item,
                'purchase_action_label': 'Редактировать закупку' if linked_purchase_item else 'Создать закупку',
                'actions': position_actions,
            }
        )
    return rows


def _history_category_for_activity(activity):
    event_type = activity.event_type or ''
    if event_type.startswith('operations.purchase'):
        return HISTORY_FILTER_PURCHASES
    if event_type.startswith('operations.cargo'):
        return HISTORY_FILTER_CARGOS
    if event_type.startswith('shipment.'):
        return HISTORY_FILTER_SHIPMENTS
    if event_type.startswith('finance.'):
        return HISTORY_FILTER_FINANCE
    if activity.source == DealActivity.SOURCE_USER:
        return HISTORY_FILTER_USER
    return HISTORY_FILTER_SYSTEM


def _history_is_noisy(activity):
    return activity.event_type in {'workflow.recomputed', 'order.synced'}


def _history_label_maps(activities):
    purchase_ids = set()
    cargo_ids = set()
    shipment_ids = set()
    reservation_ids = set()
    for activity in activities:
        payload = activity.payload or {}
        if payload.get('purchase_id'):
            purchase_ids.add(int(payload['purchase_id']))
        if payload.get('cargo_id'):
            cargo_ids.add(int(payload['cargo_id']))
        if payload.get('shipment_id'):
            shipment_ids.add(int(payload['shipment_id']))
        if payload.get('reservation_id'):
            reservation_ids.add(int(payload['reservation_id']))

    purchase_labels = dict(Purchase.objects.filter(id__in=purchase_ids).values_list('id', 'code'))
    cargo_labels = dict(Cargo.objects.filter(id__in=cargo_ids).values_list('id', 'cargo_number'))
    shipment_labels = dict(Shipment.objects.filter(id__in=shipment_ids).values_list('id', 'code'))
    reservation_labels = dict(Reservation.objects.filter(id__in=reservation_ids).values_list('id', 'code'))
    return purchase_labels, cargo_labels, shipment_labels, reservation_labels


def _history_summary(activity, purchase_labels, cargo_labels, shipment_labels, reservation_labels):
    payload = activity.payload or {}
    event_type = activity.event_type or ''
    purchase_label = purchase_labels.get(int(payload['purchase_id'])) if payload.get('purchase_id') else ''
    cargo_label = cargo_labels.get(int(payload['cargo_id'])) if payload.get('cargo_id') else ''
    shipment_label = shipment_labels.get(int(payload['shipment_id'])) if payload.get('shipment_id') else ''
    reservation_label = reservation_labels.get(int(payload['reservation_id'])) if payload.get('reservation_id') else ''

    if event_type == 'bitrix.imported':
        return 'Импорт из Bitrix'
    if event_type == 'operations.purchase_created':
        return f'Создана закупка {purchase_label or payload.get("purchase_id") or ""}'.strip()
    if event_type == 'operations.purchase_updated':
        return f'Обновлена закупка {purchase_label or payload.get("purchase_id") or ""}'.strip()
    if event_type == 'operations.cargo_prepared':
        return f'Создан груз {cargo_label or payload.get("cargo_id") or ""}'.strip()
    if event_type == 'operations.delivery_updated':
        return 'Обновлены данные доставки'
    if event_type == 'reservation.created':
        return f'Создан резерв {reservation_label or payload.get("reservation_id") or ""}'.strip()
    if event_type == 'shipment.created':
        return f'Создана отгрузка {shipment_label or payload.get("shipment_id") or ""}'.strip()
    if event_type == 'shipment.dispatched':
        return f'Отгрузка {shipment_label or payload.get("shipment_id") or ""} отправлена'.strip()
    if event_type == 'shipment.delivered':
        return f'Отгрузка {shipment_label or payload.get("shipment_id") or ""} доставлена'.strip()
    if event_type == 'shipment.cancelled':
        return f'Отгрузка {shipment_label or payload.get("shipment_id") or ""} отменена'.strip()
    if event_type == 'order_item.linked_to_catalog':
        return 'Товар связан с каталогом'
    if event_type == 'assignment.changed':
        return 'Изменён ответственный'
    if event_type == 'case_status.changed':
        return 'Изменён этап исполнения'
    if event_type == 'finance.created':
        return 'Создан финансовый кейс'
    if event_type == 'finance.adjustment_posted':
        return 'Добавлено финансовое изменение'
    if event_type == 'shipment.return_requested':
        return 'Запрошен возврат отгрузки'
    if event_type == 'shipment.return_received':
        return 'Возврат по отгрузке получен'
    if event_type == 'shipment.reversed':
        return 'Отгрузка возвращена в запас'
    return event_type


def build_history_rows(activities, *, history_filter=HISTORY_FILTER_ALL, include_noisy=False):
    activities = list(activities)
    if not include_noisy:
        activities = [activity for activity in activities if not _history_is_noisy(activity)]
    purchase_labels, cargo_labels, shipment_labels, reservation_labels = _history_label_maps(activities)
    rows = []
    for activity in activities:
        category = _history_category_for_activity(activity)
        if history_filter == HISTORY_FILTER_SYSTEM and activity.source != DealActivity.SOURCE_SYSTEM:
            continue
        if history_filter == HISTORY_FILTER_USER and activity.source != DealActivity.SOURCE_USER:
            continue
        if history_filter not in {
            HISTORY_FILTER_ALL,
            HISTORY_FILTER_SYSTEM,
            HISTORY_FILTER_USER,
        } and category != history_filter:
            continue
        rows.append(
            {
                'summary': _history_summary(activity, purchase_labels, cargo_labels, shipment_labels, reservation_labels),
                'event_type': activity.event_type,
                'created_at': activity.created_at,
                'category': category,
                'category_label': HISTORY_FILTER_DEFINITIONS.get(category, {}).get('label', 'Система'),
                'source_label': activity.get_source_display(),
                'actor': activity.actor.get_username() if activity.actor else '',
                'who_label': activity.actor.get_username() if activity.actor else activity.get_source_display(),
                'payload': activity.payload or {},
                'deal': getattr(activity, 'manager_deal', None),
                'tone': {
                    HISTORY_FILTER_PURCHASES: OPS_TONE_WORKING,
                    HISTORY_FILTER_CARGOS: OPS_TONE_INFO,
                    HISTORY_FILTER_SHIPMENTS: OPS_TONE_SUCCESS,
                    HISTORY_FILTER_FINANCE: OPS_TONE_NEUTRAL,
                    HISTORY_FILTER_USER: OPS_TONE_INFO,
                    HISTORY_FILTER_SYSTEM: OPS_TONE_NEUTRAL,
                }.get(category, OPS_TONE_NEUTRAL),
            }
        )
    return rows


def reconcile_ops_bitrix_items(import_result):
    import_result['linked_catalog_items'] = import_result.get('linked_catalog_items', 0)
    import_result['order_item_count'] = import_result.get('order_item_count') or import_result['order'].items.count()
    return import_result
