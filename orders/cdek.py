from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings


THREE_DECIMALS = Decimal('0.001')
TWO_DECIMALS = Decimal('0.01')


def _decimal_setting(name, default):
    return Decimal(str(getattr(settings, name, default)))


def calculate_cdek_delivery_for_lines(lines):
    total_weight = Decimal('0')
    total_volume_cm3 = 0

    for line in lines:
        product = line['product']
        quantity = int(line['quantity'])
        total_weight += Decimal(str(product.shipping_weight_kg)) * quantity
        total_volume_cm3 += int(product.shipping_volume_cm3) * quantity

    base_cost = _decimal_setting('CDEK_BASE_DELIVERY_COST', '350')
    cost_per_kg = _decimal_setting('CDEK_DELIVERY_COST_PER_KG', '120')
    cost_per_liter = _decimal_setting('CDEK_DELIVERY_COST_PER_LITER', '12')
    total_volume_liters = Decimal(total_volume_cm3) / Decimal('1000')
    delivery_cost = (
        base_cost
        + (total_weight * cost_per_kg)
        + (total_volume_liters * cost_per_liter)
    ).quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)

    return {
        'delivery_cost': delivery_cost,
        'total_weight_kg': total_weight.quantize(THREE_DECIMALS, rounding=ROUND_HALF_UP),
        'total_volume_cm3': total_volume_cm3,
        'total_volume_liters': total_volume_liters.quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP),
    }
