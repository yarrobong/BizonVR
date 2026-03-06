import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..cart_services import (
    COMPARE_LIMIT,
    get_compare_product_ids,
    get_favorite_product_ids,
    toggle_compare,
)
from ..models import Product
from ..stock import public_stock_status
from .common import _product_stock_totals


def _load_compare_products(compare_ids):
    if not compare_ids:
        return []
    products_map = (
        Product.objects.filter(pk__in=compare_ids, is_active=True)
        .select_related('category')
        .prefetch_related('characteristics', 'images', 'tags', 'variants')
        .in_bulk()
    )
    return [products_map[pid] for pid in compare_ids if pid in products_map]


def compare_page_view(request):
    """Публичная страница сравнения товаров."""
    compare_ids = get_compare_product_ids(request)
    products = _load_compare_products(compare_ids)
    product_stock_total = _product_stock_totals([product.pk for product in products])
    stock_status = {
        product.pk: public_stock_status(product_stock_total.get(product.pk, 0))
        for product in products
    }

    characteristic_names = sorted({
        characteristic.name
        for product in products
        for characteristic in product.characteristics.all()
    })
    characteristic_rows = []
    for name in characteristic_names:
        row = {'name': name, 'values': {}}
        for product in products:
            value = next(
                (item.value for item in product.characteristics.all() if item.name == name),
                '',
            )
            row['values'][product.pk] = value
        characteristic_rows.append(row)

    return render(request, 'catalog/compare.html', {
        'compare_products': products,
        'compare_count': len(compare_ids),
        'compare_limit': COMPARE_LIMIT,
        'favorite_product_ids': get_favorite_product_ids(request),
        'product_stock_total': product_stock_total,
        'stock_status_by_product': stock_status,
        'characteristic_rows': characteristic_rows,
    })


@require_POST
def toggle_compare_view(request, product_id):
    """Добавить или убрать товар из сравнения."""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    is_compared_now, compare_ids, limit_reached = toggle_compare(request, product)
    compare_count = len(compare_ids)

    if request.headers.get('HX-Request') == 'true':
        template_name = 'catalog/partials/compare_button_mobile.html' if request.POST.get('compact') == '1' else 'catalog/partials/compare_button.html'
        html = render(request, template_name, {
            'product': product,
            'is_compared': is_compared_now,
            'compare_count': compare_count,
            'compare_limit': COMPARE_LIMIT,
        }).content.decode()
        response = HttpResponse(html)
        response['HX-Trigger'] = json.dumps({
            'compare-updated': {'count': compare_count},
        })
        return response

    next_url = request.POST.get('next') or request.GET.get('next') or reverse('catalog:compare')
    return redirect(next_url)
