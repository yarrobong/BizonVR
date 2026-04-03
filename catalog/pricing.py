from decimal import Decimal

from django.db.models import Case, DecimalField, F, Q, Value, When


PURCHASE_MODE_STOCK = 'stock'
PURCHASE_MODE_ON_REQUEST = 'on_request'
PURCHASE_MODE_REQUEST_ONLY = 'request_only'
PURCHASE_MODE_CHOICES = (
    (PURCHASE_MODE_STOCK, 'Из наличия'),
    (PURCHASE_MODE_ON_REQUEST, 'Под заказ'),
)

PURCHASE_MODE_LABELS = {
    PURCHASE_MODE_STOCK: 'Из наличия',
    PURCHASE_MODE_ON_REQUEST: 'Под заказ',
    PURCHASE_MODE_REQUEST_ONLY: 'По заявке',
}


def normalize_purchase_mode(value):
    return PURCHASE_MODE_ON_REQUEST if value == PURCHASE_MODE_ON_REQUEST else PURCHASE_MODE_STOCK


def get_purchase_mode_label(value):
    return PURCHASE_MODE_LABELS.get(normalize_purchase_mode(value), PURCHASE_MODE_LABELS[PURCHASE_MODE_STOCK])


def resolve_in_stock_price(product, variant=None):
    if variant is not None and getattr(variant, 'price_override', None) is not None:
        return variant.price_override
    return product.price


def resolve_on_request_price(product, variant=None):
    if variant is not None and getattr(variant, 'price_on_request_override', None) is not None:
        return variant.price_on_request_override
    return getattr(product, 'price_on_request', None)


def has_explicit_in_stock_price(product, variant=None):
    return resolve_in_stock_price(product, variant) is not None


def has_explicit_on_request_price(product, variant=None):
    return resolve_on_request_price(product, variant) is not None


def resolve_price_for_mode(product, variant=None, purchase_mode=PURCHASE_MODE_STOCK):
    normalized_mode = normalize_purchase_mode(purchase_mode)
    if normalized_mode == PURCHASE_MODE_ON_REQUEST:
        on_request_price = resolve_on_request_price(product, variant)
        if on_request_price is not None:
            return on_request_price
    return resolve_in_stock_price(product, variant)


def resolve_public_purchase_mode(product, variant=None, *, stock_total=0):
    if stock_total > 0 and has_explicit_in_stock_price(product, variant):
        return PURCHASE_MODE_STOCK
    if getattr(product, 'allow_order_on_request', True) and has_explicit_on_request_price(product, variant):
        return PURCHASE_MODE_ON_REQUEST
    return PURCHASE_MODE_REQUEST_ONLY


def resolve_catalog_effective_price(product, variant=None, *, stock_total=0):
    public_mode = resolve_public_purchase_mode(product, variant, stock_total=stock_total)
    if public_mode == PURCHASE_MODE_STOCK:
        return resolve_in_stock_price(product, variant)
    if public_mode == PURCHASE_MODE_ON_REQUEST:
        return resolve_on_request_price(product, variant)
    return None


def build_catalog_effective_price_expression(
    *,
    stock_total_field='catalog_stock_total',
    in_stock_price_field='price',
    on_request_price_field='price_on_request',
    allow_on_request_field='allow_order_on_request',
):
    return Case(
        When(
            Q(**{f'{stock_total_field}__gt': 0}) & Q(**{f'{in_stock_price_field}__isnull': False}),
            then=F(in_stock_price_field),
        ),
        When(
            Q(**{allow_on_request_field: True}) & Q(**{f'{on_request_price_field}__isnull': False}),
            then=F(on_request_price_field),
        ),
        default=Value(None),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def quantize_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))
