from decimal import Decimal
from itertools import count

from catalog.tests.factories import create_product
from orders.models import Order, OrderItem, PromoCode


_order_counter = count(1)
_promo_counter = count(1)


def create_promocode(**overrides):
    index = next(_promo_counter)
    defaults = {
        'code': f'PROMO-{index}',
        'discount_amount': Decimal('50.00'),
        'is_active': True,
    }
    defaults.update(overrides)
    return PromoCode.objects.create(**defaults)


def create_order(*, product=None, create_item=False, item_quantity=1, item_price=None, **overrides):
    index = next(_order_counter)
    defaults = {
        'status': Order.STATUS_NEW,
        'payment_status': Order.PAYMENT_STATUS_UNPAID,
        'total': Decimal('100.00'),
        'phone': f'+7 999 000 00 {index:02d}',
        'email': f'order-{index}@example.com',
        'first_name': f'Client {index}',
    }
    defaults.update(overrides)
    order = Order.objects.create(**defaults)
    if create_item:
        item_product = product or create_product(price=defaults['total'])
        OrderItem.objects.create(
            order=order,
            product=item_product,
            quantity=item_quantity,
            price=item_price if item_price is not None else item_product.price,
        )
    return order
