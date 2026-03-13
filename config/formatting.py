from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


RUB_CURRENCY_CODE = 'RUB'
RUB_CURRENCY_SYMBOL = '₽'


def _to_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))

    normalized = str(value).strip()
    if not normalized:
        return None
    normalized = normalized.replace(' ', '').replace(',', '.')
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def format_amount(value, default='0', force_two_decimals=False):
    amount = _to_decimal(value)
    if amount is None:
        return default

    amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    sign = '-' if amount < 0 else ''
    amount = abs(amount)

    whole = int(amount)
    cents = int((amount - Decimal(whole)) * 100)
    whole_text = f'{whole:,}'.replace(',', ' ')

    if cents == 0 and not force_two_decimals:
        return f'{sign}{whole_text}'
    return f'{sign}{whole_text},{cents:02d}'


def format_currency_amount(value, currency=RUB_CURRENCY_CODE, default='0'):
    amount_text = format_amount(value, default=default)
    currency_code = (currency or RUB_CURRENCY_CODE).upper()
    if currency_code == RUB_CURRENCY_CODE:
        return f'{amount_text} {RUB_CURRENCY_SYMBOL}'
    return f'{amount_text} {currency_code}'


def format_decimal_amount(value, default='0,00'):
    return format_amount(value, default=default, force_two_decimals=True)
