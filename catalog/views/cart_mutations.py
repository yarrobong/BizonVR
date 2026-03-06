import json

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from ..cart_services import get_cart_count, get_cart_items, save_cart_to_db, save_cart_to_session
from ..models import City, Product, ProductBundle, ProductVariant
from .cart import cart_partial
from .common import _get_stock_in_city, _get_stock_total


def _cart_item_matches(item, product_id, variant_id=None):
    """Позиция корзины совпадает с product_id + variant_id."""
    if item.get('product_id') != product_id:
        return False
    item_vid = item.get('variant_id')
    if variant_id is None and item_vid is None:
        return True
    return item_vid == variant_id


@ratelimit(key='ip', rate='60/m', method='POST')
@require_POST
def add_to_cart_view(request, product_id):
    """
    Добавить товар в корзину (сессия). quantity из POST или 1.
    variant_id из POST — вариант товара (цвет, размер и т.п.).
    Если выбран город — ограничиваем количество доступным остатком по городу.
    """
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    variant_id = request.POST.get('variant_id')
    variant = None
    if variant_id:
        try:
            variant_id = int(variant_id)
            variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
            if not variant:
                variant_id = None
                variant = None
        except (TypeError, ValueError):
            variant_id = None
    if product.variants.exists() and not variant:
        if request.headers.get('HX-Request'):
            cart_items_err = get_cart_items(request)
            total = sum(i.get('subtotal', 0) for i in cart_items_err)
            resp = render(request, 'catalog/partials/cart_content.html', {
                'cart_items': cart_items_err,
                'total': total,
                'cart_error': 'Выберите вариант товара.',
            })
            resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
            return resp
        next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
        return redirect(next_url + '?cart_error=1')
    try:
        quantity = max(1, int(request.POST.get('quantity', 1)))
    except (TypeError, ValueError):
        quantity = 1

    cart_items = list(get_cart_items(request))
    current_in_cart = sum(
        i.get('quantity', 0) for i in cart_items
        if _cart_item_matches(i, product_id, variant_id)
    )
    selected_city_id = request.session.get('selected_city_id')
    if selected_city_id:
        stock = _get_stock_in_city(selected_city_id, product_id, variant_id)
        available = max(0, stock - current_in_cart)
        if stock > 0:
            if quantity > available:
                quantity = available
            if quantity <= 0:
                if request.headers.get('HX-Request'):
                    total = sum(i.get('subtotal', 0) for i in cart_items)
                    resp = render(request, 'catalog/partials/cart_content.html', {
                        'cart_items': cart_items,
                        'total': total,
                        'cart_error': 'Недостаточно товара в выбранном городе.',
                    })
                    resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
                    return resp
                next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
                return redirect(next_url + '?cart_error=1')
        else:
            stock_total = _get_stock_total(product_id, variant_id)
            if stock_total > 0:
                available = max(0, stock_total - current_in_cart)
                if quantity > available:
                    quantity = available
                if quantity <= 0:
                    if request.headers.get('HX-Request'):
                        total = sum(i.get('subtotal', 0) for i in cart_items)
                        resp = render(request, 'catalog/partials/cart_content.html', {
                            'cart_items': cart_items,
                            'total': total,
                            'cart_error': 'Недостаточно товара.',
                        })
                        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
                        return resp
                    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
                    return redirect(next_url + '?cart_error=1')
            else:
                if not getattr(product, 'allow_order_on_request', True):
                    if request.headers.get('HX-Request'):
                        total = sum(i.get('subtotal', 0) for i in cart_items)
                        resp = render(request, 'catalog/partials/cart_content.html', {
                            'cart_items': cart_items,
                            'total': total,
                            'cart_error': 'Товар недоступен для заказа.',
                        })
                        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
                        return resp
                    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
                    return redirect(next_url + '?cart_error=1')

    if variant:
        display_name = f'{product.name} ({variant.name})'
        price = float(variant.price)
        image_url = variant.image.url if variant.image else (product.image.url if product.image else '')
    else:
        display_name = product.name
        price = float(product.price)
        image_url = product.image.url if product.image else ''

    for item in cart_items:
        if _cart_item_matches(item, product_id, variant_id):
            item['quantity'] = item.get('quantity', 0) + quantity
            item['subtotal'] = item['price'] * item['quantity']
            break
    else:
        cart_items.append({
            'product_id': product.pk,
            'variant_id': variant_id,
            'variant_name': variant.name if variant else None,
            'name': display_name,
            'price': price,
            'quantity': quantity,
            'image_url': image_url,
            'subtotal': price * quantity,
        })

    if request.user.is_authenticated:
        save_cart_to_db(request, cart_items)
    else:
        save_cart_to_session(request, cart_items)

    cart_count = get_cart_count(request)

    if request.headers.get('HX-Request'):
        total = sum(i.get('subtotal', 0) for i in cart_items)
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
            'cart_items': cart_items,
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

    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
    return redirect(next_url)


@require_POST
def cart_update_view(request):
    """
    Обновить количество или удалить позицию (quantity=0). Для HTMX возвращает фрагмент корзины.
    POST: product_id, quantity (0 = удалить), variant_id (опционально).
    Если выбран город — ограничиваем количество остатком.
    """
    product_id = request.POST.get('product_id')
    variant_id = request.POST.get('variant_id')
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
        (idx for idx, item in enumerate(cart_items) if _cart_item_matches(item, product_id, variant_id)),
        None,
    )
    cart_items = [i for i in cart_items if not _cart_item_matches(i, product_id, variant_id)]
    if quantity > 0:
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if product:
            variant = None
            if variant_id:
                variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
                if not variant:
                    variant_id = None
            selected_city_id = request.session.get('selected_city_id')
            if selected_city_id:
                stock = _get_stock_in_city(selected_city_id, product_id, variant_id)
                if stock > 0:
                    quantity = min(quantity, stock)
                else:
                    stock_total = _get_stock_total(product_id, variant_id)
                    if stock_total > 0:
                        quantity = min(quantity, stock_total)
            if variant:
                display_name = f'{product.name} ({variant.name})'
                price = float(variant.price)
                image_url = variant.image.url if variant.image else (product.image.url if product.image else '')
            else:
                display_name = product.name
                price = float(product.price)
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
        total = sum(i.get('subtotal', 0) for i in cart_items)
        from_cart_page = (
            request.headers.get('HX-Target') in ('cart-page-content', 'main-content') or
            (request.META.get('HTTP_REFERER') or '').rstrip('/').endswith('/catalog/cart')
        )
        if from_cart_page:
            selected_city_id = request.session.get('selected_city_id')
            if cart_items:
                slugs = dict(
                    Product.objects.filter(pk__in=[i['product_id'] for i in cart_items]).values_list('pk', 'slug')
                )
                for item in cart_items:
                    pid = item['product_id']
                    vid = item.get('variant_id')
                    item['product_slug'] = slugs.get(pid, '')
                    item['stock_in_city'] = _get_stock_in_city(selected_city_id, pid, vid) if selected_city_id else None
                    item['stock_total'] = _get_stock_total(pid, vid)
            resp = render(request, 'catalog/partials/cart_page_wrapper.html', {
                'cart_items': cart_items,
                'total': total,
                'selected_city': City.objects.filter(pk=selected_city_id).first() if selected_city_id else None,
            })
        else:
            resp = render(request, 'catalog/partials/cart_content.html', {
                'cart_items': cart_items,
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
    price_override=None, bundle_id=None, bundle_name=None,
):
    """Добавить или обновить позицию товара в cart_items. Возвращает (cart_items, added_item_dict)."""
    display_name = f'{product.name} ({variant.name})' if variant else product.name
    original_price = float(variant.price) if variant else float(product.price)
    price = float(price_override) if price_override is not None else original_price
    image_url = (variant.image.url if variant and variant.image else product.image.url) if product.image else ''
    if not image_url and variant and variant.image:
        image_url = variant.image.url
    extra = {
        'bundle_id': bundle_id,
        'bundle_name': bundle_name,
        'original_price': original_price,
    }

    def item_matches_bundle(it):
        if it.get('bundle_id') != bundle_id:
            return False
        return _cart_item_matches(it, product.pk, variant_id)

    for item in cart_items:
        if (bundle_id and item_matches_bundle(item)) or (not bundle_id and _cart_item_matches(item, product.pk, variant_id)):
            item['quantity'] = item.get('quantity', 0) + quantity
            item['price'] = price
            item['subtotal'] = price * item['quantity']
            item['bundle_id'] = bundle_id
            item['bundle_name'] = bundle_name
            item['original_price'] = extra['original_price']
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


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def add_bundle_to_cart_view(request):
    """
    Добавить набор товаров в корзину.
    POST: bundle_id — добавить все товары набора (наборы задаются в админке).
    """
    cart_items = list(get_cart_items(request))
    bundle_id = request.POST.get('bundle_id')

    if bundle_id:
        try:
            bundle_id = int(bundle_id)
        except (TypeError, ValueError):
            bundle_id = None
        bundle = ProductBundle.objects.filter(pk=bundle_id).prefetch_related('items__product', 'items__product__variants').first()
        items = list(bundle.items.select_related('product').all()) if bundle else []
        if not bundle or len(items) < 2:
            if request.headers.get('HX-Request'):
                total = sum(i.get('subtotal', 0) for i in cart_items)
                resp = render(request, 'catalog/partials/cart_content.html', {
                    'cart_items': cart_items,
                    'total': total,
                    'cart_error': 'Набор не найден или содержит менее 2 позиций.',
                })
                resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
                return resp
            return redirect('catalog:product_list')

        for item in items:
            product = item.product
            if not product.is_active:
                continue
            variant = product.variants.first()
            variant_id = variant.pk if variant else None
            price_in_bundle = float(item.effective_price)
            qty = item.quantity
            cart_items, _ = _add_product_to_cart_items(
                cart_items, product, variant_id, variant, qty,
                price_override=price_in_bundle,
                bundle_id=bundle.pk,
                bundle_name=bundle.name or f'Набор #{bundle.pk}',
            )

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
        next_url = request.POST.get('next') or request.GET.get('next') or reverse('catalog:product_list')
        return redirect(next_url)

    if request.headers.get('HX-Request'):
        total = sum(i.get('subtotal', 0) for i in cart_items)
        resp = render(request, 'catalog/partials/cart_content.html', {
            'cart_items': cart_items,
            'total': total,
            'cart_error': 'Укажите набор (bundle_id).',
        })
        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': get_cart_count(request)}})
        return resp
    return redirect('catalog:product_list')
