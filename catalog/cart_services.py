"""
Сервисы корзины и избранного: привязка к профилю, слияние при входе.
"""
from django.contrib.auth import get_user_model

from .models import CartItem, CompareItem, Favorite, Product, ProductVariant

User = get_user_model()
COMPARE_LIMIT = 4
_MISSING = object()
_REQUEST_CART_ITEMS_ATTR = '_catalog_cart_items_cache'
_REQUEST_CART_COUNT_ATTR = '_catalog_cart_count_cache'
_REQUEST_FAVORITES_ATTR = '_catalog_favorite_product_ids_cache'
_REQUEST_COMPARE_IDS_ATTR = '_catalog_compare_product_ids_cache'
_REQUEST_COMPARE_COUNT_ATTR = '_catalog_compare_count_cache'


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


def invalidate_compare_request_cache(request):
    _clear_request_cached_values(request, _REQUEST_COMPARE_IDS_ATTR, _REQUEST_COMPARE_COUNT_ATTR)


def _cart_item_to_dict(item, product=None, variant=None):
    """Преобразовать CartItem в dict формата сессии (включая bundle и скидку)."""
    if not hasattr(item, 'product_id'):
        return item
    p = item.product if product is None else product
    v = item.variant if variant is None else variant
    display_name = f'{p.name} ({v.name})' if v else p.name
    original_price = float(v.price) if v else float(p.price)
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
    }


def _ensure_subtotal(item_dict):
    """Добавить subtotal в dict позиции."""
    q = item_dict.get('quantity', 1)
    p = item_dict.get('price', 0)
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
            d['subtotal'] = d['price'] * d['quantity']
            result.append(d)
        return _set_request_cached_value(request, _REQUEST_CART_ITEMS_ATTR, result)
    session_items = request.session.get('cart_items', []) or []
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
        # Цена в комплекте сохраняем как price_override
        override = None
        if bundle_id and item.get('price') is not None:
            from decimal import Decimal
            override = Decimal(str(item['price']))
        CartItem.objects.create(
            user=request.user,
            product=product,
            variant=variant,
            quantity=quantity,
            bundle=bundle,
            price_override=override,
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
        price_override = None
        if bundle_id and item.get('price') is not None:
            price_override = Decimal(str(item['price']))
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
        cart_item, created = CartItem.objects.get_or_create(
            user=user,
            product=product,
            variant=variant,
            bundle=bundle,
            defaults={'quantity': quantity, 'price_override': price_override},
        )
        if not created:
            cart_item.quantity += quantity
            cart_item.save(update_fields=['quantity'])
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


def get_compare_product_ids(request):
    """ID товаров в сравнении: для авторизованного — из БД, для анонима — из сессии."""
    cached_ids = _get_request_cached_value(request, _REQUEST_COMPARE_IDS_ATTR)
    if cached_ids is not _MISSING:
        return cached_ids

    if request.user.is_authenticated:
        compare_ids = list(
            CompareItem.objects.filter(user=request.user)
            .order_by('created_at', 'id')
            .values_list('product_id', flat=True)
        )
        return _set_request_cached_value(request, _REQUEST_COMPARE_IDS_ATTR, compare_ids)
    compare_ids = list(request.session.get('compare_product_ids', []) or [])
    return _set_request_cached_value(request, _REQUEST_COMPARE_IDS_ATTR, compare_ids)


def get_compare_count(request):
    """Количество товаров в сравнении."""
    cached_count = _get_request_cached_value(request, _REQUEST_COMPARE_COUNT_ATTR)
    if cached_count is not _MISSING:
        return cached_count
    compare_count = len(get_compare_product_ids(request))
    return _set_request_cached_value(request, _REQUEST_COMPARE_COUNT_ATTR, compare_count)


def is_compared(request, product_id):
    """Товар уже добавлен в сравнение."""
    return product_id in set(get_compare_product_ids(request))


def save_compare_to_session(request, product_ids):
    """Сохранить список сравнения в сессию."""
    request.session['compare_product_ids'] = list(product_ids)
    request.session.modified = True
    invalidate_compare_request_cache(request)


def toggle_compare(request, product):
    """
    Добавить или убрать товар из сравнения.
    Возвращает (is_compared_now, compare_ids, limit_reached).
    """
    compare_ids = get_compare_product_ids(request)
    product_id = product.pk

    if request.user.is_authenticated:
        existing = CompareItem.objects.filter(user=request.user, product=product).first()
        if existing:
            existing.delete()
            compare_ids = [pid for pid in compare_ids if pid != product_id]
            invalidate_compare_request_cache(request)
            return False, compare_ids, False
        if len(compare_ids) >= COMPARE_LIMIT:
            return False, compare_ids, True
        CompareItem.objects.create(user=request.user, product=product)
        compare_ids = [pid for pid in compare_ids if pid != product_id] + [product_id]
        invalidate_compare_request_cache(request)
        return True, compare_ids, False

    original_compare_ids = list(compare_ids)
    compare_ids = [pid for pid in compare_ids if pid != product_id]
    was_compared = len(compare_ids) != len(original_compare_ids)
    if was_compared:
        save_compare_to_session(request, compare_ids)
        return False, compare_ids, False
    if len(compare_ids) >= COMPARE_LIMIT:
        return False, compare_ids, True
    compare_ids.append(product_id)
    save_compare_to_session(request, compare_ids)
    return True, compare_ids, False


def merge_session_compare_into_user(request):
    """Слить сравнение из сессии в профиль при входе."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return
    product_ids = request.session.get('compare_product_ids', []) or []
    if not product_ids:
        return
    existing_ids = get_compare_product_ids(request)
    merged_ids = []
    for pid in product_ids + existing_ids:
        if pid not in merged_ids:
            merged_ids.append(pid)
        if len(merged_ids) >= COMPARE_LIMIT:
            break

    active_products = Product.objects.filter(pk__in=merged_ids, is_active=True).in_bulk()
    CompareItem.objects.filter(user=user).delete()
    for pid in merged_ids:
        product = active_products.get(pid)
        if product:
            CompareItem.objects.create(user=user, product=product)

    request.session.pop('compare_product_ids', None)
    request.session.modified = True
    invalidate_compare_request_cache(request)
