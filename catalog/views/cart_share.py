import json
from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from ..cart_services import (
    _build_game_pack_item_dict,
    _build_service_item_dict,
    build_cart_item_share_key,
    CART_LINE_CUSTOM_GAME_PACK,
    CART_LINE_SERVICE,
    get_cart_count,
    get_cart_items,
    save_cart_to_db,
    save_cart_to_session,
)
from ..models import CartShare, GamePack, Product, ProductVariant, Service
from ..pricing import normalize_purchase_mode, resolve_price_for_mode
from .common import ALWAYS_AVAILABLE_STOCK_TOTAL, _get_stock_total

CART_SHARE_TTL_DAYS = 30


def _parse_share_item_key(raw_key):
    if not raw_key or ':' not in raw_key:
        return None
    parts = raw_key.split(':')
    if len(parts) < 5:
        return None

    def _parse_optional_int(value):
        if value in ('', 'none', 'null'):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    product_id = _parse_optional_int(parts[0])
    variant_id = _parse_optional_int(parts[1])
    bundle_id = _parse_optional_int(parts[3])
    game_pack_id = _parse_optional_int(parts[4])
    purchase_mode = normalize_purchase_mode(parts[2])
    if product_id is None and game_pack_id is None:
        return None
    return product_id, variant_id, purchase_mode, bundle_id, game_pack_id


def _generate_cart_share_code():
    for _ in range(12):
        code = get_random_string(7, allowed_chars='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
        if not CartShare.objects.filter(code=code).exists():
            return code
    return get_random_string(7)


def _resolve_cart_share_items(items_payload):
    normalized = []
    product_ids = set()
    game_pack_ids = set()
    service_ids = set()
    variant_pairs = set()

    for raw_item in items_payload or []:
        if not isinstance(raw_item, dict):
            continue

        try:
            quantity = max(1, int(raw_item.get('quantity', 1)))
        except (TypeError, ValueError):
            quantity = 1

        purchase_mode = normalize_purchase_mode(raw_item.get('purchase_mode'))
        raw_game_pack_id = raw_item.get('game_pack_id')
        line_type = raw_item.get('line_type') or ''
        raw_service_id = raw_item.get('service_id')
        if line_type == CART_LINE_CUSTOM_GAME_PACK:
            normalized.append({
                **raw_item,
                'quantity': quantity,
                'purchase_mode': purchase_mode,
            })
            continue
        if raw_service_id not in (None, '', 'none', 'null'):
            try:
                service_id = int(raw_service_id)
            except (TypeError, ValueError):
                continue
            normalized.append({
                'product_id': None,
                'variant_id': None,
                'game_pack_id': None,
                'service_id': service_id,
                'line_type': CART_LINE_SERVICE,
                'quantity': quantity,
                'purchase_mode': purchase_mode,
            })
            service_ids.add(service_id)
            continue
        if raw_game_pack_id in (None, '', 'none', 'null'):
            game_pack_id = None
        else:
            try:
                game_pack_id = int(raw_game_pack_id)
            except (TypeError, ValueError):
                continue

        if game_pack_id is not None:
            normalized.append({
                'product_id': None,
                'variant_id': None,
                'game_pack_id': game_pack_id,
                'quantity': quantity,
                'purchase_mode': purchase_mode,
            })
            game_pack_ids.add(game_pack_id)
            continue

        try:
            product_id = int(raw_item.get('product_id'))
        except (TypeError, ValueError):
            continue

        raw_variant_id = raw_item.get('variant_id')
        if raw_variant_id in (None, '', 'none', 'null'):
            variant_id = None
        else:
            try:
                variant_id = int(raw_variant_id)
            except (TypeError, ValueError):
                continue

        normalized.append({
            'product_id': product_id,
            'variant_id': variant_id,
            'game_pack_id': None,
            'quantity': quantity,
            'purchase_mode': purchase_mode,
        })
        product_ids.add(product_id)
        if variant_id is not None:
            variant_pairs.add((product_id, variant_id))

    if not normalized:
        return []

    products = Product.objects.filter(pk__in=product_ids, is_active=True).only('id', 'name', 'slug', 'price', 'image')
    product_map = {product.pk: product for product in products}
    game_packs = GamePack.objects.filter(pk__in=game_pack_ids, is_active=True)
    game_pack_map = {game_pack.pk: game_pack for game_pack in game_packs}
    services = Service.objects.filter(pk__in=service_ids, is_active=True)
    service_map = {service.pk: service for service in services}
    variant_ids = [pair[1] for pair in variant_pairs]
    variants = ProductVariant.objects.filter(
        product_id__in=product_ids,
        pk__in=variant_ids,
    ).select_related('product')
    variant_map = {(variant.product_id, variant.pk): variant for variant in variants}

    resolved = []
    for item in normalized:
        quantity = item['quantity']
        purchase_mode = item['purchase_mode']
        if item.get('line_type') == CART_LINE_CUSTOM_GAME_PACK:
            price = float(item.get('price') or 0)
            resolved.append({
                **item,
                'price': price,
                'subtotal': price * quantity,
                'product_slug': '',
                'game_pack_slug': '',
                'is_game_pack': False,
                'is_custom_game_pack': True,
                'stock_total': 1,
            })
            continue

        if item.get('line_type') == CART_LINE_SERVICE:
            service = service_map.get(item.get('service_id'))
            if not service or service.price is None:
                continue
            resolved_item = _build_service_item_dict(service, quantity)
            resolved_item.update({
                'product_slug': '',
                'game_pack_slug': '',
                'is_game_pack': False,
                'is_service': True,
                'stock_total': 1,
                '_service_obj': service,
            })
            resolved.append(resolved_item)
            continue

        if item['game_pack_id'] is not None:
            game_pack = game_pack_map.get(item['game_pack_id'])
            if not game_pack:
                continue
            price_value = resolve_price_for_mode(game_pack, None, purchase_mode)
            if price_value is None:
                continue
            price = float(price_value)
            image_url = ''
            image = game_pack.get_display_image()
            if image is not None:
                try:
                    image_url = image.url
                except (AttributeError, ValueError):
                    image_url = ''
            resolved.append({
                'product_id': None,
                'variant_id': None,
                'game_pack_id': game_pack.pk,
                'variant_name': None,
                'name': game_pack.name,
                'price': price,
                'quantity': quantity,
                'subtotal': price * quantity,
                'image_url': image_url,
                'purchase_mode': purchase_mode,
                'product_slug': '',
                'game_pack_slug': game_pack.slug,
                'is_game_pack': True,
                '_game_pack_obj': game_pack,
                'stock_total': 1,
            })
            continue

        product_id = item['product_id']
        variant_id = item['variant_id']
        product = product_map.get(product_id)
        if not product:
            continue
        variant = None
        if variant_id is not None:
            variant = variant_map.get((product_id, variant_id))
            if variant is None:
                continue
        price_value = resolve_price_for_mode(product, variant, purchase_mode)
        if price_value is None:
            continue
        price = float(price_value)
        image_url = ''
        if variant and variant.image:
            image_url = variant.image.url
        elif product.image:
            image_url = product.image.url
        resolved.append({
            'product_id': product_id,
            'variant_id': variant_id,
            'game_pack_id': None,
            'variant_name': variant.name if variant else None,
            'name': product.name,
            'price': price,
            'quantity': quantity,
            'subtotal': price * quantity,
            'image_url': image_url,
            'purchase_mode': purchase_mode,
            'product_slug': product.slug,
            'game_pack_slug': '',
            'is_game_pack': False,
            '_product_obj': product,
            '_variant_obj': variant,
            'stock_total': (
                _get_stock_total(product_id, variant_id)
                if product.tracks_stock
                else ALWAYS_AVAILABLE_STOCK_TOTAL
            ),
        })
    return resolved


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def cart_share_create_view(request):
    selected_raw = (request.POST.get('selected_item_keys') or '').strip()
    selected_pairs_set = {raw_key.strip() for raw_key in selected_raw.split(',') if raw_key.strip()}

    if not selected_pairs_set:
        return render(request, 'catalog/partials/cart_share_modal.html', {
            'modal_mode': 'source',
            'share_items': [],
            'share_error': 'Выберите хотя бы один товар для шаринга.',
        }, status=400)

    selected_payload = []
    for item in get_cart_items(request):
        item_key = build_cart_item_share_key(item)
        if item_key not in selected_pairs_set:
            continue
        try:
            quantity = max(1, int(item.get('quantity', 1) or 1))
        except (TypeError, ValueError):
            quantity = 1
        selected_payload.append({
            'product_id': item.get('product_id'),
            'variant_id': item.get('variant_id'),
            'game_pack_id': item.get('game_pack_id'),
            'service_id': item.get('service_id'),
            'line_type': item.get('line_type'),
            'custom_key': item.get('custom_key'),
            'custom_snapshot': item.get('custom_snapshot') or {},
            'name': item.get('name'),
            'price': item.get('price'),
            'quantity': quantity,
            'purchase_mode': normalize_purchase_mode(item.get('purchase_mode')),
        })

    resolved_items = _resolve_cart_share_items(selected_payload)
    if not resolved_items:
        return render(request, 'catalog/partials/cart_share_modal.html', {
            'modal_mode': 'source',
            'share_items': [],
            'share_error': 'Не удалось собрать товары для шаринга.',
        }, status=400)

    share_payload = [
        {
            'product_id': item['product_id'],
            'variant_id': item['variant_id'],
            'game_pack_id': item.get('game_pack_id'),
            'service_id': item.get('service_id'),
            'line_type': item.get('line_type'),
            'custom_key': item.get('custom_key'),
            'custom_snapshot': item.get('custom_snapshot') or {},
            'name': item.get('name'),
            'price': item.get('price'),
            'quantity': item['quantity'],
            'purchase_mode': item['purchase_mode'],
        }
        for item in resolved_items
    ]
    share = CartShare.objects.create(
        code=_generate_cart_share_code(),
        items=share_payload,
        created_by=request.user if request.user.is_authenticated else None,
        expires_at=timezone.now() + timedelta(days=CART_SHARE_TTL_DAYS),
    )
    share_url = request.build_absolute_uri(f"{reverse('catalog:cart')}?share={share.code}")
    share_total = sum(item.get('subtotal', 0) for item in resolved_items)
    share_quantity = sum(item.get('quantity', 0) for item in resolved_items)
    return render(request, 'catalog/partials/cart_share_modal.html', {
        'modal_mode': 'source',
        'share_items': resolved_items,
        'share_url': share_url,
        'share_code': share.code,
        'share_total': share_total,
        'share_quantity': share_quantity,
    })


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def cart_share_add_all_view(request):
    share_code = (request.POST.get('share_code') or '').strip()
    if not share_code:
        return HttpResponse('Не указан код шаринга.', status=400)

    share = CartShare.objects.filter(code=share_code, expires_at__gt=timezone.now()).first()
    if not share:
        return HttpResponse('Ссылка недействительна или истекла.', status=400)

    resolved_items = _resolve_cart_share_items(share.items)
    if not resolved_items:
        return HttpResponse('В ссылке нет доступных товаров.', status=400)

    from .cart_mutations import _add_product_to_cart_items

    cart_items = list(get_cart_items(request))
    for item in resolved_items:
        if item.get('line_type') == CART_LINE_CUSTOM_GAME_PACK:
            cart_items.append({
                'product_id': None,
                'variant_id': None,
                'game_pack_id': None,
                'service_id': None,
                'line_type': CART_LINE_CUSTOM_GAME_PACK,
                'custom_key': item.get('custom_key'),
                'custom_snapshot': item.get('custom_snapshot') or {},
                'name': item.get('name'),
                'price': item.get('price'),
                'quantity': item.get('quantity', 1),
                'subtotal': item.get('subtotal', 0),
                'purchase_mode': normalize_purchase_mode(item.get('purchase_mode')),
            })
            continue
        if item.get('line_type') == CART_LINE_SERVICE and item.get('_service_obj'):
            cart_items.append(_build_service_item_dict(item['_service_obj'], item['quantity']))
            continue
        if item.get('game_pack_id'):
            existing = next(
                (
                    cart_item for cart_item in cart_items
                    if cart_item.get('game_pack_id') == item['game_pack_id']
                    and normalize_purchase_mode(cart_item.get('purchase_mode')) == normalize_purchase_mode(item.get('purchase_mode'))
                ),
                None,
            )
            if existing is not None:
                existing['quantity'] = int(existing.get('quantity') or 0) + int(item['quantity'] or 0)
                existing['subtotal'] = (existing.get('price') or 0) * existing['quantity']
            else:
                cart_items.append(
                    _build_game_pack_item_dict(
                        item['_game_pack_obj'],
                        item['quantity'],
                        purchase_mode=item.get('purchase_mode'),
                    )
                )
            continue
        cart_items, _ = _add_product_to_cart_items(
            cart_items,
            item['_product_obj'],
            item['variant_id'],
            item['_variant_obj'],
            item['quantity'],
            purchase_mode=item.get('purchase_mode'),
        )

    if request.user.is_authenticated:
        save_cart_to_db(request, cart_items)
    else:
        save_cart_to_session(request, cart_items)

    if request.headers.get('HX-Request'):
        resp = HttpResponse('<div data-share-modal-close></div>')
        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
        return resp
    return redirect(reverse('catalog:cart'))
