import logging
from decimal import Decimal
from functools import wraps
from hmac import compare_digest

from django.conf import settings
from django.db.models import IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from catalog.models import GamePack, Product, ProductBundle, Service
from catalog.pricing import build_catalog_effective_price_expression, resolve_catalog_effective_price


logger = logging.getLogger('catalog.api')

ITEM_TYPE_PRODUCT = 'product'
ITEM_TYPE_SERVICE = 'service'
ITEM_TYPE_BUNDLE = 'bundle'
SUPPORTED_ITEM_TYPES = {ITEM_TYPE_PRODUCT, ITEM_TYPE_SERVICE, ITEM_TYPE_BUNDLE}

BUNDLE_SOURCE_PRODUCT_BUNDLE = 'bundle'
BUNDLE_SOURCE_GAME_PACK = 'game-pack'
PRODUCT_SOURCE = 'product'
SERVICE_SOURCE = 'service'


def _json_error(code, message, *, status):
    return JsonResponse({'error': {'code': code, 'message': message}}, status=status)


def _client_ip(request):
    return request.META.get('REMOTE_ADDR') or ''


def _add_cors_headers(request, response):
    origin = (request.headers.get('Origin') or '').strip()
    allowed_origins = set(getattr(settings, 'CATALOG_API_ALLOWED_ORIGINS', []))
    if origin and origin in allowed_origins:
        response['Access-Control-Allow-Origin'] = origin
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Max-Age'] = '86400'
        response['Vary'] = 'Origin'
    return response


def _options_response(request):
    return _add_cors_headers(request, HttpResponse(status=204))


def _auth_failed_response(request):
    response = _json_error('unauthorized', 'Authorization token is missing or invalid.', status=401)
    response['WWW-Authenticate'] = 'Bearer realm="catalog-api"'
    return _add_cors_headers(request, response)


def _server_not_configured_response(request):
    return _add_cors_headers(
        request,
        _json_error('catalog_api_unavailable', 'Catalog API token is not configured.', status=503),
    )


def _require_catalog_api_token(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.method == 'OPTIONS':
            return _options_response(request)

        configured_token = getattr(settings, 'CATALOG_API_TOKEN', '').strip()
        if not configured_token:
            logger.error('Catalog API request rejected because CATALOG_API_TOKEN is not configured', extra={
                'path': request.path,
                'ip': _client_ip(request),
            })
            return _server_not_configured_response(request)

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            logger.warning('Catalog API request rejected due to missing bearer token', extra={
                'path': request.path,
                'ip': _client_ip(request),
            })
            return _auth_failed_response(request)

        provided_token = auth_header[7:].strip()
        if not provided_token or not compare_digest(provided_token, configured_token):
            logger.warning('Catalog API request rejected due to invalid bearer token', extra={
                'path': request.path,
                'ip': _client_ip(request),
            })
            return _auth_failed_response(request)

        response = view_func(request, *args, **kwargs)
        return _add_cors_headers(request, response)

    return wrapped


def _enforce_rate_limit(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if getattr(request, 'limited', False):
            logger.warning('Catalog API rate limit exceeded', extra={
                'path': request.path,
                'ip': _client_ip(request),
            })
            return _add_cors_headers(
                request,
                _json_error('rate_limited', 'Too many requests.', status=429),
            )
        return view_func(request, *args, **kwargs)

    return wrapped


def _serialize_category(category):
    if category is None:
        return {'id': None, 'name': None}
    return {'id': str(category.pk), 'name': category.name}


def _serialize_decimal(value):
    if value is None:
        return None
    return float(Decimal(str(value)))


def _serialize_datetime(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(timezone.UTC).isoformat().replace('+00:00', 'Z')


def _build_absolute_media_url(request, file_field):
    if not file_field:
        return None
    try:
        return request.build_absolute_uri(file_field.url)
    except Exception:
        return None


def _build_item_id(source, obj_id):
    return f'{source}:{obj_id}'


def _parse_public_item_id(raw_item_id, *, allowed_sources):
    value = (raw_item_id or '').strip()
    if not value or ':' not in value:
        raise Http404('Catalog item not found')

    source, raw_pk = value.split(':', 1)
    if source not in allowed_sources:
        raise Http404('Catalog item not found')

    try:
        obj_id = int(raw_pk)
    except (TypeError, ValueError) as exc:
        raise Http404('Catalog item not found') from exc
    return source, obj_id


def _parse_positive_int(raw_value, *, default=None, minimum=0):
    if raw_value in (None, ''):
        return default
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError('Expected integer value.') from exc
    if value < minimum:
        raise ValueError(f'Expected integer value >= {minimum}.')
    return value


def _parse_updated_after(raw_value):
    raw_value = (raw_value or '').strip()
    if not raw_value:
        return None
    parsed = parse_datetime(raw_value)
    if parsed is None:
        raise ValueError('updatedAfter must be a valid ISO-8601 datetime.')
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _resolve_item_types(raw_type):
    normalized = (raw_type or '').strip().lower()
    if not normalized:
        return SUPPORTED_ITEM_TYPES
    if normalized not in SUPPORTED_ITEM_TYPES:
        raise ValueError('type must be one of: product, service, bundle.')
    return {normalized}


def _build_product_queryset(updated_after=None, include_inactive=False, category_id=None, search_query=''):
    queryset = (
        Product.objects.select_related('category')
        .prefetch_related('variants', 'images')
        .annotate(
            catalog_stock_total=Coalesce(Sum('stocks__quantity'), Value(0), output_field=IntegerField()),
            catalog_api_price=build_catalog_effective_price_expression(),
        )
    )
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    if category_id is not None:
        queryset = queryset.filter(category_id=category_id)
    if updated_after is not None:
        queryset = queryset.filter(updated_at__gt=updated_after)
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(sku__icontains=search_query)
        )
    return queryset


def _build_service_queryset(updated_after=None, include_inactive=False, search_query=''):
    queryset = Service.objects.all()
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    if updated_after is not None:
        queryset = queryset.filter(updated_at__gt=updated_after)
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(short_description__icontains=search_query)
        )
    return queryset


def _build_product_bundle_queryset(updated_after=None, category_id=None, search_query=''):
    queryset = (
        ProductBundle.objects.select_related('category')
        .prefetch_related('items__product__category', 'items__product__variants', 'items__product__images')
    )
    if category_id is not None:
        queryset = queryset.filter(category_id=category_id)
    if updated_after is not None:
        queryset = queryset.filter(updated_at__gt=updated_after)
    if search_query:
        queryset = queryset.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))
    return queryset


def _build_game_pack_queryset(updated_after=None, include_inactive=False, category_id=None, search_query=''):
    queryset = (
        GamePack.objects.select_related('category')
        .prefetch_related(
            'entries__product__category',
            'entries__product__variants',
            'entries__product__images',
            'service_entries__service',
        )
    )
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    if category_id is not None:
        queryset = queryset.filter(category_id=category_id)
    if updated_after is not None:
        queryset = queryset.filter(updated_at__gt=updated_after)
    if search_query:
        queryset = queryset.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))
    return queryset


def _serialize_product_item(request, product):
    image = product.get_display_image()
    return {
        'id': _build_item_id(PRODUCT_SOURCE, product.pk),
        'externalId': str(product.pk),
        'type': ITEM_TYPE_PRODUCT,
        'name': product.name,
        'description': product.description,
        'unit': 'шт.',
        'price': _serialize_decimal(getattr(product, 'catalog_api_price', None)),
        'currency': 'RUB',
        'vatRate': 0,
        'sku': product.sku or None,
        'category': _serialize_category(product.category),
        'imageUrl': _build_absolute_media_url(request, image),
        'isActive': bool(product.is_active),
        'updatedAt': _serialize_datetime(product.updated_at),
    }


def _serialize_service_item(request, service):
    return {
        'id': _build_item_id(SERVICE_SOURCE, service.pk),
        'externalId': str(service.pk),
        'type': ITEM_TYPE_SERVICE,
        'name': service.name,
        'description': service.description or service.short_description,
        'unit': 'усл.',
        'price': _serialize_decimal(service.price),
        'currency': 'RUB',
        'vatRate': 0,
        'sku': None,
        'category': {'id': None, 'name': None},
        'imageUrl': None,
        'isActive': bool(service.is_active),
        'updatedAt': _serialize_datetime(service.updated_at),
    }


def _serialize_product_bundle_items(bundle):
    return [
        {
            'itemId': _build_item_id(PRODUCT_SOURCE, item.product_id),
            'type': ITEM_TYPE_PRODUCT,
            'name': item.product.name,
            'quantity': item.quantity,
            'unit': 'шт.',
            'price': _serialize_decimal(item.effective_price),
            'priceOverride': _serialize_decimal(item.price),
            'vatRate': 0,
        }
        for item in bundle.items.all()
        if item.product_id
    ]


def _serialize_game_pack_items(game_pack):
    items = []
    for entry in game_pack.entries.all():
        if entry.product_id:
            items.append({
                'itemId': _build_item_id(PRODUCT_SOURCE, entry.product_id),
                'type': ITEM_TYPE_PRODUCT,
                'name': entry.product.name,
                'quantity': entry.quantity,
                'unit': 'шт.',
                'price': _serialize_decimal(resolve_catalog_effective_price(entry.product)),
                'priceOverride': None,
                'vatRate': 0,
            })
        elif entry.unresolved_title:
            items.append({
                'itemId': None,
                'type': ITEM_TYPE_PRODUCT,
                'name': entry.unresolved_title,
                'quantity': entry.quantity,
                'unit': 'шт.',
                'price': None,
                'priceOverride': None,
                'vatRate': 0,
            })

    for entry in game_pack.service_entries.all():
        items.append({
            'itemId': _build_item_id(SERVICE_SOURCE, entry.service_id) if entry.service_id else None,
            'type': ITEM_TYPE_SERVICE,
            'name': entry.display_title,
            'quantity': entry.quantity,
            'unit': 'усл.',
            'price': _serialize_decimal(entry.service.price if entry.service_id else entry.effective_price),
            'priceOverride': _serialize_decimal(entry.price),
            'vatRate': 0,
        })
    return items


def _serialize_product_bundle_item(request, bundle):
    image = bundle.get_display_image()
    return {
        'id': _build_item_id(BUNDLE_SOURCE_PRODUCT_BUNDLE, bundle.pk),
        'externalId': str(bundle.pk),
        'type': ITEM_TYPE_BUNDLE,
        'name': bundle.name or f'Набор #{bundle.pk}',
        'description': bundle.description,
        'unit': 'комплект',
        'price': _serialize_decimal(bundle.total_price),
        'currency': 'RUB',
        'vatRate': 0,
        'sku': None,
        'category': _serialize_category(bundle.category),
        'imageUrl': _build_absolute_media_url(request, image),
        'isActive': True,
        'updatedAt': _serialize_datetime(bundle.updated_at),
    }


def _serialize_game_pack_item(request, game_pack):
    image = game_pack.get_display_image()
    return {
        'id': _build_item_id(BUNDLE_SOURCE_GAME_PACK, game_pack.pk),
        'externalId': str(game_pack.pk),
        'type': ITEM_TYPE_BUNDLE,
        'name': game_pack.name,
        'description': game_pack.description,
        'unit': 'комплект',
        'price': _serialize_decimal(resolve_catalog_effective_price(game_pack)),
        'currency': 'RUB',
        'vatRate': 0,
        'sku': None,
        'category': _serialize_category(game_pack.category),
        'imageUrl': _build_absolute_media_url(request, image),
        'isActive': bool(game_pack.is_active),
        'updatedAt': _serialize_datetime(game_pack.updated_at),
    }


def _sort_catalog_item_payloads(items):
    return sorted(
        items,
        key=lambda item: (
            item.get('updatedAt') or '',
            item.get('type') or '',
            item.get('id') or '',
        ),
        reverse=True,
    )


def _parse_list_request(request):
    item_types = _resolve_item_types(request.GET.get('type'))
    search_query = (request.GET.get('q') or '').strip()
    category_id = _parse_positive_int(request.GET.get('categoryId'), default=None, minimum=1)
    requested_limit = _parse_positive_int(
        request.GET.get('limit'),
        default=max(1, getattr(settings, 'CATALOG_API_DEFAULT_LIMIT', 20)),
        minimum=1,
    )
    max_limit = max(1, getattr(settings, 'CATALOG_API_MAX_LIMIT', 100))
    limit = min(requested_limit, max_limit)
    offset = _parse_positive_int(request.GET.get('offset'), default=0, minimum=0)
    updated_after = _parse_updated_after(request.GET.get('updatedAfter'))
    include_inactive = str(request.GET.get('includeInactive', '')).strip().lower() == 'true'
    return {
        'item_types': item_types,
        'search_query': search_query,
        'category_id': category_id,
        'limit': limit,
        'offset': offset,
        'updated_after': updated_after,
        'include_inactive': include_inactive,
    }


@require_http_methods(['GET', 'OPTIONS'])
@ratelimit(key='ip', rate='120/m', method='GET', block=False)
@_enforce_rate_limit
@_require_catalog_api_token
def catalog_items_view(request):
    try:
        params = _parse_list_request(request)
    except ValueError as exc:
        return _add_cors_headers(request, _json_error('invalid_query', str(exc), status=400))

    try:
        items = []
        if ITEM_TYPE_PRODUCT in params['item_types']:
            items.extend(
                _serialize_product_item(request, product)
                for product in _build_product_queryset(
                    updated_after=params['updated_after'],
                    include_inactive=params['include_inactive'],
                    category_id=params['category_id'],
                    search_query=params['search_query'],
                )
            )
        if ITEM_TYPE_SERVICE in params['item_types']:
            items.extend(
                _serialize_service_item(request, service)
                for service in _build_service_queryset(
                    updated_after=params['updated_after'],
                    include_inactive=params['include_inactive'],
                    search_query=params['search_query'],
                )
            )
        if ITEM_TYPE_BUNDLE in params['item_types']:
            items.extend(
                _serialize_product_bundle_item(request, bundle)
                for bundle in _build_product_bundle_queryset(
                    updated_after=params['updated_after'],
                    category_id=params['category_id'],
                    search_query=params['search_query'],
                )
            )
            items.extend(
                _serialize_game_pack_item(request, game_pack)
                for game_pack in _build_game_pack_queryset(
                    updated_after=params['updated_after'],
                    include_inactive=params['include_inactive'],
                    category_id=params['category_id'],
                    search_query=params['search_query'],
                )
            )

        items = _sort_catalog_item_payloads(items)
        total = len(items)
        page_items = items[params['offset']:params['offset'] + params['limit']]
        payload = {
            'items': page_items,
            'pagination': {
                'limit': params['limit'],
                'offset': params['offset'],
                'total': total,
                'hasMore': params['offset'] + params['limit'] < total,
            },
        }
        logger.info('Catalog API items request succeeded', extra={
            'path': request.path,
            'ip': _client_ip(request),
            'limit': params['limit'],
            'offset': params['offset'],
            'total': total,
        })
        return JsonResponse(payload)
    except Exception:
        logger.exception('Catalog API items request failed', extra={'path': request.path, 'ip': _client_ip(request)})
        return _add_cors_headers(
            request,
            _json_error('catalog_api_error', 'Unable to fetch catalog items.', status=500),
        )


@require_http_methods(['GET', 'OPTIONS'])
@ratelimit(key='ip', rate='120/m', method='GET', block=False)
@_enforce_rate_limit
@_require_catalog_api_token
def catalog_item_detail_view(request, item_id):
    try:
        source, object_id = _parse_public_item_id(
            item_id,
            allowed_sources={PRODUCT_SOURCE, SERVICE_SOURCE, BUNDLE_SOURCE_PRODUCT_BUNDLE, BUNDLE_SOURCE_GAME_PACK},
        )
        if source == PRODUCT_SOURCE:
            product = _build_product_queryset().filter(pk=object_id).first()
            if product is None:
                raise Http404('Catalog item not found')
            payload = _serialize_product_item(request, product)
        elif source == SERVICE_SOURCE:
            service = _build_service_queryset().filter(pk=object_id).first()
            if service is None:
                raise Http404('Catalog item not found')
            payload = _serialize_service_item(request, service)
        elif source == BUNDLE_SOURCE_PRODUCT_BUNDLE:
            bundle = _build_product_bundle_queryset().filter(pk=object_id).first()
            if bundle is None:
                raise Http404('Catalog item not found')
            payload = _serialize_product_bundle_item(request, bundle)
            payload['bundleItems'] = _serialize_product_bundle_items(bundle)
        else:
            game_pack = _build_game_pack_queryset().filter(pk=object_id).first()
            if game_pack is None:
                raise Http404('Catalog item not found')
            payload = _serialize_game_pack_item(request, game_pack)
            payload['bundleItems'] = _serialize_game_pack_items(game_pack)

        logger.info('Catalog API item detail request succeeded', extra={
            'path': request.path,
            'ip': _client_ip(request),
            'item_id': item_id,
        })
        return JsonResponse(payload)
    except Http404:
        return _add_cors_headers(
            request,
            _json_error('not_found', 'Catalog item was not found.', status=404),
        )
    except Exception:
        logger.exception('Catalog API item detail request failed', extra={'path': request.path, 'ip': _client_ip(request)})
        return _add_cors_headers(
            request,
            _json_error('catalog_api_error', 'Unable to fetch catalog item.', status=500),
        )


@require_http_methods(['GET', 'OPTIONS'])
@ratelimit(key='ip', rate='120/m', method='GET', block=False)
@_enforce_rate_limit
@_require_catalog_api_token
def catalog_bundle_detail_view(request, bundle_id):
    try:
        source, object_id = _parse_public_item_id(
            bundle_id,
            allowed_sources={BUNDLE_SOURCE_PRODUCT_BUNDLE, BUNDLE_SOURCE_GAME_PACK},
        )
        if source == BUNDLE_SOURCE_PRODUCT_BUNDLE:
            bundle = _build_product_bundle_queryset().filter(pk=object_id).first()
            if bundle is None:
                raise Http404('Catalog bundle not found')
            payload = _serialize_product_bundle_item(request, bundle)
            payload['items'] = _serialize_product_bundle_items(bundle)
        else:
            game_pack = _build_game_pack_queryset().filter(pk=object_id).first()
            if game_pack is None:
                raise Http404('Catalog bundle not found')
            payload = _serialize_game_pack_item(request, game_pack)
            payload['items'] = _serialize_game_pack_items(game_pack)

        logger.info('Catalog API bundle detail request succeeded', extra={
            'path': request.path,
            'ip': _client_ip(request),
            'bundle_id': bundle_id,
        })
        return JsonResponse(payload)
    except Http404:
        return _add_cors_headers(
            request,
            _json_error('not_found', 'Catalog bundle was not found.', status=404),
        )
    except Exception:
        logger.exception('Catalog API bundle detail request failed', extra={'path': request.path, 'ip': _client_ip(request)})
        return _add_cors_headers(
            request,
            _json_error('catalog_api_error', 'Unable to fetch catalog bundle.', status=500),
        )
