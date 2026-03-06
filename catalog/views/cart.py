import json

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..cart_services import clear_cart, get_cart_items
from ..models import CartShare, Product
from .cart_share import _resolve_cart_share_items
from .common import _get_stock_total


def _enrich_cart_items_for_page(cart_items):
    """Добавить в позиции корзины slug и наличие для рендера страницы корзины."""
    if not cart_items:
        return cart_items
    slugs = dict(
        Product.objects.filter(pk__in=[i['product_id'] for i in cart_items]).values_list('pk', 'slug')
    )
    for item in cart_items:
        pid = item['product_id']
        vid = item.get('variant_id')
        item['product_slug'] = slugs.get(pid, '')
        item['stock_total'] = _get_stock_total(pid, vid)
        item['share_item_key'] = f"{pid}:{vid if vid is not None else 'none'}"
    return cart_items


def cart_page_view(request):
    """Отдельная страница корзины: список товаров, изменение количества, переход к оформлению."""
    cart_items = get_cart_items(request)
    total = sum(item.get('subtotal', 0) for item in cart_items)
    _enrich_cart_items_for_page(cart_items)

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
            shared_cart_items = _resolve_cart_share_items(cart_share.items)
            shared_total = sum(item.get('subtotal', 0) for item in shared_cart_items)
            shared_quantity = sum(item.get('quantity', 0) for item in shared_cart_items)
        else:
            shared_invalid = True

    return render(request, 'catalog/cart.html', {
        'cart_items': cart_items,
        'total': total,
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
            resp = render(request, 'catalog/partials/cart_page_wrapper.html', {
                'cart_items': [],
                'total': 0,
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
