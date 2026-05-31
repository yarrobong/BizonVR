import csv
import json
import logging
import zipfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.services import normalize_email, normalize_phone
from catalog.models import Product, ProductStock, ProductVariant
from orders.models import Order, OrderItem, resolve_order_item_image_url
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
    FinanceDealAdjustment,
    FinanceDealLine,
    FinanceDealShare,
    FinanceDealType,
    FinanceDistributionRule,
    FinanceDistributionScheme,
    FinanceExpense,
    FinancePayout,
    InventoryBalance,
    InventoryLot,
    InventoryMovement,
    ManagerClient,
    ManagerDeal,
    ManagerDealParticipant,
    ManagerPersonAlias,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    SaleLineAllocation,
    Shipment,
    ShipmentItem,
    Warehouse,
)


ACTIVE_RESERVATION_STATUSES = {
    Reservation.STATUS_DRAFT,
    Reservation.STATUS_ACTIVE,
    Reservation.STATUS_PARTIAL,
}
SUPPLY_COVERAGE_STATE_COVERED_BY_STOCK = 'covered_by_stock'
SUPPLY_COVERAGE_STATE_COVERED_BY_INCOMING = 'covered_by_incoming'
SUPPLY_COVERAGE_STATE_COVERED_BY_PROCUREMENT = 'covered_by_procurement'
SUPPLY_COVERAGE_STATE_UNCOVERED = 'uncovered'
SUPPLY_COVERAGE_STATES = (
    SUPPLY_COVERAGE_STATE_COVERED_BY_STOCK,
    SUPPLY_COVERAGE_STATE_COVERED_BY_INCOMING,
    SUPPLY_COVERAGE_STATE_COVERED_BY_PROCUREMENT,
    SUPPLY_COVERAGE_STATE_UNCOVERED,
)
SUPPLY_COVERAGE_STATE_META = {
    SUPPLY_COVERAGE_STATE_COVERED_BY_STOCK: {
        'label': 'Покрыто складом',
        'tone': 'ready',
    },
    SUPPLY_COVERAGE_STATE_COVERED_BY_INCOMING: {
        'label': 'Покрыто incoming',
        'tone': 'working',
    },
    SUPPLY_COVERAGE_STATE_COVERED_BY_PROCUREMENT: {
        'label': 'В закупке',
        'tone': 'working',
    },
    SUPPLY_COVERAGE_STATE_UNCOVERED: {
        'label': 'Не обеспечена',
        'tone': 'blocked',
    },
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
BITRIX_API_TIMEOUT_SECONDS = 15
logger = logging.getLogger(__name__)


class BitrixImportError(RuntimeError):
    pass


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


def _bitrix_text(value):
    return str(value or '').strip()


def _bitrix_decimal(value, *, default='0'):
    raw_value = _bitrix_text(value).replace(' ', '').replace(',', '.')
    if not raw_value:
        raw_value = default
    try:
        return Decimal(raw_value)
    except Exception as exc:  # pragma: no cover - defensive parsing
        raise BitrixImportError(f'Не удалось прочитать денежное значение Bitrix: {value!r}') from exc


def _bitrix_int(value, *, default=0):
    try:
        return max(int(_bitrix_decimal(value, default=str(default))), 0)
    except BitrixImportError:
        return default


def _bitrix_first_multifield(value):
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                candidate = _bitrix_text(item.get('VALUE'))
            else:
                candidate = _bitrix_text(item)
            if candidate:
                return candidate
    if isinstance(value, dict):
        candidate = _bitrix_text(value.get('VALUE'))
        if candidate:
            return candidate
    return _bitrix_text(value)


def _bitrix_parse_datetime(value):
    raw_value = _bitrix_text(value)
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
    except ValueError:
        try:
            parsed = datetime.strptime(raw_value, '%Y-%m-%d')
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _bitrix_portal_root():
    webhook_url = _bitrix_text(getattr(settings, 'BITRIX_WEBHOOK_URL', ''))
    if not webhook_url:
        return ''
    parsed = urlparse(webhook_url)
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f'{parsed.scheme}://{parsed.netloc}'


def build_bitrix_deal_url(deal_id):
    portal_root = _bitrix_portal_root()
    if not portal_root:
        return ''
    return f'{portal_root}/crm/deal/details/{deal_id}/'


def _bitrix_api_request(method_name, *, params=None):
    webhook_url = _bitrix_text(getattr(settings, 'BITRIX_WEBHOOK_URL', ''))
    if not webhook_url:
        raise BitrixImportError('Не задан BITRIX_WEBHOOK_URL.')
    url = f'{webhook_url.rstrip("/")}/{method_name}.json'
    try:
        response = requests.get(url, params=params or {}, timeout=BITRIX_API_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json() or {}
    except (requests.RequestException, ValueError) as exc:
        raise BitrixImportError(f'Не удалось получить данные Bitrix по методу {method_name}.') from exc
    if payload.get('error'):
        message = payload.get('error_description') or payload.get('error') or 'Bitrix вернул ошибку.'
        raise BitrixImportError(message)
    return payload.get('result')


def _bitrix_optional_entity_id(value):
    normalized_value = _bitrix_text(value)
    if normalized_value in {'', '0'}:
        return ''
    return normalized_value


def _bitrix_optional_request(method_name, *, params=None, entity_label='', entity_id='', warnings=None):
    warnings = warnings if warnings is not None else []
    normalized_entity_id = _bitrix_optional_entity_id(entity_id)
    if not normalized_entity_id:
        return {}
    try:
        result = _bitrix_api_request(method_name, params=params)
    except BitrixImportError as exc:
        warning = (
            f'Bitrix {entity_label} #{normalized_entity_id} не импортирован: '
            f'{exc}'
        ).strip()
        logger.warning(warning)
        warnings.append(warning)
        return {}
    if not isinstance(result, dict) or not result:
        warning = f'Bitrix {entity_label} #{normalized_entity_id} не найден или вернул пустой result.'.strip()
        logger.warning(warning)
        warnings.append(warning)
        return {}
    return result


def _bitrix_deal_mapped_field(deal_data, setting_name):
    field_name = _bitrix_text(getattr(settings, setting_name, ''))
    if not field_name:
        return ''
    return _bitrix_text((deal_data or {}).get(field_name))


def _bitrix_deal_mapped_payload(deal_data):
    return {
        'city': _bitrix_deal_mapped_field(deal_data, 'BITRIX_FIELD_CITY'),
        'client_request': _bitrix_deal_mapped_field(deal_data, 'BITRIX_FIELD_CLIENT_REQUEST'),
        'delivery_address': _bitrix_deal_mapped_field(deal_data, 'BITRIX_FIELD_DELIVERY_ADDRESS'),
        'recipient_name': _bitrix_deal_mapped_field(deal_data, 'BITRIX_FIELD_RECIPIENT_NAME'),
        'recipient_phone': _bitrix_deal_mapped_field(deal_data, 'BITRIX_FIELD_RECIPIENT_PHONE'),
    }


def _bitrix_deal_comment_payload(*, comment='', client_request=''):
    base_comment = _bitrix_text(comment)
    mapped_request = _bitrix_text(client_request)
    request_comment = f'Запрос клиента: {mapped_request}' if mapped_request else ''
    combined_comment = '\n\n'.join(part for part in [base_comment, request_comment] if part)
    return {
        'comment': combined_comment,
        'delivery_comment': request_comment,
    }


def _bitrix_manager_client_comments(*, deal_id='', client_request=''):
    parts = []
    mapped_request = _bitrix_text(client_request)
    if mapped_request:
        parts.append(f'Запрос клиента: {mapped_request}')
    normalized_deal_id = _bitrix_text(deal_id)
    if normalized_deal_id:
        parts.append(f'Bitrix deal id: {normalized_deal_id}')
    return '\n'.join(parts)


def _bitrix_scalar_property_value(value):
    if isinstance(value, list):
        for item in value:
            candidate = _bitrix_scalar_property_value(item)
            if candidate:
                return candidate
        return ''
    if isinstance(value, dict):
        for key in ('value', 'VALUE', 'VALUE_ENUM', 'VALUE_NUM', 'VALUE_TEXT'):
            candidate = _bitrix_scalar_property_value(value.get(key))
            if candidate:
                return candidate
        return ''
    return _bitrix_text(value)


def _bitrix_catalog_product_payload(bitrix_product_id, *, cache=None):
    normalized_product_id = _bitrix_optional_entity_id(bitrix_product_id)
    if not normalized_product_id:
        return {}
    cache = cache if cache is not None else {}
    if normalized_product_id in cache:
        return cache[normalized_product_id]

    payload = {}
    try:
        result = _bitrix_api_request('catalog.product.get', params={'id': normalized_product_id}) or {}
    except BitrixImportError:
        result = {}
    if isinstance(result, dict):
        payload = result.get('product') if isinstance(result.get('product'), dict) else result

    cache[normalized_product_id] = payload if isinstance(payload, dict) else {}
    return cache[normalized_product_id]


def _bitrix_site_product_property_id():
    return int(getattr(settings, 'BITRIX_SITE_PRODUCT_ID_PROPERTY_ID', 107) or 107)


def _bitrix_site_product_property_candidates(product_payload, property_id):
    property_id = _bitrix_text(property_id)
    candidate_values = [
        product_payload.get(f'property{property_id}'),
        product_payload.get(f'PROPERTY{property_id}'),
        product_payload.get(f'PROPERTY_{property_id}'),
        product_payload.get(f'PROPERTY_{property_id}_VALUE'),
        product_payload.get('ID товара сайта'),
    ]

    properties = product_payload.get('properties') or product_payload.get('PROPERTIES')
    if isinstance(properties, dict):
        for key in (
            property_id,
            f'property{property_id}',
            f'PROPERTY{property_id}',
            f'PROPERTY_{property_id}',
            'ID товара сайта',
        ):
            if key in properties:
                candidate_values.append(properties.get(key))
    return candidate_values


def _bitrix_site_product_id_from_catalog_payload(product_payload, *, property_id=None):
    if not isinstance(product_payload, dict) or not product_payload:
        return None

    property_id = property_id or _bitrix_site_product_property_id()
    candidate_values = _bitrix_site_product_property_candidates(product_payload, property_id)
    for candidate in candidate_values:
        normalized_value = _bitrix_optional_entity_id(_bitrix_scalar_property_value(candidate))
        if not normalized_value:
            continue
        try:
            site_product_id = int(normalized_value)
        except (TypeError, ValueError):
            continue
        if site_product_id > 0:
            return site_product_id
    return None


def _load_bitrix_deal_payload(deal_id):
    normalized_deal_id = _bitrix_text(deal_id)
    if not normalized_deal_id:
        raise BitrixImportError('Не указан deal_id для импорта из Bitrix.')

    deal_data = _bitrix_api_request('crm.deal.get', params={'id': normalized_deal_id}) or {}
    if not isinstance(deal_data, dict) or not deal_data:
        raise BitrixImportError(f'Сделка Bitrix #{normalized_deal_id} не найдена.')

    product_rows = _bitrix_api_request('crm.deal.productrows.get', params={'id': normalized_deal_id}) or []
    if not isinstance(product_rows, list):
        raise BitrixImportError('Bitrix вернул некорректный список товарных строк.')

    return normalized_deal_id, deal_data, product_rows


def inspect_bitrix_deal_payload(deal_id):
    normalized_deal_id, deal_data, product_rows = _load_bitrix_deal_payload(deal_id)
    mapped_payload = _bitrix_deal_mapped_payload(deal_data)
    return {
        'deal_id': normalized_deal_id,
        'raw_contact_id': deal_data.get('CONTACT_ID'),
        'raw_company_id': deal_data.get('COMPANY_ID'),
        'mapped_city': mapped_payload['city'],
        'mapped_recipient_name': mapped_payload['recipient_name'],
        'mapped_recipient_phone': mapped_payload['recipient_phone'],
        'mapped_delivery_address': mapped_payload['delivery_address'],
        'mapped_client_request': mapped_payload['client_request'],
        'product_rows_count': len(product_rows),
    }


def _bitrix_variant_match(product, *, sku_candidates, variant_name):
    variants = list(product.variants.all())
    if not variants:
        return None
    normalized_skus = {_bitrix_text(value).casefold() for value in sku_candidates if _bitrix_text(value)}
    for variant in variants:
        if normalized_skus and _bitrix_text(getattr(variant, 'sku', '')).casefold() in normalized_skus:
            return variant
    normalized_variant_name = _bitrix_text(variant_name).casefold()
    if normalized_variant_name:
        for variant in variants:
            if _bitrix_text(variant.name).casefold() == normalized_variant_name:
                return variant
    return None


def _match_catalog_product_for_bitrix_row(row, *, bitrix_product_cache=None):
    product_name = _bitrix_text(row.get('PRODUCT_NAME') or row.get('NAME'))
    variant_name = _bitrix_text(
        row.get('PRODUCT_VARIATION_NAME')
        or row.get('VARIANT_NAME')
        or row.get('OFFERS_NAME')
    )
    sku_candidates = [
        row.get('SKU'),
        row.get('PRODUCT_XML_ID'),
        row.get('XML_ID'),
        row.get('PRODUCT_CODE'),
        row.get('PRODUCT_BARCODE'),
    ]
    normalized_skus = [_bitrix_text(value) for value in sku_candidates if _bitrix_text(value)]
    bitrix_product_payload = _bitrix_catalog_product_payload(
        row.get('PRODUCT_ID'),
        cache=bitrix_product_cache,
    )
    site_product_id = _bitrix_site_product_id_from_catalog_payload(bitrix_product_payload)
    if site_product_id:
        product = (
            Product.objects
            .prefetch_related('variants')
            .filter(pk=site_product_id)
            .order_by('id')
            .first()
        )
        if product is not None:
            variant = _bitrix_variant_match(product, sku_candidates=normalized_skus, variant_name=variant_name)
            return product, variant

    if normalized_skus:
        variant = (
            ProductVariant.objects
            .select_related('product')
            .filter(sku__iexact=normalized_skus[0])
            .order_by('id')
            .first()
        )
        if variant is not None:
            return variant.product, variant

        product = (
            Product.objects
            .prefetch_related('variants')
            .filter(sku__iexact=normalized_skus[0])
            .order_by('id')
            .first()
        )
        if product is not None and not product.variants.exists():
            return product, None
        if product is not None:
            variant = _bitrix_variant_match(product, sku_candidates=normalized_skus, variant_name=variant_name)
            if variant is not None:
                return product, variant

    if not product_name:
        return None, None

    products = list(
        Product.objects
        .prefetch_related('variants')
        .filter(name__iexact=product_name)
        .order_by('id')
    )
    for product in products:
        if not product.variants.exists():
            return product, None
        variant = _bitrix_variant_match(product, sku_candidates=normalized_skus, variant_name=variant_name)
        if variant is not None:
            return product, variant

    return None, None


def _bitrix_order_item_key(row, *, index):
    return (
        _bitrix_text(row.get('ID'))
        or _bitrix_text(row.get('ROW_ID'))
        or f'{_bitrix_text(row.get("PRODUCT_ID"))}:{_bitrix_text(row.get("PRODUCT_NAME") or row.get("NAME"))}:{index}'
    )


def _bitrix_delivery_type(address):
    if not _bitrix_text(address):
        return Order.DELIVERY_NEGOTIABLE
    return Order.DELIVERY_OTHER_TRANSPORT


def _bitrix_inventory_available_map():
    available = defaultdict(int)
    for row in inventory_snapshot():
        available[(row['product_id'], row['variant_id'] or 0)] += int(row['available'] or 0)
    return available


def _bitrix_row_price_payload(row):
    sale_price = _bitrix_decimal(row.get('PRICE') or row.get('PRICE_NETTO') or row.get('PRICE_ACCOUNT'), default='0')
    base_price = _bitrix_decimal(
        row.get('PRICE_EXCLUSIVE') or row.get('PRICE_BRUTTO') or row.get('BASE_PRICE') or sale_price,
        default=str(sale_price),
    )
    if base_price < sale_price:
        base_price = sale_price
    discount_amount = base_price - sale_price
    return base_price, max(discount_amount, MONEY_ZERO)


def _prepare_bitrix_order_item_payload(row, *, index, available_map, bitrix_product_cache=None):
    product_name = _bitrix_text(row.get('PRODUCT_NAME') or row.get('NAME')) or f'Товар #{index}'
    variant_name = _bitrix_text(
        row.get('PRODUCT_VARIATION_NAME')
        or row.get('VARIANT_NAME')
        or row.get('OFFERS_NAME')
    )
    bitrix_product_id = _bitrix_text(row.get('PRODUCT_ID'))
    custom_sku = _bitrix_text(
        row.get('SKU')
        or row.get('PRODUCT_XML_ID')
        or row.get('XML_ID')
        or row.get('PRODUCT_CODE')
    )
    if not custom_sku and bitrix_product_id:
        custom_sku = f'bitrix-product-{bitrix_product_id}'
    quantity = max(_bitrix_int(row.get('QUANTITY'), default=1), 1)
    base_price, discount_amount = _bitrix_row_price_payload(row)
    product, variant = _match_catalog_product_for_bitrix_row(
        row,
        bitrix_product_cache=bitrix_product_cache,
    )
    is_on_request = True
    line_type = OrderItem.LINE_TYPE_CUSTOM
    product_image_url = ''
    if product is not None:
        line_type = OrderItem.LINE_TYPE_CATALOG
        product_image_url = resolve_order_item_image_url(product=product, variant=variant)
        available_now = int(available_map.get((product.id, variant.id if variant else 0), 0))
        is_on_request = available_now < quantity
    payload = {
        'row_key': _bitrix_order_item_key(row, index=index),
        'line_type': line_type,
        'product': product,
        'variant': variant,
        'product_name': product.name if product is not None else product_name,
        'variant_name': variant.name if variant is not None else variant_name,
        'custom_sku': '' if product is not None else custom_sku,
        'price': base_price,
        'discount_amount': discount_amount,
        'quantity': quantity,
        'planned_unit_cost': Decimal('0'),
        'product_image_url': product_image_url,
        'condition': OrderItem.CONDITION_NEW,
        'comment': '',
        'is_on_request': is_on_request or line_type == OrderItem.LINE_TYPE_CUSTOM,
        'metadata': {
            'bitrix_row_key': _bitrix_order_item_key(row, index=index),
            'bitrix_row_id': _bitrix_text(row.get('ID') or row.get('ROW_ID')),
            'bitrix_product_id': bitrix_product_id,
            'bitrix_product_name': product_name,
            'bitrix_row': row,
        },
    }
    return payload


def _bitrix_contact_payload(contact_data, company_data):
    phone = _bitrix_first_multifield((contact_data or {}).get('PHONE')) or _bitrix_first_multifield((company_data or {}).get('PHONE'))
    email = _bitrix_first_multifield((contact_data or {}).get('EMAIL')) or _bitrix_first_multifield((company_data or {}).get('EMAIL'))
    full_name = ' '.join(
        part for part in [
            _bitrix_text((contact_data or {}).get('NAME')),
            _bitrix_text((contact_data or {}).get('LAST_NAME')),
        ]
        if part
    ).strip()
    company_name = _bitrix_text((company_data or {}).get('TITLE'))
    city = (
        _bitrix_text((contact_data or {}).get('ADDRESS_CITY'))
        or _bitrix_text((company_data or {}).get('ADDRESS_CITY'))
        or _bitrix_text((contact_data or {}).get('CITY'))
        or _bitrix_text((company_data or {}).get('CITY'))
    )
    address = (
        _bitrix_text((contact_data or {}).get('ADDRESS'))
        or _bitrix_text((company_data or {}).get('ADDRESS_LEGAL'))
        or _bitrix_text((company_data or {}).get('ADDRESS'))
    )
    return {
        'phone': phone,
        'email': email,
        'full_name': full_name,
        'company_name': company_name,
        'city': city,
        'address': address,
        'is_business': bool(company_name),
        'inn': _bitrix_text((company_data or {}).get('UF_CRM_INN') or (company_data or {}).get('INN')),
        'kpp': _bitrix_text((company_data or {}).get('UF_CRM_KPP') or (company_data or {}).get('KPP')),
    }

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
                'line_type': item.line_type,
                'product_id': item.product_id,
                'variant_id': item.variant_id,
                'sku': item.sku,
                'name': item.display_name,
                'quantity': int(item.quantity or 0),
                'unit': 'шт.',
                'price': str(item.unit_price),
                'line_total': str(item.subtotal),
                'planned_unit_cost': str(item.planned_unit_cost),
                'actual_unit_cost': str(item.actual_unit_cost),
                'cost_status': item.cost_status,
                'purchase_price': str(item.effective_unit_cost),
                'is_on_request': bool(item.is_on_request),
            }
        )
    return snapshot


def reservation_coverage_snapshot(order):
    supply_snapshot = order_supply_state_snapshot(order)
    lines = []
    for line in supply_snapshot['lines']:
        lines.append(
            {
                'order_item_id': line['order_item_id'],
                'product_name': line['product_name'],
                'variant_name': line['variant_name'],
                'ordered_quantity': line['ordered_quantity'],
                'reserved_quantity': line['reserved_quantity'],
                'reserved_stock_quantity': line['reserved_stock_quantity'],
                'reserved_incoming_quantity': line['reserved_incoming_quantity'],
                'purchase_quantity': line['purchase_quantity'],
                'purchase_received_quantity': line['purchase_received_quantity'],
                'cargo_quantity': line['cargo_quantity'],
                'cargo_received_quantity': line['cargo_received_quantity'],
                'shipment_quantity': line['shipment_quantity'],
                'is_supply_tracked': line['is_supply_tracked'],
                'coverage_state': line['coverage_state'],
                'coverage_label': line['coverage_label'],
                'coverage_tone': line['coverage_tone'],
                'coverage_summary': line['coverage_summary'],
                'missing_quantity': line['missing_quantity'],
            }
        )
    return {
        'lines': lines,
        'tracked_line_count': supply_snapshot['tracked_line_count'],
        'excluded_line_count': supply_snapshot['excluded_line_count'],
        'covered_by_stock_count': supply_snapshot['covered_by_stock_count'],
        'covered_by_incoming_count': supply_snapshot['covered_by_incoming_count'],
        'covered_by_procurement_count': supply_snapshot['covered_by_procurement_count'],
        'uncovered_count': supply_snapshot['uncovered_count'],
        'uncovered_lines': [line for line in lines if line['coverage_state'] == SUPPLY_COVERAGE_STATE_UNCOVERED],
    }


def order_supply_state_snapshot(order):
    order_items = list(order.items.select_related('product', 'variant').all())
    if not order_items:
        return {
            'lines': [],
            'tracked_line_count': 0,
            'excluded_line_count': 0,
            'covered_by_stock_count': 0,
            'covered_by_incoming_count': 0,
            'covered_by_procurement_count': 0,
            'uncovered_count': 0,
        }

    catalog_product_ids = [item.product_id for item in order_items if item.line_type == OrderItem.LINE_TYPE_CATALOG and item.product_id]
    stock_map = {}
    reserved_stock_map = {}
    if catalog_product_ids:
        stock_rows = (
            ProductStock.objects
            .filter(product_id__in=catalog_product_ids)
            .values('product_id', 'variant_id')
            .annotate(total=models.Sum('quantity'))
        )
        stock_map = {
            (row['product_id'], row['variant_id']): int(row['total'] or 0)
            for row in stock_rows
        }
        reserved_stock_rows = (
            ReservationItem.objects
            .filter(
                reservation__status__in=ACTIVE_RESERVATION_STATUSES,
                reservation__source_type=Reservation.SOURCE_WAREHOUSE,
                product_id__in=catalog_product_ids,
            )
            .values('product_id', 'variant_id')
            .annotate(total=models.Sum('quantity'))
        )
        reserved_stock_map = {
            (row['product_id'], row['variant_id']): int(row['total'] or 0)
            for row in reserved_stock_rows
        }

    reserved_by_item = defaultdict(int)
    reserved_stock_by_item = defaultdict(int)
    reserved_incoming_by_item = defaultdict(int)
    for reservation_item in ReservationItem.objects.filter(
        reservation__linked_order=order,
        reservation__status__in=ACTIVE_RESERVATION_STATUSES,
        order_item__isnull=False,
    ).select_related('reservation'):
        reserved_quantity = int(reservation_item.active_reserved_quantity or 0)
        if reserved_quantity <= 0:
            continue
        reserved_by_item[reservation_item.order_item_id] += reserved_quantity
        if reservation_item.reservation.source_type == Reservation.SOURCE_WAREHOUSE:
            reserved_stock_by_item[reservation_item.order_item_id] += reserved_quantity
        elif reservation_item.reservation.source_type == Reservation.SOURCE_CARGO:
            reserved_incoming_by_item[reservation_item.order_item_id] += reserved_quantity

    purchase_by_item = defaultdict(int)
    purchase_received_by_item = defaultdict(int)
    for purchase_item in PurchaseItem.objects.filter(order_item__order=order):
        purchase_by_item[purchase_item.order_item_id] += purchase_item.active_quantity
        purchase_received_by_item[purchase_item.order_item_id] += min(
            int(purchase_item.received_quantity or 0),
            int(purchase_item.active_quantity or 0),
        )

    cargo_quantity_by_item = defaultdict(int)
    cargo_received_by_item = defaultdict(int)
    for cargo_item in CargoItem.objects.filter(
        purchase_item__order_item__order=order,
    ).select_related('purchase_item'):
        order_item_id = cargo_item.purchase_item.order_item_id if cargo_item.purchase_item_id else None
        if order_item_id:
            cargo_quantity_by_item[order_item_id] += cargo_item.quantity
            cargo_received_by_item[order_item_id] += cargo_item.received_quantity

    shipment_quantity_by_item = defaultdict(int)
    for shipment_item in ShipmentItem.objects.filter(
        shipment__order=order,
        shipment__inventory_consumed_at__isnull=False,
    ).exclude(
        shipment__status=Shipment.STATUS_CANCELLED,
    ).select_related('reservation_item__order_item'):
        order_item_id = shipment_item.order_item_id or (
            shipment_item.reservation_item.order_item_id
            if shipment_item.reservation_item_id and shipment_item.reservation_item
            else None
        )
        if order_item_id:
            shipment_quantity_by_item[order_item_id] += shipment_item.quantity

    lines = []
    counts = {
        'tracked_line_count': 0,
        'excluded_line_count': 0,
        'covered_by_stock_count': 0,
        'covered_by_incoming_count': 0,
        'covered_by_procurement_count': 0,
        'uncovered_count': 0,
    }

    for item in order_items:
        is_supply_tracked = (
            item.line_type == OrderItem.LINE_TYPE_CATALOG
            and bool(item.product_id)
            and bool(getattr(item.product, 'tracks_stock', True))
        )
        ordered_quantity = int(item.active_quantity or 0)
        reserved_quantity = int(reserved_by_item.get(item.id, 0))
        reserved_stock_quantity = int(reserved_stock_by_item.get(item.id, 0))
        reserved_incoming_quantity = int(reserved_incoming_by_item.get(item.id, 0))
        purchase_quantity = int(purchase_by_item.get(item.id, 0))
        purchase_received_quantity = int(purchase_received_by_item.get(item.id, 0))
        cargo_quantity = int(cargo_quantity_by_item.get(item.id, 0))
        cargo_received_quantity = int(cargo_received_by_item.get(item.id, 0))
        shipment_quantity = int(shipment_quantity_by_item.get(item.id, 0))
        stock_total = int(stock_map.get((item.product_id, item.variant_id), 0)) if is_supply_tracked else 0
        free_stock = (
            max(stock_total - int(reserved_stock_map.get((item.product_id, item.variant_id), 0)), 0)
            if is_supply_tracked
            else 0
        )

        if not is_supply_tracked:
            counts['excluded_line_count'] += 1
            lines.append(
                {
                    'order_item_id': item.id,
                    'item': item,
                    'product_name': item.resolved_product_name,
                    'variant_name': item.resolved_variant_name,
                    'ordered_quantity': ordered_quantity,
                    'reserved_quantity': 0,
                    'reserved_stock_quantity': 0,
                    'reserved_incoming_quantity': 0,
                    'purchase_quantity': 0,
                    'purchase_received_quantity': 0,
                    'cargo_quantity': 0,
                    'cargo_received_quantity': 0,
                    'shipment_quantity': 0,
                    'stock_total': 0,
                    'free_stock': 0,
                    'is_supply_tracked': False,
                    'coverage_state': None,
                    'coverage_label': 'Вне supply contour',
                    'coverage_tone': 'neutral',
                    'coverage_summary': 'Позиция введена вручную и не участвует в складском, резервном и закупочном контуре.',
                    'missing_quantity': 0,
                }
            )
            continue

        counts['tracked_line_count'] += 1
        if ordered_quantity <= 0:
            coverage_state = SUPPLY_COVERAGE_STATE_COVERED_BY_STOCK
        elif shipment_quantity >= ordered_quantity or reserved_stock_quantity >= ordered_quantity:
            coverage_state = SUPPLY_COVERAGE_STATE_COVERED_BY_STOCK
        elif reserved_incoming_quantity >= ordered_quantity:
            coverage_state = SUPPLY_COVERAGE_STATE_COVERED_BY_INCOMING
        elif purchase_quantity > 0:
            coverage_state = SUPPLY_COVERAGE_STATE_COVERED_BY_PROCUREMENT
        else:
            coverage_state = SUPPLY_COVERAGE_STATE_UNCOVERED
        counts[f'{coverage_state}_count'] += 1

        coverage_parts = []
        if reserved_stock_quantity:
            coverage_parts.append(f'Склад {reserved_stock_quantity}/{ordered_quantity}')
        if reserved_incoming_quantity:
            coverage_parts.append(f'Incoming {reserved_incoming_quantity}/{ordered_quantity}')
        if purchase_quantity:
            coverage_parts.append(f'Закупка {purchase_received_quantity}/{purchase_quantity}')
        if cargo_quantity:
            coverage_parts.append(f'Груз {cargo_received_quantity}/{cargo_quantity}')
        if shipment_quantity:
            coverage_parts.append(f'Отгрузка {shipment_quantity}/{ordered_quantity}')
        if not coverage_parts:
            coverage_parts.append('Связей пока нет')

        lines.append(
            {
                'order_item_id': item.id,
                'item': item,
                'product_name': item.resolved_product_name,
                'variant_name': item.resolved_variant_name,
                'ordered_quantity': ordered_quantity,
                'reserved_quantity': reserved_quantity,
                'reserved_stock_quantity': reserved_stock_quantity,
                'reserved_incoming_quantity': reserved_incoming_quantity,
                'purchase_quantity': purchase_quantity,
                'purchase_received_quantity': purchase_received_quantity,
                'cargo_quantity': cargo_quantity,
                'cargo_received_quantity': cargo_received_quantity,
                'shipment_quantity': shipment_quantity,
                'stock_total': stock_total,
                'free_stock': free_stock,
                'is_supply_tracked': True,
                'coverage_state': coverage_state,
                'coverage_label': SUPPLY_COVERAGE_STATE_META[coverage_state]['label'],
                'coverage_tone': SUPPLY_COVERAGE_STATE_META[coverage_state]['tone'],
                'coverage_summary': ' · '.join(coverage_parts),
                'missing_quantity': ordered_quantity if coverage_state == SUPPLY_COVERAGE_STATE_UNCOVERED else 0,
            }
        )
    return {
        'lines': lines,
        **counts,
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
        hints.append('Распределяемая прибыль не положительная, проверь себестоимость и скидки')
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
        'expected_distributable_profit': str(deal.expected_margin),
        'expected_margin': str(deal.expected_margin),
        'payment_method': deal.order.payment_method,
        'payment_status': deal.order.payment_status,
        'delivery_method': deal.delivery_method,
        'delivery_payer': deal.delivery_payer,
        'expense_hints': finance_case_expense_hints(deal),
        'items': order_items_snapshot(deal.order),
    }


def active_finance_distribution_scheme():
    return FinanceDistributionScheme.objects.prefetch_related('rules').filter(is_active=True).order_by('name', '-version', 'id').first()


def clone_finance_distribution_scheme(source_scheme, *, activate=False):
    next_version = (
        FinanceDistributionScheme.objects.filter(name=source_scheme.name).aggregate(max_version=models.Max('version')).get('max_version')
        or 0
    ) + 1
    new_scheme = FinanceDistributionScheme.objects.create(
        name=source_scheme.name,
        version=next_version,
        is_active=bool(activate),
        description=source_scheme.description,
    )
    rule_mapping = {}
    source_rules = list(source_scheme.rules.order_by('position', 'id'))
    for rule in source_rules:
        cloned = FinanceDistributionRule.objects.create(
            scheme=new_scheme,
            participant_alias=rule.participant_alias,
            position=rule.position,
            rule_type=rule.rule_type,
            percent=rule.percent,
            owner_alias=rule.owner_alias,
            note=rule.note,
            is_active=rule.is_active,
        )
        rule_mapping[rule.pk] = cloned
    for rule in source_rules:
        if rule.reference_rule_id:
            cloned = rule_mapping[rule.pk]
            cloned.reference_rule = rule_mapping.get(rule.reference_rule_id)
            cloned.save(update_fields=['reference_rule', 'updated_at'])
    return new_scheme


def ensure_finance_deal_distribution_scheme(finance_deal):
    if finance_deal.distribution_scheme_id:
        return finance_deal.distribution_scheme
    scheme = active_finance_distribution_scheme()
    if scheme is None:
        return None
    finance_deal.distribution_scheme = scheme
    finance_deal.distribution_scheme_name_snapshot = scheme.name
    finance_deal.distribution_scheme_version_snapshot = scheme.version
    if finance_deal.pk:
        finance_deal.save(
            update_fields=[
                'distribution_scheme',
                'distribution_scheme_name_snapshot',
                'distribution_scheme_version_snapshot',
                'updated_at',
            ]
        )
    return scheme


def sync_finance_deal_lines_from_manager_deal(finance_deal):
    if not finance_deal.pk or not finance_deal.manager_deal_id:
        return []
    order_items = list(finance_deal.manager_deal.order.items.select_related('product', 'variant').all())
    current_order_item_ids = {order_item.id for order_item in order_items}
    owner_map = {
        participant.order_item_id: participant.person_alias
        for participant in finance_deal.manager_deal.participants.select_related('person_alias').filter(
            role=ManagerDealParticipant.ROLE_ITEM_OWNER,
            order_item__isnull=False,
        )
    }
    existing_lines = {line.order_item_id: line for line in finance_deal.lines.select_related('order_item', 'owner_alias').all() if line.order_item_id}
    created_or_updated = []
    for index, order_item in enumerate(order_items, start=1):
        defaults = {
            'finance_deal': finance_deal,
            'line_type': order_item.line_type,
            'product': order_item.product,
            'variant': order_item.variant,
            'sort_order': index,
            'product_name': order_item.display_name,
            'custom_sku': order_item.custom_sku,
            'quantity': order_item.active_quantity,
            'unit_cost_price': order_item.effective_unit_cost,
            'unit_sale_price': order_item.unit_price,
            'planned_unit_cost': order_item.planned_unit_cost,
            'actual_unit_cost': order_item.actual_unit_cost,
            'cost_status': order_item.cost_status,
            'owner_alias': owner_map.get(order_item.id),
            'line_status': finance_deal.manager_deal.get_deal_status_display(),
            'delivery_status': finance_deal.manager_deal.delivery_provider_name or finance_deal.manager_deal.get_shipment_status_display(),
            'source_payload': {
                'source': 'manager_deal',
                'order_item_id': order_item.id,
            },
        }
        line = existing_lines.get(order_item.id)
        if line is None:
            line = FinanceDealLine.objects.create(order_item=order_item, **defaults)
        else:
            changed_fields = []
            for field_name, value in defaults.items():
                current_value = getattr(line, f'{field_name}_id') if field_name == 'owner_alias' and value is not None else getattr(line, field_name)
                expected_value = value.pk if field_name == 'owner_alias' and value is not None else value
                if current_value != expected_value:
                    setattr(line, field_name, value)
                    changed_fields.append(field_name)
            if changed_fields:
                line.save(update_fields=changed_fields + ['updated_at'])
        created_or_updated.append(line)
    stale_line_ids = []
    for line in finance_deal.lines.only('id', 'order_item_id', 'source_payload').all():
        source_payload = line.source_payload or {}
        source_order_item_id = source_payload.get('order_item_id')
        tracked_order_item_id = line.order_item_id or source_order_item_id
        if source_payload.get('source') == 'manager_deal' and tracked_order_item_id not in current_order_item_ids:
            stale_line_ids.append(line.id)
    if stale_line_ids:
        FinanceDealLine.objects.filter(pk__in=stale_line_ids).delete()
    return created_or_updated


def link_manual_order_item_to_catalog_product(order_item, *, product, variant=None, actor=None):
    with transaction.atomic():
        locked_item = (
            OrderItem.objects.select_for_update()
            .select_related('order')
            .get(pk=order_item.pk)
        )
        if locked_item.line_type != OrderItem.LINE_TYPE_CUSTOM:
            raise ValueError('Связать с товаром сайта можно только ручную строку.')
        if locked_item.product_id or locked_item.game_pack_id:
            raise ValueError('Строка уже связана с каталогом.')
        if not getattr(product, 'tracks_stock', True):
            raise ValueError('Можно выбирать только товар, который участвует в складском контуре.')
        if variant is not None and variant.product_id != product.id:
            raise ValueError('Вариант должен относиться к выбранному товару.')

        product_variants = list(product.variants.order_by('order', 'id'))
        if variant is None and len(product_variants) == 1:
            variant = product_variants[0]
        elif variant is None and len(product_variants) > 1:
            raise ValueError('Для товара с вариантами выберите конкретный вариант.')

        previous_label = locked_item.display_name
        previous_custom_sku = locked_item.custom_sku
        metadata = dict(locked_item.metadata or {})
        link_history = list(metadata.get('manual_catalog_link_history') or [])
        link_history.append(
            {
                'linked_at': timezone.now().isoformat(),
                'actor_id': actor.id if actor else None,
                'actor_username': actor.get_username() if actor else '',
                'from_line_type': locked_item.line_type,
                'from_product_name': previous_label,
                'from_custom_sku': previous_custom_sku,
                'to_product_id': product.id,
                'to_product_name': product.name,
                'to_variant_id': variant.id if variant is not None else None,
                'to_variant_name': variant.name if variant is not None else '',
            }
        )
        metadata['manual_catalog_link_history'] = link_history
        metadata['manual_link'] = True
        metadata['manual_product_link'] = {
            'product_id': product.id,
            'variant_id': variant.id if variant is not None else None,
            'linked_at': link_history[-1]['linked_at'],
            'actor_id': actor.id if actor else None,
            'actor_username': actor.get_username() if actor else '',
        }
        locked_item.line_type = OrderItem.LINE_TYPE_CATALOG
        locked_item.product = product
        locked_item.game_pack = None
        locked_item.variant = variant
        locked_item.product_name = product.name
        locked_item.variant_name = variant.name if variant is not None else ''
        locked_item.custom_sku = ''
        locked_item.product_image_url = ''
        locked_item.metadata = metadata
        locked_item.full_clean()
        locked_item.save()

        try:
            deal = locked_item.order.manager_deal
        except ManagerDeal.DoesNotExist:
            deal = None

        if deal is not None:
            try:
                finance_deal = deal.finance_deal
            except FinanceDeal.DoesNotExist:
                finance_deal = None
            if finance_deal is not None:
                sync_finance_deal_lines_from_manager_deal(finance_deal)
                recalculate_finance_deal_totals(finance_deal, sync_lines=False)
            record_deal_activity(
                deal,
                event_type='order_item.linked_to_catalog',
                source='user',
                actor=actor,
                payload={
                    'order_item_id': locked_item.id,
                    'from_product_name': previous_label,
                    'to_product_name': locked_item.display_name,
                    'product_id': product.id,
                    'variant_id': variant.id if variant is not None else None,
                },
            )
            recompute_deal_workflow(deal, actor=actor)
        return locked_item


def create_finance_deal_line_from_order_item(
    finance_deal,
    *,
    order_item,
    owner_alias=None,
    sort_order=0,
    line_status='',
    delivery_status='',
    source_payload=None,
):
    return FinanceDealLine.objects.create(
        finance_deal=finance_deal,
        order_item=order_item,
        line_type=order_item.line_type,
        product=order_item.product,
        variant=order_item.variant,
        sort_order=sort_order,
        product_name=order_item.display_name,
        custom_sku=order_item.custom_sku,
        quantity=order_item.active_quantity,
        unit_cost_price=order_item.effective_unit_cost,
        unit_sale_price=order_item.unit_price,
        planned_unit_cost=order_item.planned_unit_cost,
        actual_unit_cost=order_item.actual_unit_cost,
        cost_status=order_item.cost_status,
        owner_alias=owner_alias,
        line_status=line_status,
        delivery_status=delivery_status,
        source_payload=source_payload or {},
    )


def _distribution_percent_label(value):
    normalized = (Decimal(value or 0) * Decimal('100')).quantize(Decimal('0.01'))
    return f'{normalized}%'


def _rule_runtime_params(rule, existing_share):
    override_payload = dict(existing_share.rule_params_override or {}) if existing_share is not None else {}
    percent = Decimal(str(override_payload.get('percent', rule.percent or 0)))
    owner_alias_id = override_payload.get('owner_alias_id') or rule.owner_alias_id
    return {
        'percent': percent,
        'owner_alias_id': owner_alias_id,
        'override_payload': override_payload,
    }


def recalculate_finance_deal_distribution(finance_deal):
    if not finance_deal.pk:
        return []
    scheme = ensure_finance_deal_distribution_scheme(finance_deal)
    if scheme is None:
        return []
    rules = list(
        scheme.rules.select_related('participant_alias', 'owner_alias', 'reference_rule')
        .filter(is_active=True)
        .order_by('position', 'id')
    )
    if not rules:
        return []
    existing_shares = {
        share.participant_alias_id: share
        for share in finance_deal.shares.select_related('participant_alias', 'rule').all()
        if share.participant_alias_id
    }
    lines = list(finance_deal.lines.select_related('owner_alias').all())
    total_distributable_profit = _quantize_money(finance_deal.distributable_profit)
    owner_gross_profit_map = defaultdict(lambda: MONEY_ZERO)
    owner_quantity_map = defaultdict(int)
    for line in lines:
        owner_gross_profit_map[line.owner_alias_id] += _quantize_money(line.gross_profit_total)
        owner_quantity_map[line.owner_alias_id] += int(line.quantity or 0)

    result_rows = []
    calculated_amounts_by_rule = {}
    non_remainder_total = MONEY_ZERO
    remainder_rows = []

    for rule in rules:
        existing_share = existing_shares.get(rule.participant_alias_id)
        params = _rule_runtime_params(rule, existing_share)
        percent = params['percent']
        owner_alias_id = params['owner_alias_id']
        manual_amount = _quantize_money(existing_share.manual_amount_override) if existing_share and existing_share.manual_amount_override is not None else None
        base_amount = MONEY_ZERO
        calculated_amount = MONEY_ZERO
        quantity_basis = None
        formula_label = ''

        if rule.rule_type == FinanceDistributionRule.RULE_PERCENT_OWNER_MARGIN:
            base_amount = _quantize_money(owner_gross_profit_map.get(owner_alias_id, MONEY_ZERO))
            calculated_amount = _quantize_money(base_amount * percent)
            quantity_basis = owner_quantity_map.get(owner_alias_id) or None
            owner_label = rule.owner_alias.display_name if rule.owner_alias_id else '—'
            if owner_alias_id and owner_alias_id != rule.owner_alias_id:
                owner_label = ManagerPersonAlias.objects.filter(pk=owner_alias_id).values_list('display_name', flat=True).first() or owner_label
            formula_label = f'{_distribution_percent_label(percent)} × валовая прибыль строк {owner_label}'
        elif rule.rule_type == FinanceDistributionRule.RULE_PERCENT_TOTAL_MARGIN:
            base_amount = total_distributable_profit
            calculated_amount = _quantize_money(base_amount * percent)
            formula_label = f'{_distribution_percent_label(percent)} × распределяемая прибыль сделки'
        elif rule.rule_type == FinanceDistributionRule.RULE_PERCENT_REMAINDER_AFTER_RULE:
            reference_amount = calculated_amounts_by_rule.get(rule.reference_rule_id, MONEY_ZERO)
            base_amount = _quantize_money(total_distributable_profit - reference_amount)
            calculated_amount = _quantize_money(base_amount * percent)
            reference_name = rule.reference_rule.participant_alias.display_name if rule.reference_rule_id else 'предыдущего правила'
            formula_label = f'{_distribution_percent_label(percent)} × (распределяемая прибыль - {reference_name})'
        else:
            formula_label = 'Равная доля остатка'

        row = {
            'rule': rule,
            'existing_share': existing_share,
            'manual_amount': manual_amount,
            'base_amount': base_amount,
            'calculated_amount': calculated_amount,
            'final_amount': manual_amount if manual_amount is not None else calculated_amount,
            'quantity_basis': quantity_basis,
            'formula_label': formula_label,
            'params': params,
        }
        if rule.rule_type == FinanceDistributionRule.RULE_EQUAL_SPLIT_REMAINDER:
            remainder_rows.append(row)
        else:
            non_remainder_total += row['final_amount']
            calculated_amounts_by_rule[rule.id] = row['final_amount']
        result_rows.append(row)

    manual_remainder_total = sum((row['manual_amount'] for row in remainder_rows if row['manual_amount'] is not None), MONEY_ZERO)
    auto_remainder_rows = [row for row in remainder_rows if row['manual_amount'] is None]
    remainder_pool = _quantize_money(total_distributable_profit - non_remainder_total - manual_remainder_total)
    auto_remainder_amount = (
        _quantize_money(remainder_pool / Decimal(len(auto_remainder_rows)))
        if auto_remainder_rows
        else MONEY_ZERO
    )
    for row in remainder_rows:
        row['base_amount'] = remainder_pool if row['manual_amount'] is None else row['manual_amount']
        row['calculated_amount'] = row['manual_amount'] if row['manual_amount'] is not None else auto_remainder_amount
        row['final_amount'] = row['manual_amount'] if row['manual_amount'] is not None else auto_remainder_amount
        calculated_amounts_by_rule[row['rule'].id] = row['final_amount']

    share_total = sum((row['final_amount'] for row in result_rows), MONEY_ZERO)
    delta = _quantize_money(total_distributable_profit - share_total)
    if delta and result_rows:
        adjust_target = next((row for row in reversed(result_rows) if row['manual_amount'] is None), result_rows[-1])
        adjust_target['calculated_amount'] = _quantize_money(adjust_target['calculated_amount'] + delta)
        adjust_target['final_amount'] = _quantize_money(adjust_target['final_amount'] + delta)

    persisted_shares = []
    used_participant_ids = set()
    with transaction.atomic():
        for row in result_rows:
            rule = row['rule']
            participant = rule.participant_alias
            used_participant_ids.add(participant.id)
            share = row['existing_share'] or FinanceDealShare(
                finance_deal=finance_deal,
                participant_alias=participant,
            )
            share.rule = rule
            share.participant_name_snapshot = participant.display_name
            share.calculation_type = rule.rule_type
            share.formula_label = row['formula_label']
            share.base_amount = _quantize_money(row['base_amount'])
            share.calculated_amount = _quantize_money(row['calculated_amount'])
            share.final_amount = _quantize_money(row['final_amount'])
            share.quantity_basis = row['quantity_basis']
            share.scheme_name_snapshot = scheme.name
            share.scheme_version_snapshot = scheme.version
            share.breakdown = {
                'participant': participant.display_name,
                'rule_type': rule.rule_type,
                'percent': str(row['params']['percent']),
                'owner_alias_id': row['params']['owner_alias_id'],
                'base_amount': str(_quantize_money(row['base_amount'])),
                'calculated_amount': str(_quantize_money(row['calculated_amount'])),
                'final_amount': str(_quantize_money(row['final_amount'])),
                'manual_override': row['manual_amount'] is not None,
                'convergence_target': str(total_distributable_profit),
            }
            share.is_manual_override = share.manual_amount_override is not None or bool(share.rule_params_override)
            share.save()
            persisted_shares.append(share)

        finance_deal.shares.exclude(participant_alias_id__in=used_participant_ids).delete()
        distribution_state = {
            'scheme_name': scheme.name,
            'scheme_version': scheme.version,
            'sum_of_shares': str(_quantize_money(sum((share.final_amount for share in persisted_shares), MONEY_ZERO))),
            'distributable_profit': str(total_distributable_profit),
            'margin': str(total_distributable_profit),
            'is_converged': _quantize_money(sum((share.final_amount for share in persisted_shares), MONEY_ZERO)) == total_distributable_profit,
        }
        snapshot_data = dict(finance_deal.snapshot_data or {})
        snapshot_data['distribution'] = distribution_state
        FinanceDeal.objects.filter(pk=finance_deal.pk).update(
            partner_share_amount=_quantize_money(sum((share.final_amount for share in persisted_shares), MONEY_ZERO)),
            distribution_scheme_id=scheme.pk,
            distribution_scheme_name_snapshot=scheme.name,
            distribution_scheme_version_snapshot=scheme.version,
            snapshot_data=snapshot_data,
            updated_at=timezone.now(),
        )
    finance_deal.refresh_from_db()
    return persisted_shares


def recalculate_finance_deal_totals(finance_deal, *, sync_lines=False):
    def _sum_adjustments(field_name):
        return _quantize_money(
            sum((Decimal(getattr(adjustment, field_name) or 0) for adjustment in finance_deal.adjustments.all()), MONEY_ZERO)
        )

    if not finance_deal.pk:
        finance_deal.save()
    if sync_lines and finance_deal.manager_deal_id and not finance_deal.lines.exists():
        sync_finance_deal_lines_from_manager_deal(finance_deal)
    lines = list(finance_deal.lines.all())
    base_lines = [line for line in lines if not line.replacement_of_id]
    if base_lines:
        revenue = _quantize_money(sum((line.sale_total for line in base_lines), MONEY_ZERO))
        planned_cost_of_goods = _quantize_money(sum((line.planned_cost_total for line in base_lines), MONEY_ZERO))
        actual_cost_of_goods = _quantize_money(sum((line.actual_cost_total for line in base_lines), MONEY_ZERO))
        cost_of_goods = _quantize_money(sum((line.cost_total for line in base_lines), MONEY_ZERO))
    else:
        revenue = _quantize_money(finance_deal.revenue)
        planned_cost_of_goods = _quantize_money(finance_deal.cost_of_goods)
        actual_cost_of_goods = MONEY_ZERO
        cost_of_goods = _quantize_money(finance_deal.cost_of_goods)

    revenue += _sum_adjustments('revenue_delta')
    planned_cost_of_goods += _sum_adjustments('cost_of_goods_delta')
    actual_cost_of_goods += _sum_adjustments('cost_of_goods_delta')
    cost_of_goods += _sum_adjustments('cost_of_goods_delta')

    direct_expense_rows = list(finance_deal.expenses.filter(affects_direct_expenses=True))
    direct_expenses_base = _quantize_money(sum((Decimal(expense.amount or 0) for expense in direct_expense_rows), MONEY_ZERO))
    if not direct_expense_rows and Decimal(finance_deal.direct_expenses or 0):
        direct_expenses_base = _quantize_money(finance_deal.direct_expenses)
    direct_expenses = _quantize_money(direct_expenses_base + _sum_adjustments('direct_expenses_delta'))
    manager_bonus = _quantize_money(Decimal(finance_deal.manager_bonus or 0) + _sum_adjustments('manager_bonus_delta'))
    gross_profit = _quantize_money(revenue - cost_of_goods)
    distributable_profit = _quantize_money(gross_profit - direct_expenses - manager_bonus)
    expected_distributable_profit = _quantize_money(revenue - planned_cost_of_goods - direct_expenses - manager_bonus)
    actual_distributable_profit = _quantize_money(revenue - actual_cost_of_goods - direct_expenses - manager_bonus)

    snapshot_data = dict(finance_deal.snapshot_data or {})
    snapshot_data['costs'] = {
        'planned_cost_of_goods': str(planned_cost_of_goods),
        'actual_cost_of_goods': str(actual_cost_of_goods),
        'effective_cost_of_goods': str(cost_of_goods),
        'gross_profit': str(gross_profit),
        'planned_gross_profit': str(_quantize_money(revenue - planned_cost_of_goods)),
        'actual_gross_profit': str(_quantize_money(revenue - actual_cost_of_goods)),
        'distributable_profit': str(distributable_profit),
        'planned_distributable_profit': str(expected_distributable_profit),
        'actual_distributable_profit': str(actual_distributable_profit),
        'planned_cost_price': str(planned_cost_of_goods),
        'actual_cost_price': str(actual_cost_of_goods),
        'effective_cost_price': str(cost_of_goods),
        'planned_margin': str(expected_distributable_profit),
        'actual_margin': str(actual_distributable_profit),
    }
    snapshot_data['adjustments'] = {
        'count': finance_deal.adjustments.count(),
        'revenue_delta': str(_sum_adjustments('revenue_delta')),
        'cost_of_goods_delta': str(_sum_adjustments('cost_of_goods_delta')),
        'direct_expenses_delta': str(_sum_adjustments('direct_expenses_delta')),
        'manager_bonus_delta': str(_sum_adjustments('manager_bonus_delta')),
    }
    FinanceDeal.objects.filter(pk=finance_deal.pk).update(
        revenue=revenue,
        cost_of_goods=cost_of_goods,
        direct_expenses=direct_expenses,
        manager_bonus=manager_bonus,
        distributable_profit=distributable_profit,
        expected_distributable_profit_snapshot=expected_distributable_profit,
        snapshot_data=snapshot_data,
        updated_at=timezone.now(),
    )
    finance_deal.refresh_from_db()
    if finance_deal.distribution_scheme_id or active_finance_distribution_scheme() is not None:
        recalculate_finance_deal_distribution(finance_deal)
    return finance_deal


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
    if not finance_deal.snapshot_data.get('items') and not finance_deal.lines.exists():
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
        existing_reserved[item.order_item_id] += int(item.active_reserved_quantity or 0)

    lines = []
    for order_item in deal.order.items.select_related('product', 'variant').all():
        if not order_item.product_id:
            continue
        reserved_quantity = existing_reserved.get(order_item.id, 0)
        missing_quantity = max(int(order_item.active_quantity or 0) - reserved_quantity, 0)
        if missing_quantity <= 0:
            continue
        lines.append(
            {
                'order_item': order_item,
                'product': order_item.product,
                'variant': order_item.variant,
                'product_name': order_item.resolved_product_name,
                'variant_name': order_item.resolved_variant_name,
                'ordered_quantity': int(order_item.active_quantity or 0),
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
    coverage = reservation_coverage_snapshot(deal.order)
    if coverage['tracked_line_count'] == 0:
        return ManagerDeal.FULFILLMENT_STATUS_FULFILLED
    tracked_lines_fully_shipped = True
    tracked_line_seen = False
    for item in deal.order.items.select_related('product', 'variant').all():
        if item.is_on_request or not item.product_id:
            continue
        tracked_line_seen = True
        if item.shipped_quantity < item.active_quantity:
            tracked_lines_fully_shipped = False
            break
    if tracked_line_seen and tracked_lines_fully_shipped:
        return ManagerDeal.FULFILLMENT_STATUS_FULFILLED
    reservation = _deal_primary_reservation(deal)
    if reservation and deal.primary_reservation_id != reservation.id:
        deal.primary_reservation = reservation
        deal.save(update_fields=['primary_reservation', 'updated_at'])
    if deal.order.status in {Order.STATUS_SHIPPING, Order.STATUS_DONE}:
        return ManagerDeal.FULFILLMENT_STATUS_FULFILLED
    if coverage['uncovered_count'] == 0 and coverage['covered_by_procurement_count'] == 0:
        if coverage['covered_by_incoming_count'] > 0:
            return ManagerDeal.FULFILLMENT_STATUS_RESERVED_INCOMING
        return ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK
    if deal.deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST:
        if coverage['uncovered_count'] > 0 or coverage['covered_by_procurement_count'] > 0:
            return ManagerDeal.FULFILLMENT_STATUS_PROCUREMENT_REQUIRED
    elif coverage['uncovered_count'] > 0:
        return ManagerDeal.FULFILLMENT_STATUS_NOT_RESERVED
    return ManagerDeal.FULFILLMENT_STATUS_NOT_RESERVED


def _deal_delivery_required(deal):
    return deal.requires_delivery_workflow


def _deal_delivery_status(deal):
    shipments = deal.shipments.exclude(status=Shipment.STATUS_CANCELLED)
    if deal.order.status == Order.STATUS_DONE or shipments.filter(status=Shipment.STATUS_DELIVERED).exists():
        return ManagerDeal.DELIVERY_STATUS_DELIVERED
    if deal.delivery_status == ManagerDeal.DELIVERY_STATUS_DELIVERED:
        return ManagerDeal.DELIVERY_STATUS_DELIVERED
    if deal.order.status == Order.STATUS_SHIPPING or shipments.filter(status=Shipment.STATUS_SHIPPED).exists():
        return ManagerDeal.DELIVERY_STATUS_SHIPPED
    if deal.delivery_status == ManagerDeal.DELIVERY_STATUS_SHIPPED:
        return ManagerDeal.DELIVERY_STATUS_SHIPPED
    if shipments.exists():
        return ManagerDeal.DELIVERY_STATUS_PREPARING
    if deal.shipment_status == ManagerDeal.SHIPMENT_SENT or (deal.tracking_number or '').strip():
        return ManagerDeal.DELIVERY_STATUS_SHIPPED
    if deal.shipment_status == ManagerDeal.SHIPMENT_PENDING:
        return ManagerDeal.DELIVERY_STATUS_PREPARING
    if not _deal_delivery_required(deal):
        return ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED
    if _deal_delivery_required(deal):
        return ManagerDeal.DELIVERY_STATUS_READY
    return ManagerDeal.DELIVERY_STATUS_NOT_REQUIRED


def _deal_shipment_status(deal):
    shipments = deal.shipments.exclude(status=Shipment.STATUS_CANCELLED)
    if not shipments.exists():
        if deal.delivery_status == ManagerDeal.DELIVERY_STATUS_DELIVERED:
            return ManagerDeal.SHIPMENT_DELIVERED
        if (
            deal.delivery_status == ManagerDeal.DELIVERY_STATUS_SHIPPED
            or deal.shipment_status == ManagerDeal.SHIPMENT_SENT
            or (deal.tracking_number or '').strip()
        ):
            return ManagerDeal.SHIPMENT_SENT
        if deal.shipment_status == ManagerDeal.SHIPMENT_PENDING:
            return ManagerDeal.SHIPMENT_PENDING
        return ManagerDeal.SHIPMENT_DRAFT
    if not shipments.exclude(status=Shipment.STATUS_DELIVERED).exists():
        return ManagerDeal.SHIPMENT_DELIVERED
    if shipments.filter(
        Q(status=Shipment.STATUS_SHIPPED)
        | Q(status=Shipment.STATUS_DELIVERED)
        | Q(inventory_consumed_at__isnull=False)
    ).exists():
        return ManagerDeal.SHIPMENT_SENT
    if shipments.filter(status__in=[Shipment.STATUS_DRAFT, Shipment.STATUS_PENDING]).exists():
        return ManagerDeal.SHIPMENT_PENDING
    return ManagerDeal.SHIPMENT_DRAFT


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
    coverage = reservation_coverage_snapshot(deal.order)
    if coverage['tracked_line_count'] == 0:
        return False
    inventory_totals = _inventory_totals_map()
    has_catalog_items = False
    for item in deal.order.items.select_related('product', 'variant'):
        if (
            item.line_type != OrderItem.LINE_TYPE_CATALOG
            or item.is_on_request
            or not item.product_id
            or not getattr(item.product, 'tracks_stock', True)
        ):
            continue
        has_catalog_items = True
        available = inventory_totals.get((item.product_id, item.variant_id or 0), 0)
        if available < item.quantity:
            return False
    return has_catalog_items


def _compute_next_step_for_deal(deal, *, case_status, payment_state, fulfillment_status, delivery_status, documents_status):
    coverage = reservation_coverage_snapshot(deal.order)
    if deal.deal_status == ManagerDeal.DEAL_STATUS_RETURNED and deal.returned_to_stock_at is None:
        return ManagerDeal.NEXT_STEP_RETURN_TO_STOCK, 'По сделке оформлен возврат. Подтвердите reverse-flow, верните товар на склад и зафиксируйте корректировки.'
    if deal.deal_status == ManagerDeal.DEAL_STATUS_RETURNED and deal.returned_to_stock_at is not None:
        return ManagerDeal.NEXT_STEP_COMPLETED, 'Возврат принят на склад, reverse-flow зафиксирован.'
    if case_status in {ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED} or deal.order.status == Order.STATUS_DONE:
        return ManagerDeal.NEXT_STEP_COMPLETED, 'Заказ завершен.'
    if delivery_status in {ManagerDeal.DELIVERY_STATUS_SHIPPED, ManagerDeal.DELIVERY_STATUS_DELIVERED} or deal.order.status == Order.STATUS_SHIPPING:
        return ManagerDeal.NEXT_STEP_SHIPPED, 'Заказ уже отправлен и находится в доставке.'
    if case_status == ManagerDeal.CASE_STATUS_NEW or deal.order.status == Order.STATUS_NEW:
        return ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION, 'Новый заказ без подтверждения менеджером.'
    if _deal_document_needs_preparation(deal):
        return ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS, 'Для сделки нужен документ, но он еще не готов к отправке клиенту.'
    if deal.deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST and coverage['uncovered_count'] > 0:
        return ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT, 'Товара нет в доступном остатке, требуется закупка.'
    if _deal_can_confirm_availability(deal):
        return ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION, 'Нужно подтвердить доступный склад и наличие до создания брони.'
    if _deal_document_ready_for_dispatch(deal):
        return ManagerDeal.NEXT_STEP_NEEDS_DOCUMENT_DISPATCH, 'Документы готовы. Отправьте клиенту договорный пакет.'
    if payment_state in {ManagerDeal.PAYMENT_STATE_UNPAID, ManagerDeal.PAYMENT_STATE_PARTIAL}:
        return ManagerDeal.NEXT_STEP_NEEDS_PAYMENT, 'Оплата не закрыта полностью.'
    if coverage['tracked_line_count'] > 0 and coverage['uncovered_count'] > 0:
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
        'shipment_status': deal.shipment_status,
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
    shipment_status = _deal_shipment_status(deal)

    if delivery_status == ManagerDeal.DELIVERY_STATUS_DELIVERED and shipment_status == ManagerDeal.SHIPMENT_DELIVERED:
        changed['case_status'] = ManagerDeal.CASE_STATUS_COMPLETED

    changed['payment_state'] = payment_state
    changed['fulfillment_status'] = fulfillment_status
    changed['documents_status'] = documents_status
    changed['delivery_status'] = delivery_status
    changed['shipment_status'] = shipment_status

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
            'shipment_status',
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
    distribution_scheme = finance_deal.distribution_scheme if finance_deal.distribution_scheme_id else active_finance_distribution_scheme()
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
        'cost_of_goods': deal.outgoing_cost_total,
        'distribution_scheme': distribution_scheme,
        'expected_distributable_profit_snapshot': deal.expected_margin,
        'snapshot_data': snapshot_data,
        'comment': finance_deal.comment or 'Подготовлено из карточки сделки.',
    }
    contract_number = ''
    if linked_document is not None:
        contract_number = linked_document.number or linked_document.title or ''
    if not contract_number:
        contract_number = deal_manager_client(deal).name if deal_manager_client(deal) else f'Сделка #{deal.order_id}'
    updates['contract_number'] = contract_number
    relation_fields = {'manager_deal', 'responsible_manager', 'linked_document', 'deal_type', 'distribution_scheme'}
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
        sync_finance_deal_lines_from_manager_deal(finance_deal)
        finance_deal = recalculate_finance_deal_totals(finance_deal, sync_lines=False)
        return finance_deal
    finance_type = FinanceDealType.objects.filter(is_active=True).order_by('name', 'id').first()
    if finance_type is None:
        finance_type = FinanceDealType.objects.create(name='Операционная сделка', partner_share=Decimal('0'))
    finance_deal = FinanceDeal.objects.create(
        manager_deal=deal,
        responsible_manager=deal.responsible_manager or actor,
        linked_document=_deal_linked_document(deal),
        distribution_scheme=active_finance_distribution_scheme(),
        date=(deal.order.created_at or timezone.now()).date(),
        contract_number='',
        deal_type=finance_type,
        payment_method=deal.order.payment_method,
        payment_state=deal.order.payment_status,
        revenue=deal.grand_total,
        cost_of_goods=deal.outgoing_cost_total,
        expected_distributable_profit_snapshot=deal.expected_margin,
        snapshot_data=build_finance_case_snapshot(deal),
        comment='Создано из карточки сделки.',
        created_by=actor,
    )
    finance_deal = _hydrate_finance_deal_from_manager_deal(finance_deal, deal, actor=actor)
    sync_finance_deal_lines_from_manager_deal(finance_deal)
    finance_deal = recalculate_finance_deal_totals(finance_deal, sync_lines=False)
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
    if active_reservations and coverage['uncovered_count'] == 0:
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


@transaction.atomic
def reserve_order_item_for_manager_deal(
    deal,
    *,
    order_item,
    warehouse,
    quantity,
    comment='',
    actor=None,
):
    if deal is None or order_item is None or warehouse is None:
        raise ValueError('Для создания резерва нужны сделка, строка заказа и склад.')
    if order_item.order_id != deal.order_id:
        raise ValueError('Строка заказа не относится к этой сделке.')
    if order_item.line_type != OrderItem.LINE_TYPE_CATALOG or not order_item.product_id:
        raise ValueError('Резерв можно создать только для каталоговой позиции сделки.')
    if not getattr(order_item.product, 'tracks_stock', True):
        raise ValueError('Для этого товара складской резерв не используется.')

    requested_quantity = int(quantity or 0)
    if requested_quantity <= 0:
        raise ValueError('Количество резерва должно быть больше нуля.')

    existing_reserved = sum(
        int(item.active_reserved_quantity or 0)
        for item in ReservationItem.objects.filter(
            reservation__linked_order=deal.order,
            reservation__status__in=ACTIVE_RESERVATION_STATUSES,
            order_item=order_item,
        ).select_related('reservation')
    )
    missing_quantity = max(int(order_item.active_quantity or 0) - existing_reserved, 0)
    if missing_quantity <= 0:
        raise ValueError('Эта позиция уже полностью обеспечена резервом.')
    if requested_quantity > missing_quantity:
        raise ValueError(f'Нельзя зарезервировать больше {missing_quantity} шт. по этой позиции.')

    client_resolution = ensure_manager_client_for_order(deal.order)
    normalized_comment = (comment or '').strip()
    reservation, created = _get_or_create_order_reservation(
        order=deal.order,
        client=client_resolution['client'],
        warehouse=warehouse,
        comment=normalized_comment or 'Ручной резерв по сделке.',
        manager_deal=deal,
    )
    if normalized_comment and reservation.comments != normalized_comment:
        reservation.comments = normalized_comment
        reservation.save(update_fields=['comments', 'updated_at'])

    reservation_item = ReservationItem(
        reservation=reservation,
        order_item=order_item,
        product=order_item.product,
        variant=order_item.variant,
        quantity=requested_quantity,
    )
    validate_reservation_availability(reservation, items=[reservation_item])
    reservation_item.save()
    create_or_update_reservation_movements(
        reservation,
        movement_type=InventoryMovement.TYPE_RESERVE,
        author=actor,
        comment=normalized_comment or 'Ручной резерв по сделке.',
        items=[reservation_item],
    )
    sync_public_stock_for_warehouse(warehouse)

    active_reservations = list(
        deal.reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES)
        .select_related('source_warehouse')
        .order_by('id')
    )
    unique_warehouse_ids = {
        active_reservation.source_warehouse_id
        for active_reservation in active_reservations
        if active_reservation.source_warehouse_id
    }
    update_fields = []
    primary = _deal_primary_reservation(deal) or reservation
    if primary and deal.primary_reservation_id != primary.id:
        deal.primary_reservation = primary
        update_fields.append('primary_reservation')
    if deal.reserve_created_at is None:
        deal.reserve_created_at = timezone.now()
        update_fields.append('reserve_created_at')
    if len(unique_warehouse_ids) == 1:
        warehouse_id = next(iter(unique_warehouse_ids))
        if deal.stock_warehouse_id != warehouse_id:
            deal.stock_warehouse_id = warehouse_id
            update_fields.append('stock_warehouse')
    if update_fields:
        deal.save(update_fields=update_fields + ['updated_at'])

    record_deal_activity(
        deal,
        event_type='reservation.created',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'reservation_id': reservation.id,
            'reservation_item_id': reservation_item.id,
            'order_item_id': order_item.id,
            'warehouse_id': warehouse.id,
            'quantity': requested_quantity,
            'created_reservation': created,
        },
    )
    recompute_deal_workflow(deal, actor=actor)
    return reservation, reservation_item


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


def _reversal_adjustment_kinds():
    return {
        FinanceDealAdjustment.KIND_SHIPMENT_RETURN,
        FinanceDealAdjustment.KIND_SHIPMENT_CANCELLATION,
        FinanceDealAdjustment.KIND_REPLACEMENT_REVERSAL,
    }


def _shipped_cost_snapshot_for_order_item(order_item, *, quantity):
    shipped_allocations = list(
        SaleLineAllocation.objects.filter(order_item=order_item, status=SaleLineAllocation.STATUS_SHIPPED)
    )
    shipped_qty = sum(int(allocation.shipped_qty or 0) for allocation in shipped_allocations)
    if shipped_qty > 0:
        total_cost = sum(
            (Decimal(allocation.unit_cost_snapshot or 0) * Decimal(allocation.shipped_qty or 0))
            for allocation in shipped_allocations
        )
        unit_cost = _quantize_money(total_cost / Decimal(shipped_qty))
    else:
        unit_cost = _quantize_money(order_item.effective_unit_cost)
    return unit_cost, _quantize_money(unit_cost * Decimal(quantity))


def _reversal_revenue_for_order_item(order_item, *, quantity):
    if order_item is None:
        return MONEY_ZERO
    return _quantize_money(Decimal(order_item.unit_price or 0) * Decimal(quantity))


def _create_reverse_document_for_deal(
    deal,
    *,
    reverse_kind,
    actor=None,
    related_activity=None,
    related_adjustments=None,
    related_shipment=None,
    finance_lines=None,
):
    client = deal_manager_client(deal) or ensure_manager_client_for_order(deal.order)['client']
    document = ContractDocument.objects.create(
        manager_deal=deal,
        linked_order=deal.order,
        manager_client=client,
        responsible_manager=deal.responsible_manager or actor,
        created_by=actor,
        document_type=ContractTemplate.DOC_TYPE_OTHER,
        status=ContractDocument.STATUS_DRAFT,
        title=f'Корректировка {reverse_kind} по сделке #{deal.order_id}',
        notes='Системный reverse document для аудита разворота.',
        document_data={
            'document_role': 'reverse_event',
            'reverse_kind': reverse_kind,
            'related_activity_id': related_activity.id if related_activity else None,
            'related_shipment_id': related_shipment.id if related_shipment else None,
            'finance_adjustment_ids': [adjustment.id for adjustment in (related_adjustments or [])],
            'finance_line_ids': [line.id for line in (finance_lines or [])],
        },
    )
    return document


def _refundable_expense_adjustments(
    finance_deal,
    *,
    reversed_quantity_by_line=None,
    reversed_revenue=None,
    related_shipment=None,
    related_activity=None,
    related_document=None,
    actor=None,
):
    reversed_quantity_by_line = reversed_quantity_by_line or {}
    reversed_revenue = _quantize_money(reversed_revenue or MONEY_ZERO)
    original_reversible_deal_revenue = _quantize_money(
        sum((line.sale_total for line in finance_deal.lines.all() if not line.replacement_of_id), MONEY_ZERO)
        or finance_deal.revenue
    )
    created = []
    for expense in finance_deal.expenses.filter(affects_direct_expenses=True):
        if expense.refund_policy == FinanceExpense.REFUND_POLICY_NON_REFUNDABLE:
            continue
        if expense.finance_line_id:
            original_scope = Decimal(expense.finance_line.quantity or 0)
            cumulative_reversed_scope = abs(
                sum(
                    (
                        Decimal(adjustment.quantity_delta or 0)
                        for adjustment in finance_deal.adjustments.filter(
                            related_expense=expense,
                            adjustment_kind=FinanceDealAdjustment.KIND_DIRECT_EXPENSE_REFUND,
                        )
                    ),
                    Decimal('0'),
                )
            )
            cumulative_reversed_scope += Decimal(reversed_quantity_by_line.get(expense.finance_line_id, 0))
        else:
            original_scope = Decimal(original_reversible_deal_revenue or 0)
            cumulative_reversed_scope = abs(
                sum(
                    (
                        Decimal(adjustment.payload.get('reversed_revenue', '0') or 0)
                        for adjustment in finance_deal.adjustments.filter(
                            related_expense=expense,
                            adjustment_kind=FinanceDealAdjustment.KIND_DIRECT_EXPENSE_REFUND,
                        )
                    ),
                    Decimal('0'),
                )
            )
            cumulative_reversed_scope += Decimal(reversed_revenue or 0)
        if original_scope <= 0:
            continue
        ratio = min(cumulative_reversed_scope / original_scope, Decimal('1'))
        if expense.refund_policy == FinanceExpense.REFUND_POLICY_ON_FULL_REVERSAL:
            ratio = Decimal('1') if ratio >= Decimal('1') else Decimal('0')
        already_refunded = abs(
            sum(
                (
                    Decimal(adjustment.direct_expenses_delta or 0)
                    for adjustment in finance_deal.adjustments.filter(
                        related_expense=expense,
                        adjustment_kind=FinanceDealAdjustment.KIND_DIRECT_EXPENSE_REFUND,
                    )
                ),
                Decimal('0'),
            )
        )
        target_refund_total = _quantize_money(Decimal(expense.amount or 0) * ratio)
        refund_delta = _quantize_money(target_refund_total - already_refunded)
        if refund_delta <= 0:
            continue
        created.append(
            FinanceDealAdjustment.objects.create(
                finance_deal=finance_deal,
                finance_line=expense.finance_line,
                related_expense=expense,
                related_shipment=related_shipment,
                related_activity=related_activity,
                related_document=related_document,
                adjustment_kind=FinanceDealAdjustment.KIND_DIRECT_EXPENSE_REFUND,
                reason_code=expense.refund_policy,
                direct_expenses_delta=-refund_delta,
                payload={
                    'refund_policy': expense.refund_policy,
                    'target_refund_total': str(target_refund_total),
                    'already_refunded': str(already_refunded),
                    'reversed_revenue': str(reversed_revenue),
                    'reversed_quantity_by_line': {
                        str(line_id): str(value) for line_id, value in reversed_quantity_by_line.items()
                    },
                },
                created_by=actor,
            )
        )
    return created


def reverse_shipment_for_manager_deal(deal, *, actor=None, reason_code='shipment_return'):
    shipments = list(
        deal.shipments.exclude(status=Shipment.STATUS_CANCELLED)
        .filter(status__in=[Shipment.STATUS_SHIPPED, Shipment.STATUS_DELIVERED])
        .select_related('source_warehouse')
        .prefetch_related('items__order_item', 'items__product', 'items__variant')
        .order_by('id')
    )
    if not shipments:
        raise ValueError('Для reverse-flow нужна отгрузка в статусе "Отправлено" или "Доставлено".')
    if deal.returned_to_stock_at is not None:
        raise ValueError('Reverse-flow по этой сделке уже зафиксирован.')

    finance_deal = ensure_finance_deal_for_manager_deal(deal, actor=actor)
    requested_activity = record_deal_activity(
        deal,
        event_type='shipment.return_requested',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={'shipment_ids': [shipment.id for shipment in shipments], 'reason_code': reason_code},
    )

    created_lots = []
    created_adjustments = []
    reversed_quantity_by_line = defaultdict(Decimal)
    reversed_revenue = MONEY_ZERO
    return_reference_type = 'avito_return' if reason_code == 'avito_return' else 'return'

    with transaction.atomic():
        for shipment in shipments:
            source_warehouse = shipment.source_warehouse or deal.stock_warehouse
            if source_warehouse is None:
                raise ValueError('Не удалось определить склад-источник для возврата.')
            for shipment_item in shipment.items.select_related('order_item', 'product', 'variant').all():
                quantity = int(shipment_item.quantity or 0)
                if quantity <= 0:
                    continue
                return_reference_id = deal.pk if reason_code == 'avito_return' else shipment.id
                unit_cost, cost_total = _shipped_cost_snapshot_for_order_item(
                    shipment_item.order_item,
                    quantity=quantity,
                ) if shipment_item.order_item_id else (_quantize_money(Decimal('0')), MONEY_ZERO)
                return_lot = InventoryLot.objects.create(
                    warehouse=source_warehouse,
                    product=shipment_item.product,
                    variant=shipment_item.variant,
                    received_qty=quantity,
                    remaining_qty=quantity,
                    unit_cost=unit_cost,
                    unit_cost_base=unit_cost,
                    unit_cost_final=unit_cost,
                    received_at=timezone.now(),
                    reference_type=return_reference_type,
                    reference_id=return_reference_id,
                )
                InventoryMovement.objects.create(
                    warehouse=source_warehouse,
                    product=shipment_item.product,
                    variant=shipment_item.variant,
                    movement_type=InventoryMovement.TYPE_RECEIPT,
                    quantity=quantity,
                    reference_type=return_reference_type,
                    reference_id=return_reference_id,
                    comment='Reverse-flow после отгрузки.',
                    author=actor,
                )
                created_lots.append(return_lot)
                if shipment_item.order_item_id:
                    finance_line = finance_deal.lines.filter(order_item=shipment_item.order_item).order_by('id').first()
                    revenue_delta = -_reversal_revenue_for_order_item(
                        shipment_item.order_item,
                        quantity=quantity,
                    )
                    adjustment = FinanceDealAdjustment.objects.create(
                        finance_deal=finance_deal,
                        finance_line=finance_line,
                        related_shipment=shipment,
                        related_activity=requested_activity,
                        adjustment_kind=FinanceDealAdjustment.KIND_SHIPMENT_RETURN,
                        reason_code=reason_code,
                        quantity_delta=Decimal(-quantity),
                        revenue_delta=revenue_delta,
                        cost_of_goods_delta=-cost_total,
                        payload={
                            'shipment_id': shipment.id,
                            'order_item_id': shipment_item.order_item_id,
                            'return_lot_id': return_lot.id,
                            'unit_cost': str(unit_cost),
                            'quantity': quantity,
                        },
                        created_by=actor,
                    )
                    created_adjustments.append(adjustment)
                    if finance_line is not None:
                        reversed_quantity_by_line[finance_line.id] += Decimal(quantity)
                    reversed_revenue += abs(revenue_delta)
            rebuild_inventory_balance_cache(warehouse_ids=[source_warehouse.id])
            sync_public_stock_for_warehouse(source_warehouse)

        reverse_document = _create_reverse_document_for_deal(
            deal,
            reverse_kind='shipment_return',
            actor=actor,
            related_activity=requested_activity,
            related_adjustments=created_adjustments,
            related_shipment=shipments[-1],
            finance_lines=[adjustment.finance_line for adjustment in created_adjustments if adjustment.finance_line_id],
        )
        FinanceDealAdjustment.objects.filter(pk__in=[item.pk for item in created_adjustments]).update(
            related_document=reverse_document
        )
        expense_adjustments = _refundable_expense_adjustments(
            finance_deal,
            reversed_quantity_by_line=reversed_quantity_by_line,
            reversed_revenue=reversed_revenue,
            related_shipment=shipments[-1],
            related_activity=requested_activity,
            related_document=reverse_document,
            actor=actor,
        )
        created_adjustments.extend(expense_adjustments)

        deal.returned_to_stock_at = timezone.now()
        update_fields = ['returned_to_stock_at']
        if deal.primary_reservation_id and deal.primary_reservation.status not in ACTIVE_RESERVATION_STATUSES:
            deal.primary_reservation = None
            update_fields.append('primary_reservation')
        deal.save(update_fields=update_fields + ['updated_at'])

    record_deal_activity(
        deal,
        event_type='shipment.return_received',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'shipment_ids': [shipment.id for shipment in shipments],
            'return_lot_ids': [lot.id for lot in created_lots],
            'adjustment_ids': [adjustment.id for adjustment in created_adjustments],
            'document_id': reverse_document.id,
        },
    )
    record_deal_activity(
        deal,
        event_type='shipment.reversed',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'shipment_ids': [shipment.id for shipment in shipments],
            'return_lot_ids': [lot.id for lot in created_lots],
            'document_id': reverse_document.id,
        },
    )
    record_deal_activity(
        deal,
        event_type='finance.adjustment_posted',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'finance_deal_id': finance_deal.id,
            'adjustment_ids': [adjustment.id for adjustment in created_adjustments],
            'document_id': reverse_document.id,
        },
    )
    recalculate_finance_deal_totals(finance_deal, sync_lines=False)
    recompute_deal_workflow(deal, actor=actor)
    return {
        'return_lot_ids': [lot.id for lot in created_lots],
        'adjustment_ids': [adjustment.id for adjustment in created_adjustments],
        'document_id': reverse_document.id,
    }


def cancel_pending_shipment_for_manager_deal(deal, *, actor=None, reason_code='shipment_cancelled'):
    finance_deal = ensure_finance_deal_for_manager_deal(deal, actor=actor)
    shipments = list(
        deal.shipments.exclude(status=Shipment.STATUS_CANCELLED)
        .filter(status__in=[Shipment.STATUS_DRAFT, Shipment.STATUS_PENDING])
        .prefetch_related('items__order_item')
        .order_by('id')
    )
    reservations = list(
        deal.reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES)
        .select_related('source_warehouse', 'source_cargo__destination_warehouse')
        .prefetch_related('items__order_item')
        .order_by('id')
    )
    if not shipments and not reservations:
        raise ValueError('Нет активных отгрузок или резервов для отмены до shipment.')
    created_adjustments = []
    reversed_quantity_by_line = defaultdict(Decimal)
    reversed_revenue = MONEY_ZERO
    for shipment in shipments:
        shipment.status = Shipment.STATUS_CANCELLED
        shipment.save(update_fields=['status', 'updated_at'])
        for shipment_item in shipment.items.select_related('order_item').all():
            if not shipment_item.order_item_id:
                continue
            finance_line = finance_deal.lines.filter(order_item=shipment_item.order_item).order_by('id').first()
            quantity = int(shipment_item.quantity or 0)
            revenue_delta = -_reversal_revenue_for_order_item(
                shipment_item.order_item,
                quantity=quantity,
            )
            created_adjustments.append(
                FinanceDealAdjustment.objects.create(
                    finance_deal=finance_deal,
                    finance_line=finance_line,
                    related_shipment=shipment,
                    adjustment_kind=FinanceDealAdjustment.KIND_SHIPMENT_CANCELLATION,
                    reason_code=reason_code,
                    quantity_delta=Decimal(-quantity),
                    revenue_delta=revenue_delta,
                    payload={'shipment_id': shipment.id, 'order_item_id': shipment_item.order_item_id},
                    created_by=actor,
                )
            )
            if finance_line is not None:
                reversed_quantity_by_line[finance_line.id] += Decimal(quantity)
            reversed_revenue += abs(revenue_delta)
    released_reservations = []
    for reservation in reservations:
        warehouse = reservation_effective_warehouse(reservation)
        create_or_update_reservation_movements(
            reservation,
            movement_type=InventoryMovement.TYPE_RELEASE,
            author=actor,
            comment='Снятие резерва при отмене до shipment.',
        )
        reservation.status = Reservation.STATUS_CANCELLED
        reservation.save(update_fields=['status', 'updated_at'])
        if warehouse is not None:
            sync_public_stock_for_warehouse(warehouse)
        released_reservations.append(reservation.id)
    expense_adjustments = _refundable_expense_adjustments(
        finance_deal,
        reversed_quantity_by_line=reversed_quantity_by_line,
        reversed_revenue=reversed_revenue,
        actor=actor,
    )
    created_adjustments.extend(expense_adjustments)
    record_deal_activity(
        deal,
        event_type='finance.adjustment_posted',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'finance_deal_id': finance_deal.id,
            'adjustment_ids': [adjustment.id for adjustment in created_adjustments],
            'released_reservation_ids': released_reservations,
        },
    )
    recalculate_finance_deal_totals(finance_deal, sync_lines=False)
    recompute_deal_workflow(deal, actor=actor)
    return {
        'adjustment_ids': [adjustment.id for adjustment in created_adjustments],
        'released_reservation_ids': released_reservations,
    }


def record_finance_line_replacement(source_line, replacement_line, *, actor=None, reason_code='replacement'):
    if source_line.finance_deal_id != replacement_line.finance_deal_id:
        raise ValueError('Замена должна жить в рамках одного финансового кейса.')
    finance_deal = source_line.finance_deal
    if replacement_line.replacement_of_id != source_line.id:
        replacement_line.replacement_of = source_line
        replacement_line.save(update_fields=['replacement_of', 'updated_at'])
    replacement_activity = None
    reverse_document = None
    reversal = FinanceDealAdjustment.objects.create(
        finance_deal=finance_deal,
        finance_line=source_line,
        adjustment_kind=FinanceDealAdjustment.KIND_REPLACEMENT_REVERSAL,
        reason_code=reason_code,
        quantity_delta=-Decimal(source_line.quantity or 0),
        revenue_delta=-_quantize_money(source_line.sale_total),
        cost_of_goods_delta=-_quantize_money(source_line.cost_total),
        payload={'replacement_line_id': replacement_line.id},
        created_by=actor,
    )
    addition = FinanceDealAdjustment.objects.create(
        finance_deal=finance_deal,
        finance_line=replacement_line,
        adjustment_kind=FinanceDealAdjustment.KIND_REPLACEMENT_ADDITION,
        reason_code=reason_code,
        quantity_delta=Decimal(replacement_line.quantity or 0),
        revenue_delta=_quantize_money(replacement_line.sale_total),
        cost_of_goods_delta=_quantize_money(replacement_line.cost_total),
        payload={'replacement_of_line_id': source_line.id},
        created_by=actor,
    )
    if finance_deal.manager_deal_id:
        replacement_activity = record_deal_activity(
            finance_deal.manager_deal,
            event_type='replacement.recorded',
            source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
            actor=actor,
            payload={
                'finance_deal_id': finance_deal.id,
                'source_line_id': source_line.id,
                'replacement_line_id': replacement_line.id,
                'adjustment_ids': [reversal.id, addition.id],
            },
        )
        reverse_document = _create_reverse_document_for_deal(
            finance_deal.manager_deal,
            reverse_kind='replacement_adjustment',
            actor=actor,
            related_activity=replacement_activity,
            related_adjustments=[reversal, addition],
            finance_lines=[source_line, replacement_line],
        )
        FinanceDealAdjustment.objects.filter(pk__in=[reversal.pk, addition.pk]).update(
            related_activity=replacement_activity,
            related_document=reverse_document,
        )
        record_deal_activity(
            finance_deal.manager_deal,
            event_type='finance.adjustment_posted',
            source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
            actor=actor,
            payload={
                'finance_deal_id': finance_deal.id,
                'adjustment_ids': [reversal.id, addition.id],
                'document_id': reverse_document.id,
            },
        )
    recalculate_finance_deal_totals(finance_deal, sync_lines=False)
    if finance_deal.manager_deal_id:
        recompute_deal_workflow(finance_deal.manager_deal, actor=actor)
    return reversal, addition


def restore_avito_return_to_stock(deal, *, actor=None):
    if deal is None or not deal.is_avito:
        raise ValueError('Возврат на склад доступен только для сделок Avito.')
    if deal.deal_status != ManagerDeal.DEAL_STATUS_RETURNED:
        raise ValueError('Вернуть товар на склад можно только после перевода сделки в этап "Возврат".')
    result = reverse_shipment_for_manager_deal(deal, actor=actor, reason_code='avito_return')
    record_deal_activity(
        deal,
        event_type='inventory.returned_to_stock',
        source=DealActivity.SOURCE_USER if actor else DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'return_lot_ids': result['return_lot_ids'],
            'adjustment_ids': result['adjustment_ids'],
            'document_id': result['document_id'],
            'receipts_total': len(result['return_lot_ids']),
        },
    )
    return result


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
                    'quantity': item.active_reserved_quantity,
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
        reservation_quantity = int(item.active_reserved_quantity or 0)
        if reservation_quantity <= 0:
            continue
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
            row['reserved_on_hand'] += reservation_quantity
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
                row['inbound_reserved'] += reservation_quantity

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


def rebuild_inventory_balance_cache(*, warehouse_ids=None):
    lot_queryset = InventoryLot.objects.all()
    balance_queryset = InventoryBalance.objects.all()
    if warehouse_ids:
        lot_queryset = lot_queryset.filter(warehouse_id__in=warehouse_ids)
        balance_queryset = balance_queryset.filter(warehouse_id__in=warehouse_ids)
    totals = defaultdict(int)
    min_stock_map = {}
    for balance in balance_queryset:
        min_stock_map[(balance.warehouse_id, balance.product_id, balance.variant_id)] = balance.min_stock
    for lot in lot_queryset:
        totals[(lot.warehouse_id, lot.product_id, lot.variant_id)] += int(lot.remaining_qty or 0)
    with transaction.atomic():
        balance_queryset.update(quantity=0)
        for (warehouse_id, product_id, variant_id), quantity in totals.items():
            defaults = {
                'quantity': quantity,
                'min_stock': min_stock_map.get((warehouse_id, product_id, variant_id), 0),
            }
            if variant_id is None:
                balance = InventoryBalance.objects.filter(
                    warehouse_id=warehouse_id,
                    product_id=product_id,
                    variant__isnull=True,
                ).first()
                if balance:
                    balance.quantity = quantity
                    balance.min_stock = defaults['min_stock']
                    balance.save(update_fields=['quantity', 'min_stock', 'updated_at'])
                else:
                    InventoryBalance.objects.create(
                        warehouse_id=warehouse_id,
                        product_id=product_id,
                        variant=None,
                        **defaults,
                    )
            else:
                InventoryBalance.objects.update_or_create(
                    warehouse_id=warehouse_id,
                    product_id=product_id,
                    variant_id=variant_id,
                    defaults=defaults,
                )


def _purchase_items_for_order_item(order_item):
    return list(
        PurchaseItem.objects.filter(order_item=order_item).order_by('purchase__date', 'id')
    )


def _sync_finance_lines_for_order_item(order_item):
    for finance_line in order_item.finance_deal_lines.all():
        finance_line.line_type = order_item.line_type
        finance_line.product = order_item.product
        finance_line.variant = order_item.variant
        finance_line.product_name = order_item.display_name
        finance_line.custom_sku = order_item.custom_sku
        finance_line.quantity = order_item.active_quantity
        finance_line.unit_sale_price = order_item.unit_price
        finance_line.planned_unit_cost = order_item.planned_unit_cost
        finance_line.actual_unit_cost = order_item.actual_unit_cost
        finance_line.cost_status = order_item.cost_status
        finance_line.unit_cost_price = order_item.effective_unit_cost
        finance_line.save()
        recalculate_finance_deal_totals(finance_line.finance_deal, sync_lines=False)


def sync_order_item_planned_cost(order_item):
    purchase_items = _purchase_items_for_order_item(order_item)
    if not purchase_items:
        if Decimal(order_item.actual_unit_cost or 0) > 0:
            order_item.purchase_price = order_item.actual_unit_cost
            update_fields = ['purchase_price']
        else:
            order_item.cost_status = OrderItem.COST_STATUS_NONE
            order_item.planned_unit_cost = Decimal('0')
            order_item.purchase_price = Decimal('0')
            update_fields = ['cost_status', 'planned_unit_cost', 'purchase_price']
        order_item.save(update_fields=update_fields + ['updated_at'] if 'updated_at' not in update_fields else update_fields)
        _sync_finance_lines_for_order_item(order_item)
        return order_item
    total_qty = sum(int(item.active_quantity or 0) for item in purchase_items)
    total_cost = sum((Decimal(item.unit_cost or 0) * Decimal(item.active_quantity or 0) for item in purchase_items), Decimal('0'))
    planned_unit_cost = _quantize_money(total_cost / Decimal(total_qty)) if total_qty else Decimal('0')
    order_item.planned_unit_cost = planned_unit_cost
    order_item.purchase_price = order_item.actual_unit_cost if Decimal(order_item.actual_unit_cost or 0) > 0 else planned_unit_cost
    order_item.cost_status = (
        OrderItem.COST_STATUS_ACTUAL
        if Decimal(order_item.actual_unit_cost or 0) > 0
        else OrderItem.COST_STATUS_PLANNED
    )
    order_item.save(update_fields=['planned_unit_cost', 'purchase_price', 'cost_status'])
    _sync_finance_lines_for_order_item(order_item)
    return order_item


def _reserved_quantity_for_lot(lot):
    return sum(
        int(allocation.reserved_qty or 0) - int(allocation.shipped_qty or 0)
        for allocation in lot.allocations.filter(status=SaleLineAllocation.STATUS_RESERVED)
    )


def _available_quantity_for_lot_reservation(lot):
    return max(int(lot.remaining_qty or 0) - _reserved_quantity_for_lot(lot), 0)


def _ensure_lot_coverage_from_balance(*, warehouse, product_id, variant_id):
    balance = InventoryBalance.objects.filter(
        warehouse=warehouse,
        product_id=product_id,
        variant_id=variant_id,
    ).first()
    balance_qty = int(balance.quantity or 0) if balance else 0
    lot_qty = sum(
        int(value or 0)
        for value in InventoryLot.objects.filter(
            warehouse=warehouse,
            product_id=product_id,
            variant_id=variant_id,
        ).values_list('remaining_qty', flat=True)
    )
    missing_qty = max(balance_qty - lot_qty, 0)
    if missing_qty <= 0:
        return None
    return InventoryLot.objects.create(
        warehouse=warehouse,
        product_id=product_id,
        variant_id=variant_id,
        received_qty=missing_qty,
        remaining_qty=missing_qty,
        unit_cost=Decimal('0'),
        unit_cost_base=Decimal('0'),
        unit_cost_final=Decimal('0'),
        received_at=timezone.now(),
        reference_type='balance_backfill',
        reference_id=balance.id if balance else None,
    )


def allocate_inventory_to_order_item(*, order_item, warehouse, quantity, mode):
    if not order_item.product_id or quantity <= 0:
        return []
    _ensure_lot_coverage_from_balance(
        warehouse=warehouse,
        product_id=order_item.product_id,
        variant_id=order_item.variant_id,
    )
    lots = list(
        InventoryLot.objects.filter(
            warehouse=warehouse,
            product_id=order_item.product_id,
            variant_id=order_item.variant_id,
            remaining_qty__gt=0,
        ).order_by('received_at', 'id')
    )
    needed = int(quantity)
    allocations = []
    with transaction.atomic():
        for lot in lots:
            if needed <= 0:
                break
            if mode == SaleLineAllocation.STATUS_RESERVED:
                lot_available = _available_quantity_for_lot_reservation(lot)
            else:
                lot_available = int(lot.remaining_qty or 0)
            if lot_available <= 0:
                continue
            take = min(lot_available, needed)
            if mode == SaleLineAllocation.STATUS_RESERVED:
                allocation, _ = SaleLineAllocation.objects.get_or_create(
                    order_item=order_item,
                    inventory_lot=lot,
                    status=SaleLineAllocation.STATUS_RESERVED,
                    defaults={'reserved_qty': 0, 'shipped_qty': 0, 'unit_cost_snapshot': lot.unit_cost_final},
                )
                allocation.reserved_qty += take
                allocation.unit_cost_snapshot = lot.unit_cost_final
                allocation.save(update_fields=['reserved_qty', 'unit_cost_snapshot', 'updated_at'])
            else:
                allocation, _ = SaleLineAllocation.objects.get_or_create(
                    order_item=order_item,
                    inventory_lot=lot,
                    status=SaleLineAllocation.STATUS_SHIPPED,
                    defaults={'reserved_qty': 0, 'shipped_qty': 0, 'unit_cost_snapshot': lot.unit_cost_final},
                )
                allocation.reserved_qty += take
                allocation.shipped_qty += take
                allocation.unit_cost_snapshot = lot.unit_cost_final
                allocation.save(update_fields=['reserved_qty', 'shipped_qty', 'unit_cost_snapshot', 'updated_at'])
                lot.remaining_qty = max(int(lot.remaining_qty or 0) - take, 0)
                lot.save(update_fields=['remaining_qty', 'updated_at'])
            allocations.append(allocation)
            needed -= take
        if needed > 0:
            raise ValueError(f'Недостаточно остатков в лотах для "{order_item.display_name}". Не хватает {needed} шт.')
    rebuild_inventory_balance_cache(warehouse_ids=[warehouse.id])
    return allocations


def release_reserved_allocations(*, order_item, quantity=None, warehouse=None):
    queryset = SaleLineAllocation.objects.filter(
        order_item=order_item,
        status=SaleLineAllocation.STATUS_RESERVED,
    ).select_related('inventory_lot').order_by('inventory_lot__received_at', 'inventory_lot_id', 'id')
    if warehouse is not None:
        queryset = queryset.filter(inventory_lot__warehouse=warehouse)
    to_release = sum(int(allocation.reserved_qty or 0) - int(allocation.shipped_qty or 0) for allocation in queryset)
    if quantity is not None:
        to_release = min(to_release, int(quantity))
    if to_release <= 0:
        return []
    changed = []
    with transaction.atomic():
        for allocation in queryset:
            if to_release <= 0:
                break
            free_reserved = int(allocation.reserved_qty or 0) - int(allocation.shipped_qty or 0)
            if free_reserved <= 0:
                continue
            release_qty = min(free_reserved, to_release)
            allocation.reserved_qty -= release_qty
            if allocation.reserved_qty == 0 and allocation.shipped_qty == 0:
                allocation.status = SaleLineAllocation.STATUS_RELEASED
            allocation.save(update_fields=['reserved_qty', 'status', 'updated_at'])
            changed.append(allocation)
            to_release -= release_qty
    return changed


def _reservation_item_active_quantity(reservation_item):
    return int(reservation_item.active_reserved_quantity or 0)


def _set_reservation_item_progress(reservation_item, *, fulfilled_delta=0, released_delta=0):
    fulfilled_delta = int(fulfilled_delta or 0)
    released_delta = int(released_delta or 0)
    if fulfilled_delta < 0 or released_delta < 0:
        raise ValueError('Количество изменения строки брони не может быть отрицательным.')
    if fulfilled_delta == 0 and released_delta == 0:
        return reservation_item
    reservation_item.fulfilled_quantity += fulfilled_delta
    reservation_item.released_quantity += released_delta
    if reservation_item.fulfilled_quantity + reservation_item.released_quantity > reservation_item.quantity:
        raise ValueError('Сумма исполненного и освобожденного количества превышает количество строки брони.')
    reservation_item.save(update_fields=['fulfilled_quantity', 'released_quantity'])
    return reservation_item


def reactivate_reservation_items(reservation):
    changed = False
    for item in reservation.items.all():
        if item.released_quantity <= 0:
            continue
        item.released_quantity = 0
        item.save(update_fields=['released_quantity'])
        changed = True
    return changed


def recompute_reservation_status(reservation):
    if reservation.status in {Reservation.STATUS_CANCELLED, Reservation.STATUS_EXPIRED}:
        return reservation.status
    items = list(reservation.items.all())
    if not items:
        new_status = Reservation.STATUS_DRAFT
    else:
        active_qty = sum(_reservation_item_active_quantity(item) for item in items)
        fulfilled_qty = sum(int(item.fulfilled_quantity or 0) for item in items)
        released_qty = sum(int(item.released_quantity or 0) for item in items)
        total_qty = sum(int(item.quantity or 0) for item in items)
        if total_qty <= 0:
            new_status = Reservation.STATUS_DRAFT
        elif fulfilled_qty >= total_qty:
            new_status = Reservation.STATUS_FULFILLED
        elif released_qty >= total_qty:
            new_status = Reservation.STATUS_RELEASED
        elif active_qty == total_qty and fulfilled_qty == 0 and released_qty == 0:
            new_status = Reservation.STATUS_ACTIVE
        else:
            new_status = Reservation.STATUS_PARTIAL
    if reservation.status != new_status:
        reservation.status = new_status
        reservation.save(update_fields=['status', 'updated_at'])
    return new_status


def sync_order_item_actual_cost(order_item):
    shipped_allocations = list(
        SaleLineAllocation.objects.filter(order_item=order_item, status=SaleLineAllocation.STATUS_SHIPPED)
    )
    shipped_qty = sum(int(allocation.shipped_qty or 0) for allocation in shipped_allocations)
    if shipped_qty <= 0:
        return order_item
    total_cost = sum(
        (Decimal(allocation.unit_cost_snapshot or 0) * Decimal(allocation.shipped_qty or 0))
        for allocation in shipped_allocations
    )
    actual_unit_cost = _quantize_money(total_cost / Decimal(shipped_qty))
    update_fields = ['actual_unit_cost', 'purchase_price']
    order_item.actual_unit_cost = actual_unit_cost
    order_item.purchase_price = actual_unit_cost
    if shipped_qty >= int(order_item.active_quantity or 0):
        order_item.cost_status = OrderItem.COST_STATUS_ACTUAL
        update_fields.append('cost_status')
    elif Decimal(order_item.planned_unit_cost or 0) > 0 and order_item.cost_status == OrderItem.COST_STATUS_NONE:
        order_item.cost_status = OrderItem.COST_STATUS_PLANNED
        update_fields.append('cost_status')
    order_item.save(update_fields=update_fields)
    _sync_finance_lines_for_order_item(order_item)
    return order_item


def _consume_lots_without_allocation(*, warehouse, product, variant=None, quantity):
    needed = int(quantity)
    lots = list(
        InventoryLot.objects.filter(
            warehouse=warehouse,
            product=product,
            variant=variant,
            remaining_qty__gt=0,
        ).order_by('received_at', 'id')
    )
    for lot in lots:
        if needed <= 0:
            break
        available = int(lot.remaining_qty or 0)
        if available <= 0:
            continue
        take = min(available, needed)
        lot.remaining_qty = max(available - take, 0)
        lot.save(update_fields=['remaining_qty', 'updated_at'])
        needed -= take
    if needed > 0:
        raise ValueError(f'Недостаточно остатков в лотах для "{product.name}". Не хватает {needed} шт.')


def _available_map_for_source(source_type, source_warehouse=None, source_cargo=None):
    if source_type == Reservation.SOURCE_WAREHOUSE and source_warehouse:
        rows = inventory_snapshot_for_warehouse(source_warehouse)
        return {(row['product_id'], row['variant_id'] or 0): row['available'] for row in rows}
    if source_type == Reservation.SOURCE_CARGO and source_cargo and source_cargo.destination_warehouse_id:
        rows = inventory_snapshot_for_warehouse(source_cargo.destination_warehouse)
        return {(row['product_id'], row['variant_id'] or 0): row['inbound_available'] for row in rows}
    return {}


def receipt_inventory(
    *,
    warehouse,
    product,
    variant=None,
    quantity,
    author=None,
    comment='',
    reference_type='manual',
    reference_id=None,
    unit_cost=Decimal('0'),
    purchase_item=None,
    received_at=None,
):
    effective_received_at = _normalize_received_at(received_at)
    with transaction.atomic():
        InventoryLot.objects.create(
            purchase_item=purchase_item,
            warehouse=warehouse,
            product=product,
            variant=variant,
            received_qty=int(quantity),
            remaining_qty=int(quantity),
            unit_cost=Decimal(unit_cost or 0),
            unit_cost_base=Decimal(unit_cost or 0),
            unit_cost_final=Decimal(unit_cost or 0),
            received_at=effective_received_at,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        movement = InventoryMovement.objects.create(
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
        if received_at is not None:
            InventoryMovement.objects.filter(pk=movement.pk).update(created_at=effective_received_at)
        rebuild_inventory_balance_cache(warehouse_ids=[warehouse.id])
        sync_public_stock_for_warehouse(warehouse)
    return InventoryBalance.objects.filter(warehouse=warehouse, product=product, variant=variant).first()


def create_or_update_reservation_movements(reservation, *, movement_type, author=None, comment='', items=None):
    source_warehouse = reservation.source_warehouse
    if reservation.source_type == Reservation.SOURCE_CARGO and reservation.source_cargo_id:
        source_warehouse = reservation.source_cargo.destination_warehouse
    if not source_warehouse:
        return
    item_iterable = items if items is not None else reservation.items.select_related('product', 'variant').all()
    for item in item_iterable:
        quantity = _reservation_item_active_quantity(item)
        if quantity <= 0:
            continue
        InventoryMovement.objects.create(
            warehouse=source_warehouse,
            product=item.product,
            variant=item.variant,
            movement_type=movement_type,
            quantity=quantity,
            reference_type='reservation',
            reference_id=reservation.id,
            comment=comment,
            author=author,
        )
        if item.order_item_id and item.product_id:
            if movement_type == InventoryMovement.TYPE_RESERVE:
                allocate_inventory_to_order_item(
                    order_item=item.order_item,
                    warehouse=source_warehouse,
                    quantity=quantity,
                    mode=SaleLineAllocation.STATUS_RESERVED,
                )
            elif movement_type == InventoryMovement.TYPE_RELEASE:
                release_reserved_allocations(order_item=item.order_item, quantity=quantity, warehouse=source_warehouse)
                _set_reservation_item_progress(item, released_delta=quantity)
    recompute_reservation_status(reservation)


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
            if all(item.received_quantity >= item.active_quantity for item in linked_purchase_items):
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
        existing_reserved[item.order_item_id] += int(item.active_reserved_quantity or 0)

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
            remaining = max(order_item.active_quantity - existing_reserved[order_item.id], 0)
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
        remaining = max(order_item.active_quantity - existing_reserved[order_item.id], 0)
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
        'reservations': [],
    }


def _bitrix_order_item_has_manual_product_link(order_item):
    metadata = dict(order_item.metadata or {})
    return bool(
        metadata.get('manual_link')
        or metadata.get('manual_product_link')
        or metadata.get('manual_catalog_link_history')
    )


def _merge_bitrix_order_item_metadata(order_item, payload_metadata):
    metadata = dict(order_item.metadata or {})
    metadata.update(payload_metadata or {})
    return metadata


def _apply_bitrix_payload_to_existing_order_item(order_item, payload, *, warnings):
    existing_has_catalog_link = bool(
        order_item.line_type == OrderItem.LINE_TYPE_CATALOG
        and order_item.product_id
    )
    has_manual_product_link = _bitrix_order_item_has_manual_product_link(order_item)
    payload_product = payload.get('product')
    payload_variant = payload.get('variant')
    payload_is_catalog = bool(
        payload.get('line_type') == OrderItem.LINE_TYPE_CATALOG
        and payload_product is not None
    )
    metadata = _merge_bitrix_order_item_metadata(order_item, payload.get('metadata'))

    resolved_line_type = payload['line_type']
    resolved_product = payload_product
    resolved_variant = payload_variant
    resolved_custom_sku = payload['custom_sku']
    resolved_product_image_url = payload['product_image_url']

    if existing_has_catalog_link and not payload_is_catalog:
        resolved_line_type = order_item.line_type
        resolved_product = order_item.product
        resolved_variant = order_item.variant
        resolved_custom_sku = ''
        resolved_product_image_url = order_item.product_image_url
    elif payload_is_catalog and has_manual_product_link and order_item.product_id:
        if payload_product.id != order_item.product_id:
            warnings.append(
                'Bitrix import сохранил ручную catalog-связку '
                f'для строки #{order_item.id}: сайт связал её с товаром #{order_item.product_id}, '
                f'а Bitrix предложил товар #{payload_product.id}.'
            )
            resolved_line_type = order_item.line_type
            resolved_product = order_item.product
            resolved_variant = order_item.variant
            resolved_custom_sku = ''
            resolved_product_image_url = order_item.product_image_url
        else:
            resolved_line_type = order_item.line_type
            resolved_product = order_item.product
            resolved_variant = order_item.variant or payload_variant
            resolved_custom_sku = ''
            resolved_product_image_url = order_item.product_image_url or payload['product_image_url']

    return {
        'line_type': resolved_line_type,
        'product': resolved_product,
        'variant': resolved_variant,
        'product_name': payload['product_name'],
        'custom_sku': resolved_custom_sku,
        'product_image_url': resolved_product_image_url,
        'quantity': payload['quantity'],
        'price': payload['price'],
        'variant_name': payload['variant_name'],
        'condition': payload['condition'],
        'purchase_price': payload['planned_unit_cost'],
        'planned_unit_cost': payload['planned_unit_cost'],
        'cost_status': OrderItem.COST_STATUS_NONE,
        'discount_amount': payload['discount_amount'],
        'comment': payload['comment'],
        'is_on_request': payload['is_on_request'],
        'metadata': metadata,
    }


@transaction.atomic
def sync_bitrix_deal_into_operations(deal_id, *, actor=None):
    normalized_deal_id, deal_data, product_rows = _load_bitrix_deal_payload(deal_id)
    mapped_payload = _bitrix_deal_mapped_payload(deal_data)
    warnings = []
    contact_data = {}
    company_data = {}
    contact_id = _bitrix_optional_entity_id(deal_data.get('CONTACT_ID'))
    company_id = _bitrix_optional_entity_id(deal_data.get('COMPANY_ID'))
    if contact_id:
        contact_data = _bitrix_optional_request(
            'crm.contact.get',
            params={'id': contact_id},
            entity_label='контакт',
            entity_id=contact_id,
            warnings=warnings,
        )
    if company_id:
        company_data = _bitrix_optional_request(
            'crm.company.get',
            params={'id': company_id},
            entity_label='компания',
            entity_id=company_id,
            warnings=warnings,
        )

    contact = _bitrix_contact_payload(contact_data, company_data)
    available_map = _bitrix_inventory_available_map()
    bitrix_product_cache = {}
    item_payloads = [
        _prepare_bitrix_order_item_payload(
            row,
            index=index,
            available_map=available_map,
            bitrix_product_cache=bitrix_product_cache,
        )
        for index, row in enumerate(product_rows, start=1)
    ]
    if not item_payloads:
        fallback_price = _bitrix_decimal(deal_data.get('OPPORTUNITY'), default='0')
        item_payloads.append(
            {
                'row_key': f'deal:{normalized_deal_id}:fallback',
                'line_type': OrderItem.LINE_TYPE_CUSTOM,
                'product': None,
                'variant': None,
                'product_name': _bitrix_text(deal_data.get('TITLE')) or f'Сделка Bitrix #{normalized_deal_id}',
                'variant_name': '',
                'custom_sku': '',
                'price': fallback_price,
                'discount_amount': MONEY_ZERO,
                'quantity': 1,
                'planned_unit_cost': MONEY_ZERO,
                'product_image_url': '',
                'condition': OrderItem.CONDITION_NEW,
                'comment': '',
                'is_on_request': True,
                'metadata': {
                    'bitrix_row_key': f'deal:{normalized_deal_id}:fallback',
                    'bitrix_product_name': _bitrix_text(deal_data.get('TITLE')),
                },
            }
        )

    goods_total = sum(
        (max(item['price'] - item['discount_amount'], MONEY_ZERO) * Decimal(item['quantity']) for item in item_payloads),
        MONEY_ZERO,
    )
    created_at = _bitrix_parse_datetime(deal_data.get('DATE_CREATE') or deal_data.get('BEGINDATE')) or timezone.now()
    deal_url = build_bitrix_deal_url(normalized_deal_id)
    order_comment_payload = _bitrix_deal_comment_payload(
        comment=deal_data.get('COMMENTS'),
        client_request=mapped_payload['client_request'],
    )
    manager_client_comments = _bitrix_manager_client_comments(
        deal_id=normalized_deal_id,
        client_request=mapped_payload['client_request'],
    )
    fallback_client_name = _bitrix_text(deal_data.get('TITLE')) or f'Клиент Bitrix #{normalized_deal_id}'
    recipient_name = mapped_payload['recipient_name'] or contact['company_name'] or contact['full_name'] or fallback_client_name
    address = mapped_payload['delivery_address'] or contact['address']
    city = mapped_payload['city'] or contact['city']
    contact_phone = normalize_phone(contact['phone']) or contact['phone']
    recipient_phone = normalize_phone(mapped_payload['recipient_phone']) or mapped_payload['recipient_phone']
    phone = contact_phone or recipient_phone
    email = normalize_email(contact['email']) or contact['email']
    first_name = _bitrix_text((contact_data or {}).get('NAME'))
    last_name = _bitrix_text((contact_data or {}).get('LAST_NAME'))
    delivery_type = _bitrix_delivery_type(address)
    order_payment_method = Order.PAYMENT_METHOD_MANAGER_PAYMENT if contact['is_business'] else Order.PAYMENT_METHOD_ONLINE

    manager_deal = ManagerDeal.objects.select_related('order').filter(bitrix_deal_id=normalized_deal_id).first()
    order = manager_deal.order if manager_deal is not None else None
    if order is None:
        order = Order.objects.create(
            user=None,
            status=Order.STATUS_CONFIRMED,
            total=goods_total,
            promo_discount=MONEY_ZERO,
            payment_method=order_payment_method,
            contact_channel=Order.CONTACT_CHANNEL_EMAIL if email and not phone else Order.CONTACT_CHANNEL_CALL,
            contact_handle=email if email and not phone else '',
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=delivery_type,
            phone=phone,
            email=email,
            first_name=first_name,
            last_name=last_name,
            recipient_name=recipient_name,
            recipient_phone=recipient_phone or phone,
            recipient_is_customer=True,
            country='Россия',
            city_text=city,
            address_line=address,
            delivery_comment=order_comment_payload['delivery_comment'],
            address=address,
            business_company_name=contact['company_name'],
            business_inn=contact['inn'],
            business_kpp=contact['kpp'],
            business_phone=phone if contact['is_business'] else '',
            delivery_cost=MONEY_ZERO,
            comment=order_comment_payload['comment'],
        )
    else:
        order_updates = {
            'status': Order.STATUS_CONFIRMED,
            'total': goods_total,
            'payment_method': order_payment_method,
            'contact_channel': Order.CONTACT_CHANNEL_EMAIL if email and not phone else Order.CONTACT_CHANNEL_CALL,
            'contact_handle': email if email and not phone else '',
            'payment_status': Order.PAYMENT_STATUS_PAID,
            'delivery_type': delivery_type,
            'phone': phone,
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
            'recipient_name': recipient_name,
            'recipient_phone': recipient_phone or phone,
            'city_text': city,
            'address_line': address,
            'delivery_comment': order_comment_payload['delivery_comment'],
            'address': address,
            'business_company_name': contact['company_name'],
            'business_inn': contact['inn'],
            'business_kpp': contact['kpp'],
            'business_phone': phone if contact['is_business'] else '',
            'comment': order_comment_payload['comment'],
        }
        update_fields = []
        for field, value in order_updates.items():
            if getattr(order, field) != value:
                setattr(order, field, value)
                update_fields.append(field)
        if update_fields:
            order.save(update_fields=[*update_fields, 'updated_at'])

    if order.created_at != created_at:
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        order.refresh_from_db()

    existing_items = {
        _bitrix_text((item.metadata or {}).get('bitrix_row_key')): item
        for item in order.items.select_related('product', 'variant').all()
    }
    created_items = 0
    updated_items = 0
    for payload in item_payloads:
        row_key = payload['row_key']
        order_item = existing_items.get(row_key)
        item_fields = {
            'line_type': payload['line_type'],
            'product': payload['product'],
            'variant': payload['variant'],
            'product_name': payload['product_name'],
            'custom_sku': payload['custom_sku'],
            'product_image_url': payload['product_image_url'],
            'quantity': payload['quantity'],
            'price': payload['price'],
            'variant_name': payload['variant_name'],
            'condition': payload['condition'],
            'purchase_price': payload['planned_unit_cost'],
            'planned_unit_cost': payload['planned_unit_cost'],
            'cost_status': OrderItem.COST_STATUS_NONE,
            'discount_amount': payload['discount_amount'],
            'comment': payload['comment'],
            'is_on_request': payload['is_on_request'],
            'metadata': payload['metadata'],
        }
        if order_item is None:
            OrderItem.objects.create(order=order, **item_fields)
            created_items += 1
            continue

        item_fields = _apply_bitrix_payload_to_existing_order_item(
            order_item,
            payload,
            warnings=warnings,
        )
        update_fields = []
        for field, value in item_fields.items():
            if getattr(order_item, field) != value:
                setattr(order_item, field, value)
                update_fields.append(field)
        if update_fields:
            order_item.save(update_fields=update_fields)
            updated_items += 1

    client_resolution = resolve_manager_client(
        user=order.user,
        name=recipient_name or fallback_client_name,
        phone=recipient_phone,
        email=email,
        address=address,
        comments=manager_client_comments,
        order=order,
    )
    imported_deal = ensure_manager_deal_for_order(
        order,
        customer_source=ManagerDeal.SOURCE_OTHER,
    )
    deal_update_fields = []
    if imported_deal.bitrix_deal_id != normalized_deal_id:
        imported_deal.bitrix_deal_id = normalized_deal_id
        deal_update_fields.append('bitrix_deal_id')
    if imported_deal.bitrix_deal_url != deal_url:
        imported_deal.bitrix_deal_url = deal_url
        deal_update_fields.append('bitrix_deal_url')
    if imported_deal.customer_source != ManagerDeal.SOURCE_OTHER:
        imported_deal.customer_source = ManagerDeal.SOURCE_OTHER
        deal_update_fields.append('customer_source')
    if imported_deal.deal_created_at != created_at:
        imported_deal.deal_created_at = created_at
        deal_update_fields.append('deal_created_at')
    if deal_update_fields:
        imported_deal.save(update_fields=[*deal_update_fields, 'updated_at'])

    record_deal_activity(
        imported_deal,
        event_type='bitrix.imported',
        source=DealActivity.SOURCE_SYSTEM,
        actor=actor,
        payload={
            'bitrix_deal_id': normalized_deal_id,
            'created_items': created_items,
            'updated_items': updated_items,
            'item_count': len(item_payloads),
        },
    )
    recompute_deal_workflow(imported_deal, actor=actor)
    return {
        'order': order,
        'order_item_count': len(item_payloads),
        'manager_client': client_resolution['client'],
        'manager_deal': imported_deal,
        'created_items': created_items,
        'updated_items': updated_items,
        'warnings': warnings,
    }


def import_bitrix_deal_into_operations(deal_id, *, actor=None):
    return sync_bitrix_deal_into_operations(deal_id, actor=actor)


def _shipment_target_status_from_order(order):
    if order is not None and order.status == Order.STATUS_DONE:
        return Shipment.STATUS_DELIVERED
    return Shipment.STATUS_SHIPPED


def _normalize_shipment_event_dt(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def dispatch_shipment(shipment, *, author=None, comment=''):
    shipment = Shipment.objects.select_related(
        'order',
        'reservation',
        'source_warehouse',
        'manager_deal',
    ).get(pk=shipment.pk)
    if shipment.inventory_consumed_at is not None:
        return shipment
    if shipment.status == Shipment.STATUS_CANCELLED:
        raise ValueError('Нельзя провести складской эффект для отмененной отгрузки.')
    source_warehouse = shipment.source_warehouse or (
        reservation_effective_warehouse(shipment.reservation) if shipment.reservation_id else None
    )
    if source_warehouse is None:
        raise ValueError('У отгрузки не указан склад-источник.')
    shipment_items = list(
        shipment.items.select_related('order_item', 'reservation_item__reservation', 'product', 'variant').all()
    )
    if not shipment_items:
        raise ValueError('Нельзя провести пустую отгрузку.')
    touched_order_items = {}
    touched_reservations = {}
    with transaction.atomic():
        locked_shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if locked_shipment.inventory_consumed_at is not None:
            return locked_shipment
        for shipment_item in shipment_items:
            quantity = int(shipment_item.quantity or 0)
            if quantity <= 0:
                continue
            order_item = shipment_item.order_item
            reservation_item = shipment_item.reservation_item
            if order_item is None and reservation_item is not None:
                order_item = reservation_item.order_item
            if reservation_item is not None:
                open_reserved = int(reservation_item.active_reserved_quantity or 0)
                if quantity > open_reserved:
                    raise ValueError('Количество в отгрузке превышает доступный остаток брони.')
            if order_item is not None:
                already_shipped = int(order_item.shipped_quantity or 0)
                remaining_shippable = max(int(order_item.active_quantity or 0) - already_shipped, 0)
                if quantity > remaining_shippable:
                    raise ValueError(f'Отгрузка превышает доступное количество для "{order_item.display_name}".')
                release_reserved_allocations(
                    order_item=order_item,
                    quantity=quantity,
                    warehouse=source_warehouse,
                )
                allocate_inventory_to_order_item(
                    order_item=order_item,
                    warehouse=source_warehouse,
                    quantity=quantity,
                    mode=SaleLineAllocation.STATUS_SHIPPED,
                )
                touched_order_items[order_item.pk] = order_item
            else:
                _consume_lots_without_allocation(
                    warehouse=source_warehouse,
                    product=shipment_item.product,
                    variant=shipment_item.variant,
                    quantity=quantity,
                )
            if reservation_item is not None:
                _set_reservation_item_progress(reservation_item, fulfilled_delta=quantity)
                touched_reservations[reservation_item.reservation_id] = reservation_item.reservation
            InventoryMovement.objects.create(
                warehouse=source_warehouse,
                product=shipment_item.product,
                variant=shipment_item.variant,
                movement_type=InventoryMovement.TYPE_RELEASE,
                quantity=quantity,
                reference_type='shipment',
                reference_id=locked_shipment.id,
                comment=comment or 'Списание по отгрузке',
                author=author,
            )
        rebuild_inventory_balance_cache(warehouse_ids=[source_warehouse.id])
        sync_public_stock_for_warehouse(source_warehouse)
        for order_item in touched_order_items.values():
            sync_order_item_actual_cost(order_item)
        for reservation in touched_reservations.values():
            recompute_reservation_status(reservation)
        locked_shipment.inventory_consumed_at = timezone.now()
        target_status = _shipment_target_status_from_order(locked_shipment.order)
        locked_shipment.status = target_status
        if not locked_shipment.shipped_at:
            locked_shipment.shipped_at = locked_shipment.inventory_consumed_at
        if target_status == Shipment.STATUS_DELIVERED and not locked_shipment.delivered_at:
            locked_shipment.delivered_at = locked_shipment.inventory_consumed_at
        locked_shipment.save(update_fields=['inventory_consumed_at', 'status', 'shipped_at', 'delivered_at', 'updated_at'])
        if locked_shipment.order_id and not locked_shipment.order.stock_decreased:
            locked_shipment.order.stock_decreased = True
            locked_shipment.order.save(update_fields=['stock_decreased'])
    if locked_shipment.manager_deal_id:
        recompute_deal_workflow(locked_shipment.manager_deal, actor=author)
    return locked_shipment


def ship_shipment(
    shipment,
    *,
    author=None,
    carrier='',
    tracking_number='',
    shipped_at=None,
    comment='',
):
    shipment = Shipment.objects.select_related('manager_deal').get(pk=shipment.pk)
    if shipment.status == Shipment.STATUS_CANCELLED:
        raise ValueError('Нельзя отправить отмененную отгрузку.')
    if shipment.inventory_consumed_at is not None or shipment.status in {
        Shipment.STATUS_SHIPPED,
        Shipment.STATUS_DELIVERED,
    }:
        raise ValueError('Эта отгрузка уже отправлена.')

    normalized_carrier = (carrier or '').strip()
    normalized_tracking_number = (tracking_number or '').strip()
    normalized_comment = (comment or '').strip()
    normalized_shipped_at = _normalize_shipment_event_dt(shipped_at)
    if not normalized_tracking_number:
        raise ValueError('Укажите трек-номер отгрузки.')

    update_fields = []
    if shipment.delivery_provider_name != normalized_carrier:
        shipment.delivery_provider_name = normalized_carrier
        update_fields.append('delivery_provider_name')
    if shipment.tracking_number != normalized_tracking_number:
        shipment.tracking_number = normalized_tracking_number
        update_fields.append('tracking_number')
    if shipment.comments != normalized_comment:
        shipment.comments = normalized_comment
        update_fields.append('comments')
    if update_fields:
        shipment.save(update_fields=update_fields + ['updated_at'])

    dispatched = dispatch_shipment(
        shipment,
        author=author,
        comment=normalized_comment or f'Списание по отгрузке {normalized_tracking_number}',
    )

    update_fields = []
    if normalized_carrier != dispatched.delivery_provider_name:
        dispatched.delivery_provider_name = normalized_carrier
        update_fields.append('delivery_provider_name')
    if normalized_tracking_number != dispatched.tracking_number:
        dispatched.tracking_number = normalized_tracking_number
        update_fields.append('tracking_number')
    if normalized_comment != dispatched.comments:
        dispatched.comments = normalized_comment
        update_fields.append('comments')
    if normalized_shipped_at is not None and dispatched.shipped_at != normalized_shipped_at:
        dispatched.shipped_at = normalized_shipped_at
        update_fields.append('shipped_at')
        if dispatched.inventory_consumed_at != normalized_shipped_at:
            dispatched.inventory_consumed_at = normalized_shipped_at
            update_fields.append('inventory_consumed_at')
    if update_fields:
        dispatched.save(update_fields=update_fields + ['updated_at'])

    if dispatched.manager_deal_id:
        record_deal_activity(
            dispatched.manager_deal,
            event_type='shipment.dispatched',
            source=DealActivity.SOURCE_USER if author else DealActivity.SOURCE_SYSTEM,
            actor=author,
            payload={
                'shipment_id': dispatched.id,
                'carrier': dispatched.delivery_provider_name,
                'tracking_number': dispatched.tracking_number,
            },
        )
    return dispatched


def mark_shipment_delivered(shipment, *, author=None, delivered_at=None):
    shipment = Shipment.objects.select_related('manager_deal').get(pk=shipment.pk)
    if shipment.status == Shipment.STATUS_CANCELLED:
        raise ValueError('Нельзя отметить доставку для отмененной отгрузки.')
    if shipment.inventory_consumed_at is None and shipment.status not in {
        Shipment.STATUS_SHIPPED,
        Shipment.STATUS_DELIVERED,
    }:
        raise ValueError('Сначала отправьте отгрузку.')

    normalized_delivered_at = _normalize_shipment_event_dt(delivered_at) or timezone.now()
    with transaction.atomic():
        locked_shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if locked_shipment.status == Shipment.STATUS_CANCELLED:
            raise ValueError('Нельзя отметить доставку для отмененной отгрузки.')
        update_fields = []
        if locked_shipment.status != Shipment.STATUS_DELIVERED:
            locked_shipment.status = Shipment.STATUS_DELIVERED
            update_fields.append('status')
        if locked_shipment.delivered_at != normalized_delivered_at:
            locked_shipment.delivered_at = normalized_delivered_at
            update_fields.append('delivered_at')
        if not locked_shipment.shipped_at:
            locked_shipment.shipped_at = normalized_delivered_at
            update_fields.append('shipped_at')
        if locked_shipment.inventory_consumed_at is None:
            locked_shipment.inventory_consumed_at = locked_shipment.shipped_at or normalized_delivered_at
            update_fields.append('inventory_consumed_at')
        if update_fields:
            locked_shipment.save(update_fields=update_fields + ['updated_at'])

        deal = shipment.manager_deal
        if deal is not None:
            remaining_shipments = deal.shipments.exclude(status=Shipment.STATUS_CANCELLED).exclude(
                status=Shipment.STATUS_DELIVERED
            )
            if not remaining_shipments.exists() and deal.case_status != ManagerDeal.CASE_STATUS_COMPLETED:
                deal.case_status = ManagerDeal.CASE_STATUS_COMPLETED
                deal.save(update_fields=['case_status', 'updated_at'])

    if locked_shipment.manager_deal_id:
        record_deal_activity(
            locked_shipment.manager_deal,
            event_type='shipment.delivered',
            source=DealActivity.SOURCE_USER if author else DealActivity.SOURCE_SYSTEM,
            actor=author,
            payload={'shipment_id': locked_shipment.id},
        )
        recompute_deal_workflow(locked_shipment.manager_deal, actor=author)
    return locked_shipment


def cancel_shipment(shipment, *, author=None, comment=''):
    shipment = Shipment.objects.select_related('reservation', 'manager_deal').get(pk=shipment.pk)
    if shipment.inventory_consumed_at is not None or shipment.status in {
        Shipment.STATUS_SHIPPED,
        Shipment.STATUS_DELIVERED,
    }:
        raise ValueError('Можно отменить только неподтвержденную отгрузку до списания склада.')
    if shipment.status == Shipment.STATUS_CANCELLED:
        return shipment

    normalized_comment = (comment or '').strip()
    reservation = shipment.reservation
    reservation_items = []
    effective_warehouse = reservation_effective_warehouse(reservation) if reservation is not None else None
    if reservation is not None:
        reservation_item_ids = list(
            shipment.items.filter(reservation_item__isnull=False).values_list('reservation_item_id', flat=True)
        )
        reservation_items = list(reservation.items.filter(id__in=reservation_item_ids).select_related('product', 'variant'))

    with transaction.atomic():
        locked_shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if locked_shipment.status == Shipment.STATUS_CANCELLED:
            return locked_shipment
        if reservation is not None and reservation_items:
            create_or_update_reservation_movements(
                reservation,
                movement_type=InventoryMovement.TYPE_RELEASE,
                author=author,
                comment=normalized_comment or 'Снятие резерва при отмене отгрузки.',
                items=reservation_items,
            )
        locked_shipment.status = Shipment.STATUS_CANCELLED
        update_fields = ['status']
        if normalized_comment and locked_shipment.comments != normalized_comment:
            locked_shipment.comments = normalized_comment
            update_fields.append('comments')
        locked_shipment.save(update_fields=update_fields + ['updated_at'])

    if effective_warehouse is not None:
        sync_public_stock_for_warehouse(effective_warehouse)
    if locked_shipment.manager_deal_id:
        record_deal_activity(
            locked_shipment.manager_deal,
            event_type='shipment.cancelled',
            source=DealActivity.SOURCE_USER if author else DealActivity.SOURCE_SYSTEM,
            actor=author,
            payload={'shipment_id': locked_shipment.id},
        )
        recompute_deal_workflow(locked_shipment.manager_deal, actor=author)
    return locked_shipment


def fulfill_reservation(reservation, *, author=None, comment='', shipment=None):
    if shipment is None:
        raise ValueError('Прямое исполнение брони без shipment больше не поддерживается.')
    if shipment.reservation_id and shipment.reservation_id != reservation.id:
        raise ValueError('Shipment не связан с этой бронью.')
    if shipment.reservation_id is None:
        shipment.reservation = reservation
        shipment.source_warehouse = shipment.source_warehouse or reservation_effective_warehouse(reservation)
        shipment.save(update_fields=['reservation', 'source_warehouse', 'updated_at'])
    return dispatch_shipment(shipment, author=author, comment=comment)


def release_order_reservations(order, *, author=None, comment='Снятие резерва по отмене заказа сайта.'):
    reservations = list(
        order.manager_reservations.filter(status__in=ACTIVE_RESERVATION_STATUSES)
        .select_related('source_warehouse', 'source_cargo__destination_warehouse')
        .order_by('id')
    )
    if not reservations:
        return []

    touched_warehouse_ids = set()
    released_ids = []
    for reservation in reservations:
        warehouse = reservation_effective_warehouse(reservation)
        create_or_update_reservation_movements(
            reservation,
            movement_type=InventoryMovement.TYPE_RELEASE,
            author=author,
            comment=comment,
        )
        reservation.status = Reservation.STATUS_CANCELLED
        reservation.save(update_fields=['status', 'updated_at'])
        if warehouse is not None:
            touched_warehouse_ids.add(warehouse.pk)
        released_ids.append(reservation.pk)

    for warehouse_id in touched_warehouse_ids:
        sync_public_stock_for_warehouse(Warehouse.objects.get(pk=warehouse_id))

    try:
        deal = order.manager_deal
    except ManagerDeal.DoesNotExist:
        deal = None
    if deal is not None:
        update_fields = []
        if deal.primary_reservation_id in released_ids:
            deal.primary_reservation = None
            update_fields.append('primary_reservation')
        if update_fields:
            deal.save(update_fields=update_fields + ['updated_at'])
        recompute_deal_workflow(deal, actor=author)

    return reservations


def consume_inventory_for_order(order, *, author=None):
    return False


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
        'status': Shipment.STATUS_PENDING,
        'comments': (deal.shipping_comment if deal is not None else '') or order.delivery_comment or '',
    }
    if shipment is None:
        shipment, _ = Shipment.objects.get_or_create(order=order, defaults=defaults)
    else:
        shipment = Shipment.objects.get(pk=shipment.pk)
    update_fields = []
    if shipment.inventory_consumed_at is None and shipment.status in {Shipment.STATUS_SHIPPED, Shipment.STATUS_DELIVERED}:
        if tracking_number and shipment.tracking_number != tracking_number:
            shipment.tracking_number = tracking_number
            update_fields.append('tracking_number')
        if defaults['comments'] and shipment.comments != defaults['comments']:
            shipment.comments = defaults['comments']
            update_fields.append('comments')
        if update_fields:
            shipment.save(update_fields=update_fields + ['updated_at'])
        if deal is not None:
            recompute_deal_workflow(deal, actor=author)
        return shipment
    if shipment.inventory_consumed_at is not None:
        if tracking_number and shipment.tracking_number != tracking_number:
            shipment.tracking_number = tracking_number
            update_fields.append('tracking_number')
        if defaults['comments'] and shipment.comments != defaults['comments']:
            shipment.comments = defaults['comments']
            update_fields.append('comments')
        if order.status == Order.STATUS_DONE and shipment.status == Shipment.STATUS_SHIPPED:
            shipment.status = Shipment.STATUS_DELIVERED
            update_fields.append('status')
            if not shipment.delivered_at:
                shipment.delivered_at = timezone.now()
                update_fields.append('delivered_at')
        if update_fields:
            shipment.save(update_fields=update_fields + ['updated_at'])
        if deal is not None:
            recompute_deal_workflow(deal, actor=author)
        return shipment

    for field, value in defaults.items():
        if field == 'status':
            continue
        if getattr(shipment, field) != value and value not in (None, ''):
            setattr(shipment, field, value)
            update_fields.append(field)
    if shipment.status not in {Shipment.STATUS_CANCELLED, Shipment.STATUS_PENDING}:
        shipment.status = Shipment.STATUS_PENDING
        update_fields.append('status')
    if tracking_number and shipment.tracking_number != tracking_number:
        shipment.tracking_number = tracking_number
        update_fields.append('tracking_number')
    if update_fields:
        shipment.save(update_fields=update_fields + ['updated_at'])

    ShipmentItem.objects.filter(shipment=shipment).delete()
    if reservation:
        for reservation_item in reservation.items.select_related('product', 'variant', 'order_item'):
            quantity = int(reservation_item.active_reserved_quantity or 0)
            if quantity <= 0:
                continue
            ShipmentItem.objects.create(
                shipment=shipment,
                order_item=reservation_item.order_item,
                reservation_item=reservation_item,
                product=reservation_item.product,
                variant=reservation_item.variant,
                quantity=quantity,
            )
    else:
        for order_item in order.items.select_related('product', 'variant'):
            if not order_item.product_id:
                continue
            quantity = max(int(order_item.active_quantity or 0) - int(order_item.shipped_quantity or 0), 0)
            if quantity <= 0:
                continue
            ShipmentItem.objects.create(
                shipment=shipment,
                order_item=order_item,
                product=order_item.product,
                variant=order_item.variant,
                quantity=quantity,
            )
    if deal is not None:
        recompute_deal_workflow(deal, actor=author)
    return shipment


def sync_order_workflow_state(order, *, author=None, previous_status=None):
    deal = ensure_manager_deal_for_order(order)
    if order.status in {Order.STATUS_SHIPPING, Order.STATUS_DONE}:
        shipments = list(order.manager_shipments.exclude(status=Shipment.STATUS_CANCELLED).order_by('id'))
        if not shipments:
            shipments = [create_or_update_shipment_for_order(order, author=author)]
        elif len(shipments) == 1:
            shipments = [create_or_update_shipment_for_order(order, author=author, shipment=shipments[0])]
        if (
            previous_status != order.status
            and len(shipments) == 1
            and shipments[0].status in {Shipment.STATUS_DRAFT, Shipment.STATUS_PENDING}
            and shipments[0].inventory_consumed_at is None
        ):
            dispatch_candidate = shipments[0]
            dispatch_source = dispatch_candidate.source_warehouse or (
                reservation_effective_warehouse(dispatch_candidate.reservation)
                if dispatch_candidate.reservation_id
                else None
            )
            if dispatch_source and dispatch_candidate.items.exists():
                dispatch_shipment(dispatch_candidate, author=author, comment='Автодиспатч по смене статуса заказа.')
    recompute_deal_workflow(deal, actor=author)


def _normalize_received_at(received_at):
    if received_at is None:
        return timezone.now()
    if isinstance(received_at, date) and not isinstance(received_at, datetime):
        received_at = datetime.combine(received_at, time.min)
    if timezone.is_naive(received_at):
        return timezone.make_aware(received_at, timezone.get_current_timezone())
    return received_at


def receive_cargo_item(cargo_item, *, quantity, author=None, comment='', warehouse=None, received_at=None):
    receipt_warehouse = warehouse or cargo_item.cargo.destination_warehouse
    if not receipt_warehouse:
        raise ValueError('У груза не указан склад назначения.')
    quantity = int(quantity or 0)
    if quantity <= 0:
        raise ValueError('Количество для приемки должно быть больше нуля.')
    if quantity > cargo_item.remaining_quantity:
        raise ValueError('Нельзя принять больше, чем осталось в грузе.')
    effective_received_at = _normalize_received_at(received_at)
    with transaction.atomic():
        cargo = cargo_item.cargo
        if cargo.destination_warehouse_id != receipt_warehouse.id:
            cargo.destination_warehouse = receipt_warehouse
            cargo.save(update_fields=['destination_warehouse', 'updated_at'])

        cargo_item.received_quantity += quantity
        cargo_item.save(update_fields=['received_quantity'])
        if cargo_item.purchase_item_id:
            purchase_item = cargo_item.purchase_item
            purchase_item.received_quantity = min(
                purchase_item.received_quantity + quantity,
                purchase_item.active_quantity,
            )
            purchase_item.received_at = effective_received_at
            purchase_item.save(update_fields=['received_quantity', 'received_at'])
            purchase = purchase_item.purchase
            linked_purchase_items = list(purchase.items.all())
            if linked_purchase_items:
                if all(item.received_quantity >= item.active_quantity for item in linked_purchase_items):
                    purchase_status = Purchase.STATUS_RECEIVED
                elif any(int(item.received_quantity or 0) > 0 for item in linked_purchase_items):
                    purchase_status = Purchase.STATUS_PARTIAL
                else:
                    purchase_status = purchase.status
                if purchase.status != purchase_status:
                    purchase.status = purchase_status
                    purchase.save(update_fields=['status', 'updated_at'])
        receipt_inventory(
            warehouse=receipt_warehouse,
            product=cargo_item.product,
            variant=cargo_item.variant,
            quantity=quantity,
            author=author,
            comment=comment or f'Приемка по грузу {cargo.cargo_number}',
            reference_type='cargo',
            reference_id=cargo_item.cargo_id,
            unit_cost=cargo_item.purchase_item.unit_cost if cargo_item.purchase_item_id else Decimal('0'),
            purchase_item=cargo_item.purchase_item if cargo_item.purchase_item_id else None,
            received_at=effective_received_at,
        )
        order_item = cargo_item.purchase_item.order_item if cargo_item.purchase_item_id else None
        if order_item is not None:
            sync_order_item_planned_cost(order_item)
            deal = ManagerDeal.objects.filter(order=order_item.order).first()
            if deal and deal.stock_warehouse_id != receipt_warehouse.id:
                deal.stock_warehouse = receipt_warehouse
                deal.save(update_fields=['stock_warehouse', 'updated_at'])
        has_remaining_items = cargo.items.filter(quantity__gt=models.F('received_quantity')).exists()
        next_status = Cargo.STATUS_AWAITING_RECEIPT if has_remaining_items else Cargo.STATUS_RECEIVED
        if cargo.status != next_status:
            cargo.status = next_status
            cargo.save(update_fields=['status', 'updated_at'])
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


def _dashboard_bucket_rows(active_deals):
    buckets = {
        'needs_review': {'code': 'needs_review', 'label': 'Нужно разобрать', 'count': 0},
        'needs_procurement': {'code': 'needs_procurement', 'label': 'Нужно закупить', 'count': 0},
        'partially_covered': {'code': 'partially_covered', 'label': 'Частично обеспечено', 'count': 0},
        'in_transit': {'code': 'in_transit', 'label': 'В пути', 'count': 0},
        'partially_arrived': {'code': 'partially_arrived', 'label': 'Частично приехало', 'count': 0},
        'ready_to_ship': {'code': 'ready_to_ship', 'label': 'Готово к отправке', 'count': 0},
        'problems': {'code': 'problems', 'label': 'Проблемы', 'count': 0},
    }
    for deal in active_deals:
        snapshot = order_supply_state_snapshot(deal.order)
        lines = snapshot['lines']
        covered_count = (
            snapshot['covered_by_stock_count']
            + snapshot['covered_by_incoming_count']
            + snapshot['covered_by_procurement_count']
        )
        has_partial_coverage = snapshot['uncovered_count'] > 0 and covered_count > 0
        has_in_transit = any(
            int(line.get('cargo_quantity') or 0) > int(line.get('cargo_received_quantity') or 0)
            for line in lines
        )
        has_partial_arrival = any(
            (
                0 < int(line.get('purchase_received_quantity') or 0) < int(line.get('purchase_quantity') or 0)
            )
            or (
                0 < int(line.get('cargo_received_quantity') or 0) < int(line.get('cargo_quantity') or 0)
            )
            for line in lines
        )

        if deal.case_status == ManagerDeal.CASE_STATUS_NEW or deal.next_step_code in {
            ManagerDeal.NEXT_STEP_NEEDS_CONFIRMATION,
            ManagerDeal.NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION,
        }:
            buckets['needs_review']['count'] += 1
        if deal.next_step_code == ManagerDeal.NEXT_STEP_NEEDS_PROCUREMENT or snapshot['uncovered_count'] > 0:
            buckets['needs_procurement']['count'] += 1
        if has_partial_coverage:
            buckets['partially_covered']['count'] += 1
        if has_in_transit:
            buckets['in_transit']['count'] += 1
        if has_partial_arrival:
            buckets['partially_arrived']['count'] += 1
        if deal.case_status == ManagerDeal.CASE_STATUS_READY_TO_SHIP or deal.next_step_code == ManagerDeal.NEXT_STEP_READY_TO_SHIP:
            buckets['ready_to_ship']['count'] += 1
        if deal.problem_flags:
            buckets['problems']['count'] += 1
    return list(buckets.values())


def dashboard_stats():
    inventory_rows = inventory_snapshot()
    active_deals = list(
        ManagerDeal.objects.select_related('order', 'responsible_manager')
        .exclude(case_status__in=[ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_CANCELLED])
        .order_by(
            models.F('sla_due_at').asc(nulls_last=True),
            models.F('last_activity_at').desc(nulls_last=True),
            '-deal_created_at',
            '-id',
        )
    )
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
        'operations_buckets': _dashboard_bucket_rows(active_deals),
        'problem_deals': [deal for deal in active_deals if deal.problem_flags][:6],
        'ready_deals': [
            deal for deal in active_deals
            if deal.case_status == ManagerDeal.CASE_STATUS_READY_TO_SHIP or deal.next_step_code == ManagerDeal.NEXT_STEP_READY_TO_SHIP
        ][:6],
        'active_deals_total': len(active_deals),
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
    ).prefetch_related('shares')
    expenses = FinanceExpense.objects.filter(date__gte=start, date__lt=end).select_related('category', 'deal', 'created_by')
    payouts = FinancePayout.objects.filter(date__gte=start, date__lt=end).select_related('created_by')

    turnover = _sum_decimal(deals, 'revenue')
    cost_of_goods = _sum_decimal(deals, 'cost_of_goods')
    distributable_profit_total = _sum_decimal(deals, 'distributable_profit')
    gross_profit_total = _quantize_money(turnover - cost_of_goods)
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
    net_profit = distributable_profit_total - total_opex_display
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
    participant_groups = {}
    for deal in deals:
        for share in deal.shares.all():
            participant_label = share.participant_name_snapshot or (share.participant_alias.display_name if share.participant_alias_id else 'Неизвестный участник')
            group = participant_groups.setdefault(
                participant_label,
                {
                    'participant': participant_label,
                    'amount': MONEY_ZERO,
                    'deal_count': 0,
                    'deals': [],
                },
            )
            group['amount'] += Decimal(share.final_amount or 0)
            group['deal_count'] += 1
            group['deals'].append(
                {
                    'id': deal.pk,
                    'label': deal.contract_number or str(deal),
                    'amount': _quantize_money(share.final_amount),
                }
            )
    participant_share_rows = [
        {
            'participant': row['participant'],
            'amount': _quantize_money(row['amount']),
            'deal_count': row['deal_count'],
            'deals': row['deals'][:5],
        }
        for row in sorted(participant_groups.values(), key=lambda item: (-item['amount'], item['participant']))
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
        'gross_profit_total': _quantize_money(gross_profit_total),
        'distributable_profit_total': _quantize_money(distributable_profit_total),
        'company_profit': _quantize_money(distributable_profit_total),
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
        'participant_share_rows': participant_share_rows,
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
                'distributable_profit': MONEY_ZERO,
            },
        )
        group['deal_types'].add(deal.deal_type.name)
        group['distributable_profit'] += Decimal(deal.distributable_profit or 0)

    rows = []
    total_distributable_profit = sum((group['distributable_profit'] for group in groups.values()), MONEY_ZERO)
    total_opex = Decimal(total_opex or 0)
    total_net = total_distributable_profit - total_opex
    weight_sum = sum((group['distributable_profit'] * group['share'] for group in groups.values()), MONEY_ZERO)

    for share, group in sorted(groups.items(), key=lambda item: (item[0], sorted(item[1]['deal_types']))):
        distributable_profit = group['distributable_profit']
        weight = distributable_profit * share
        if total_distributable_profit <= 0:
            net_profit = MONEY_ZERO
        elif weight_sum <= 0:
            net_profit = total_net * (distributable_profit / total_distributable_profit)
        else:
            net_profit = total_net * (weight / weight_sum)
        partner_profit = net_profit * share if net_profit > 0 else MONEY_ZERO
        opex_allocated = distributable_profit - net_profit
        rows.append(
            {
                'deal_type': ' + '.join(sorted(group['deal_types'])),
                'share': _quantize_percent(share),
                'distributable_profit': _quantize_money(distributable_profit),
                'margin': _quantize_money(distributable_profit),
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
                    {'metric': 'gross_profit_total', 'value': data['gross_profit_total']},
                    {'metric': 'distributable_profit_total', 'value': data['distributable_profit_total']},
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
                [
                    'id',
                    'date',
                    'contract_number',
                    'deal_type',
                    'revenue',
                    'cost_of_goods',
                    'gross_profit',
                    'direct_expenses',
                    'manager_bonus',
                    'distributable_profit',
                    'partner_share_amount',
                    'comment',
                ],
                [
                    {
                        'id': deal.id,
                        'date': deal.date,
                        'contract_number': deal.contract_number,
                        'deal_type': deal.deal_type.name,
                        'revenue': deal.revenue,
                        'cost_of_goods': deal.cost_of_goods,
                        'gross_profit': deal.gross_profit,
                        'direct_expenses': deal.direct_expenses,
                        'manager_bonus': deal.manager_bonus,
                        'distributable_profit': deal.distributable_profit,
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
