from collections import OrderedDict

from django.db.models import Q
from django.utils import timezone

from django.contrib.auth import get_user_model

from manager_portal.models import Cargo

from .services import (
    IN_TRANSIT_CARGO_STATUSES,
    OPERATION_STATUS_DEFINITIONS,
    classify_operation_deal,
    ops_tone_for_operation_status,
    operation_status_label,
)


PROBLEM_FILTER_ANY = ''
PROBLEM_FILTER_YES = 'yes'
PROBLEM_FILTER_NO = 'no'

PROBLEM_FILTER_CHOICES = [
    (PROBLEM_FILTER_ANY, 'Любая'),
    (PROBLEM_FILTER_YES, 'Есть проблемы'),
    (PROBLEM_FILTER_NO, 'Без проблем'),
]


def operations_responsible_choices():
    users = get_user_model().objects.filter(is_staff=True).order_by('username')
    return [('', 'Любой ответственный')] + [(str(user.pk), user.get_username()) for user in users]


def build_operation_search_haystack(deal):
    item_tokens = []
    for item in deal.order.items.all():
        item_tokens.extend(
            [
                item.display_name,
                item.resolved_product_name,
                item.resolved_variant_name,
                item.sku,
                str((item.metadata or {}).get('bitrix_product_id') or ''),
                str((item.metadata or {}).get('bitrix_product_name') or ''),
            ]
        )
    tokens = [
        deal.code or '',
        deal.identity_code or '',
        str(deal.order_id or ''),
        deal.customer_name or '',
        deal.customer_phone or '',
        deal.order.email or '',
        deal.bitrix_deal_id or '',
        deal.title or '',
        deal.short_label or '',
        *item_tokens,
    ]
    return ' '.join(token for token in tokens if token).lower()


def prepare_operation_deal(deal, *, snapshot=None):
    snapshot = snapshot or getattr(deal, 'operation_snapshot', None) or classify_operation_deal(deal)
    deal.operation_snapshot = snapshot
    deal.ops_summary = {
        'identity_code': deal.identity_code,
        'client_name': deal.customer_name or 'Клиент',
        'amount': deal.grand_total,
        'bitrix_id': deal.bitrix_deal_id,
        'bitrix_url': deal.bitrix_deal_url,
        'items_count': deal.order.items.count(),
        'fulfillment_status_label': snapshot.get('fulfillment_status_label') or operation_status_label(snapshot['status_code']),
        'fulfillment_tone': snapshot.get('fulfillment_tone'),
        'delivery_status_label': snapshot.get('delivery_status_label') or deal.get_delivery_status_display(),
        'delivery_tone': snapshot.get('delivery_tone'),
        'last_updated_at': deal.last_activity_at or deal.updated_at or deal.deal_created_at,
        'blockers_preview': snapshot['blockers'][:3],
        'primary_blocker': snapshot.get('primary_blocker') or '',
        'action_text': snapshot['action_text'],
        'reason': snapshot['reason'],
        'status_label': snapshot['status_label'],
        'status_tone': snapshot.get('status_tone'),
    }
    return deal


def filter_operation_deals(deals, cleaned_data):
    query = (cleaned_data.get('q') or '').strip().lower()
    status_code = cleaned_data.get('status') or ''
    problem_filter = cleaned_data.get('problem') or PROBLEM_FILTER_ANY
    responsible_manager = cleaned_data.get('responsible_manager')
    needs_link_products = bool(cleaned_data.get('needs_link_products'))
    needs_procurement = bool(cleaned_data.get('needs_procurement'))
    ready_to_ship = bool(cleaned_data.get('ready_to_ship'))
    in_transit = bool(cleaned_data.get('in_transit'))
    missing_delivery = bool(cleaned_data.get('missing_delivery_data'))

    filtered = []
    for deal in deals:
        snapshot = getattr(deal, 'operation_snapshot', None) or classify_operation_deal(deal)
        prepare_operation_deal(deal, snapshot=snapshot)
        if query and query not in build_operation_search_haystack(deal):
            continue
        if status_code and snapshot['status_code'] != status_code:
            continue
        has_problem = snapshot['status_code'] == 'problems' or bool(snapshot['blockers'])
        if problem_filter == PROBLEM_FILTER_YES and not has_problem:
            continue
        if problem_filter == PROBLEM_FILTER_NO and has_problem:
            continue
        if responsible_manager and deal.responsible_manager_id != responsible_manager.pk:
            continue
        if needs_link_products and not snapshot['custom_items']:
            continue
        if needs_procurement and not snapshot['needs_procurement']:
            continue
        if ready_to_ship and snapshot['status_code'] != 'ready_to_ship':
            continue
        if in_transit and snapshot['status_code'] not in {'in_transit', 'partially_arrived'}:
            continue
        if missing_delivery and not snapshot['missing_delivery_fields']:
            continue
        filtered.append(deal)
    return filtered


def dashboard_groups_for_deals(deals):
    grouped = OrderedDict()
    for deal in deals:
        snapshot = getattr(deal, 'operation_snapshot', None) or classify_operation_deal(deal)
        prepare_operation_deal(deal, snapshot=snapshot)
        bucket = grouped.setdefault(
            snapshot['status_code'],
            {
                'code': snapshot['status_code'],
                'label': snapshot['status_label'],
                'description': snapshot['status_description'],
                'tone': snapshot.get('status_tone'),
                'count': 0,
                'items': [],
            },
        )
        bucket['count'] += 1
        bucket['items'].append(deal)

    ordered_groups = []
    for code, meta in OPERATION_STATUS_DEFINITIONS.items():
        bucket = grouped.get(
            code,
            {
                'code': code,
                'label': meta['label'],
                'description': meta['description'],
                'tone': ops_tone_for_operation_status(code),
                'count': 0,
                'items': [],
            },
        )
        ordered_groups.append(bucket)
    return ordered_groups


def dashboard_kpis_for_deals(deals):
    today = timezone.localdate()
    metrics = {
        'active_deals': 0,
        'deals_with_blockers': 0,
        'deals_without_assignee': 0,
        'ready_to_ship': 0,
        'cargos_in_transit': 0,
        'cargos_without_eta': 0,
        'overdue_eta': 0,
    }
    for deal in deals:
        snapshot = getattr(deal, 'operation_snapshot', None) or classify_operation_deal(deal)
        prepare_operation_deal(deal, snapshot=snapshot)
        metrics['active_deals'] += 1
        if snapshot['blockers']:
            metrics['deals_with_blockers'] += 1
        if deal.responsible_manager_id is None:
            metrics['deals_without_assignee'] += 1
        if snapshot['status_code'] == 'ready_to_ship':
            metrics['ready_to_ship'] += 1

    order_ids = [deal.order_id for deal in deals if deal.order_id]
    if order_ids:
        related_cargos = (
            Cargo.objects.filter(
                Q(items__purchase_item__order_item__order_id__in=order_ids)
                | Q(cargo_reservations__linked_order_id__in=order_ids)
            )
            .distinct()
            .only('id', 'status', 'eta')
        )
        for cargo in related_cargos:
            if cargo.status in IN_TRANSIT_CARGO_STATUSES:
                metrics['cargos_in_transit'] += 1
            if cargo.status != cargo.STATUS_CANCELLED and cargo.eta is None:
                metrics['cargos_without_eta'] += 1
            if cargo.status not in {cargo.STATUS_RECEIVED, cargo.STATUS_CANCELLED} and cargo.eta and cargo.eta < today:
                metrics['overdue_eta'] += 1

    return [
        {'code': 'active_deals', 'label': 'Активных сделок', 'value': metrics['active_deals'], 'tone': 'info'},
        {'code': 'deals_with_blockers', 'label': 'С блокерами', 'value': metrics['deals_with_blockers'], 'tone': 'critical'},
        {'code': 'deals_without_assignee', 'label': 'Без ответственного', 'value': metrics['deals_without_assignee'], 'tone': 'attention'},
        {'code': 'ready_to_ship', 'label': 'Готово к отгрузке', 'value': metrics['ready_to_ship'], 'tone': 'success'},
        {'code': 'cargos_in_transit', 'label': 'Грузов в пути', 'value': metrics['cargos_in_transit'], 'tone': 'info'},
        {'code': 'cargos_without_eta', 'label': 'Грузов без ETA', 'value': metrics['cargos_without_eta'], 'tone': 'neutral'},
        {'code': 'overdue_eta', 'label': 'Просроченных ETA', 'value': metrics['overdue_eta'], 'tone': 'critical'},
    ]
