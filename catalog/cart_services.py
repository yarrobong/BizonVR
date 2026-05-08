from django.contrib.auth import get_user_model

from .models import CartItem, Favorite, GamePack, Product, ProductBundle, ProductVariant, Service
from .pricing import (
    PURCHASE_MODE_ON_REQUEST,
    PURCHASE_MODE_REQUEST_ONLY,
    PURCHASE_MODE_STOCK,
    has_explicit_in_stock_price,
    has_explicit_on_request_price,
    normalize_purchase_mode,
    resolve_catalog_effective_price,
    resolve_in_stock_base_price,
    resolve_in_stock_price,
    resolve_on_request_price,
    resolve_public_purchase_mode,
)

User = get_user_model()
_MISSING = object()
_REQUEST_CART_ITEMS_ATTR = '_catalog_cart_items_cache'
_REQUEST_CART_COUNT_ATTR = '_catalog_cart_count_cache'
_REQUEST_FAVORITES_ATTR = '_catalog_favorite_product_ids_cache'
BUY_NOW_CHECKOUT_SESSION_KEY = 'buy_now_checkout'
CART_LINE_EQUIPMENT = 'equipment'
CART_LINE_GAME = 'game'
CART_LINE_SERVICE = 'service'
CART_LINE_CUSTOM_GAME_PACK = 'custom_game_pack'
CART_GROUPS = (
    (CART_LINE_EQUIPMENT, 'Оборудование'),
    (CART_LINE_GAME, 'Игры'),
    (CART_LINE_CUSTOM_GAME_PACK, 'Игры'),
    (CART_LINE_SERVICE, 'Услуги'),
)


def _get_request_cached_value(request, attr_name):
    return getattr(request, attr_name, _MISSING)


def _set_request_cached_value(request, attr_name, value):
    setattr(request, attr_name, value)
    return value


def _clear_request_cached_values(request, *attr_names):
    for attr_name in attr_names:
        if hasattr(request, attr_name):
            delattr(request, attr_name)


def invalidate_cart_request_cache(request):
    _clear_request_cached_values(request, _REQUEST_CART_ITEMS_ATTR, _REQUEST_CART_COUNT_ATTR)


def invalidate_favorites_request_cache(request):
    _clear_request_cached_values(request, _REQUEST_FAVORITES_ATTR)


def _float_or_none(value):
    return float(value) if value is not None else None


def _build_game_pack_snapshot(game_pack):
    games = []
    for entry in game_pack.entries.select_related('product').all():
        product = entry.product if entry.product_id else None
        price = resolve_in_stock_price(product) if product is not None else None
        games.append({
            'id': product.pk if product is not None else None,
            'name': product.name if product is not None else entry.unresolved_title,
            'quantity': entry.quantity,
            'price': _float_or_none(price),
            'note': entry.note,
        })

    services = []
    for entry in game_pack.service_entries.select_related('service').all():
        price = entry.effective_price
        service = entry.service if entry.service_id else None
        services.append({
            'id': service.pk if service is not None else None,
            'name': entry.display_title,
            'quantity': entry.quantity,
            'price': _float_or_none(price),
            'note': entry.note,
        })

    return {
        'game_pack_id': game_pack.pk,
        'game_pack_slug': game_pack.slug,
        'games': games,
        'services': services,
    }


def _build_game_pack_item_dict(game_pack, quantity, *, price_override=None, purchase_mode=PURCHASE_MODE_STOCK):
    purchase_mode = normalize_purchase_mode(purchase_mode)
    original_price = _float_or_none(resolve_in_stock_base_price(game_pack))
    price = _float_or_none(price_override if price_override is not None else resolve_in_stock_price(game_pack))
    image_url = ''
    display_image = game_pack.get_display_image()
    if display_image is not None:
        try:
            image_url = display_image.url
        except (AttributeError, ValueError):
            image_url = ''
    return {
        'product_id': None,
        'variant_id': None,
        'variant_name': None,
        'game_pack_id': game_pack.pk,
        'game_pack_slug': game_pack.slug,
        'name': game_pack.name,
        'price': price,
        'quantity': quantity,
        'image_url': image_url,
        'subtotal': (price or 0) * quantity,
        'bundle_id': None,
        'bundle_name': None,
        'original_price': original_price,
        'purchase_mode': purchase_mode,
        'line_type': CART_LINE_GAME,
        'service_id': None,
        'custom_key': '',
        'custom_snapshot': _build_game_pack_snapshot(game_pack),
    }


def _build_service_item_dict(service, quantity=1):
    price = _float_or_none(service.price)
    image_url = ''
    return {
        'product_id': None,
        'variant_id': None,
        'variant_name': None,
        'game_pack_id': None,
        'game_pack_slug': '',
        'service_id': service.pk,
        'name': service.name,
        'price': price,
        'quantity': quantity,
        'image_url': image_url,
        'subtotal': (price or 0) * quantity,
        'bundle_id': None,
        'bundle_name': None,
        'original_price': price,
        'purchase_mode': PURCHASE_MODE_STOCK,
        'line_type': CART_LINE_SERVICE,
        'custom_key': '',
        'custom_snapshot': {
            'service_kind': service.service_kind,
            'short_description': service.short_description,
            'price_from': service.price_from,
        },
    }


def build_custom_game_pack_item_dict(*, name, game_ids, games, services=None, quantity=1, headset_count=1, club_format='', devices='', audience=''):
    game_lines = []
    total = 0
    for game in games:
        price = resolve_in_stock_price(game) or 0
        total += float(price)
        game_lines.append({
            'id': game.pk,
            'name': game.name,
            'price': _float_or_none(price),
        })
    custom_key = 'custom-games-' + '-'.join(str(pk) for pk in sorted(game_ids))
    snapshot = {
        'game_ids': list(game_ids),
        'games': game_lines,
        'services': services or [],
        'headset_count': headset_count,
        'club_format': club_format,
        'devices': devices,
        'audience': audience,
    }
    return {
        'product_id': None,
        'variant_id': None,
        'variant_name': None,
        'game_pack_id': None,
        'game_pack_slug': '',
        'service_id': None,
        'name': name or 'Индивидуальный комплект игр для VR-клуба',
        'price': total,
        'quantity': quantity,
        'image_url': '',
        'subtotal': total * quantity,
        'bundle_id': None,
        'bundle_name': None,
        'original_price': total,
        'purchase_mode': PURCHASE_MODE_STOCK,
        'line_type': CART_LINE_CUSTOM_GAME_PACK,
        'custom_key': custom_key,
        'custom_snapshot': snapshot,
    }


def _cart_item_to_dict(item, product=None, variant=None, game_pack=None):
    if not hasattr(item, 'product_id'):
        return item
    if getattr(item, 'game_pack_id', None):
        gp = item.game_pack if game_pack is None else game_pack
        data = _build_game_pack_item_dict(
            gp,
            item.quantity,
            price_override=item.price_override,
            purchase_mode=getattr(item, 'purchase_mode', PURCHASE_MODE_STOCK),
        )
        if getattr(item, 'custom_snapshot', None):
            data['custom_snapshot'] = item.custom_snapshot
        return data
    if getattr(item, 'service_id', None):
        return _build_service_item_dict(item.service, item.quantity)
    if getattr(item, 'line_type', '') == CART_LINE_CUSTOM_GAME_PACK:
        snapshot = dict(getattr(item, 'custom_snapshot', None) or {})
        price = _float_or_none(item.price_override)
        quantity = item.quantity
        return {
            'product_id': None,
            'variant_id': None,
            'variant_name': None,
            'game_pack_id': None,
            'game_pack_slug': '',
            'service_id': None,
            'name': snapshot.get('name') or 'Индивидуальный комплект игр для VR-клуба',
            'price': price,
            'quantity': quantity,
            'image_url': '',
            'subtotal': (price or 0) * quantity,
            'bundle_id': None,
            'bundle_name': None,
            'original_price': price,
            'purchase_mode': PURCHASE_MODE_STOCK,
            'line_type': CART_LINE_CUSTOM_GAME_PACK,
            'custom_key': snapshot.get('custom_key') or '',
            'custom_snapshot': snapshot,
        }

    p = item.product if product is None else product
    v = item.variant if variant is None else variant
    purchase_mode = normalize_purchase_mode(getattr(item, 'purchase_mode', PURCHASE_MODE_STOCK))
    display_name = f'{p.name} ({v.name})' if v else p.name
    original_price = _float_or_none(resolve_in_stock_base_price(p, v))
    bundle = getattr(item, 'bundle', None)
    if bundle:
        price = original_price
    else:
        price = float(item.price_override) if getattr(item, 'price_override', None) is not None else original_price
    bundle_id = bundle.pk if bundle else None
    bundle_name = bundle.name if bundle else None
    image_url = (v.image.url if v and v.image else p.image.url) if p.image else ''
    if v and v.image:
        image_url = v.image.url
    elif p.image:
        image_url = p.image.url
    return {
        'product_id': p.pk,
        'variant_id': v.pk if v else None,
        'variant_name': v.name if v else None,
        'game_pack_id': None,
        'game_pack_slug': '',
        'name': display_name,
        'price': price,
        'quantity': item.quantity,
        'image_url': image_url,
        'subtotal': (price or 0) * item.quantity,
        'bundle_id': bundle_id,
        'bundle_name': bundle_name,
        'original_price': original_price,
        'purchase_mode': purchase_mode,
        'line_type': CART_LINE_EQUIPMENT,
        'service_id': None,
        'custom_key': '',
        'custom_snapshot': {},
    }


def _normalize_session_bundle_prices(session_items):
    normalized_items = []
    changed = False

    product_ids = [item.get('product_id') for item in session_items if item.get('product_id')]
    variant_ids = [item.get('variant_id') for item in session_items if item.get('variant_id')]
    game_pack_ids = [item.get('game_pack_id') for item in session_items if item.get('game_pack_id')]
    service_ids = [item.get('service_id') for item in session_items if item.get('service_id')]
    products = Product.objects.filter(pk__in=product_ids, is_active=True).in_bulk() if product_ids else {}
    variants = (
        ProductVariant.objects.filter(pk__in=variant_ids, product_id__in=product_ids).select_related('product').in_bulk()
        if variant_ids else {}
    )
    game_packs = GamePack.objects.filter(pk__in=game_pack_ids, is_active=True).in_bulk() if game_pack_ids else {}
    services = Service.objects.filter(pk__in=service_ids, is_active=True).in_bulk() if service_ids else {}

    for raw_item in session_items:
        item = dict(raw_item)
        normalized_mode = normalize_purchase_mode(item.get('purchase_mode'))
        if item.get('purchase_mode') != normalized_mode:
            item['purchase_mode'] = normalized_mode
            changed = True

        if item.get('game_pack_id'):
            game_pack = game_packs.get(item.get('game_pack_id'))
            if game_pack:
                refreshed = _build_game_pack_item_dict(game_pack, max(0, int(item.get('quantity') or 0)), purchase_mode=normalized_mode)
                refreshed['subtotal'] = refreshed['price'] * refreshed['quantity'] if refreshed['price'] is not None else 0
                if refreshed != {**item, **{k: item.get(k) for k in []}}:
                    item.update(refreshed)
                    changed = True
        elif item.get('service_id'):
            service = services.get(item.get('service_id'))
            if service:
                refreshed = _build_service_item_dict(service, max(1, int(item.get('quantity') or 1)))
                if refreshed != item:
                    item.update(refreshed)
                    changed = True
        elif item.get('line_type') == CART_LINE_CUSTOM_GAME_PACK:
            item.setdefault('product_id', None)
            item.setdefault('variant_id', None)
            item.setdefault('game_pack_id', None)
            item.setdefault('service_id', None)
            item.setdefault('bundle_id', None)
            item.setdefault('purchase_mode', PURCHASE_MODE_STOCK)
            item.setdefault('custom_snapshot', {})
            item.setdefault('custom_key', item.get('custom_snapshot', {}).get('custom_key', ''))
            item['quantity'] = max(1, int(item.get('quantity') or 1))
            item['subtotal'] = (item.get('price') or 0) * item['quantity']
        elif item.get('bundle_id'):
            product = products.get(item.get('product_id'))
            variant_id = item.get('variant_id')
            variant = variants.get(variant_id) if variant_id else None
            current_price = _float_or_none(resolve_in_stock_price(product, variant)) if product else None
            regular_price = _float_or_none(resolve_in_stock_base_price(product, variant)) if product else None
            if current_price is not None:
                quantity = max(0, int(item.get('quantity') or 0))
                expected_subtotal = current_price * quantity
                if item.get('price') != current_price:
                    item['price'] = current_price
                    changed = True
                if item.get('original_price') != regular_price:
                    item['original_price'] = regular_price
                    changed = True
                if item.get('subtotal') != expected_subtotal:
                    item['subtotal'] = expected_subtotal
                    changed = True
        normalized_items.append(item)

    return normalized_items, changed


def get_cart_items(request):
    cached_items = _get_request_cached_value(request, _REQUEST_CART_ITEMS_ATTR)
    if cached_items is not _MISSING:
        return cached_items

    if request.user.is_authenticated:
        items = (
            CartItem.objects
            .filter(user=request.user)
            .select_related('product', 'variant', 'bundle', 'game_pack')
            .select_related('service')
            .order_by('id')
        )
        result = []
        for ci in items:
            if ci.game_pack_id:
                if not ci.game_pack.is_active:
                    continue
            elif ci.service_id:
                if not ci.service.is_active:
                    continue
            elif ci.line_type == CART_LINE_CUSTOM_GAME_PACK:
                pass
            elif not ci.product or not ci.product.is_active:
                continue
            result.append(_cart_item_to_dict(ci))
        return _set_request_cached_value(request, _REQUEST_CART_ITEMS_ATTR, result)

    session_items = request.session.get('cart_items', []) or []
    normalized_items, changed = _normalize_session_bundle_prices(session_items)
    if changed:
        request.session['cart_items'] = normalized_items
        request.session.modified = True
    return _set_request_cached_value(request, _REQUEST_CART_ITEMS_ATTR, normalized_items)


def get_cart_count(request):
    cached_count = _get_request_cached_value(request, _REQUEST_CART_COUNT_ATTR)
    if cached_count is not _MISSING:
        return cached_count
    count = sum(i.get('quantity', 0) for i in get_cart_items(request))
    return _set_request_cached_value(request, _REQUEST_CART_COUNT_ATTR, count)


def save_cart_to_session(request, cart_items):
    request.session['cart_items'] = cart_items
    request.session.modified = True
    invalidate_cart_request_cache(request)


def clear_cart(request):
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user).delete()
    else:
        request.session.pop('cart_items', None)
        request.session.modified = True
    invalidate_cart_request_cache(request)


def get_buy_now_checkout_items(request):
    payload = request.session.get(BUY_NOW_CHECKOUT_SESSION_KEY) or {}
    items = payload.get('items')
    if not isinstance(items, list):
        return []
    normalized_items, changed = _normalize_session_bundle_prices(items)
    if changed:
        request.session[BUY_NOW_CHECKOUT_SESSION_KEY] = {'items': normalized_items}
        request.session.modified = True
    return normalized_items


def save_buy_now_checkout_items(request, cart_items):
    request.session[BUY_NOW_CHECKOUT_SESSION_KEY] = {'items': cart_items}
    request.session.modified = True


def clear_buy_now_checkout_items(request):
    request.session.pop(BUY_NOW_CHECKOUT_SESSION_KEY, None)
    request.session.modified = True


def build_cart_item_signature(item):
    return (
        item.get('line_type') or CART_LINE_EQUIPMENT,
        item.get('product_id'),
        item.get('variant_id'),
        normalize_purchase_mode(item.get('purchase_mode')),
        item.get('bundle_id'),
        item.get('game_pack_id'),
        item.get('service_id'),
        item.get('custom_key') or item.get('custom_snapshot', {}).get('custom_key', ''),
    )


def build_cart_item_share_key(item):
    line_type, product_id, variant_id, purchase_mode, bundle_id, game_pack_id, service_id, custom_key = build_cart_item_signature(item)
    product_part = product_id if product_id is not None else 'none'
    return f'{line_type}:{product_part}:{variant_id if variant_id is not None else "none"}:{purchase_mode}:{bundle_id if bundle_id is not None else "none"}:{game_pack_id if game_pack_id is not None else "none"}:{service_id if service_id is not None else "none"}:{custom_key or "none"}'


def remove_cart_items(request, items_to_remove):
    signatures = {
        build_cart_item_signature(item)
        for item in items_to_remove
        if item.get('product_id') or item.get('game_pack_id') or item.get('service_id') or item.get('line_type') == CART_LINE_CUSTOM_GAME_PACK
    }
    if not signatures:
        return

    if request.user.is_authenticated:
        existing_items = list(
            CartItem.objects.filter(user=request.user).values(
                'id', 'line_type', 'product_id', 'variant_id', 'purchase_mode', 'bundle_id', 'game_pack_id', 'service_id', 'custom_snapshot'
            )
        )
        ids_to_delete = [
            row['id']
            for row in existing_items
            if (
                row['line_type'] or CART_LINE_EQUIPMENT,
                row['product_id'],
                row['variant_id'],
                normalize_purchase_mode(row['purchase_mode']),
                row['bundle_id'],
                row['game_pack_id'],
                row['service_id'],
                (row['custom_snapshot'] or {}).get('custom_key', ''),
            ) in signatures
        ]
        if ids_to_delete:
            CartItem.objects.filter(id__in=ids_to_delete).delete()
    else:
        session_items = request.session.get('cart_items', []) or []
        request.session['cart_items'] = [item for item in session_items if build_cart_item_signature(item) not in signatures]
        request.session.modified = True
    invalidate_cart_request_cache(request)


def enrich_cart_items(cart_items):
    if not cart_items:
        return []

    from .views.common import ALWAYS_AVAILABLE_STOCK_TOTAL, _get_stock_total

    product_ids = [item.get('product_id') for item in cart_items if item.get('product_id')]
    variant_ids = [item.get('variant_id') for item in cart_items if item.get('variant_id')]
    game_pack_ids = [item.get('game_pack_id') for item in cart_items if item.get('game_pack_id')]
    service_ids = [item.get('service_id') for item in cart_items if item.get('service_id')]
    products = Product.objects.filter(pk__in=product_ids, is_active=True).in_bulk()
    variants = ProductVariant.objects.filter(pk__in=variant_ids, product_id__in=product_ids).select_related('product').in_bulk()
    game_packs = GamePack.objects.filter(pk__in=game_pack_ids, is_active=True).in_bulk()
    services = Service.objects.filter(pk__in=service_ids, is_active=True).in_bulk()

    enriched = []
    for raw_item in cart_items:
        item = dict(raw_item)
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
        quantity = max(0, int(item.get('quantity') or 0))
        item['purchase_mode'] = purchase_mode
        item['purchase_mode_label'] = 'Под заказ' if purchase_mode == PURCHASE_MODE_ON_REQUEST else 'Из наличия'
        item['share_item_key'] = build_cart_item_share_key(item)
        item['is_stock_purchase'] = purchase_mode == PURCHASE_MODE_STOCK
        item['is_on_request_purchase'] = purchase_mode == PURCHASE_MODE_ON_REQUEST
        item['line_type'] = item.get('line_type') or (CART_LINE_GAME if item.get('game_pack_id') else CART_LINE_EQUIPMENT)

        game_pack = game_packs.get(item.get('game_pack_id')) if item.get('game_pack_id') else None
        if game_pack is not None:
            item['product_slug'] = ''
            item['game_pack_slug'] = game_pack.slug
            item['stock_total'] = 1
            item['is_game_pack'] = True
            item['supports_on_request_price'] = bool(has_explicit_on_request_price(game_pack))
            item['price_in_stock'] = _float_or_none(resolve_in_stock_price(game_pack))
            item['price_on_request'] = _float_or_none(resolve_on_request_price(game_pack))
            item['catalog_effective_price'] = _float_or_none(resolve_catalog_effective_price(game_pack, stock_total=1))
            item['public_purchase_mode'] = resolve_public_purchase_mode(game_pack, stock_total=1)
            item['is_request_only'] = item['public_purchase_mode'] == PURCHASE_MODE_REQUEST_ONLY
            item['has_in_stock_price'] = has_explicit_in_stock_price(game_pack)
            item['is_checkout_available'] = item['public_purchase_mode'] != PURCHASE_MODE_REQUEST_ONLY or purchase_mode == PURCHASE_MODE_ON_REQUEST
            item['checkout_unavailable_reason'] = '' if item['is_checkout_available'] else 'Игровой пак доступен только по заявке.'
            item['checkout_subtotal'] = (item.get('subtotal') or 0) if item['is_checkout_available'] else 0
            enriched.append(item)
            continue

        service = services.get(item.get('service_id')) if item.get('service_id') else None
        if service is not None:
            item['product_slug'] = ''
            item['game_pack_slug'] = ''
            item['stock_total'] = 1
            item['is_game_pack'] = False
            item['is_service'] = True
            item['is_custom_game_pack'] = False
            item['supports_on_request_price'] = False
            item['price_in_stock'] = _float_or_none(service.price)
            item['price_on_request'] = None
            item['catalog_effective_price'] = _float_or_none(service.price)
            item['public_purchase_mode'] = PURCHASE_MODE_STOCK if service.price is not None else PURCHASE_MODE_REQUEST_ONLY
            item['is_request_only'] = service.price is None
            item['has_in_stock_price'] = service.price is not None
            item['is_checkout_available'] = service.price is not None
            item['checkout_unavailable_reason'] = '' if service.price is not None else 'Услуга оформляется по запросу.'
            item['checkout_subtotal'] = (item.get('subtotal') or 0) if item['is_checkout_available'] else 0
            enriched.append(item)
            continue

        if item.get('line_type') == CART_LINE_CUSTOM_GAME_PACK:
            item['product_slug'] = ''
            item['game_pack_slug'] = ''
            item['stock_total'] = 1
            item['is_game_pack'] = False
            item['is_service'] = False
            item['is_custom_game_pack'] = True
            item['supports_on_request_price'] = False
            item['price_in_stock'] = _float_or_none(item.get('price'))
            item['price_on_request'] = None
            item['catalog_effective_price'] = _float_or_none(item.get('price'))
            item['public_purchase_mode'] = PURCHASE_MODE_STOCK
            item['is_request_only'] = False
            item['has_in_stock_price'] = True
            item['is_checkout_available'] = True
            item['checkout_unavailable_reason'] = ''
            item['checkout_subtotal'] = item.get('subtotal') or 0
            enriched.append(item)
            continue

        product = products.get(item.get('product_id'))
        variant_id = item.get('variant_id')
        variant = variants.get(variant_id) if variant_id else None
        stock_total = (
            _get_stock_total(item.get('product_id'), variant_id)
            if product and product.tracks_stock
            else ALWAYS_AVAILABLE_STOCK_TOTAL if product else 0
        )
        item['product_slug'] = product.slug if product else ''
        item['stock_total'] = stock_total
        item['game_pack_slug'] = ''
        item['is_game_pack'] = bool(product and product.is_game_pack)
        item['is_service'] = False
        item['is_custom_game_pack'] = False
        item['supports_on_request_price'] = bool(product and has_explicit_on_request_price(product, variant))

        if product:
            item['price_in_stock'] = _float_or_none(resolve_in_stock_price(product, variant))
            item['price_on_request'] = _float_or_none(resolve_on_request_price(product, variant))
            item['catalog_effective_price'] = _float_or_none(resolve_catalog_effective_price(product, variant, stock_total=stock_total))
            item['public_purchase_mode'] = resolve_public_purchase_mode(product, variant, stock_total=stock_total)
            item['is_request_only'] = item['public_purchase_mode'] == PURCHASE_MODE_REQUEST_ONLY
            item['has_in_stock_price'] = has_explicit_in_stock_price(product, variant)
        else:
            item['price_in_stock'] = _float_or_none(item.get('original_price') or item.get('price'))
            item['price_on_request'] = None
            item['catalog_effective_price'] = _float_or_none(item.get('price'))
            item['public_purchase_mode'] = PURCHASE_MODE_REQUEST_ONLY
            item['is_request_only'] = True
            item['has_in_stock_price'] = False

        is_checkout_available = True
        checkout_unavailable_reason = ''
        if not product or (variant_id and not variant):
            is_checkout_available = False
            checkout_unavailable_reason = 'Товар больше недоступен.'
        elif purchase_mode == PURCHASE_MODE_ON_REQUEST:
            if not product.allow_order_on_request or not has_explicit_on_request_price(product, variant):
                is_checkout_available = False
                checkout_unavailable_reason = 'Товар больше нельзя оформить под заказ.'
        elif ((product.tracks_stock and (stock_total <= 0 or stock_total < quantity)) or not has_explicit_in_stock_price(product, variant)):
            is_checkout_available = False
            checkout_unavailable_reason = (
                'Только под заказ.'
                if product.allow_order_on_request and has_explicit_on_request_price(product, variant)
                else 'Товар доступен только по заявке.'
            )
        item['is_checkout_available'] = is_checkout_available
        item['checkout_unavailable_reason'] = checkout_unavailable_reason
        item['checkout_subtotal'] = (item.get('subtotal') or 0) if is_checkout_available else 0
        enriched.append(item)
    return enriched


def group_cart_items(cart_items):
    groups_map = {
        CART_LINE_EQUIPMENT: {'key': CART_LINE_EQUIPMENT, 'title': 'Оборудование', 'items': [], 'subtotal': 0, 'quantity': 0},
        CART_LINE_GAME: {'key': CART_LINE_GAME, 'title': 'Игры', 'items': [], 'subtotal': 0, 'quantity': 0},
        CART_LINE_SERVICE: {'key': CART_LINE_SERVICE, 'title': 'Услуги', 'items': [], 'subtotal': 0, 'quantity': 0},
    }
    for item in cart_items:
        line_type = item.get('line_type') or CART_LINE_EQUIPMENT
        group_key = CART_LINE_SERVICE if line_type == CART_LINE_SERVICE else CART_LINE_GAME if line_type in {CART_LINE_GAME, CART_LINE_CUSTOM_GAME_PACK} else CART_LINE_EQUIPMENT
        group = groups_map[group_key]
        group['items'].append(item)
        group['subtotal'] += item.get('checkout_subtotal', item.get('subtotal', 0)) or 0
        group['quantity'] += item.get('quantity', 0) or 0
    return [group for group in groups_map.values() if group['items']]


def save_cart_to_db(request, cart_items):
    if not request.user.is_authenticated:
        return
    CartItem.objects.filter(user=request.user).delete()
    for item in cart_items:
        quantity = item.get('quantity', 1)
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
        if quantity <= 0:
            continue
        if item.get('line_type') == CART_LINE_CUSTOM_GAME_PACK:
            from decimal import Decimal
            snapshot = dict(item.get('custom_snapshot') or {})
            snapshot['name'] = item.get('name') or snapshot.get('name') or 'Индивидуальный комплект игр для VR-клуба'
            snapshot['custom_key'] = item.get('custom_key') or snapshot.get('custom_key') or ''
            CartItem.objects.create(
                user=request.user,
                line_type=CART_LINE_CUSTOM_GAME_PACK,
                quantity=quantity,
                price_override=Decimal(str(item.get('price') or 0)),
                custom_snapshot=snapshot,
            )
            continue
        service_id = item.get('service_id')
        if service_id:
            service = Service.objects.filter(pk=service_id, is_active=True).first()
            if not service:
                continue
            CartItem.objects.create(
                user=request.user,
                service=service,
                line_type=CART_LINE_SERVICE,
                quantity=quantity,
                price_override=service.price,
                custom_snapshot=item.get('custom_snapshot') or {},
            )
            continue
        game_pack_id = item.get('game_pack_id')
        if game_pack_id:
            game_pack = GamePack.objects.filter(pk=game_pack_id, is_active=True).first()
            if not game_pack:
                continue
            from decimal import Decimal
            CartItem.objects.create(
                user=request.user,
                game_pack=game_pack,
                line_type=CART_LINE_GAME,
                quantity=quantity,
                price_override=Decimal(str(item.get('price') or 0)),
                purchase_mode=purchase_mode,
                custom_snapshot=item.get('custom_snapshot') or {},
            )
            continue
        product_id = item.get('product_id')
        if not product_id:
            continue
        variant_id = item.get('variant_id')
        bundle_id = item.get('bundle_id')
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if not product:
            continue
        variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first() if variant_id else None
        bundle = ProductBundle.objects.filter(pk=bundle_id).first() if bundle_id else None
        override = None
        if not bundle and item.get('price') is not None:
            from decimal import Decimal
            selected_price = Decimal(str(item['price']))
            base_price = resolve_in_stock_price(product, variant)
            if selected_price != base_price:
                override = selected_price
        CartItem.objects.create(
            user=request.user,
            product=product,
            variant=variant,
            quantity=quantity,
            bundle=bundle,
            line_type=CART_LINE_EQUIPMENT,
            price_override=override,
            purchase_mode=purchase_mode,
        )
    invalidate_cart_request_cache(request)


def merge_session_cart_into_user(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return
    session_items = request.session.get('cart_items', []) or []
    if not session_items:
        return
    from decimal import Decimal
    for item in session_items:
        quantity = item.get('quantity', 1)
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
        if quantity <= 0:
            continue
        if item.get('line_type') == CART_LINE_CUSTOM_GAME_PACK:
            snapshot = dict(item.get('custom_snapshot') or {})
            custom_key = item.get('custom_key') or snapshot.get('custom_key') or ''
            snapshot['custom_key'] = custom_key
            snapshot['name'] = item.get('name') or snapshot.get('name') or 'Индивидуальный комплект игр для VR-клуба'
            cart_item = CartItem.objects.create(
                user=user,
                line_type=CART_LINE_CUSTOM_GAME_PACK,
                quantity=quantity,
                price_override=Decimal(str(item.get('price') or 0)),
                custom_snapshot=snapshot,
            )
            continue
        service_id = item.get('service_id')
        if service_id:
            service = Service.objects.filter(pk=service_id, is_active=True).first()
            if not service:
                continue
            cart_item, created = CartItem.objects.get_or_create(
                user=user,
                service=service,
                defaults={
                    'line_type': CART_LINE_SERVICE,
                    'quantity': quantity,
                    'price_override': service.price,
                    'custom_snapshot': item.get('custom_snapshot') or {},
                },
            )
            if not created:
                cart_item.quantity += quantity
                cart_item.save(update_fields=['quantity'])
            continue
        game_pack_id = item.get('game_pack_id')
        if game_pack_id:
            game_pack = GamePack.objects.filter(pk=game_pack_id, is_active=True).first()
            if not game_pack:
                continue
            cart_item, created = CartItem.objects.get_or_create(
                user=user,
                game_pack=game_pack,
                purchase_mode=purchase_mode,
                defaults={'quantity': quantity},
            )
            if not created:
                cart_item.quantity += quantity
                cart_item.save(update_fields=['quantity'])
            continue

        product_id = item.get('product_id')
        variant_id = item.get('variant_id')
        bundle_id = item.get('bundle_id')
        price_override = None
        if not product_id:
            continue
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if not product:
            continue
        variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first() if variant_id else None
        bundle = ProductBundle.objects.filter(pk=bundle_id).first() if bundle_id else None
        if not bundle and item.get('price') is not None:
            selected_price = Decimal(str(item['price']))
            base_price = resolve_in_stock_price(product, variant)
            if selected_price != base_price:
                price_override = selected_price
        cart_item, created = CartItem.objects.get_or_create(
            user=user,
            product=product,
            variant=variant,
            bundle=bundle,
            purchase_mode=purchase_mode,
            defaults={'quantity': quantity, 'price_override': price_override},
        )
        if not created:
            cart_item.quantity += quantity
            update_fields = ['quantity']
            if cart_item.price_override != price_override:
                cart_item.price_override = price_override
                update_fields.append('price_override')
            cart_item.save(update_fields=update_fields)
    request.session.pop('cart_items', None)
    request.session.modified = True
    invalidate_cart_request_cache(request)


def get_favorite_product_ids(request):
    cached_ids = _get_request_cached_value(request, _REQUEST_FAVORITES_ATTR)
    if cached_ids is not _MISSING:
        return cached_ids
    if request.user.is_authenticated:
        favorite_ids = set(Favorite.objects.filter(user=request.user).values_list('product_id', flat=True))
        return _set_request_cached_value(request, _REQUEST_FAVORITES_ATTR, favorite_ids)
    favorite_ids = set(request.session.get('favorite_product_ids', []) or [])
    return _set_request_cached_value(request, _REQUEST_FAVORITES_ATTR, favorite_ids)


def is_favorite(request, product_id):
    return product_id in get_favorite_product_ids(request)


def merge_session_favorites_into_user(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return
    product_ids = request.session.get('favorite_product_ids', []) or []
    if not product_ids:
        return
    products = Product.objects.filter(pk__in=product_ids, is_active=True)
    for product in products:
        Favorite.objects.get_or_create(user=user, product=product)
    request.session.pop('favorite_product_ids', None)
    request.session.modified = True
    invalidate_favorites_request_cache(request)
