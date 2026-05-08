from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..models import Product
from .common import _product_stock_totals, _with_game_pack_availability

FOOTER_PRODUCTS_ROWS_PER_BATCH = 3
FOOTER_PRODUCTS_COLS = 5
FOOTER_PRODUCTS_MAX_PAGES = 8


def _footer_products_page_size(layout: str) -> int:
    """Размер пачки = 3 строки × 5 колонок."""
    return FOOTER_PRODUCTS_ROWS_PER_BATCH * FOOTER_PRODUCTS_COLS


@require_GET
def footer_products_feed_view(request):
    """Порционная выдача карточек товаров для общего блока перед футером (персонализировано)."""
    from ..cart_services import get_favorite_product_ids
    from ..footer_recommendations import get_footer_recommended_product_ids

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
    ).only('id', 'name', 'slug', 'price', 'image', 'created_at').prefetch_related('tags', 'images')
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
        'product_stock_total': _with_game_pack_availability(
            _product_stock_totals([product.pk for product in products]),
            products,
        ),
    })
