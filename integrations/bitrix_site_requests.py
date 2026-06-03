import logging
from decimal import Decimal
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone

from accounts.services import normalize_email, normalize_phone
from config.utils.marketing import UTM_FIELDS, get_marketing_context
from orders.models import Order, OrderItem

from .models import SiteLeadRequest

logger = logging.getLogger(__name__)

BITRIX_API_TIMEOUT_SECONDS = 20
BITRIX_SOURCE_LABEL = 'Сайт'
MONEY_ZERO = Decimal('0')
DEAL_TYPE_LABELS = {
    SiteLeadRequest.SOURCE_CHECKOUT: 'Заказ товаров',
    SiteLeadRequest.SOURCE_PURCHASE_REQUEST: 'Заявка на товар',
    SiteLeadRequest.SOURCE_CONTACTS: 'Обратная связь',
    SiteLeadRequest.SOURCE_CALLBACK_ARENDA: 'Обратная связь',
    SiteLeadRequest.SOURCE_CALLBACK_USLUGI: 'Услуга',
    SiteLeadRequest.SOURCE_COMPACT_VR: 'Услуга',
    SiteLeadRequest.SOURCE_VR_CLUB: 'VR-клуб',
    SiteLeadRequest.SOURCE_TEST: 'Тест',
}
TITLE_LABELS = {
    SiteLeadRequest.SOURCE_CHECKOUT: 'Сайт — заказ товаров',
    SiteLeadRequest.SOURCE_PURCHASE_REQUEST: 'Сайт — заявка на товар',
    SiteLeadRequest.SOURCE_CONTACTS: 'Сайт — обратная связь',
    SiteLeadRequest.SOURCE_CALLBACK_ARENDA: 'Сайт — обратная связь',
    SiteLeadRequest.SOURCE_CALLBACK_USLUGI: 'Сайт — услуга',
    SiteLeadRequest.SOURCE_COMPACT_VR: 'Сайт — услуга',
    SiteLeadRequest.SOURCE_VR_CLUB: 'Сайт — VR-клуб',
    SiteLeadRequest.SOURCE_TEST: 'Сайт — тестовая заявка',
}


class BitrixSiteRequestSyncError(RuntimeError):
    pass


def _clean(value, *, limit=None):
    cleaned = str(value or '').strip()
    if limit is not None:
        return cleaned[:limit]
    return cleaned


def _stringify_decimal(value):
    try:
        decimal_value = Decimal(value)
    except Exception:
        decimal_value = MONEY_ZERO
    return format(decimal_value.quantize(Decimal('0.01')), 'f')


def _absolute_url(request, value=''):
    value = _clean(value, limit=500)
    if not value:
        return request.build_absolute_uri(request.get_full_path()) if request is not None else ''
    if value.startswith(('http://', 'https://')):
        return value
    if request is None:
        return value
    return request.build_absolute_uri(value)


def _payload_from_request(request):
    if request is None or not getattr(request, 'POST', None):
        return {}

    payload = {}
    for key, values in request.POST.lists():
        if key == 'csrfmiddlewaretoken':
            continue
        cleaned_values = [_clean(value, limit=4000) for value in values]
        if len(cleaned_values) == 1:
            payload[key] = cleaned_values[0]
        else:
            payload[key] = cleaned_values
    return payload


def summarize_spam_check(result):
    if result is None:
        return SiteLeadRequest.SPAM_STATUS_CLEAN, ''
    if result.is_spam:
        return SiteLeadRequest.SPAM_STATUS_SPAM, ', '.join(result.reasons)
    if result.reasons or result.score:
        return SiteLeadRequest.SPAM_STATUS_SUSPICIOUS, ', '.join(result.reasons)
    return SiteLeadRequest.SPAM_STATUS_CLEAN, ''


def build_order_cart_snapshot(order):
    if order is None:
        return []
    snapshot = []
    for item in order.items.select_related('product', 'variant', 'game_pack').all():
        snapshot.append({
            'order_item_id': item.id,
            'line_type': item.line_type,
            'product_id': item.product_id,
            'game_pack_id': item.game_pack_id,
            'variant_id': item.variant_id,
            'name': item.resolved_product_name,
            'variant_name': item.resolved_variant_name,
            'quantity': int(item.quantity or 0),
            'price': _stringify_decimal(item.price),
            'discount_amount': _stringify_decimal(item.discount_amount),
            'unit_price': _stringify_decimal(item.unit_price),
            'is_on_request': bool(item.is_on_request),
            'sku': item.sku,
            'metadata': item.metadata or {},
        })
    return snapshot


def _bitrix_portal_root():
    webhook_url = _clean(getattr(settings, 'BITRIX_WEBHOOK_URL', ''))
    if not webhook_url:
        return ''
    parsed = urlparse(webhook_url)
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f'{parsed.scheme}://{parsed.netloc}'


def build_bitrix_deal_url(deal_id):
    deal_id = _clean(deal_id)
    portal_root = _bitrix_portal_root()
    if not deal_id or not portal_root:
        return ''
    return f'{portal_root}/crm/deal/details/{deal_id}/'


def _bitrix_api_request(method_name, *, params=None):
    webhook_url = _clean(getattr(settings, 'BITRIX_WEBHOOK_URL', ''))
    if not webhook_url:
        raise BitrixSiteRequestSyncError('Не задан BITRIX_WEBHOOK_URL.')
    url = f'{webhook_url.rstrip("/")}/{method_name}.json'
    try:
        response = requests.post(url, data=params or {}, timeout=BITRIX_API_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json() or {}
    except (requests.RequestException, ValueError) as exc:
        raise BitrixSiteRequestSyncError(f'Не удалось выполнить запрос Bitrix {method_name}.') from exc
    if payload.get('error'):
        message = payload.get('error_description') or payload.get('error') or 'Bitrix вернул ошибку.'
        raise BitrixSiteRequestSyncError(message)
    return payload.get('result')


def _bitrix_additional_field(fields, setting_name, value):
    field_name = _clean(getattr(settings, setting_name, ''))
    value = _clean(value)
    if field_name and value:
        fields[field_name] = value


def _extract_marketing_value(request, field_name):
    if request is not None:
        direct_value = _clean(request.POST.get(field_name) or request.GET.get(field_name), limit=255)
        if direct_value:
            return direct_value
    stored = get_marketing_context(request)
    return _clean(stored.get(field_name), limit=255)


def create_site_lead_request(
    *,
    request,
    source_type,
    name='',
    phone='',
    email='',
    city='',
    message='',
    page_url='',
    cart_snapshot=None,
    raw_payload=None,
    spam_status=SiteLeadRequest.SPAM_STATUS_CLEAN,
    spam_reason='',
    order=None,
):
    resolved_page_url = _absolute_url(request, page_url)
    sync_status = SiteLeadRequest.SYNC_STATUS_PENDING
    if spam_status == SiteLeadRequest.SPAM_STATUS_SPAM:
        sync_status = SiteLeadRequest.SYNC_STATUS_SKIPPED

    referer = ''
    if request is not None:
        referer = _clean(request.META.get('HTTP_REFERER'), limit=500)
    marketing_context = get_marketing_context(request)
    if not referer:
        referer = _clean(marketing_context.get('latest_referer'), limit=500)

    site_request = SiteLeadRequest.objects.create(
        source_type=source_type,
        order=order,
        name=_clean(name, limit=255),
        phone=_clean(phone, limit=64),
        email=_clean(email, limit=254),
        city=_clean(city, limit=255),
        message=_clean(message, limit=8000),
        page_url=resolved_page_url,
        referer=referer,
        utm_source=_extract_marketing_value(request, 'utm_source'),
        utm_medium=_extract_marketing_value(request, 'utm_medium'),
        utm_campaign=_extract_marketing_value(request, 'utm_campaign'),
        utm_content=_extract_marketing_value(request, 'utm_content'),
        utm_term=_extract_marketing_value(request, 'utm_term'),
        cart_snapshot=cart_snapshot or [],
        raw_payload=raw_payload if raw_payload is not None else _payload_from_request(request),
        spam_status=spam_status,
        spam_reason=_clean(spam_reason, limit=4000),
        sync_status=sync_status,
    )
    return site_request


def _contact_multifield(value, *, value_type='WORK'):
    value = _clean(value)
    if not value:
        return []
    return [{'VALUE': value, 'VALUE_TYPE': value_type}]


def _contact_fields_from_site_request(site_request):
    order = site_request.order
    address = ''
    if order is not None:
        address = _clean(order.display_address, limit=1000)

    fields = {
        'NAME': _clean(site_request.name, limit=100),
        'PHONE': _contact_multifield(site_request.phone),
        'EMAIL': _contact_multifield(site_request.email),
        'ADDRESS_CITY': _clean(site_request.city, limit=255),
        'ADDRESS': address,
        'COMMENTS': _clean(site_request.message, limit=4000),
    }
    return {key: value for key, value in fields.items() if value not in ('', [], None)}


def _extract_duplicate_contact_id(result):
    if not isinstance(result, dict):
        return ''
    candidates = result.get('CONTACT') or result.get('CONTACTS') or []
    if isinstance(candidates, dict):
        candidates = list(candidates.keys()) or list(candidates.values())
    if isinstance(candidates, list):
        for candidate in candidates:
            normalized = _clean(candidate)
            if normalized:
                return normalized
    return ''


def _find_contact_id_by_phone_or_email(site_request):
    phone = normalize_phone(site_request.phone) or _clean(site_request.phone)
    email = normalize_email(site_request.email) or _clean(site_request.email)

    if phone:
        result = _bitrix_api_request(
            'crm.duplicate.findbycomm',
            params={'type': 'PHONE', 'values[]': [phone]},
        )
        contact_id = _extract_duplicate_contact_id(result)
        if contact_id:
            return contact_id
    if email:
        result = _bitrix_api_request(
            'crm.duplicate.findbycomm',
            params={'type': 'EMAIL', 'values[]': [email]},
        )
        contact_id = _extract_duplicate_contact_id(result)
        if contact_id:
            return contact_id
    return ''


def create_or_update_contact_from_site_request(site_request):
    contact_fields = _contact_fields_from_site_request(site_request)
    existing_contact_id = _find_contact_id_by_phone_or_email(site_request)
    if existing_contact_id:
        if contact_fields:
            _bitrix_api_request(
                'crm.contact.update',
                params={'id': existing_contact_id, 'fields': contact_fields},
            )
        return existing_contact_id
    if not contact_fields:
        return ''
    created_contact_id = _bitrix_api_request(
        'crm.contact.add',
        params={'fields': contact_fields},
    )
    return _clean(created_contact_id)


def _site_request_title(site_request):
    return TITLE_LABELS.get(site_request.source_type, 'Сайт — заявка')


def _site_request_deal_type_label(site_request):
    return DEAL_TYPE_LABELS.get(site_request.source_type, 'Заявка')


def _site_request_client_request(site_request):
    parts = []
    if site_request.message:
        parts.append(site_request.message)
    if site_request.source_type == SiteLeadRequest.SOURCE_CHECKOUT and site_request.cart_snapshot:
        parts.append(
            'Состав заказа: ' + ', '.join(
                f'{item.get("name") or "Товар"} x{item.get("quantity") or 0}'
                for item in site_request.cart_snapshot
            )
        )
    return '\n'.join(part for part in parts if part)


def _site_request_comment(site_request):
    order = site_request.order
    parts = [
        f'Источник: {site_request.get_source_type_display()}',
        f'Страница: {site_request.page_url}',
    ]
    if site_request.referer:
        parts.append(f'Referer: {site_request.referer}')
    utm_lines = [
        f'{field_name}={getattr(site_request, field_name)}'
        for field_name in UTM_FIELDS
        if _clean(getattr(site_request, field_name))
    ]
    if utm_lines:
        parts.append('UTM: ' + ', '.join(utm_lines))
    if site_request.spam_status == SiteLeadRequest.SPAM_STATUS_SUSPICIOUS:
        parts.append(f'Подозрительность: {site_request.spam_reason or "score>0"}')
    if site_request.message:
        parts.append(f'Текст заявки:\n{site_request.message}')
    if order is not None:
        if order.recipient_name:
            parts.append(f'Получатель: {order.recipient_name}')
        if order.recipient_phone:
            parts.append(f'Телефон получателя: {order.recipient_phone}')
        if order.display_address:
            parts.append(f'Доставка: {order.display_address}')
        if order.comment and order.comment != site_request.message:
            parts.append(f'Комментарий к заказу:\n{order.comment}')
    if site_request.cart_snapshot:
        parts.append(
            'Позиции:\n' + '\n'.join(
                f'- {item.get("name") or "Товар"}'
                + (f' ({item.get("variant_name")})' if item.get('variant_name') else '')
                + f' x{item.get("quantity") or 0} · {item.get("unit_price") or item.get("price") or "0"}'
                for item in site_request.cart_snapshot
            )
        )
    return '\n\n'.join(part for part in parts if _clean(part))


def _lookup_bitrix_catalog_product_id(order_item, *, cache):
    cache_key = (
        order_item.product_id or 0,
        order_item.variant_id or 0,
        order_item.game_pack_id or 0,
    )
    if cache_key in cache:
        return cache[cache_key]

    site_product_id = order_item.product_id or order_item.game_pack_id
    if not site_product_id:
        cache[cache_key] = ''
        return ''

    property_id = int(getattr(settings, 'BITRIX_SITE_PRODUCT_ID_PROPERTY_ID', 107) or 107)
    filters = [{f'property{property_id}': str(site_product_id)}]
    if order_item.sku:
        filters.append({'sku': order_item.sku})

    for item_filter in filters:
        try:
            result = _bitrix_api_request(
                'catalog.product.list',
                params={'filter': item_filter, 'select': ['id']},
            )
        except BitrixSiteRequestSyncError:
            continue

        candidates = result
        if isinstance(result, dict):
            candidates = result.get('products') or result.get('items') or result.get('result') or []
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate_id = _clean(candidate.get('id') or candidate.get('ID'))
            else:
                candidate_id = _clean(candidate)
            if candidate_id:
                cache[cache_key] = candidate_id
                return candidate_id

    cache[cache_key] = ''
    return ''


def attach_product_rows_to_deal(site_request, deal_id):
    rows = []
    cache = {}
    order = site_request.order
    if order is not None:
        order_items = list(order.items.select_related('product', 'variant', 'game_pack').all())
    else:
        order_items = []

    for order_item in order_items:
        row = {
            'PRODUCT_NAME': order_item.display_name,
            'PRICE': _stringify_decimal(order_item.unit_price),
            'QUANTITY': int(order_item.quantity or 0),
        }
        bitrix_product_id = ''
        if order_item.line_type == OrderItem.LINE_TYPE_CATALOG:
            bitrix_product_id = _lookup_bitrix_catalog_product_id(order_item, cache=cache)
        if bitrix_product_id:
            row['PRODUCT_ID'] = bitrix_product_id
        rows.append(row)

    if not rows:
        return []

    _bitrix_api_request(
        'crm.deal.productrows.set',
        params={'id': deal_id, 'rows': rows},
    )
    return rows


def create_deal_from_site_request(site_request, *, contact_id=''):
    order = site_request.order
    fields = {
        'TITLE': _site_request_title(site_request),
        'CONTACT_ID': _clean(contact_id),
        'SOURCE_ID': 'WEB',
        'COMMENTS': _site_request_comment(site_request),
    }
    assigned_by_id = _clean(getattr(settings, 'BITRIX_ASSIGNED_BY_ID', ''))
    if assigned_by_id:
        fields['ASSIGNED_BY_ID'] = assigned_by_id

    client_request = _site_request_client_request(site_request)
    _bitrix_additional_field(fields, 'BITRIX_FIELD_DEAL_TYPE', _site_request_deal_type_label(site_request))
    _bitrix_additional_field(fields, 'BITRIX_FIELD_CLIENT_SOURCE', BITRIX_SOURCE_LABEL)
    _bitrix_additional_field(fields, 'BITRIX_FIELD_CITY', site_request.city)
    _bitrix_additional_field(fields, 'BITRIX_FIELD_CLIENT_REQUEST', client_request)

    if order is not None:
        _bitrix_additional_field(fields, 'BITRIX_FIELD_RECIPIENT_NAME', order.recipient_name or order.shipping_contact_name)
        _bitrix_additional_field(fields, 'BITRIX_FIELD_RECIPIENT_PHONE', order.recipient_phone or order.shipping_phone)
        _bitrix_additional_field(fields, 'BITRIX_FIELD_DELIVERY_ADDRESS', order.display_address)

    if site_request.utm_source:
        fields['UTM_SOURCE'] = site_request.utm_source
    if site_request.utm_medium:
        fields['UTM_MEDIUM'] = site_request.utm_medium
    if site_request.utm_campaign:
        fields['UTM_CAMPAIGN'] = site_request.utm_campaign
    if site_request.utm_content:
        fields['UTM_CONTENT'] = site_request.utm_content
    if site_request.utm_term:
        fields['UTM_TERM'] = site_request.utm_term

    deal_id = _bitrix_api_request('crm.deal.add', params={'fields': fields})
    return _clean(deal_id)


def _update_site_request_sync_state(site_request, *, sync_status, sync_error='', contact_id='', deal_id=''):
    site_request.sync_status = sync_status
    site_request.sync_error = _clean(sync_error, limit=8000)
    site_request.bitrix_contact_id = _clean(contact_id, limit=64)
    site_request.bitrix_deal_id = _clean(deal_id, limit=64)
    site_request.bitrix_entity_type = SiteLeadRequest.BITRIX_ENTITY_TYPE_DEAL if deal_id else ''
    site_request.bitrix_entity_id = _clean(deal_id or contact_id, limit=64)
    site_request.bitrix_synced_at = timezone.now() if sync_status == SiteLeadRequest.SYNC_STATUS_SYNCED else None
    site_request.save(
        update_fields=[
            'sync_status',
            'sync_error',
            'bitrix_contact_id',
            'bitrix_deal_id',
            'bitrix_entity_type',
            'bitrix_entity_id',
            'bitrix_synced_at',
            'updated_at',
        ]
    )


def send_site_request_to_bitrix(site_request):
    if not getattr(settings, 'BITRIX_SITE_REQUESTS_ENABLED', False):
        return {'contact_id': '', 'deal_id': '', 'product_rows': []}
    if site_request.spam_status == SiteLeadRequest.SPAM_STATUS_SPAM:
        _update_site_request_sync_state(
            site_request,
            sync_status=SiteLeadRequest.SYNC_STATUS_SKIPPED,
            sync_error='spam skipped',
        )
        return {'contact_id': '', 'deal_id': '', 'product_rows': []}

    try:
        contact_id = create_or_update_contact_from_site_request(site_request)
        deal_id = create_deal_from_site_request(site_request, contact_id=contact_id)
        product_rows = attach_product_rows_to_deal(site_request, deal_id)
    except BitrixSiteRequestSyncError as exc:
        _update_site_request_sync_state(
            site_request,
            sync_status=SiteLeadRequest.SYNC_STATUS_FAILED,
            sync_error=str(exc),
        )
        raise

    _update_site_request_sync_state(
        site_request,
        sync_status=SiteLeadRequest.SYNC_STATUS_SYNCED,
        contact_id=contact_id,
        deal_id=deal_id,
    )
    return {'contact_id': contact_id, 'deal_id': deal_id, 'product_rows': product_rows}


def sync_pending_site_requests(*, queryset=None, limit=None):
    queryset = queryset or SiteLeadRequest.objects.exclude(spam_status=SiteLeadRequest.SPAM_STATUS_SPAM).filter(
        sync_status__in=[SiteLeadRequest.SYNC_STATUS_PENDING, SiteLeadRequest.SYNC_STATUS_FAILED]
    )
    if limit:
        queryset = queryset.order_by('created_at', 'id')[: int(limit)]

    processed = 0
    succeeded = 0
    failed = 0
    for site_request in queryset:
        processed += 1
        try:
            send_site_request_to_bitrix(site_request)
        except BitrixSiteRequestSyncError:
            failed += 1
            logger.exception('Failed to sync site request %s to Bitrix.', site_request.pk)
        else:
            succeeded += 1
    return {'processed': processed, 'succeeded': succeeded, 'failed': failed}
