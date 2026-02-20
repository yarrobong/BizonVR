import json
import re
from datetime import timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.db.models import Case, Count, F, IntegerField, Q, Sum, Value, When
from django.db.utils import ProgrammingError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, ListView
from django_ratelimit.decorators import ratelimit

from .cart_services import clear_cart, get_cart_count, get_cart_items, save_cart_to_db, save_cart_to_session
from .models import CartShare, CatalogSection, Category, City, Favorite, PickupPoint, Product, ProductBundle, ProductBundleItem, ProductCharacteristic, ProductStock, ProductTag, ProductVariant
from .recommendations import build_pdp_recommendations

FOOTER_PRODUCTS_ROWS_PER_BATCH = 3
FOOTER_PRODUCTS_COLS = 5
FOOTER_PRODUCTS_MAX_PAGES = 8
CART_SHARE_TTL_DAYS = 30


def _footer_products_page_size(layout: str) -> int:
    """Размер пачки = 3 строки × 5 колонок."""
    return FOOTER_PRODUCTS_ROWS_PER_BATCH * FOOTER_PRODUCTS_COLS


def _get_stock_in_city(city_id, product_id, variant_id=None):
    """Суммарный остаток товара по городу. variant_id — для товаров с вариантами."""
    if not city_id:
        return None
    qs = ProductStock.objects.filter(
        product_id=product_id,
        pickup_point__city_id=city_id,
    )
    if variant_id is not None:
        qs = qs.filter(variant_id=variant_id)
    else:
        qs = qs.filter(variant__isnull=True)
    total = qs.aggregate(s=Sum('quantity'))
    return (total['s'] or 0)


def _get_stock_total(product_id, variant_id=None):
    """Суммарный остаток товара по всей России. variant_id — для товаров с вариантами."""
    qs = ProductStock.objects.filter(product_id=product_id)
    if variant_id is not None:
        qs = qs.filter(variant_id=variant_id)
    else:
        qs = qs.filter(variant__isnull=True)
    total = qs.aggregate(s=Sum('quantity'))
    return (total['s'] or 0)


def _safe_redirect_target(url, request):
    """Проверка, что URL безопасен для редиректа (внутренний или относительный путь)."""
    if not url:
        return False
    if url.startswith('/') and not url.startswith('//'):
        return True
    return url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()})


def _enrich_cart_items_for_page(cart_items, selected_city_id):
    """Добавить в позиции корзины slug и наличие для рендера страницы корзины."""
    if not cart_items:
        return cart_items
    slugs = dict(
        Product.objects.filter(pk__in=[i['product_id'] for i in cart_items]).values_list('pk', 'slug')
    )
    for item in cart_items:
        pid = item['product_id']
        vid = item.get('variant_id')
        key = (pid, vid)
        item['product_slug'] = slugs.get(pid, '')
        item['stock_in_city'] = _get_stock_in_city(selected_city_id, pid, vid) if selected_city_id else None
        item['stock_total'] = _get_stock_total(pid, vid)
        item['share_item_key'] = f"{pid}:{vid if vid is not None else 'none'}"
    return cart_items


def _parse_share_item_key(raw_key):
    """Разобрать ключ позиции в формате product_id:variant_id|none."""
    if not raw_key or ':' not in raw_key:
        return None
    product_part, variant_part = raw_key.split(':', 1)
    try:
        product_id = int(product_part)
    except (TypeError, ValueError):
        return None
    if variant_part in ('', 'none', 'null'):
        return product_id, None
    try:
        variant_id = int(variant_part)
    except (TypeError, ValueError):
        return None
    return product_id, variant_id


def _generate_cart_share_code():
    """Сгенерировать короткий уникальный код шаринга корзины."""
    for _ in range(12):
        code = get_random_string(7, allowed_chars='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
        if not CartShare.objects.filter(code=code).exists():
            return code
    return get_random_string(7)


def _resolve_cart_share_items(items_payload, selected_city_id=None):
    """
    Преобразовать payload шаринга в карточки с актуальными данными товара.
    Удалённые/неактивные товары и невалидные варианты пропускаются.
    """
    normalized = []
    product_ids = set()
    variant_pairs = set()
    for raw_item in items_payload or []:
        if not isinstance(raw_item, dict):
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
        try:
            quantity = max(1, int(raw_item.get('quantity', 1)))
        except (TypeError, ValueError):
            quantity = 1
        normalized.append({
            'product_id': product_id,
            'variant_id': variant_id,
            'quantity': quantity,
        })
        product_ids.add(product_id)
        if variant_id is not None:
            variant_pairs.add((product_id, variant_id))

    if not normalized:
        return []

    products = Product.objects.filter(pk__in=product_ids, is_active=True).only('id', 'name', 'slug', 'price', 'image')
    product_map = {p.pk: p for p in products}
    variant_ids = [pair[1] for pair in variant_pairs]
    variants = ProductVariant.objects.filter(
        product_id__in=product_ids,
        pk__in=variant_ids,
    ).select_related('product')
    variant_map = {(v.product_id, v.pk): v for v in variants}

    resolved = []
    for item in normalized:
        product_id = item['product_id']
        variant_id = item['variant_id']
        quantity = item['quantity']
        product = product_map.get(product_id)
        if not product:
            continue
        variant = None
        if variant_id is not None:
            variant = variant_map.get((product_id, variant_id))
            if variant is None:
                continue
        price = float(variant.price) if variant else float(product.price)
        image_url = ''
        if variant and variant.image:
            image_url = variant.image.url
        elif product.image:
            image_url = product.image.url
        resolved.append({
            'product_id': product_id,
            'variant_id': variant_id,
            'variant_name': variant.name if variant else None,
            'name': product.name,
            'price': price,
            'quantity': quantity,
            'subtotal': price * quantity,
            'image_url': image_url,
            'product_slug': product.slug,
            '_product_obj': product,
            '_variant_obj': variant,
            'stock_in_city': _get_stock_in_city(selected_city_id, product_id, variant_id) if selected_city_id else None,
            'stock_total': _get_stock_total(product_id, variant_id),
        })
    return resolved


@require_POST
def set_city_view(request):
    """Установить выбранный город в сессии. Редирект на next, referer или каталог."""
    city_id = request.POST.get('city_id')
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if not _safe_redirect_target(next_url, request):
        next_url = reverse('catalog:product_list')
    # На главной при смене города — в каталог, чтобы сразу видеть наличие
    if next_url:
        path = urlparse(next_url).path if '//' in next_url else next_url
        if path.rstrip('/') == '':
            next_url = reverse('catalog:product_list')
    if city_id:
        try:
            city_id = int(city_id)
            if City.objects.filter(pk=city_id).exists():
                request.session['selected_city_id'] = city_id
                request.session.modified = True
        except (TypeError, ValueError):
            pass
    else:
        request.session.pop('selected_city_id', None)
        request.session.modified = True
    return redirect(next_url)


def cart_page_view(request):
    """Отдельная страница корзины: список товаров, изменение количества, переход к оформлению."""
    cart_items = get_cart_items(request)
    total = sum(item.get('subtotal', 0) for item in cart_items)
    selected_city_id = request.session.get('selected_city_id')
    _enrich_cart_items_for_page(cart_items, selected_city_id)

    shared_cart_items = []
    shared_cart_code = ''
    shared_modal_open = False
    shared_invalid = False
    shared_total = 0
    shared_quantity = 0
    share_code = (request.GET.get('share') or '').strip()
    if share_code:
        shared_modal_open = True
        shared_cart_code = share_code
        cart_share = CartShare.objects.filter(code=share_code, expires_at__gt=timezone.now()).first()
        if cart_share:
            shared_cart_code = cart_share.code
            shared_cart_items = _resolve_cart_share_items(cart_share.items, selected_city_id)
            shared_total = sum(item.get('subtotal', 0) for item in shared_cart_items)
            shared_quantity = sum(item.get('quantity', 0) for item in shared_cart_items)
        else:
            shared_invalid = True

    return render(request, 'catalog/cart.html', {
        'cart_items': cart_items,
        'total': total,
        'selected_city': City.objects.filter(pk=selected_city_id).first() if selected_city_id else None,
        'shared_cart_items': shared_cart_items,
        'shared_cart_code': shared_cart_code,
        'shared_modal_open': shared_modal_open,
        'shared_invalid': shared_invalid,
        'shared_total': shared_total,
        'shared_quantity': shared_quantity,
    })


def cart_partial(request):
    """Фрагмент корзины для модального окна (HTMX)."""
    cart_items = get_cart_items(request)
    total = sum(item.get('subtotal', 0) for item in cart_items)
    return render(request, 'catalog/partials/cart_content.html', {'cart_items': cart_items, 'total': total})


@require_POST
def cart_clear_view(request):
    """Очистить корзину. Для HTMX возвращает обновлённый фрагмент/страницу корзины."""
    clear_cart(request)

    if request.headers.get('HX-Request'):
        from_cart_page = (
            request.headers.get('HX-Target') in ('cart-page-content', 'main-content') or
            (request.META.get('HTTP_REFERER') or '').rstrip('/').endswith('/catalog/cart')
        )
        if from_cart_page:
            selected_city_id = request.session.get('selected_city_id')
            resp = render(request, 'catalog/partials/cart_page_wrapper.html', {
                'cart_items': [],
                'total': 0,
                'selected_city': City.objects.filter(pk=selected_city_id).first() if selected_city_id else None,
            })
            resp['HX-Push-Url'] = reverse('catalog:cart')
        else:
            resp = render(request, 'catalog/partials/cart_content.html', {
                'cart_items': [],
                'total': 0,
            })
        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': 0}})
        return resp

    next_url = request.POST.get('next') or request.GET.get('next') or reverse('catalog:cart')
    return redirect(next_url)


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def cart_share_create_view(request):
    """Создать ссылку шаринга выбранных позиций корзины и вернуть модальное окно."""
    selected_raw = (request.POST.get('selected_item_keys') or '').strip()
    selected_pairs = []
    selected_pairs_set = set()
    for raw_key in selected_raw.split(','):
        parsed = _parse_share_item_key(raw_key.strip())
        if parsed and parsed not in selected_pairs_set:
            selected_pairs.append(parsed)
            selected_pairs_set.add(parsed)

    if not selected_pairs:
        return render(request, 'catalog/partials/cart_share_modal.html', {
            'modal_mode': 'source',
            'share_items': [],
            'share_error': 'Выберите хотя бы один товар для шаринга.',
        }, status=400)

    selected_payload = []
    for item in get_cart_items(request):
        try:
            item_product_id = int(item.get('product_id'))
        except (TypeError, ValueError):
            continue
        raw_item_variant_id = item.get('variant_id')
        if raw_item_variant_id in (None, '', 'none', 'null'):
            item_variant_id = None
        else:
            try:
                item_variant_id = int(raw_item_variant_id)
            except (TypeError, ValueError):
                continue
        item_key = (item_product_id, item_variant_id)
        if item_key in selected_pairs_set:
            try:
                quantity = max(1, int(item.get('quantity', 1) or 1))
            except (TypeError, ValueError):
                quantity = 1
            selected_payload.append({
                'product_id': item_product_id,
                'variant_id': item_variant_id,
                'quantity': quantity,
            })

    selected_city_id = request.session.get('selected_city_id')
    resolved_items = _resolve_cart_share_items(selected_payload, selected_city_id)
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
            'quantity': item['quantity'],
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
    """Добавить все товары из shared-ссылки в текущую корзину."""
    share_code = (request.POST.get('share_code') or '').strip()
    if not share_code:
        return HttpResponse('Не указан код шаринга.', status=400)

    share = CartShare.objects.filter(code=share_code, expires_at__gt=timezone.now()).first()
    if not share:
        return HttpResponse('Ссылка недействительна или истекла.', status=400)

    selected_city_id = request.session.get('selected_city_id')
    resolved_items = _resolve_cart_share_items(share.items, selected_city_id)
    if not resolved_items:
        return HttpResponse('В ссылке нет доступных товаров.', status=400)

    cart_items = list(get_cart_items(request))
    for item in resolved_items:
        cart_items, _ = _add_product_to_cart_items(
            cart_items,
            item['_product_obj'],
            item['variant_id'],
            item['_variant_obj'],
            item['quantity'],
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

    cart_items = list(get_cart_items(request))  # копия для изменения
    current_in_cart = sum(
        i.get('quantity', 0) for i in cart_items
        if _cart_item_matches(i, product_id, variant_id)
    )
    selected_city_id = request.session.get('selected_city_id')
    if selected_city_id:
        stock = _get_stock_in_city(selected_city_id, product_id, variant_id)
        available = max(0, stock - current_in_cart)
        if stock > 0:
            # Товар в наличии — ограничиваем остатком
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
            # Товара нет в городе — проверяем общий остаток по России
            stock_total = _get_stock_total(product_id, variant_id)
            if stock_total > 0:
                # В наличии в другом городе — ограничиваем общим остатком
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
                # Нет нигде — под заказ (если разрешено)
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
                    # иначе stock_total == 0 — под заказ, quantity не ограничиваем
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
        # HTMX от страницы корзины — возвращаем контент страницы (hx-target или Referer)
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
    # Для позиций из комплекта совпадение — по product+variant+bundle_id
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


class BundleDetailView(DetailView):
    """Страница набора: описание, состав, кнопка «Купить комплект»."""
    model = ProductBundle
    context_object_name = 'bundle'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/bundle_detail.html'

    def get_queryset(self):
        return ProductBundle.objects.prefetch_related(
            'items__product', 'items__product__images'
        ).annotate(items_count=Count('items')).filter(items_count__gte=2)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bundle = self.object
        items = list(bundle.items.select_related('product').all())
        for item in items:
            item.line_total = float(item.effective_price) * item.quantity
        context['bundle_items'] = items
        context['total_without_discount'] = float(bundle.total_price_without_discount)
        context['total_with_discount'] = float(bundle.total_price)
        context['discount_total'] = context['total_without_discount'] - context['total_with_discount']
        selected_city_id = self.request.session.get('selected_city_id')
        context['selected_city'] = City.objects.filter(pk=selected_city_id).first() if selected_city_id else None
        if context['selected_city']:
            context['pickup_points_count'] = PickupPoint.objects.filter(city=context['selected_city']).count()
        else:
            context['pickup_points_count'] = 0
        context['bundles_category'] = Category.objects.filter(is_bundles_category=True).first()
        return context


class ProductListView(ListView):
    """Список товаров с фильтрацией по категории, пагинацией и сортировкой."""
    model = Product
    context_object_name = 'products'
    paginate_by = 20
    template_name = 'catalog/product_list.html'

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('tags', 'characteristics', 'variants', 'images').order_by('-created_at')
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            qs = qs.filter(
                Q(name__icontains=search_query) | Q(description__icontains=search_query)
            )
        category_slug = self.request.GET.get('category')
        if category_slug:
            cat = Category.objects.filter(slug=category_slug).first()
            if cat and getattr(cat, 'is_bundles_category', False):
                return Product.objects.none()
            qs = qs.filter(category__slug=category_slug)
        section_slug = self.request.GET.get('section')
        if section_slug:
            qs = qs.filter(category__section__slug=section_slug)
        tag_slug = (self.request.GET.get('tag') or '').strip()
        if tag_slug:
            qs = qs.filter(tags__slug=tag_slug).distinct()
        # Фильтр по цене
        price_min = self.request.GET.get('price_min')
        if price_min:
            try:
                qs = qs.filter(price__gte=float(price_min))
            except (ValueError, TypeError):
                pass
        price_max = self.request.GET.get('price_max')
        if price_max:
            try:
                qs = qs.filter(price__lte=float(price_max))
            except (ValueError, TypeError):
                pass
        # Фильтр по характеристикам (char_<name>=<value>)
        for key, value in self.request.GET.items():
            if key.startswith('char_') and value:
                ch_name = key[5:]
                qs = qs.filter(characteristics__name=ch_name, characteristics__value=value).distinct()
        sort = self.request.GET.get('sort', 'newest')
        # При поиске по умолчанию сортируем по релевантности
        if search_query and sort == 'newest':
            sort = 'relevance'

        if sort == 'relevance' and search_query:
            qs = qs.annotate(
                relevance=Case(
                    When(name__istartswith=search_query, then=Value(3)),
                    When(name__icontains=search_query, then=Value(2)),
                    When(description__icontains=search_query, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ).order_by('-relevance', '-created_at')
        elif sort == 'price_asc':
            qs = qs.order_by('price')
        elif sort == 'price_desc':
            qs = qs.order_by('-price')
        elif sort == 'name':
            qs = qs.order_by('name')
        elif sort == 'popularity':
            qs = qs.annotate(
                favorited_count=Count('favorited_by', distinct=True),
                cart_count=Count('cart_items', distinct=True),
            ).annotate(
                popularity=F('views_count') + F('favorited_count') * 5 + F('cart_count') * 3
            ).order_by('-popularity', '-created_at')
        elif sort == 'relevance' and not search_query:
            qs = qs.order_by('-created_at')
        else:
            qs = qs.order_by('-created_at')
        return qs

    def _get_filter_base_queryset(self):
        """Базовый queryset для сбора опций фильтров (без пагинации, без char-фильтров)."""
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants', 'images')
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            qs = qs.filter(
                Q(name__icontains=search_query) | Q(description__icontains=search_query)
            )
        category_slug = self.request.GET.get('category')
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        section_slug = self.request.GET.get('section')
        if section_slug:
            qs = qs.filter(category__section__slug=section_slug)
        tag_slug = (self.request.GET.get('tag') or '').strip()
        if tag_slug:
            qs = qs.filter(tags__slug=tag_slug).distinct()
        price_min = self.request.GET.get('price_min')
        if price_min:
            try:
                qs = qs.filter(price__gte=float(price_min))
            except (ValueError, TypeError):
                pass
        price_max = self.request.GET.get('price_max')
        if price_max:
            try:
                qs = qs.filter(price__lte=float(price_max))
            except (ValueError, TypeError):
                pass
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_catalog_root'] = not self.request.GET
        context['current_category'] = self.request.GET.get('category', '')
        context['current_section'] = self.request.GET.get('section', '')
        context['categories'] = list(Category.objects.select_related('section').order_by('name'))
        if context['current_section']:
            context['categories'] = [c for c in context['categories'] if c.section and c.section.slug == context['current_section']]
        context['catalog_sections'] = list(CatalogSection.objects.prefetch_related('categories').order_by('order', 'name'))
        context['current_tag'] = (self.request.GET.get('tag') or '').strip()
        sort = self.request.GET.get('sort', 'newest')
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query and sort == 'newest':
            sort = 'relevance'
        context['current_sort'] = sort
        context['search_query'] = (self.request.GET.get('q') or '').strip()
        context['price_min_filter'] = self.request.GET.get('price_min', '')
        context['price_max_filter'] = self.request.GET.get('price_max', '')
        context['char_filters'] = {k[5:]: v for k, v in self.request.GET.items() if k.startswith('char_') and v}
        context['filter_clear'] = ''  # для filter_url: удалить параметр

        # UI-контекст для иерархии категорий в фильтрах
        selected_category = None
        if context['current_category']:
            selected_category = Category.objects.select_related('section').filter(slug=context['current_category']).first()
        effective_section_slug = context['current_section'] or (
            selected_category.section.slug if selected_category and selected_category.section else ''
        )
        context['current_section_effective'] = effective_section_slug
        context['current_category_obj'] = selected_category
        context['is_bundles_category'] = bool(
            selected_category and getattr(selected_category, 'is_bundles_category', False)
        )

        # Для категории «Наборы» — список комплектов с пагинацией
        if context['is_bundles_category']:
            bundles_qs = (
                ProductBundle.objects
                .prefetch_related('items__product', 'items__product__images')
                .annotate(items_count=Count('items'))
                .filter(items_count__gte=2)
                .order_by('name')
            )
            paginator = Paginator(bundles_qs, self.paginate_by)
            page_number = self.request.GET.get('page', 1)
            try:
                page_number = max(1, int(page_number))
            except (TypeError, ValueError):
                page_number = 1
            bundle_page = paginator.get_page(page_number)
            context['bundles'] = bundle_page.object_list
            context['bundle_page_obj'] = bundle_page
        else:
            context['bundles'] = []
            context['bundle_page_obj'] = None

        # Опции фильтров из товаров текущего раздела
        base_qs = self._get_filter_base_queryset()
        from django.db.models import Min, Max
        price_agg = base_qs.aggregate(min_p=Min('price'), max_p=Max('price'))
        context['filter_price_min'] = int(price_agg['min_p']) if price_agg['min_p'] is not None else 0
        context['filter_price_max'] = int(price_agg['max_p']) if price_agg['max_p'] is not None else 0

        tags_qs = ProductTag.objects.order_by('order', 'name')
        if effective_section_slug:
            tags_qs = tags_qs.filter(products__category__section__slug=effective_section_slug)
        context['product_tags'] = list(tags_qs.distinct())

        char_qs = ProductCharacteristic.objects.filter(product__in=base_qs).values('name', 'value').distinct().order_by('name', 'value')
        from collections import OrderedDict
        char_options = OrderedDict()
        for row in char_qs:
            name = row['name']
            if name not in char_options:
                char_options[name] = []
            if row['value'] not in char_options[name]:
                char_options[name].append(row['value'])
        context['filter_characteristics'] = char_options

        section_name_map = {s.slug: s.name for s in context['catalog_sections']}
        category_name_map = {}
        for section in context['catalog_sections']:
            for cat in section.categories.all():
                category_name_map[cat.slug] = cat.name
        context['section_name_map'] = section_name_map
        context['category_name_map'] = category_name_map

        similar_categories = []
        if selected_category and selected_category.section:
            candidates = [c for c in selected_category.section.categories.all() if c.pk != selected_category.pk]

            def _normalize_tokens(value):
                return [t for t in re.split(r'[^a-zA-Zа-яА-Я0-9]+', value.lower()) if t]

            base_tokens = set(_normalize_tokens(selected_category.name))
            scored = []
            for cat in candidates:
                cat_tokens = set(_normalize_tokens(cat.name))
                token_score = len(base_tokens & cat_tokens) * 2
                ratio_score = SequenceMatcher(None, selected_category.name.lower(), cat.name.lower()).ratio()
                score = token_score + ratio_score
                scored.append((score, cat))
            scored.sort(key=lambda x: x[0], reverse=True)
            similar_categories = [cat for _, cat in scored[:3]]
        context['similar_categories'] = similar_categories

        from .cart_services import get_favorite_product_ids
        context['favorite_product_ids'] = get_favorite_product_ids(self.request)
        selected_city_id = self.request.session.get('selected_city_id')
        stock_total_qs = (
            ProductStock.objects
            .values('product_id')
            .annotate(total=Sum('quantity'))
        )
        context['product_stock_total'] = {row['product_id']: row['total'] for row in stock_total_qs}
        if selected_city_id:
            stock_qs = (
                ProductStock.objects
                .filter(pickup_point__city_id=selected_city_id)
                .values('product_id')
                .annotate(total=Sum('quantity'))
            )
            context['product_stock_in_city'] = {row['product_id']: row['total'] for row in stock_qs}
        else:
            context['product_stock_in_city'] = {}
        return context


class ProductDetailView(DetailView):
    """Детальная страница товара."""
    model = Product
    context_object_name = 'product'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/product_detail.html'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        Product.objects.filter(pk=self.object.pk).update(views_count=F('views_count') + 1)
        viewed = request.session.get('viewed_product_ids', [])
        viewed = [self.object.pk] + [x for x in viewed if x != self.object.pk][:9]
        request.session['viewed_product_ids'] = viewed
        request.session.modified = True
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_queryset(self):
        return Product.objects.filter(is_active=True).prefetch_related(
            'characteristics', 'tags', 'variants', 'variants__characteristics', 'images'
        ).select_related('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .cart_services import get_favorite_product_ids, is_favorite
        context['is_favorite'] = is_favorite(self.request, self.object.pk)
        context['favorite_product_ids'] = get_favorite_product_ids(self.request)
        selected_city_id = self.request.session.get('selected_city_id')

        # Остатки: для товаров с вариантами — по варианту, иначе — по товару
        if self.object.variants.exists():
            context['stock_by_variant'] = {
                v.pk: _get_stock_total(self.object.pk, v.pk)
                for v in self.object.variants.all()
            }
            context['stock_in_city_by_variant'] = {}
            if selected_city_id:
                context['stock_in_city_by_variant'] = {
                    v.pk: _get_stock_in_city(selected_city_id, self.object.pk, v.pk)
                    for v in self.object.variants.all()
                }
            context['stock_total'] = None
            context['stock_in_city'] = None
        else:
            context['stock_total'] = _get_stock_total(self.object.pk)
            context['stock_in_city'] = _get_stock_in_city(selected_city_id, self.object.pk) if selected_city_id else None
            context['stock_by_variant'] = {}
            context['stock_in_city_by_variant'] = {}

        context['selected_city'] = City.objects.filter(pk=selected_city_id).first() if selected_city_id else None
        selected_city = context['selected_city']

        # Точки выдачи по выбранному городу (превью для buy-box)
        if selected_city:
            pp_qs = PickupPoint.objects.filter(city=selected_city).order_by('order', 'name')
            context['pickup_points_count'] = pp_qs.count()
            context['pickup_points_preview'] = list(pp_qs[:3])
        else:
            context['pickup_points_count'] = 0
            context['pickup_points_preview'] = []

        rec_data = build_pdp_recommendations(self.request, self.object)
        context['recommendation_sections'] = rec_data['sections']
        context['product_stock_total'] = rec_data['product_stock_total']
        context['product_stock_in_city'] = rec_data['product_stock_in_city']
        context['recommended_variant_ids'] = rec_data['recommended_variant_ids']

        # Характеристики вариантов для шаблона
        context['variant_characteristics'] = {
            v.pk: [(c.name, c.value) for c in v.characteristics.all()]
            for v in self.object.variants.all()
        }

        # Наборы с текущим товаром (через ProductBundleItem)
        try:
            bundles = list(
                ProductBundle.objects
                .filter(items__product=self.object)
                .prefetch_related('items__product', 'items__product__variants', 'items__product__images')
                .distinct()
            )
            # Оставляем только наборы с 2+ позициями
            context['bundles'] = [b for b in bundles if b.items.count() >= 2]
            # Остатки для товаров из комплектов (сумма по всем вариантам, как в recommendations)
            for b in context['bundles']:
                for item in b.items.all():
                    if item.product_id != self.object.pk:
                        pid = item.product_id
                        if pid not in context['product_stock_total']:
                            qs = ProductStock.objects.filter(product_id=pid).aggregate(s=Sum('quantity'))
                            context['product_stock_total'][pid] = int(qs['s'] or 0)
                        if selected_city_id and pid not in context['product_stock_in_city']:
                            qs = ProductStock.objects.filter(
                                product_id=pid, pickup_point__city_id=selected_city_id
                            ).aggregate(s=Sum('quantity'))
                            context['product_stock_in_city'][pid] = int(qs['s'] or 0)
        except ProgrammingError:
            # Защита от устаревшей схемы (catalog_productbundle_products)
            context['bundles'] = []

        # Галерея фото: только основное + общие доп. фото (без фото вариантов — они показываются при выборе варианта)
        gallery = []
        seen = set()
        try:
            if self.object.image:
                url = self.request.build_absolute_uri(self.object.image.url)
                gallery.append(url)
                seen.add(url)
            for img in self.object.images.all():
                if img.image:
                    url = self.request.build_absolute_uri(img.image.url)
                    if url not in seen:
                        gallery.append(url)
                        seen.add(url)
        except (ValueError, OSError):
            pass  # файл удалён или некорректный путь
        context['product_gallery'] = gallery

        # Данные для Alpine.js (json_script) — избегаем проблем с x-data в атрибуте
        def _safe_image_url(img_field):
            try:
                return self.request.build_absolute_uri(img_field.url) if img_field else ''
            except (ValueError, OSError):
                return ''
        variants_data = [
            {
                'id': v.pk,
                'name': v.name,
                'price': float(v.price),
                'imageUrl': _safe_image_url(v.image),
            }
            for v in self.object.variants.all()
        ]
        context['product_detail_data'] = {
            'variants': variants_data,
            'productImage': _safe_image_url(self.object.image),
            'productPrice': float(self.object.price),
            'productGallery': gallery,
            'productCharacteristics': [[c.name, c.value] for c in self.object.characteristics.all()],
            'variantCharacteristics': context['variant_characteristics'],
            'stockByVariant': context['stock_by_variant'],
            'stockInCityByVariant': context['stock_in_city_by_variant'],
            'stockTotalProduct': context['stock_total'] if context['stock_total'] is not None else 0,
            'stockInCityProduct': context['stock_in_city'],
            'selectedCityName': context['selected_city'].name if context['selected_city'] else '',
        }

        # Текущие количества товара в корзине: отдельно по товару и по вариантам.
        cart_qty_product = 0
        cart_qty_by_variant = {}
        for item in get_cart_items(self.request):
            if item.get('product_id') != self.object.pk:
                continue
            quantity = max(0, int(item.get('quantity') or 0))
            variant_id = item.get('variant_id')
            if variant_id is None:
                cart_qty_product += quantity
            else:
                key = str(variant_id)
                cart_qty_by_variant[key] = cart_qty_by_variant.get(key, 0) + quantity
        context['product_detail_data']['cartQtyProduct'] = cart_qty_product
        context['product_detail_data']['cartQtyByVariant'] = cart_qty_by_variant

        return context


def favorite_list_view(request):
    """Страница «Моё избранное»: список товаров, добавленных в избранное. Поддержка анонимов (сессия)."""
    from .cart_services import get_favorite_product_ids
    favorite_ids = get_favorite_product_ids(request)
    if not favorite_ids:
        products = []
    else:
        products = list(
            Product.objects.filter(pk__in=favorite_ids, is_active=True)
            .select_related('category')
            .prefetch_related('tags', 'variants', 'images')
        )
    return render(request, 'catalog/favorite_list.html', {
        'products': products,
        'favorite_product_ids': set(p.pk for p in products),
    })


@require_GET
def footer_products_feed_view(request):
    """Порционная выдача карточек товаров для общего блока перед футером (персонализировано)."""
    from .cart_services import get_favorite_product_ids
    from .footer_recommendations import get_footer_recommended_product_ids

    footer_products_layout = (request.GET.get('layout') or 'catalog').strip().lower()
    if footer_products_layout not in {'home', 'catalog'}:
        footer_products_layout = 'catalog'

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)

    product_ids = get_footer_recommended_product_ids(request)
    if not product_ids:
        return render(request, 'catalog/partials/footer_products_chunk.html', {
            'products': [],
            'has_next': False,
            'has_more_after_limit': False,
            'next_page': None,
            'footer_products_layout': footer_products_layout,
            'favorite_product_ids': set(),
        })

    page_size = _footer_products_page_size(footer_products_layout)
    paginator = Paginator(product_ids, page_size)
    limited_pages = min(paginator.num_pages, FOOTER_PRODUCTS_MAX_PAGES)
    current_page = min(page, limited_pages)
    page_obj = paginator.get_page(current_page)
    page_ids = list(page_obj.object_list)

    products_qs = Product.objects.filter(
        pk__in=page_ids, is_active=True
    ).only('id', 'name', 'slug', 'price', 'image', 'created_at').prefetch_related('tags')
    product_map = {p.pk: p for p in products_qs}
    products = [product_map[pid] for pid in page_ids if pid in product_map]

    has_next = current_page < limited_pages
    if has_next:
        has_more_after_limit = False
    else:
        total_in_catalog = Product.objects.filter(is_active=True).count()
        has_more_after_limit = (
            total_in_catalog > FOOTER_PRODUCTS_MAX_PAGES * page_size
        )

    return render(request, 'catalog/partials/footer_products_chunk.html', {
        'products': products,
        'has_next': has_next,
        'has_more_after_limit': has_more_after_limit,
        'next_page': current_page + 1 if has_next else None,
        'footer_products_layout': footer_products_layout,
        'favorite_product_ids': get_favorite_product_ids(request),
    })


@require_POST
def toggle_favorite_view(request, product_id):
    """Добавить или убрать товар из избранного. Анонимы — в сессию, при входе сольётся в профиль."""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    if request.user.is_authenticated:
        fav, created = Favorite.objects.get_or_create(user=request.user, product=product)
        if not created:
            fav.delete()
    else:
        ids = set(request.session.get('favorite_product_ids', []) or [])
        if product_id in ids:
            ids.discard(product_id)
        else:
            ids.add(product_id)
        request.session['favorite_product_ids'] = list(ids)
        request.session.modified = True

    # HTMX: вернуть обновлённую кнопку без редиректа/перезагрузки страницы
    if request.headers.get('HX-Request') == 'true':
        from .cart_services import get_favorite_product_ids, is_favorite
        favorite_ids = get_favorite_product_ids(request)
        ctx = {'product': product, 'is_favorite': is_favorite(request, product.pk)}
        button_html = render(request, 'catalog/partials/favorite_button.html', ctx).content.decode()
        resp = HttpResponse(button_html)
        if request.POST.get('from_favorites_page') == '1':
            products_list = list(
                Product.objects.filter(pk__in=favorite_ids, is_active=True)
                .select_related('category')
                .prefetch_related('tags', 'variants', 'images')
            )
            grid_html = render(request, 'catalog/partials/favorites_grid_oob.html', {
                'products': products_list,
                'favorite_product_ids': favorite_ids,
            }).content.decode()
            resp = HttpResponse(button_html + grid_html)
        resp['HX-Trigger'] = json.dumps({
            'favorites-updated': {'count': len(favorite_ids)},
        })
        return resp

    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
    # Якорь #product-{id} — браузер прокрутит к карточке после перезагрузки
    if '#' in next_url:
        next_url = next_url.split('#')[0]
    next_url = f'{next_url}#product-{product_id}'
    return redirect(next_url)
