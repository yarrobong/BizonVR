import re
from decimal import Decimal

from django.db.models import Sum

from catalog.models import ProductStock


def _get_stock_in_city(city_id, product_id):
    """Суммарный остаток товара по городу."""
    if not city_id:
        return None
    total = (
        ProductStock.objects
        .filter(product_id=product_id, pickup_point__city_id=city_id)
        .aggregate(s=Sum('quantity'))
    )
    return total['s'] or 0


def _get_stock_at_pickup_point(pickup_point_id, product_id):
    """Остаток товара в точке выдачи."""
    if not pickup_point_id:
        return None
    stock = ProductStock.objects.filter(
        product_id=product_id,
        pickup_point_id=pickup_point_id,
    ).first()
    return stock.quantity if stock else 0


def _get_stock_total(product_id):
    """Суммарный остаток товара по всей России."""
    total = (
        ProductStock.objects
        .filter(product_id=product_id)
        .aggregate(s=Sum('quantity'))
    )
    return total['s'] or 0


def _normalize_phone(phone):
    """Оставляем только цифры для сравнения."""
    if not phone:
        return ''
    return re.sub(r'\D', '', str(phone).strip())


def _discount_for_promo(subtotal, promo):
    """Скидка по промокоду: не больше суммы заказа. promo — PromoCode или None."""
    if not promo or subtotal <= 0:
        return Decimal('0')
    return min(promo.discount_amount, subtotal)
