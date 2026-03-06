from django.db.models import Sum
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import ProductStock


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
