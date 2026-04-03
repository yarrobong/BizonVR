"""
Сервисы корзины и избранного: привязка к профилю, слияние при входе.
"""
from django.contrib.auth import get_user_model

from .models import CartItem, Favorite, Product, ProductVariant
from .pricing import (
    PURCHASE_MODE_ON_REQUEST,
    PURCHASE_MODE_REQUEST_ONLY,
    PURCHASE_MODE_STOCK,
    has_explicit_in_stock_price,
    has_explicit_on_request_price,
    normalize_purchase_mode,
    resolve_catalog_effective_price,
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


def _cart_item_to_dict(item, product=None, variant=None):
    """Преобразовать CartItem в dict формата сессии (включая bundle и скидку)."""
    if not hasattr(item, 'product_id'):
        return item
    p = item.product if product is None else product
    v = item.variant if variant is None else variant
    purchase_mode = normalize_purchase_mode(getattr(item, 'purchase_mode', PURCHASE_MODE_STOCK))
    display_name = f'{p.name} ({v.name})' if v else p.name
    original_price = _float_or_none(resolve_in_stock_price(p, v))
    price = float(item.price_override) if getattr(item, 'price_override', None) is not None else original_price
    bundle = getattr(item, 'bundle', None)
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
        'name': display_name,
        'price': price,
        'quantity': item.quantity,
        'image_url': image_url,
        'subtotal': 0,
        'bundle_id': bundle_id,
        'bundle_name': bundle_name,
        'original_price': original_price,
        'purchase_mode': purchase_mode,
    }


def _ensure_subtotal(item_dict):
    """Добавить subtotal в dict позиции."""
    q = item_dict.get('quantity', 1)
    p = item_dict.get('price') or 0
    item_dict['subtotal'] = p * q
    return item_dict


def get_cart_items(request):
    """
    Корзина: для авторизованного — из БД, для анонима — из сессии.
    Возвращает список dict с ключами product_id, variant_id, name, price, quantity, subtotal, image_url.
    """
    cached_items = _get_request_cached_value(request, _REQUEST_CART_ITEMS_ATTR)
    if cached_items is not _MISSING:
        return cached_items

    if request.user.is_authenticated:
        # Явно сохраняем порядок вставки позиций в корзину.
        items = (
            CartItem.objects
            .filter(user=request.user)
            .select_related('product', 'variant', 'bundle')
            .order_by('id')
        )
        result = []
        for ci in items:
            if not ci.product.is_active:
                continue
            d = _cart_item_to_dict(ci)
            d['subtotal'] = (d['price'] or 0) * d['quantity']
            result.append(d)
        return _set_request_cached_value(request, _REQUEST_CART_ITEMS_ATTR, result)
    session_items = request.session.get('cart_items', []) or []
    for item in session_items:
        item['purchase_mode'] = normalize_purchase_mode(item.get('purchase_mode'))
    return _set_request_cached_value(request, _REQUEST_CART_ITEMS_ATTR, session_items)


def get_cart_count(request):
    """Количество товаров в корзине (сумма quantity)."""
    cached_count = _get_request_cached_value(request, _REQUEST_CART_COUNT_ATTR)
    if cached_count is not _MISSING:
        return cached_count
    items = get_cart_items(request)
    count = sum(i.get('quantity', 0) for i in items)
    return _set_request_cached_value(request, _REQUEST_CART_COUNT_ATTR, count)


def save_cart_to_session(request, cart_items):
    """Сохранить корзину в сессии (для анонима)."""
    request.session['cart_items'] = cart_items
    request.session.modified = True
    invalidate_cart_request_cache(request)


def clear_cart(request):
    """Очистить корзину после оформления заказа."""
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user).delete()
    else:
        request.session.pop('cart_items', None)
        request.session.modified = True
    invalidate_cart_request_cache(request)


def get_buy_now_checkout_items(request):
    """Получить одноразовый состав заказа для сценария `Купить сейчас`."""
    payload = request.session.get(BUY_NOW_CHECKOUT_SESSION_KEY) or {}
    items = payload.get('items')
    return items if isinstance(items, list) else []


def save_buy_now_checkout_items(request, cart_items):
    """Сохранить одноразовый состав заказа для сценария `Купить сейчас`."""
    request.session[BUY_NOW_CHECKOUT_SESSION_KEY] = {
        'items': cart_items,
    }
    request.session.modified = True


def clear_buy_now_checkout_items(request):
    """Очистить одноразовый состав заказа для сценария `Купить сейчас`."""
    request.session.pop(BUY_NOW_CHECKOUT_SESSION_KEY, None)
    request.session.modified = True


def build_cart_item_signature(item):
    """Уникальный ключ позиции корзины с учётом режима покупки и комплекта."""
    return (
        item.get('product_id'),
        item.get('variant_id'),
        normalize_purchase_mode(item.get('purchase_mode')),
        item.get('bundle_id'),
    )


def build_cart_item_share_key(item):
    product_id, variant_id, purchase_mode, bundle_id = build_cart_item_signature(item)
    return f'{product_id}:{variant_id if variant_id is not None else "none"}:{purchase_mode}:{bundle_id if bundle_id is not None else "none"}'


def remove_cart_items(request, items_to_remove):
    """Удалить из корзины конкретные позиции, не трогая остальные."""
    signatures = {
        build_cart_item_signature(item)
        for item in items_to_remove
        if item.get('product_id')
    }
    if not signatures:
        return

    if request.user.is_authenticated:
        existing_items = list(
            CartItem.objects
            .filter(user=request.user)
            .values('id', 'product_id', 'variant_id', 'purchase_mode', 'bundle_id')
        )
        ids_to_delete = [
            row['id']
            for row in existing_items
            if (
                row['product_id'],
                row['variant_id'],
                normalize_purchase_mode(row['purchase_mode']),
                row['bundle_id'],
            ) in signatures
        ]
        if ids_to_delete:
            CartItem.objects.filter(id__in=ids_to_delete).delete()
    else:
        session_items = request.session.get('cart_items', []) or []
        request.session['cart_items'] = [
            item for item in session_items
            if build_cart_item_signature(item) not in signatures
        ]
        request.session.modified = True

    invalidate_cart_request_cache(request)


def enrich_cart_items(cart_items):
    """Добавить в позиции корзины режим покупки, актуальное наличие и статус checkout."""
    if not cart_items:
        return []

    from .views.common import _get_stock_total

    product_ids = [item.get('product_id') for item in cart_items if item.get('product_id')]
    variant_ids = [item.get('variant_id') for item in cart_items if item.get('variant_id')]
    products = Product.objects.filter(pk__in=product_ids, is_active=True).in_bulk()
    variants = ProductVariant.objects.filter(
        pk__in=variant_ids,
        product_id__in=product_ids,
    ).select_related('product').in_bulk()

    enriched = []
    for raw_item in cart_items:
        item = dict(raw_item)
        product = products.get(item.get('product_id'))
        variant_id = item.get('variant_id')
        variant = variants.get(variant_id) if variant_id else None
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
        stock_total = _get_stock_total(item.get('product_id'), variant_id) if product else 0
        quantity = max(0, int(item.get('quantity') or 0))
        product_slug = product.slug if product else ''
        bundle_id = item.get('bundle_id')

        item['purchase_mode'] = purchase_mode
        item['purchase_mode_label'] = (
            'Под заказ'
            if purchase_mode == PURCHASE_MODE_ON_REQUEST
            else 'Из наличия'
        )
        item['product_slug'] = product_slug
        item['stock_total'] = stock_total
        item['share_item_key'] = build_cart_item_share_key(item)
        item['is_stock_purchase'] = purchase_mode == PURCHASE_MODE_STOCK
        item['is_on_request_purchase'] = purchase_mode == PURCHASE_MODE_ON_REQUEST
        item['supports_on_request_price'] = bool(product and has_explicit_on_request_price(product, variant))

        if product:
            in_stock_price = resolve_in_stock_price(product, variant)
            on_request_price = resolve_on_request_price(product, variant)
            public_purchase_mode = resolve_public_purchase_mode(product, variant, stock_total=stock_total)
            item['price_in_stock'] = _float_or_none(in_stock_price)
            item['price_on_request'] = _float_or_none(on_request_price)
            item['catalog_effective_price'] = _float_or_none(resolve_catalog_effective_price(product, variant, stock_total=stock_total))
            item['public_purchase_mode'] = public_purchase_mode
            item['is_request_only'] = public_purchase_mode == PURCHASE_MODE_REQUEST_ONLY
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
        elif stock_total <= 0 or stock_total < quantity or not has_explicit_in_stock_price(product, variant):
            is_checkout_available = False
            checkout_unavailable_reason = (
                'Только под заказ.'
                if product.allow_order_on_request and has_explicit_on_request_price(product, variant)
                else 'Товар доступен только по заявке.'
            )

        item['is_checkout_available'] = is_checkout_available
        item['checkout_unavailable_reason'] = checkout_unavailable_reason
        item['checkout_subtotal'] = (item.get('subtotal') or 0) if is_checkout_available else 0
        item['bundle_id'] = bundle_id
        enriched.append(item)
    return enriched


def save_cart_to_db(request, cart_items):
    """Сохранить корзину в БД (для авторизованного). Перезаписывает существующую корзину."""
    if not request.user.is_authenticated:
        return
    CartItem.objects.filter(user=request.user).delete()
    for item in cart_items:
        product_id = item.get('product_id')
        variant_id = item.get('variant_id')
        quantity = item.get('quantity', 1)
        bundle_id = item.get('bundle_id')
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
        if not product_id or quantity <= 0:
            continue
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if not product:
            continue
        variant = None
        if variant_id:
            variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
        bundle = None
        if bundle_id:
            from .models import ProductBundle
            bundle = ProductBundle.objects.filter(pk=bundle_id).first()
        # Сохраняем выбранную цену, если она отличается от обычной цены из наличия.
        override = None
        if item.get('price') is not None:
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
            price_override=override,
            purchase_mode=purchase_mode,
        )
    invalidate_cart_request_cache(request)


def merge_session_cart_into_user(request):
    """Слить корзину из сессии в профиль пользователя при входе."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return
    session_items = request.session.get('cart_items', []) or []
    if not session_items:
        return
    from .models import ProductBundle
    from decimal import Decimal
    for item in session_items:
        product_id = item.get('product_id')
        variant_id = item.get('variant_id')
        quantity = item.get('quantity', 1)
        bundle_id = item.get('bundle_id')
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
        price_override = None
        if not product_id or quantity <= 0:
            continue
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if not product:
            continue
        variant = None
        if variant_id:
            variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
        bundle = None
        if bundle_id:
            bundle = ProductBundle.objects.filter(pk=bundle_id).first()
        if item.get('price') is not None:
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
    """ID товаров в избранном: для авторизованного — из БД, для анонима — из сессии."""
    cached_ids = _get_request_cached_value(request, _REQUEST_FAVORITES_ATTR)
    if cached_ids is not _MISSING:
        return cached_ids

    if request.user.is_authenticated:
        favorite_ids = set(
            Favorite.objects.filter(user=request.user)
            .values_list('product_id', flat=True)
        )
        return _set_request_cached_value(request, _REQUEST_FAVORITES_ATTR, favorite_ids)
    favorite_ids = set(request.session.get('favorite_product_ids', []) or [])
    return _set_request_cached_value(request, _REQUEST_FAVORITES_ATTR, favorite_ids)


def is_favorite(request, product_id):
    """Товар в избранном."""
    return product_id in get_favorite_product_ids(request)


def merge_session_favorites_into_user(request):
    """Слить избранное из сессии в профиль при входе."""
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
