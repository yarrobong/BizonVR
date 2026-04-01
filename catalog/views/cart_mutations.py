import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from ..cart_services import (
    enrich_cart_items,
    get_cart_count,
    get_cart_items,
    save_buy_now_checkout_items,
    save_cart_to_db,
    save_cart_to_session,
)
from ..models import Product, ProductBundle, ProductVariant
from ..pricing import (
    PURCHASE_MODE_ON_REQUEST,
    PURCHASE_MODE_STOCK,
    has_explicit_on_request_price,
    normalize_purchase_mode,
    resolve_in_stock_price,
    resolve_price_for_mode,
)
from .cart import cart_partial
from .common import _get_stock_total


def _cart_item_matches(item, product_id, variant_id=None, purchase_mode=PURCHASE_MODE_STOCK):
    """Позиция корзины совпадает с product_id + variant_id."""
    if item.get('product_id') != product_id:
        return False
    item_vid = item.get('variant_id')
    item_mode = normalize_purchase_mode(item.get('purchase_mode'))
    if variant_id is None and item_vid is None:
        return item_mode == normalize_purchase_mode(purchase_mode)
    return item_vid == variant_id and item_mode == normalize_purchase_mode(purchase_mode)


def _get_next_url(request, fallback_url):
    return request.POST.get('next') or request.GET.get('next') or fallback_url


def _with_cart_error_flag(url):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query['cart_error'] = '1'
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _render_cart_error(request, cart_items, message):
    total = sum(i.get('checkout_subtotal', i.get('subtotal', 0)) for i in cart_items)
    resp = render(request, 'catalog/partials/cart_content.html', {
        'cart_items': cart_items,
        'total': total,
        'cart_error': message,
    })
    resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
    return resp


def _render_or_redirect_cart_error(request, *, cart_items, message, fallback_url):
    if request.headers.get('HX-Request'):
        return _render_cart_error(request, cart_items, message)
    return redirect(_with_cart_error_flag(_get_next_url(request, fallback_url)))


def _get_requested_quantity(request):
    try:
        return max(1, int(request.POST.get('quantity', 1)))
    except (TypeError, ValueError):
        return 1


def _get_requested_purchase_mode(request):
    return normalize_purchase_mode(request.POST.get('purchase_mode'))


def _resolve_purchase_mode(product, variant, requested_mode):
    purchase_mode = normalize_purchase_mode(requested_mode)
    if purchase_mode == PURCHASE_MODE_ON_REQUEST:
        if not product.allow_order_on_request:
            return None, 'Товар недоступен под заказ.'
        if not has_explicit_on_request_price(product, variant):
            return None, 'Для товара не настроена цена под заказ.'
    return purchase_mode, ''


def _get_product_variant(product, product_id, raw_variant_id):
    variant = None
    variant_id = None
    if raw_variant_id:
        try:
            variant_id = int(raw_variant_id)
            variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
            if not variant:
                variant_id = None
        except (TypeError, ValueError):
            variant_id = None
    if not variant:
        variant = None
    return variant_id, variant


@ratelimit(key='ip', rate='60/m', method='POST')
@require_POST
def add_to_cart_view(request, product_id):
    """
    Добавить товар в корзину (сессия). quantity из POST или 1.
    variant_id из POST — вариант товара (цвет, размер и т.п.).
    Если выбран город — ограничиваем количество доступным остатком по городу.
    """
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    variant_id, variant = _get_product_variant(product, product_id, request.POST.get('variant_id'))
    if product.variants.exists() and not variant:
        return _render_or_redirect_cart_error(
            request,
            cart_items=enrich_cart_items(get_cart_items(request)),
            message='Выберите вариант товара.',
            fallback_url=product.get_absolute_url(),
        )
    quantity = _get_requested_quantity(request)
    purchase_mode, purchase_mode_error = _resolve_purchase_mode(
        product,
        variant,
        _get_requested_purchase_mode(request),
    )
    if purchase_mode_error:
        return _render_or_redirect_cart_error(
            request,
            cart_items=enrich_cart_items(get_cart_items(request)),
            message=purchase_mode_error,
            fallback_url=product.get_absolute_url(),
        )

    cart_items = list(get_cart_items(request))
    current_in_cart = sum(
        i.get('quantity', 0) for i in cart_items
        if _cart_item_matches(i, product_id, variant_id, purchase_mode)
    )
    stock_total = _get_stock_total(product_id, variant_id)
    if purchase_mode == PURCHASE_MODE_STOCK and stock_total > 0:
        available = max(0, stock_total - current_in_cart)
        if quantity > available:
            quantity = available
        if quantity <= 0:
            return _render_or_redirect_cart_error(
                request,
                cart_items=enrich_cart_items(cart_items),
                message='Недостаточно товара.',
                fallback_url=product.get_absolute_url(),
            )
    elif purchase_mode == PURCHASE_MODE_STOCK:
        if not getattr(product, 'allow_order_on_request', True):
            return _render_or_redirect_cart_error(
                request,
                cart_items=enrich_cart_items(cart_items),
                message='Товар недоступен для заказа.',
                fallback_url=product.get_absolute_url(),
            )
        if has_explicit_on_request_price(product, variant):
            return _render_or_redirect_cart_error(
                request,
                cart_items=enrich_cart_items(cart_items),
                message='Товар доступен только под заказ. Выберите цену на странице товара.',
                fallback_url=product.get_absolute_url(),
            )

    for item in cart_items:
        if _cart_item_matches(item, product_id, variant_id, purchase_mode):
            item['quantity'] = item.get('quantity', 0) + quantity
            item['subtotal'] = item['price'] * item['quantity']
            break
    else:
        cart_items, added_item = _add_product_to_cart_items(
            cart_items,
            product,
            variant_id,
            variant,
            quantity,
            purchase_mode=purchase_mode,
        )
    if 'added_item' not in locals():
        _, added_item = _add_product_to_cart_items(
            [],
            product,
            variant_id,
            variant,
            quantity,
            purchase_mode=purchase_mode,
        )
    display_name = added_item['name']
    price = added_item['price']
    image_url = added_item['image_url']

    if request.user.is_authenticated:
        save_cart_to_db(request, cart_items)
    else:
        save_cart_to_session(request, cart_items)

    cart_count = get_cart_count(request)

    if request.headers.get('HX-Request'):
        enriched_items = enrich_cart_items(cart_items)
        total = sum(i.get('checkout_subtotal', i.get('subtotal', 0)) for i in enriched_items)
        added_item = {
            'name': display_name,
            'quantity': quantity,
            'price': price,
            'subtotal': price * quantity,
            'image_url': request.build_absolute_uri(image_url) if image_url else '',
        }
        items_preview = [
            {'name': i['name'], 'quantity': i['quantity'], 'subtotal': i['subtotal'], 'image_url': request.build_absolute_uri(i['image_url']) if i.get('image_url') else ''}
            for i in reversed(cart_items[-5:])
        ]
        resp = render(request, 'catalog/partials/cart_content.html', {
            'cart_items': enriched_items,
            'total': total,
        })
        resp['HX-Trigger'] = json.dumps({
            'cart-updated': {
                'count': cart_count,
                'total': total,
                'added_item': added_item,
                'items': items_preview,
            }
        })
        return resp

    return redirect(_get_next_url(request, product.get_absolute_url()))


@require_POST
def cart_update_view(request):
    """
    Обновить количество или удалить позицию (quantity=0). Для HTMX возвращает фрагмент корзины.
    POST: product_id, quantity (0 = удалить), variant_id (опционально).
    Если выбран город — ограничиваем количество остатком.
    """
    product_id = request.POST.get('product_id')
    variant_id = request.POST.get('variant_id')
    purchase_mode = _get_requested_purchase_mode(request)
    try:
        product_id = int(product_id)
        quantity = int(request.POST.get('quantity', 0))
        if variant_id:
            variant_id = int(variant_id)
        else:
            variant_id = None
    except (TypeError, ValueError):
        if request.headers.get('HX-Request'):
            return cart_partial(request)
        return redirect('catalog:product_list')

    cart_items = list(get_cart_items(request))
    existing_index = next(
        (
            idx for idx, item in enumerate(cart_items)
            if _cart_item_matches(item, product_id, variant_id, purchase_mode)
        ),
        None,
    )
    existing_item = cart_items[existing_index] if existing_index is not None else None
    cart_items = [
        i for i in cart_items
        if not _cart_item_matches(i, product_id, variant_id, purchase_mode)
    ]
    if quantity > 0:
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if product:
            variant = None
            if variant_id:
                variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
                if not variant:
                    variant_id = None
            purchase_mode, purchase_mode_error = _resolve_purchase_mode(product, variant, purchase_mode)
            if purchase_mode_error and existing_item is None:
                if request.headers.get('HX-Request'):
                    return _render_cart_error(request, enrich_cart_items(cart_items), purchase_mode_error)
                return redirect(request.POST.get('next') or request.GET.get('next') or reverse('catalog:cart'))
            stock_total = _get_stock_total(product_id, variant_id)
            if purchase_mode == PURCHASE_MODE_STOCK:
                if stock_total > 0:
                    quantity = min(quantity, stock_total)
                elif has_explicit_on_request_price(product, variant):
                    if existing_item is not None:
                        quantity = min(quantity, max(1, int(existing_item.get('quantity') or 1)))
                    else:
                        quantity = 0
            display_name = f'{product.name} ({variant.name})' if variant else product.name
            price = float(resolve_price_for_mode(product, variant, purchase_mode))
            if variant and variant.image:
                image_url = variant.image.url
            else:
                image_url = product.image.url if product.image else ''
            if quantity > 0:
                updated_item = {
                    'product_id': product.pk,
                    'variant_id': variant_id,
                    'variant_name': variant.name if variant else None,
                    'name': display_name,
                    'price': price,
                    'quantity': quantity,
                    'image_url': image_url,
                    'subtotal': price * quantity,
                    'original_price': float(resolve_in_stock_price(product, variant)),
                    'purchase_mode': purchase_mode,
                }
                if existing_index is not None and existing_index <= len(cart_items):
                    cart_items.insert(existing_index, updated_item)
                else:
                    cart_items.append(updated_item)
    if request.user.is_authenticated:
        save_cart_to_db(request, cart_items)
    else:
        save_cart_to_session(request, cart_items)

    if request.headers.get('HX-Request'):
        enriched_items = enrich_cart_items(cart_items)
        total = sum(i.get('checkout_subtotal', i.get('subtotal', 0)) for i in enriched_items)
        from_cart_page = (
            request.headers.get('HX-Target') in ('cart-page-content', 'main-content') or
            (request.META.get('HTTP_REFERER') or '').rstrip('/').endswith('/catalog/cart')
        )
        if from_cart_page:
            if enriched_items:
                slugs = dict(
                    Product.objects.filter(pk__in=[i['product_id'] for i in enriched_items]).values_list('pk', 'slug')
                )
                for item in enriched_items:
                    pid = item['product_id']
                    vid = item.get('variant_id')
                    item['product_slug'] = slugs.get(pid, '')
                    item['stock_total'] = _get_stock_total(pid, vid)
            resp = render(request, 'catalog/partials/cart_page_wrapper.html', {
                'cart_items': enriched_items,
                'total': total,
            })
        else:
            resp = render(request, 'catalog/partials/cart_content.html', {
                'cart_items': enriched_items,
                'total': total,
            })
        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
        if from_cart_page:
            resp['HX-Push-Url'] = reverse('catalog:cart')
        return resp
    next_url = request.POST.get('next') or request.GET.get('next')
    return redirect(next_url or reverse('catalog:cart'))


def _add_product_to_cart_items(
    cart_items, product, variant_id, variant, quantity,
    price_override=None, bundle_id=None, bundle_name=None, purchase_mode=PURCHASE_MODE_STOCK,
):
    """Добавить или обновить позицию товара в cart_items. Возвращает (cart_items, added_item_dict)."""
    display_name = f'{product.name} ({variant.name})' if variant else product.name
    purchase_mode = normalize_purchase_mode(purchase_mode)
    original_price = float(resolve_in_stock_price(product, variant))
    price = float(price_override) if price_override is not None else float(resolve_price_for_mode(product, variant, purchase_mode))
    image_url = (variant.image.url if variant and variant.image else product.image.url) if product.image else ''
    if not image_url and variant and variant.image:
        image_url = variant.image.url
    extra = {
        'bundle_id': bundle_id,
        'bundle_name': bundle_name,
        'original_price': original_price,
        'purchase_mode': purchase_mode,
    }

    def item_matches_bundle(it):
        if it.get('bundle_id') != bundle_id:
            return False
        return _cart_item_matches(it, product.pk, variant_id, purchase_mode)

    for item in cart_items:
        if (bundle_id and item_matches_bundle(item)) or (not bundle_id and _cart_item_matches(item, product.pk, variant_id, purchase_mode)):
            item['quantity'] = item.get('quantity', 0) + quantity
            item['price'] = price
            item['subtotal'] = price * item['quantity']
            item['bundle_id'] = bundle_id
            item['bundle_name'] = bundle_name
            item['original_price'] = extra['original_price']
            item['purchase_mode'] = purchase_mode
            return cart_items, {**{'product_id': product.pk, 'variant_id': variant_id, 'variant_name': variant.name if variant else None, 'name': display_name, 'price': price, 'quantity': quantity, 'image_url': image_url, 'subtotal': price * quantity}, **extra}
    new_item = {
        'product_id': product.pk,
        'variant_id': variant_id,
        'variant_name': variant.name if variant else None,
        'name': display_name,
        'price': price,
        'quantity': quantity,
        'image_url': image_url,
        'subtotal': price * quantity,
        **extra,
    }
    cart_items.append(new_item)
    return cart_items, new_item


def _get_bundle_with_items(raw_bundle_id):
    try:
        bundle_id = int(raw_bundle_id)
    except (TypeError, ValueError):
        return None, []
    bundle = ProductBundle.objects.filter(pk=bundle_id).prefetch_related('items__product', 'items__product__variants').first()
    items = list(bundle.items.select_related('product').all()) if bundle else []
    return bundle, items


def _build_bundle_cart_items(bundle, items, *, base_cart_items=None):
    cart_items = list(base_cart_items or [])
    for item in items:
        product = item.product
        if not product.is_active:
            continue
        variant = product.variants.first()
        variant_id = variant.pk if variant else None
        cart_items, _ = _add_product_to_cart_items(
            cart_items,
            product,
            variant_id,
            variant,
            item.quantity,
            price_override=float(item.effective_price),
            bundle_id=bundle.pk,
            bundle_name=bundle.name or f'Набор #{bundle.pk}',
        )
    return cart_items


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def add_bundle_to_cart_view(request):
    """
    Добавить набор товаров в корзину.
    POST: bundle_id — добавить все товары набора (наборы задаются в админке).
    """
    cart_items = list(get_cart_items(request))
    bundle, items = _get_bundle_with_items(request.POST.get('bundle_id'))

    if bundle:
        if len(items) < 2:
            return _render_or_redirect_cart_error(
                request,
                cart_items=cart_items,
                message='Набор не найден или содержит менее 2 позиций.',
                fallback_url=reverse('catalog:product_list'),
            )

        cart_items = _build_bundle_cart_items(bundle, items, base_cart_items=cart_items)

        if request.user.is_authenticated:
            save_cart_to_db(request, cart_items)
        else:
            save_cart_to_session(request, cart_items)

        if request.headers.get('HX-Request'):
            total = sum(i.get('subtotal', 0) for i in cart_items)
            bundle_total = float(bundle.total_price)
            bundle_image = ''
            if bundle.image:
                bundle_image = request.build_absolute_uri(bundle.image.url)
            elif items:
                first_product = items[0].product
                if first_product.image:
                    bundle_image = request.build_absolute_uri(first_product.image.url)
            added_item = {
                'name': bundle.name or f'Набор #{bundle.pk}',
                'quantity': 1,
                'price': bundle_total,
                'subtotal': bundle_total,
                'image_url': bundle_image,
            }
            items_preview = [
                {
                    'name': i.get('name', ''),
                    'quantity': i.get('quantity', 0),
                    'subtotal': i.get('subtotal', 0),
                    'image_url': request.build_absolute_uri(i['image_url']) if i.get('image_url') else '',
                }
                for i in reversed(cart_items[-5:])
            ]
            resp = render(request, 'catalog/partials/cart_content.html', {
                'cart_items': cart_items,
                'total': total,
            })
            resp['HX-Trigger'] = json.dumps({
                'cart-updated': {
                    'count': get_cart_count(request),
                    'total': total,
                    'added_item': added_item,
                    'items': items_preview,
                }
            })
            return resp
        return redirect(_get_next_url(request, reverse('catalog:product_list')))

    return _render_or_redirect_cart_error(
        request,
        cart_items=cart_items,
        message='Укажите набор (bundle_id).',
        fallback_url=reverse('catalog:product_list'),
    )


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def buy_now_product_view(request, product_id):
    """Подготовить одноразовый checkout только для выбранного товара."""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    variant_id, variant = _get_product_variant(product, product_id, request.POST.get('variant_id'))
    if product.variants.exists() and not variant:
        return _render_or_redirect_cart_error(
            request,
            cart_items=enrich_cart_items(get_cart_items(request)),
            message='Выберите вариант товара.',
            fallback_url=product.get_absolute_url(),
        )

    quantity = _get_requested_quantity(request)
    purchase_mode, purchase_mode_error = _resolve_purchase_mode(
        product,
        variant,
        _get_requested_purchase_mode(request),
    )
    if purchase_mode_error:
        return _render_or_redirect_cart_error(
            request,
            cart_items=enrich_cart_items(get_cart_items(request)),
            message=purchase_mode_error,
            fallback_url=product.get_absolute_url(),
        )
    stock_total = _get_stock_total(product_id, variant_id)
    if purchase_mode == PURCHASE_MODE_STOCK and stock_total > 0 and quantity > stock_total:
        quantity = stock_total
    if purchase_mode == PURCHASE_MODE_STOCK and stock_total > 0 and quantity <= 0:
        return _render_or_redirect_cart_error(
            request,
            cart_items=enrich_cart_items(get_cart_items(request)),
            message='Недостаточно товара.',
            fallback_url=product.get_absolute_url(),
        )
    if purchase_mode == PURCHASE_MODE_STOCK and stock_total <= 0:
        if not getattr(product, 'allow_order_on_request', True):
            return _render_or_redirect_cart_error(
                request,
                cart_items=enrich_cart_items(get_cart_items(request)),
                message='Товар недоступен для заказа.',
                fallback_url=product.get_absolute_url(),
            )
        if has_explicit_on_request_price(product, variant):
            return _render_or_redirect_cart_error(
                request,
                cart_items=enrich_cart_items(get_cart_items(request)),
                message='Товар доступен только под заказ. Выберите цену на странице товара.',
                fallback_url=product.get_absolute_url(),
            )

    buy_now_items, _ = _add_product_to_cart_items(
        [],
        product,
        variant_id,
        variant,
        quantity,
        purchase_mode=purchase_mode,
    )
    save_buy_now_checkout_items(request, buy_now_items)
    return redirect(f"{reverse('orders:checkout')}?mode=buy_now")


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def buy_now_bundle_view(request):
    """Подготовить одноразовый checkout только для выбранного набора."""
    bundle, items = _get_bundle_with_items(request.POST.get('bundle_id'))
    if not bundle or len(items) < 2:
        return _render_or_redirect_cart_error(
            request,
            cart_items=get_cart_items(request),
            message='Набор не найден или содержит менее 2 позиций.',
            fallback_url=_get_next_url(request, reverse('catalog:product_list')),
        )

    buy_now_items = _build_bundle_cart_items(bundle, items)
    save_buy_now_checkout_items(request, buy_now_items)
    return redirect(f"{reverse('orders:checkout')}?mode=buy_now")
