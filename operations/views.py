import json
import secrets
from datetime import datetime, time

from django.conf import settings
from django.contrib import messages
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from manager_portal.access import staff_required
from manager_portal.models import Cargo, CargoItem, DealActivity, ManagerDeal, Purchase, PurchaseItem, Shipment
from manager_portal.services import (
    apply_deal_assignment,
    BitrixImportError,
    cancel_shipment,
    ensure_shipment_for_manager_deal,
    link_manual_order_item_to_catalog_product,
    mark_shipment_delivered,
    receive_cargo_item,
    reserve_order_item_for_manager_deal,
    ship_shipment,
    sync_bitrix_deal_into_operations,
)

from .forms import (
    CustomOrderItemLinkForm,
    OperationsCargoAcceptanceForm,
    OperationsCargoCreateForm,
    OperationsDealFilterForm,
    OperationsOrderDeliveryForm,
    OperationsPurchaseForm,
    OperationsReservationCreateForm,
    OperationsShipmentDispatchForm,
)
from .selectors import dashboard_groups_for_deals, dashboard_kpis_for_deals, filter_operation_deals, prepare_operation_deal
from .services import (
    HISTORY_FILTER_ALL,
    HISTORY_FILTER_DEFINITIONS,
    bitrix_sync_meta_for_detail,
    create_cargo_for_purchase_item,
    build_history_rows,
    build_purchase_rows,
    build_position_rows,
    client_summary_for_detail,
    classify_operation_deal,
    delivery_summary_for_detail,
    finance_summary_for_detail,
    operation_detail_relations,
    operation_status_choices,
    operations_deals_queryset,
    ops_tone_for_cargo_status,
    ops_tone_for_reservation_status,
    ops_tone_for_shipment_status,
    purchase_item_cargo_available_quantity,
    purchase_form_summary,
    purchase_initial_data_for_order_item,
    reservation_candidates_for_deal,
    sync_delivery_data_for_deal,
    upsert_purchase_for_order_item,
)
from orders.models import OrderItem

OPS_MODE_SIMPLE = 'simple'
OPS_MODE_ADVANCED = 'advanced'
OPS_MODE_SESSION_KEY = 'ops_mode'

DEAL_DETAIL_TABS = [
    ('overview', 'Обзор'),
    ('goods', 'Товары'),
    ('purchases', 'Закупки'),
    ('cargos', 'Грузы'),
    ('reservations', 'Резервы'),
    ('shipments', 'Отгрузки'),
    ('finance', 'Финансы'),
    ('history', 'История'),
]


def _ops_mode(request):
    requested_mode = (request.GET.get('mode') or '').strip().lower()
    if requested_mode in {OPS_MODE_SIMPLE, OPS_MODE_ADVANCED}:
        request.session[OPS_MODE_SESSION_KEY] = requested_mode
        return requested_mode
    stored_mode = (request.session.get(OPS_MODE_SESSION_KEY) or '').strip().lower()
    if stored_mode in {OPS_MODE_SIMPLE, OPS_MODE_ADVANCED}:
        return stored_mode
    return OPS_MODE_SIMPLE


def _url_with_query(request, *, route_name=None, kwargs=None, updates=None, drop_keys=None):
    base_url = reverse(route_name, kwargs=kwargs) if route_name else request.path
    query = request.GET.copy()
    for key in drop_keys or []:
        query.pop(key, None)
    for key, value in (updates or {}).items():
        if value in {None, ''}:
            query.pop(key, None)
        else:
            query[key] = value
    query_string = query.urlencode()
    return f'{base_url}?{query_string}' if query_string else base_url


def _ops_nav_groups(request, *, mode):
    return [
        {
            'label': 'Главное',
            'items': [
                {'label': 'Обзор', 'url': _url_with_query(request, route_name='operations:dashboard', updates={'mode': mode}), 'active': request.path == reverse('operations:dashboard')},
                {'label': 'Сделки', 'url': _url_with_query(request, route_name='operations:deal_list', updates={'mode': mode}), 'active': request.path.startswith(reverse('operations:deal_list')) and not request.path.startswith(reverse('operations:history'))},
            ],
        },
        {
            'label': 'Исполнение',
            'items': [
                {'label': 'Закупки', 'url': reverse('manager_portal:purchase_list'), 'active': False},
                {'label': 'Грузы', 'url': reverse('manager_portal:cargo_list'), 'active': False},
                {'label': 'Резервы', 'url': reverse('manager_portal:reservation_list'), 'active': False},
                {'label': 'Отгрузки', 'url': reverse('manager_portal:shipments'), 'active': False},
            ],
        },
        {
            'label': 'Учёт',
            'items': [
                {'label': 'Склад', 'url': reverse('manager_portal:inventory'), 'active': False},
                {'label': 'Финансы', 'url': reverse('manager_portal:finance'), 'active': False},
                {'label': 'История', 'url': _url_with_query(request, route_name='operations:history', updates={'mode': mode}), 'active': request.path.startswith(reverse('operations:history'))},
            ],
        },
        {
            'label': 'Система',
            'items': [
                {'label': 'Справочники', 'url': reverse('admin:app_list', kwargs={'app_label': 'manager_portal'}), 'active': False},
                {'label': 'Настройки', 'url': reverse('admin:index'), 'active': False},
                {'label': 'Админка', 'url': reverse('admin:index'), 'active': False},
            ],
        },
    ]


def _render(request, template_name, **context):
    mode = _ops_mode(request)
    base_context = {
        'ops_mode': mode,
        'ops_mode_label': 'Расширенный' if mode == OPS_MODE_ADVANCED else 'Простой',
        'ops_mode_toggle_url': _url_with_query(request, updates={'mode': OPS_MODE_SIMPLE if mode == OPS_MODE_ADVANCED else OPS_MODE_ADVANCED}),
        'ops_nav_groups': _ops_nav_groups(request, mode=mode),
        'show_ops_reserve_debug': settings.DEBUG and getattr(settings, 'OPS_SHOW_RESERVE_DEBUG', False),
    }
    base_context.update(context)
    return render(request, template_name, base_context)


def _pluralize(value, one, few, many):
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


def _deal_tab_url(deal, tab_code='overview', anchor=''):
    url = reverse('operations:deal_detail', kwargs={'pk': deal.pk})
    if tab_code:
        url = f'{url}?tab={tab_code}'
    if anchor:
        url = f'{url}{anchor}'
    return url


def _ops_shipment_datetime_from_date(value):
    if value is None:
        return None
    return timezone.make_aware(datetime.combine(value, time.min), timezone.get_current_timezone())


def _history_context(request, *, activities, route_name, route_kwargs=None, default_limit=7):
    mode = _ops_mode(request)
    history_filter = (request.GET.get('history_filter') or HISTORY_FILTER_ALL).strip().lower()
    if history_filter not in HISTORY_FILTER_DEFINITIONS:
        history_filter = HISTORY_FILTER_ALL
    show_all = (request.GET.get('history') or '').strip().lower() == 'all'
    include_noisy = mode == OPS_MODE_ADVANCED
    history_rows_all = build_history_rows(
        activities,
        history_filter=history_filter,
        include_noisy=include_noisy,
    )
    history_limit = None if (show_all or mode == OPS_MODE_ADVANCED) else default_limit
    history_rows = history_rows_all if history_limit is None else history_rows_all[:history_limit]
    filter_links = [
        {
            'code': code,
            'label': meta['label'],
            'active': code == history_filter,
            'url': _url_with_query(
                request,
                route_name=route_name,
                kwargs=route_kwargs,
                updates={'history_filter': code, 'history': 'all' if show_all else None, 'mode': mode},
            ),
        }
        for code, meta in HISTORY_FILTER_DEFINITIONS.items()
    ]
    if mode == OPS_MODE_ADVANCED:
        toggle_label = 'Переключить на простой режим'
        toggle_url = _url_with_query(
            request,
            route_name=route_name,
            kwargs=route_kwargs,
            updates={'mode': OPS_MODE_SIMPLE, 'history': None},
        )
    elif show_all:
        toggle_label = 'Показать меньше'
        toggle_url = _url_with_query(
            request,
            route_name=route_name,
            kwargs=route_kwargs,
            updates={'history': None, 'mode': mode},
        )
    else:
        toggle_label = 'Показать всю историю'
        toggle_url = _url_with_query(
            request,
            route_name=route_name,
            kwargs=route_kwargs,
            updates={'history': 'all', 'mode': mode},
        )
    return {
        'history_filter': history_filter,
        'history_rows': history_rows,
        'history_rows_total': len(history_rows_all),
        'history_filter_links': filter_links,
        'history_show_all': show_all or mode == OPS_MODE_ADVANCED,
        'history_is_truncated': history_limit is not None and len(history_rows_all) > len(history_rows),
        'history_toggle_label': toggle_label,
        'history_toggle_url': toggle_url,
    }


def _primary_action_payload(deal, candidate):
    code = candidate.get('code')
    payload = {
        'label': candidate.get('cta_label') or candidate.get('text'),
        'text': candidate.get('text'),
        'reason': candidate.get('reason'),
        'code': code,
        'kind': 'link',
        'url': _deal_tab_url(deal),
        'hidden_fields': [],
    }
    if code == 'assign_self':
        payload.update({'kind': 'post', 'post_action': 'assign_self'})
    elif code in {'fill_recipient', 'fill_phone', 'fill_address'}:
        payload['url'] = reverse('operations:deal_delivery_edit', kwargs={'pk': deal.pk})
    elif code == 'link_products' and candidate.get('item_id'):
        payload['url'] = _deal_tab_url(deal, 'goods', f'#item-{candidate["item_id"]}')
    elif code == 'reserve_stock':
        item_query = f'?item={candidate["item_id"]}' if candidate.get('item_id') else ''
        payload['url'] = f'{reverse("operations:deal_reserve_create", kwargs={"pk": deal.pk})}{item_query}'
    elif code == 'create_purchase' and candidate.get('item_id'):
        payload['url'] = reverse('operations:purchase_form', kwargs={'pk': deal.pk, 'item_pk': candidate['item_id']})
    elif code == 'create_cargo':
        query = []
        if candidate.get('purchase_id'):
            query.append(f'purchase={candidate["purchase_id"]}')
        if candidate.get('purchase_item_id'):
            query.append(f'purchase_item={candidate["purchase_item_id"]}')
        suffix = f'?{"&".join(query)}' if query else ''
        payload['url'] = f'{reverse("operations:deal_cargo_create", kwargs={"pk": deal.pk})}{suffix}'
    elif code == 'receive_cargo' and candidate.get('cargo_item_id'):
        payload['url'] = f'{reverse("operations:deal_cargo_receive", kwargs={"pk": deal.pk})}?item={candidate["cargo_item_id"]}'
    elif code == 'create_shipment':
        payload.update({'kind': 'post', 'post_action': 'create_shipment'})
    elif code == 'ship_shipment' and candidate.get('shipment_id'):
        payload['url'] = reverse(
            'operations:deal_shipment_dispatch',
            kwargs={'pk': deal.pk, 'shipment_pk': candidate['shipment_id']},
        )
    elif code == 'deliver_shipment' and candidate.get('shipment_id'):
        payload.update(
            {
                'kind': 'post',
                'post_action': 'deliver_shipment',
                'hidden_fields': [{'name': 'shipment_id', 'value': candidate['shipment_id']}],
            }
        )
    elif code == 'shipment_delivered':
        payload['url'] = _deal_tab_url(deal, 'shipments')
    elif code == 'deal_completed':
        payload['url'] = _deal_tab_url(deal, 'overview')
    elif code == 'fill_finance':
        payload['url'] = _deal_tab_url(deal, 'finance')
    elif code == 'fill_tracking_number':
        payload['url'] = _deal_tab_url(deal, 'shipments')
    elif code == 'resolve_problem':
        payload['url'] = _deal_tab_url(deal, 'overview', '#blockers')
    return payload


def _position_action_payload(deal, action):
    payload = {
        'code': action['code'],
        'label': action['label'],
        'kind': action['kind'],
        'tone': action.get('tone', 'secondary'),
    }
    if action['kind'] == 'anchor':
        payload['url'] = _deal_tab_url(deal, 'goods', action['url'])
    elif action['kind'] == 'reserve':
        payload['url'] = f'{reverse("operations:deal_reserve_create", kwargs={"pk": deal.pk})}?item={action["item_id"]}'
    elif action['kind'] == 'post':
        payload['post_action'] = action['post_action']
    elif action['kind'] == 'purchase':
        payload['url'] = reverse('operations:purchase_form', kwargs={'pk': deal.pk, 'item_pk': action['item_id']})
    elif action['kind'] == 'cargo':
        payload['url'] = (
            f'{reverse("operations:deal_cargo_create", kwargs={"pk": deal.pk})}'
            f'?purchase={action["purchase_id"]}&purchase_item={action["purchase_item_id"]}'
        )
    elif action['kind'] == 'receive_cargo':
        payload['url'] = f'{reverse("operations:deal_cargo_receive", kwargs={"pk": deal.pk})}?item={action["cargo_item_id"]}'
    return payload


def _blocker_rows(deal, snapshot, position_rows, relations):
    if snapshot.get('status_code') == 'completed':
        return []
    blocker_rows = []
    primary_action = snapshot.get('primary_action') or {}

    def add_blocker(code, label, action):
        if any(existing['code'] == code for existing in blocker_rows):
            return
        blocker_rows.append({'code': code, 'label': label, 'action': action})

    if deal.responsible_manager_id is None:
        add_blocker(
            'assignee',
            'Нет ответственного',
            {'label': 'Назначить себя', 'kind': 'post', 'post_action': 'assign_self'},
        )
    if any('телефон' in blocker.lower() for blocker in snapshot.get('blockers', [])):
        add_blocker(
            'phone',
            'Нет телефона получателя',
            {'label': 'Заполнить доставку', 'kind': 'link', 'url': reverse('operations:deal_delivery_edit', kwargs={'pk': deal.pk})},
        )
    if any('адрес' in blocker.lower() for blocker in snapshot.get('blockers', [])):
        add_blocker(
            'address',
            'Нет адреса доставки',
            {'label': 'Заполнить доставку', 'kind': 'link', 'url': reverse('operations:deal_delivery_edit', kwargs={'pk': deal.pk})},
        )
    custom_rows = [row for row in position_rows if row['is_link_required']]
    if custom_rows:
        count = len(custom_rows)
        add_blocker(
            'catalog_link',
            f'{count} {_pluralize(count, "товар не связан", "товара не связаны", "товаров не связаны")} с каталогом',
            {'label': 'Связать товар', 'kind': 'link', 'url': _deal_tab_url(deal, 'goods', f'#item-{custom_rows[0]["item"].id}')},
        )
    uncovered_rows = [row for row in position_rows if not row['is_link_required'] and row['missing'] > 0]
    if uncovered_rows:
        count = len(uncovered_rows)
        coverage_action = (
            _primary_action_payload(deal, primary_action)
            if primary_action.get('code') in {'reserve_stock', 'create_purchase', 'create_cargo'}
            else {'label': 'Открыть товары', 'kind': 'link', 'url': _deal_tab_url(deal, 'goods')}
        )
        add_blocker(
            'coverage',
            f'Не хватает обеспечения по {count} {_pluralize(count, "позиции", "позициям", "позициям")}',
            coverage_action,
        )
    purchase_missing_rows = [
        row
        for row in uncovered_rows
        if row['purchase_item'] is None and row['free_stock'] <= row['reserved']
    ]
    if purchase_missing_rows:
        count = len(purchase_missing_rows)
        add_blocker(
            'purchase',
            f'Нет закупки для {count} {_pluralize(count, "позиции", "позиций", "позиций")}',
            {
                'label': 'Создать закупку',
                'kind': 'link',
                'url': reverse('operations:purchase_form', kwargs={'pk': deal.pk, 'item_pk': purchase_missing_rows[0]['item'].id}),
            },
        )
    cargo_without_eta = next(
        (
            cargo
            for cargo in relations['cargos']
            if cargo.status not in {Cargo.STATUS_CANCELLED, Cargo.STATUS_RECEIVED} and cargo.eta is None
        ),
        None,
    )
    if cargo_without_eta is not None:
        add_blocker(
            'cargo_eta',
            f'Груз {cargo_without_eta.cargo_number or cargo_without_eta.pk} без ETA',
            {'label': 'Открыть груз', 'kind': 'link', 'url': _deal_tab_url(deal, 'cargos', f'#cargo-{cargo_without_eta.id}')},
        )
    if snapshot.get('status_code') == 'ready_to_ship' and not relations['shipments']:
        add_blocker(
            'shipment',
            'Нет отгрузки',
            {'label': 'Создать отгрузку', 'kind': 'post', 'post_action': 'create_shipment'},
        )
    return blocker_rows


def _overview_cards(position_rows, relations):
    ready_to_ship = sum(1 for row in position_rows if row['status_label'] == 'Готово к отгрузке')
    missing = sum(1 for row in position_rows if row['missing'] > 0 and not row['is_link_required'])
    in_transit = sum(1 for row in position_rows if row['in_transit'] > 0)
    return [
        {
            'title': 'Позиции',
            'summary': f'{len(position_rows)} строк, {ready_to_ship} готовы к отгрузке',
            'detail': f'Не хватает обеспечения по {missing}, в пути {in_transit}.',
        },
        {
            'title': 'Закупки',
            'summary': f'{len(relations["purchases"])} закупок',
            'detail': 'Подробности вынесены на отдельную вкладку.',
        },
        {
            'title': 'Грузы',
            'summary': f'{len(relations["cargos"])} грузов',
            'detail': f'В работе {sum(1 for cargo in relations["cargos"] if cargo.status != Cargo.STATUS_RECEIVED)}.',
        },
        {
            'title': 'Отгрузки',
            'summary': f'{len(relations["shipments"])} отгрузок',
            'detail': 'Финальный этап исполнения сделки.',
        },
    ]


def _ops_cargo_status_label(cargo):
    label_map = {
        Cargo.STATUS_CREATED: 'Создан',
        Cargo.STATUS_IN_TRANSIT: 'В пути',
        Cargo.STATUS_ARRIVED_RF: 'Прибыл',
        Cargo.STATUS_DELIVERY_RF: 'В пути',
        Cargo.STATUS_AWAITING_RECEIPT: 'Ожидает приемки',
        Cargo.STATUS_RECEIVED: 'Принят',
        Cargo.STATUS_CANCELLED: 'Отменен',
    }
    return label_map.get(cargo.status, cargo.get_status_display())


def _build_cargo_rows(deal, cargos):
    rows = []
    for cargo in cargos:
        item_rows = []
        first_receivable_url = ''
        for cargo_item in cargo.items.all():
            purchase_item = cargo_item.purchase_item
            order_item = purchase_item.order_item if purchase_item and purchase_item.order_item_id else None
            if order_item is not None and order_item.order_id != deal.order_id:
                continue
            receive_url = f"{reverse('operations:deal_cargo_receive', kwargs={'pk': deal.pk})}?item={cargo_item.id}"
            if cargo_item.remaining_quantity > 0 and not first_receivable_url:
                first_receivable_url = receive_url
            item_rows.append(
                {
                    'item': cargo_item,
                    'order_item': order_item,
                    'can_receive': cargo_item.remaining_quantity > 0,
                    'receive_url': receive_url,
                }
            )
        if item_rows:
            rows.append(
                {
                    'cargo': cargo,
                    'status_label': _ops_cargo_status_label(cargo),
                    'status_tone': ops_tone_for_cargo_status(cargo.status),
                    'items': item_rows,
                    'can_receive_any': bool(first_receivable_url),
                    'receive_url': first_receivable_url,
                }
            )
    return rows


def _deal_list_context(request, *, deals=None):
    deals = deals if deals is not None else list(operations_deals_queryset())
    filter_form = OperationsDealFilterForm(
        request.GET or None,
        status_choices=operation_status_choices(),
    )
    if filter_form.is_valid():
        filtered_deals = filter_operation_deals(deals, filter_form.cleaned_data)
    else:
        filtered_deals = []
        for deal in deals:
            snapshot = getattr(deal, 'operation_snapshot', None) or classify_operation_deal(deal)
            prepare_operation_deal(deal, snapshot=snapshot)
            filtered_deals.append(deal)

    return {
        'filter_form': filter_form,
        'deals': filtered_deals,
        'deals_total': len(filtered_deals),
    }


@staff_required
def dashboard_view(request):
    deals = list(operations_deals_queryset())
    dashboard_groups = dashboard_groups_for_deals(deals)
    for group in dashboard_groups:
        group['url'] = f"{reverse('operations:deal_list')}?status={group['code']}"
        group['preview_items'] = group['items'][:4]
    return _render(
        request,
        'operations/dashboard.html',
        page_title='Операторский портал',
        page_subtitle='Bitrix24 остаётся источником продаж, а здесь живёт исполнение сделки.',
        dashboard_kpis=dashboard_kpis_for_deals(deals),
        dashboard_groups=dashboard_groups,
        active_deals_total=len(deals),
    )


@staff_required
def deal_list_view(request):
    context = _deal_list_context(request)
    return _render(
        request,
        'operations/deal_list.html',
        page_title='Операционные сделки',
        page_subtitle='Только исполнение: товар, обеспечение, закупки, грузы, резервы, отгрузки и финансы.',
        **context,
    )


@staff_required
def history_view(request):
    activities = list(
        DealActivity.objects.select_related('actor', 'manager_deal')
        .exclude(manager_deal__case_status__in=[ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED])
        .order_by('-created_at', '-id')[:120]
    )
    history_context = _history_context(
        request,
        activities=activities,
        route_name='operations:history',
        default_limit=20,
    )
    return _render(
        request,
        'operations/history.html',
        page_title='История исполнения',
        page_subtitle='Последние действия по активным сделкам без CRM-шумов.',
        **history_context,
    )


def _shipment_row_actions(deal, shipment):
    if shipment.status in {shipment.STATUS_DRAFT, shipment.STATUS_PENDING} and shipment.inventory_consumed_at is None:
        return [
            {
                'label': 'Отправить',
                'kind': 'link',
                'url': reverse('operations:deal_shipment_dispatch', kwargs={'pk': deal.pk, 'shipment_pk': shipment.pk}),
            },
            {
                'label': 'Отменить',
                'kind': 'post',
                'post_action': 'cancel_shipment',
                'hidden_fields': [{'name': 'shipment_id', 'value': shipment.pk}],
            },
        ]
    if shipment.status == shipment.STATUS_SHIPPED:
        return [
            {
                'label': 'Отметить доставлено',
                'kind': 'post',
                'post_action': 'deliver_shipment',
                'hidden_fields': [{'name': 'shipment_id', 'value': shipment.pk}],
            }
        ]
    return []


def _headline_shipment(shipments):
    if not shipments:
        return None
    for status in (Shipment.STATUS_PENDING, Shipment.STATUS_DRAFT, Shipment.STATUS_SHIPPED, Shipment.STATUS_DELIVERED):
        candidate = next((shipment for shipment in shipments if shipment.status == status), None)
        if candidate is not None:
            return candidate
    return shipments[0]


def _detail_context(request, deal, *, link_forms=None, active_tab='overview'):
    relations = operation_detail_relations(deal)
    operation_snapshot = classify_operation_deal(deal, relations=relations)
    prepare_operation_deal(deal, snapshot=operation_snapshot)
    order_items = list(deal.order.items.select_related('product', 'variant').all())
    link_forms = link_forms or {}
    order_item_rows = []
    for item in order_items:
        link_form = None
        if item.line_type == item.LINE_TYPE_CUSTOM:
            link_form = link_forms.get(
                item.id,
                CustomOrderItemLinkForm(prefix=f'item-{item.id}', initial={'item_id': item.id}),
            )
        order_item_rows.append({'item': item, 'link_form': link_form})
    link_forms_by_item_id = {row['item'].id: row['link_form'] for row in order_item_rows if row['link_form'] is not None}
    purchase_rows = build_purchase_rows(deal, relations['purchases'])
    purchase_items_by_order_item = {}
    for purchase_row in purchase_rows:
        for item_row in purchase_row['items']:
            purchase_items_by_order_item.setdefault(item_row['order_item'].id, item_row['item'])
    pending_cargo_items_by_order_item = {}
    for group in operation_snapshot['pending_cargo_receipts']:
        for cargo_item in group['items']:
            purchase_item = cargo_item.purchase_item
            order_item = purchase_item.order_item if purchase_item and purchase_item.order_item_id else None
            if order_item is None:
                continue
            pending_cargo_items_by_order_item.setdefault(order_item.id, cargo_item)
    position_rows = build_position_rows(
        deal,
        supply_snapshot=operation_snapshot['supply_snapshot'],
        purchase_items_by_order_item=purchase_items_by_order_item,
        pending_cargo_items_by_order_item=pending_cargo_items_by_order_item,
        shipments=relations['shipments'],
    )
    for line in position_rows:
        line['actions'] = [_position_action_payload(deal, action) for action in line['actions']]
        line['link_form'] = link_forms_by_item_id.get(line['item'].id)
    is_completed = operation_snapshot['status_code'] == 'completed'
    shipment_action_enabled = bool(
        not is_completed
        and not relations['shipments']
        and any(
            action.get('code') == 'create_shipment'
            for line in position_rows
            for action in line['actions']
        )
    )
    purchase_target_item = next(
        (
            row['item']
            for row in position_rows
            for action in row['actions']
            if action['code'] == 'create_purchase'
        ),
        None,
    )
    purchase_target_blocked_reason = ''
    if is_completed:
        purchase_target_item = None
        purchase_target_blocked_reason = 'Сделка уже исполнена.'
    elif purchase_target_item is None and operation_snapshot['custom_items']:
        purchase_target_blocked_reason = 'Сначала свяжите товар с каталогом сайта.'
    cargo_target_purchase_item = next(
        (
            item_row['item']
            for purchase_row in purchase_rows
            for item_row in purchase_row['items']
            if purchase_item_cargo_available_quantity(item_row['item']) > 0
            and item_row['order_item'].shipped_quantity < item_row['order_item'].active_quantity
        ),
        None,
    )
    if is_completed:
        cargo_target_purchase_item = None
    history_context = _history_context(
        request,
        activities=relations['activities'],
        route_name='operations:deal_detail',
        route_kwargs={'pk': deal.pk},
    )
    headline_shipment = _headline_shipment(relations['shipments'])
    return {
        'deal': deal,
        'operation_snapshot': operation_snapshot,
        'position_rows': position_rows,
        'detail_tabs': [
            {'code': code, 'label': label, 'active': code == active_tab, 'url': _deal_tab_url(deal, code)}
            for code, label in DEAL_DETAIL_TABS
        ],
        'active_tab': active_tab,
        'primary_action': _primary_action_payload(deal, operation_snapshot['primary_action']),
        'blocker_rows': _blocker_rows(deal, operation_snapshot, position_rows, relations),
        'overview_cards': _overview_cards(position_rows, relations),
        'purchase_target_item': purchase_target_item,
        'purchase_target_blocked_reason': purchase_target_blocked_reason,
        'cargo_target_purchase_item': cargo_target_purchase_item,
        'client_summary': client_summary_for_detail(deal),
        'delivery_summary': delivery_summary_for_detail(deal),
        'headline_shipment': headline_shipment,
        'relations': relations,
        'purchase_rows': purchase_rows,
        'cargo_rows': _build_cargo_rows(deal, relations['cargos']),
        'reservation_rows': [
            {'reservation': reservation, 'status_tone': ops_tone_for_reservation_status(reservation.status)}
            for reservation in relations['reservations']
        ],
        'shipment_rows': [
            {
                'shipment': shipment,
                'status_tone': ops_tone_for_shipment_status(shipment.status),
                'actions': _shipment_row_actions(deal, shipment),
                'items_total': sum(int(item.quantity or 0) for item in shipment.items.all()),
            }
            for shipment in relations['shipments']
        ],
        'shipment_action_enabled': shipment_action_enabled,
        'finance_summary': finance_summary_for_detail(relations['finance_deal']),
        'order_item_rows': order_item_rows,
        'source_bitrix': bitrix_sync_meta_for_detail(deal, relations['activities']),
        **history_context,
    }


def _cargo_form_scope(deal, source):
    purchase = None
    purchase_item = None
    raw_purchase_id = ''
    if hasattr(source, 'get'):
        raw_purchase_id = str(source.get('purchase') or source.get('scope_purchase') or '').strip()
    if raw_purchase_id:
        purchase = get_object_or_404(
            Purchase.objects.filter(items__order_item__order=deal.order)
            .exclude(status=Purchase.STATUS_CANCELLED)
            .distinct(),
            pk=raw_purchase_id,
        )

    purchase_items = (
        PurchaseItem.objects.filter(order_item__order=deal.order)
        .exclude(purchase__status=Purchase.STATUS_CANCELLED)
        .select_related('purchase', 'product', 'variant', 'order_item')
        .prefetch_related('cargo_items__cargo')
    )
    if purchase is not None:
        purchase_items = purchase_items.filter(purchase=purchase)

    raw_purchase_item_id = ''
    if hasattr(source, 'get'):
        raw_purchase_item_id = str(source.get('scope_purchase_item') or source.get('purchase_item') or '').strip()
    if raw_purchase_item_id:
        purchase_item = get_object_or_404(purchase_items, pk=raw_purchase_item_id)
        purchase = purchase_item.purchase
    return purchase, purchase_item


def _pending_cargo_items_queryset(deal):
    return (
        CargoItem.objects.filter(
            purchase_item__order_item__order=deal.order,
            quantity__gt=F('received_quantity'),
        )
        .exclude(cargo__status=Cargo.STATUS_CANCELLED)
        .select_related(
            'cargo',
            'cargo__destination_warehouse',
            'product',
            'variant',
            'purchase_item',
            'purchase_item__order_item',
        )
        .order_by('cargo__eta', 'cargo_id', 'id')
    )


@staff_required
def deal_detail_view(request, pk):
    deal = get_object_or_404(
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse'),
        pk=pk,
    )
    valid_tabs = {code for code, _label in DEAL_DETAIL_TABS}
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        try:
            if action == 'assign_self':
                apply_deal_assignment(deal, responsible_manager=request.user, actor=request.user)
                messages.success(request, 'Вы назначены ответственным по сделке.')
                return redirect('operations:deal_detail', pk=deal.pk)
            if action == 'reserve_stock':
                first_candidate = next(iter(reservation_candidates_for_deal(deal).values()), None)
                reserve_url = reverse('operations:deal_reserve_create', kwargs={'pk': deal.pk})
                if first_candidate is not None:
                    reserve_url = f'{reserve_url}?item={first_candidate["order_item"].id}'
                return redirect(reserve_url)
            if action == 'create_purchase':
                messages.error(request, 'Выберите строку товара и заполните форму закупки.')
                return redirect('operations:deal_detail', pk=deal.pk)
            if action == 'create_cargo':
                return redirect('operations:deal_cargo_create', pk=deal.pk)
            if action == 'create_shipment':
                shipment = ensure_shipment_for_manager_deal(deal, actor=request.user)
                messages.success(request, f'Отгрузка {shipment.code or shipment.pk} подготовлена.')
                return redirect(f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments')
            if action == 'deliver_shipment':
                shipment = get_object_or_404(deal.shipments.exclude(status=Shipment.STATUS_CANCELLED), pk=request.POST.get('shipment_id'))
                shipment = mark_shipment_delivered(shipment, author=request.user)
                messages.success(request, f'Отгрузка {shipment.code or shipment.pk} отмечена как доставленная.')
                return redirect(f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments')
            if action == 'cancel_shipment':
                shipment = get_object_or_404(deal.shipments.exclude(status=Shipment.STATUS_CANCELLED), pk=request.POST.get('shipment_id'))
                shipment = cancel_shipment(shipment, author=request.user, comment='Отменено из OPS.')
                messages.success(request, f'Отгрузка {shipment.code or shipment.pk} отменена.')
                return redirect(f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments')
            if action == 'link_product':
                raw_item_id = request.POST.get('item_id') or ''
                if not raw_item_id:
                    for key, value in request.POST.items():
                        if key.endswith('-item_id') and str(value).strip():
                            raw_item_id = value
                            break
                item_id = int(raw_item_id or 0)
                order_item = get_object_or_404(deal.order.items.all(), pk=item_id)
                form = CustomOrderItemLinkForm(request.POST, prefix=f'item-{item_id}')
                if form.is_valid():
                    linked_item = link_manual_order_item_to_catalog_product(
                        order_item,
                        product=form.cleaned_data['product'],
                        variant=form.cleaned_data.get('variant'),
                        actor=request.user,
                    )
                    messages.success(request, f'Позиция "{linked_item.display_name}" связана с каталогом сайта.')
                    return redirect('operations:deal_detail', pk=deal.pk)
                active_tab = (request.POST.get('tab') or request.GET.get('tab') or 'goods').strip()
                if active_tab not in valid_tabs:
                    active_tab = 'goods'
                context = _detail_context(request, deal, link_forms={item_id: form}, active_tab=active_tab)
                context['page_title'] = f'Сделка {deal.code or deal.order_id}'
                context['page_subtitle'] = 'Операционная карточка без CRM-слоя.'
                return _render(request, 'operations/deal_detail.html', **context)
            messages.error(request, 'Неизвестное действие.')
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect('operations:deal_detail', pk=deal.pk)

    active_tab = (request.GET.get('tab') or 'overview').strip()
    if active_tab not in valid_tabs:
        active_tab = 'overview'
    context = _detail_context(request, deal, active_tab=active_tab)
    context['page_title'] = f'Сделка {deal.code or deal.order_id}'
    context['page_subtitle'] = 'Операционная карточка без CRM-слоя.'
    return _render(request, 'operations/deal_detail.html', **context)


@staff_required
def reservation_form_view(request, pk):
    deal = get_object_or_404(
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse'),
        pk=pk,
    )
    selected_order_item = None
    raw_item_id = (request.GET.get('item') or request.POST.get('order_item') or '').strip()
    candidate_map = reservation_candidates_for_deal(deal)
    if raw_item_id.isdigit():
        selected_candidate = candidate_map.get(int(raw_item_id))
        if selected_candidate is not None:
            selected_order_item = selected_candidate['order_item']

    if request.method == 'POST':
        form = OperationsReservationCreateForm(request.POST, deal=deal, selected_order_item=selected_order_item)
        if form.is_valid():
            reservation, reservation_item = reserve_order_item_for_manager_deal(
                deal,
                order_item=form.cleaned_data['order_item'],
                warehouse=form.cleaned_data['warehouse'],
                quantity=form.cleaned_data['quantity'],
                comment=form.cleaned_data.get('comment', ''),
                actor=request.user,
            )
            messages.success(
                request,
                f'Резерв {reservation.code or reservation.pk} создан: {reservation_item.product.name} · {reservation_item.quantity} шт.',
            )
            return redirect(f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=goods')
    else:
        form = OperationsReservationCreateForm(deal=deal, selected_order_item=selected_order_item)

    selected_candidate = form.current_candidate
    return _render(
        request,
        'operations/reservation_form.html',
        page_title=f'Резерв по сделке {deal.code or deal.order_id}',
        page_subtitle='Закрепляем конкретный складской остаток под строку сделки и сразу пересчитываем обеспечение.',
        deal=deal,
        form=form,
        has_candidates=form.has_candidates,
        selected_candidate=selected_candidate,
    )


@staff_required
def shipment_dispatch_form_view(request, pk, shipment_pk):
    deal = get_object_or_404(
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse'),
        pk=pk,
    )
    shipment = get_object_or_404(
        deal.shipments.select_related('source_warehouse', 'target_warehouse', 'reservation'),
        pk=shipment_pk,
    )

    if request.method == 'POST':
        form = OperationsShipmentDispatchForm(request.POST, shipment=shipment)
        if form.is_valid():
            dispatched = ship_shipment(
                shipment,
                author=request.user,
                carrier=form.cleaned_data['carrier'],
                tracking_number=form.cleaned_data['tracking_number'],
                shipped_at=_ops_shipment_datetime_from_date(form.cleaned_data['shipped_at']),
                comment=form.cleaned_data.get('comment', ''),
            )
            messages.success(request, f'Отгрузка {dispatched.code or dispatched.pk} отправлена.')
            return redirect(f'{reverse("operations:deal_detail", kwargs={"pk": deal.pk})}?tab=shipments')
    else:
        form = OperationsShipmentDispatchForm(shipment=shipment)

    return _render(
        request,
        'operations/shipment_dispatch_form.html',
        page_title=f'Отправить отгрузку {shipment.code or shipment.pk}',
        page_subtitle='Фиксируем отправку, трек и проводим складской эффект по текущей отгрузке.',
        deal=deal,
        shipment=shipment,
        form=form,
        operation_snapshot=classify_operation_deal(deal),
        client_summary=client_summary_for_detail(deal),
    )


@staff_required
def cargo_receive_view(request, pk):
    deal = get_object_or_404(
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse'),
        pk=pk,
    )
    pending_items = _pending_cargo_items_queryset(deal)
    selected_item = None
    raw_item_id = (request.GET.get('item') or request.POST.get('cargo_item') or '').strip()
    if raw_item_id.isdigit():
        selected_item = pending_items.filter(pk=int(raw_item_id)).first()

    if request.method == 'POST':
        form = OperationsCargoAcceptanceForm(request.POST, deal=deal, cargo_item=selected_item)
        if form.is_valid():
            cargo_item = form.cleaned_data['cargo_item']
            quantity = form.cleaned_data['quantity']
            receive_cargo_item(
                cargo_item,
                quantity=quantity,
                warehouse=form.cleaned_data['warehouse'],
                received_at=form.cleaned_data['received_date'],
                comment=form.cleaned_data.get('comment', ''),
                author=request.user,
            )
            messages.success(
                request,
                f'По грузу {cargo_item.cargo.cargo_number or cargo_item.cargo.pk} принято {quantity} шт.',
            )
            return redirect('operations:deal_detail', pk=deal.pk)
    else:
        form = OperationsCargoAcceptanceForm(deal=deal, cargo_item=selected_item)

    context = {
        'deal': deal,
        'form': form,
        'page_title': f'Приемка груза · {deal.code or deal.order_id}',
        'page_subtitle': 'Проведите груз в складской контур и обновите обеспечение по сделке.',
        'pending_items': list(pending_items),
        'selected_item': selected_item,
    }
    return _render(request, 'operations/cargo_receive_form.html', **context)


@staff_required
def deal_delivery_edit_view(request, pk):
    deal = get_object_or_404(
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse'),
        pk=pk,
    )
    if request.method == 'POST':
        form = OperationsOrderDeliveryForm(request.POST, instance=deal.order)
        if form.is_valid():
            form.save()
            sync_delivery_data_for_deal(deal, actor=request.user)
            messages.success(request, 'Данные доставки сохранены.')
            return redirect('operations:deal_detail', pk=deal.pk)
    else:
        form = OperationsOrderDeliveryForm(instance=deal.order)

    return _render(
        request,
        'operations/deal_delivery_form.html',
        page_title=f'Доставка по сделке {deal.code or deal.order_id}',
        page_subtitle='Заполните данные получателя и доставки.',
        deal=deal,
        form=form,
        operation_snapshot=classify_operation_deal(deal),
        client_summary=client_summary_for_detail(deal),
    )


@staff_required
def cargo_form_view(request, pk):
    deal = get_object_or_404(
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse'),
        pk=pk,
    )
    scope_source = request.GET if request.method == 'GET' else request.POST
    purchase, purchase_item = _cargo_form_scope(deal, scope_source)

    if request.method == 'POST':
        form = OperationsCargoCreateForm(
            request.POST,
            deal=deal,
            purchase=purchase,
            purchase_item=purchase_item,
        )
        if form.is_valid():
            cargo, cargo_item = create_cargo_for_purchase_item(
                deal,
                purchase_item=form.cleaned_data['purchase_item'],
                quantity=form.cleaned_data['quantity'],
                destination_warehouse=form.cleaned_data['destination_warehouse'],
                eta=form.cleaned_data.get('eta'),
                status=form.cleaned_data['status'],
                comments=form.cleaned_data.get('comments', ''),
                cargo_number=form.cleaned_data.get('cargo_number', ''),
                actor=request.user,
            )
            messages.success(
                request,
                f'Груз {cargo.cargo_number or cargo.pk} создан: {cargo_item.quantity} шт. по позиции закупки.',
            )
            return redirect('operations:deal_detail', pk=deal.pk)
    else:
        form = OperationsCargoCreateForm(
            deal=deal,
            purchase=purchase,
            purchase_item=purchase_item,
        )

    return _render(
        request,
        'operations/cargo_form.html',
        page_title=f'Груз по сделке {deal.code or deal.order_id}',
        page_subtitle='Заполните груз и привяжите его к конкретной позиции закупки.',
        deal=deal,
        form=form,
        has_purchase_items=form.fields['purchase_item'].queryset.exists(),
        selected_purchase=purchase,
        selected_purchase_item=purchase_item,
    )


@staff_required
def purchase_form_view(request, pk, item_pk):
    deal = get_object_or_404(
        ManagerDeal.objects.select_related('order', 'responsible_manager', 'stock_warehouse'),
        pk=pk,
    )
    order_item = get_object_or_404(
        deal.order.items.select_related('product', 'variant'),
        pk=item_pk,
    )
    if order_item.line_type != OrderItem.LINE_TYPE_CATALOG or not order_item.product_id:
        messages.error(request, 'Закупку можно оформить только для каталоговой позиции.')
        return redirect('operations:deal_detail', pk=deal.pk)

    initial_data, existing_purchase_item = purchase_initial_data_for_order_item(deal, order_item)
    current_currency = (
        request.POST.get('currency')
        if request.method == 'POST'
        else initial_data.get('currency')
    )
    if request.method == 'POST':
        form = OperationsPurchaseForm(request.POST, currency_value=current_currency)
        if form.is_valid():
            purchase, _purchase_item, created = upsert_purchase_for_order_item(
                deal,
                order_item,
                supplier_name=form.cleaned_data['supplier_name'],
                quantity=form.cleaned_data['quantity'],
                unit_cost=form.cleaned_data['unit_cost'],
                currency=form.cleaned_data['currency'],
                status=form.cleaned_data['status'],
                comments=form.cleaned_data['comments'],
                actor=request.user,
            )
            action_label = 'создана' if created else 'обновлена'
            messages.success(request, f'Закупка {purchase.code or purchase.pk} {action_label}.')
            return redirect('operations:deal_detail', pk=deal.pk)
    else:
        form = OperationsPurchaseForm(initial=initial_data, currency_value=current_currency)

    purchase_summary = purchase_form_summary(
        order_item,
        quantity=request.POST.get('quantity') if request.method == 'POST' else initial_data.get('quantity'),
        unit_cost=request.POST.get('unit_cost') if request.method == 'POST' else initial_data.get('unit_cost'),
    )

    return _render(
        request,
        'operations/purchase_form.html',
        page_title=f'Закупка по сделке {deal.code or deal.order_id}',
        page_subtitle='Заполните закупку по конкретной строке заказа.',
        deal=deal,
        order_item=order_item,
        form=form,
        existing_purchase_item=existing_purchase_item,
        purchase_summary=purchase_summary,
    )


@csrf_exempt
@require_POST
def bitrix_deal_in_work_view(request):
    payload = request.POST
    if request.content_type and 'application/json' in request.content_type:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}

    expected_token = (getattr(settings, 'BITRIX_INGEST_TOKEN', '') or '').strip()
    provided_token = (payload.get('token') if hasattr(payload, 'get') else '') or request.headers.get('X-Bizon-Bitrix-Token') or ''
    provided_token = str(provided_token).strip()
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        return JsonResponse({'ok': False, 'error': 'Неверный token.'}, status=403)

    deal_id = str((payload.get('deal_id') if hasattr(payload, 'get') else '') or '').strip()
    if not deal_id:
        return JsonResponse({'ok': False, 'error': 'Не указан deal_id.'}, status=400)

    try:
        result = sync_bitrix_deal_into_operations(deal_id)
    except BitrixImportError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=502)

    return JsonResponse(
        {
            'ok': True,
            'order_id': result['order'].pk,
            'manager_deal_id': result['manager_deal'].pk,
            'items_count': result.get('order_item_count') or result['order'].items.count(),
            'warnings': result.get('warnings', []),
        }
    )
