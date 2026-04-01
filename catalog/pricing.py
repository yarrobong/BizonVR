from decimal import Decimal


PURCHASE_MODE_STOCK = 'stock'
PURCHASE_MODE_ON_REQUEST = 'on_request'
PURCHASE_MODE_CHOICES = (
    (PURCHASE_MODE_STOCK, 'Из наличия'),
    (PURCHASE_MODE_ON_REQUEST, 'Под заказ'),
)

PURCHASE_MODE_LABELS = {
    PURCHASE_MODE_STOCK: 'Из наличия',
    PURCHASE_MODE_ON_REQUEST: 'Под заказ',
}


def normalize_purchase_mode(value):
    return PURCHASE_MODE_ON_REQUEST if value == PURCHASE_MODE_ON_REQUEST else PURCHASE_MODE_STOCK


def get_purchase_mode_label(value):
    return PURCHASE_MODE_LABELS.get(normalize_purchase_mode(value), PURCHASE_MODE_LABELS[PURCHASE_MODE_STOCK])


def resolve_in_stock_price(product, variant=None):
    if variant is not None:
        return variant.price
    return product.price


def resolve_on_request_price(product, variant=None):
    if variant is not None and getattr(variant, 'price_on_request_override', None) is not None:
        return variant.price_on_request_override
    return getattr(product, 'price_on_request', None)


def has_explicit_on_request_price(product, variant=None):
    return resolve_on_request_price(product, variant) is not None


def resolve_price_for_mode(product, variant=None, purchase_mode=PURCHASE_MODE_STOCK):
    normalized_mode = normalize_purchase_mode(purchase_mode)
    if normalized_mode == PURCHASE_MODE_ON_REQUEST:
        on_request_price = resolve_on_request_price(product, variant)
        if on_request_price is not None:
            return on_request_price
    return resolve_in_stock_price(product, variant)


def quantize_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))
