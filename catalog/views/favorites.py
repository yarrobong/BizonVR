import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import Favorite, Product
from .common import _product_stock_totals, _with_game_pack_availability


def favorite_list_view(request):
    """Страница «Моё избранное»: список товаров, добавленных в избранное. Поддержка анонимов (сессия)."""
    from ..cart_services import get_favorite_product_ids

    favorite_ids = get_favorite_product_ids(request)
    if not favorite_ids:
        products = []
    else:
        products = list(
            Product.objects.filter(pk__in=favorite_ids, is_active=True)
            .select_related('category')
            .prefetch_related('tags', 'variants', 'images')
        )
    product_stock_total = _with_game_pack_availability(
        _product_stock_totals([product.pk for product in products]),
        products,
    )
    return render(request, 'catalog/favorite_list.html', {
        'products': products,
        'favorite_product_ids': set(p.pk for p in products),
        'product_stock_total': product_stock_total,
    })


@require_POST
def toggle_favorite_view(request, product_id):
    """Добавить или убрать товар из избранного. Анонимы — в сессию, при входе сольётся в профиль."""
    from ..cart_services import get_favorite_product_ids, invalidate_favorites_request_cache, is_favorite

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
    invalidate_favorites_request_cache(request)

    if request.headers.get('HX-Request') == 'true':
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
                'product_stock_total': _with_game_pack_availability(
                    _product_stock_totals([product.pk for product in products_list]),
                    products_list,
                ),
            }).content.decode()
            resp = HttpResponse(button_html + grid_html)
        resp['HX-Trigger'] = json.dumps({
            'favorites-updated': {'count': len(favorite_ids)},
        })
        return resp

    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
    if '#' in next_url:
        next_url = next_url.split('#')[0]
    next_url = f'{next_url}#product-{product_id}'
    return redirect(next_url)
