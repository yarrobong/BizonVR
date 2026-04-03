import json
from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from ..cart_services import get_cart_count, get_cart_items, save_cart_to_db, save_cart_to_session
from ..models import CartShare, Product, ProductVariant
from ..pricing import normalize_purchase_mode, resolve_price_for_mode
from .common import _get_stock_total

CART_SHARE_TTL_DAYS = 30


def _parse_share_item_key(raw_key):
    """Разобрать ключ позиции в формате product_id:variant_id|none:purchase_mode:bundle_id|none."""
    if not raw_key or ':' not in raw_key:
        return None
    parts = raw_key.split(':')
    if len(parts) < 2:
        return None
    product_part = parts[0]
    variant_part = parts[1]
    purchase_mode_part = parts[2] if len(parts) >= 3 else 'stock'
    bundle_part = parts[3] if len(parts) >= 4 else 'none'
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
    if bundle_part in ('', 'none', 'null'):
        bundle_id = None
    else:
        try:
            bundle_id = int(bundle_part)
        except (TypeError, ValueError):
            return None
    return product_id, variant_id, normalize_purchase_mode(purchase_mode_part), bundle_id


def _generate_cart_share_code():
    """Сгенерировать короткий уникальный код шаринга корзины."""
    for _ in range(12):
        code = get_random_string(7, allowed_chars='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
        if not CartShare.objects.filter(code=code).exists():
            return code
    return get_random_string(7)


def _resolve_cart_share_items(items_payload):
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
            'purchase_mode': normalize_purchase_mode(raw_item.get('purchase_mode')),
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
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
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
            'variant_name': variant.name if variant else None,
            'name': product.name,
            'price': price,
            'quantity': quantity,
            'subtotal': price * quantity,
            'image_url': image_url,
            'purchase_mode': purchase_mode,
            'product_slug': product.slug,
            '_product_obj': product,
            '_variant_obj': variant,
            'stock_total': _get_stock_total(product_id, variant_id),
        })
    return resolved


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
        item_key = (
            item_product_id,
            item_variant_id,
            normalize_purchase_mode(item.get('purchase_mode')),
            item.get('bundle_id'),
        )
        if item_key in selected_pairs_set:
            try:
                quantity = max(1, int(item.get('quantity', 1) or 1))
            except (TypeError, ValueError):
                quantity = 1
            selected_payload.append({
                'product_id': item_product_id,
                'variant_id': item_variant_id,
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
    """Добавить все товары из shared-ссылки в текущую корзину."""
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
