"""
Сервисы заказов: начисление бонуса партнёру при оплате заказа по промокоду;
списание остатков с точек выдачи при оплате.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F


def apply_partner_bonus_for_order(order):
    """
    Начислить бонус партнёру за заказ, оплаченный по промокоду.
    Вызывать при переходе заказа в статус «Оплачен» (webhook или тестовый режим).
    Идемпотентно: повторный вызов не дублирует начисление.
    """
    if order.status != 'paid':
        return
    if order.partner_bonus_applied:
        return
    promo = order.promo_code
    if not promo or not promo.partner_user_id or not promo.partner_bonus or promo.partner_bonus <= 0:
        return

    from accounts.models import Profile, BalanceTransaction

    with transaction.atomic():
        order.refresh_from_db()
        if order.partner_bonus_applied:
            return
        profile, _ = Profile.objects.get_or_create(
            user=promo.partner_user,
            defaults={'phone': promo.partner_user.username},
        )
        BalanceTransaction.objects.create(
            user=promo.partner_user,
            kind=BalanceTransaction.TYPE_PROMO_BONUS,
            amount=promo.partner_bonus,
            order=order,
        )
        profile.balance += promo.partner_bonus
        profile.save(update_fields=['balance'])
        order.partner_bonus_applied = True
        order.save(update_fields=['partner_bonus_applied'])


def decrease_stock_for_order(order):
    """
    Списать остатки по заказу при переходе в статус «Оплачен».
    Если у заказа указана точка выдачи — списываем с неё; иначе — с одной из точек города.
    Идемпотентно: не списывает повторно (order.stock_decreased).
    """
    if order.status != 'paid':
        return
    if order.stock_decreased:
        return

    from catalog.models import ProductStock, PickupPoint

    with transaction.atomic():
        order.refresh_from_db()
        if order.stock_decreased:
            return
        for item in order.items.select_related('product').all():
            product_id = item.product_id
            qty = item.quantity
            if order.pickup_point_id:
                ProductStock.objects.filter(
                    product_id=product_id,
                    pickup_point_id=order.pickup_point_id,
                ).update(quantity=F('quantity') - qty)
            elif order.city_id:
                points = list(
                    PickupPoint.objects.filter(city_id=order.city_id)
                    .order_by('order', 'id')
                )
                for point in points:
                    stock = ProductStock.objects.filter(
                        product_id=product_id,
                        pickup_point_id=point.pk,
                    ).first()
                    if stock and stock.quantity >= qty:
                        ProductStock.objects.filter(pk=stock.pk).update(
                            quantity=F('quantity') - qty
                        )
                        break
                    elif stock and stock.quantity > 0:
                        take = min(qty, stock.quantity)
                        ProductStock.objects.filter(pk=stock.pk).update(
                            quantity=F('quantity') - take
                        )
                        qty -= take
                        if qty <= 0:
                            break
        order.stock_decreased = True
        order.save(update_fields=['stock_decreased'])
