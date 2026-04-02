"""Утилиты сортировки значений характеристик для фильтров каталога."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


NUMERIC_UNIT_RE = re.compile(r'^\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>tb|тб|gb|гб|mb|мб|hz|гц)?\s*$', re.IGNORECASE)
SCREEN_SIZE_RE = re.compile(r'^\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?:["″]|inch|дюйм(?:а|ов)?)?\s*$', re.IGNORECASE)
RESOLUTION_RE = re.compile(r'^\s*(?P<width>\d+)\s*[xх×]\s*(?P<height>\d+)\s*$', re.IGNORECASE)
BOOLEAN_TRUE_VALUES = {'да', 'есть', 'true', 'yes', '1'}
BOOLEAN_FALSE_VALUES = {'нет', 'false', 'no', '0'}
UNIT_MULTIPLIERS = {
    'mb': Decimal('1'),
    'мб': Decimal('1'),
    'gb': Decimal('1024'),
    'гб': Decimal('1024'),
    'tb': Decimal('1048576'),
    'тб': Decimal('1048576'),
    'hz': Decimal('1'),
    'гц': Decimal('1'),
}


def _parse_decimal(raw_value: str):
    try:
        return Decimal((raw_value or '').replace(',', '.'))
    except (InvalidOperation, AttributeError):
        return None


def get_typed_value_sort_key(value: str, *, sorting_mode: str = '') -> tuple:
    """Возвращает ключ сортировки для значения фильтра в зависимости от режима сортировки."""
    cleaned_value = (value or '').strip()
    lowered = cleaned_value.lower()

    if sorting_mode == 'boolean':
        if lowered in BOOLEAN_TRUE_VALUES:
            return (0, 0, cleaned_value.lower())
        if lowered in BOOLEAN_FALSE_VALUES:
            return (0, 1, cleaned_value.lower())
        return (1, cleaned_value.lower())

    if sorting_mode == 'resolution':
        match = RESOLUTION_RE.match(cleaned_value)
        if match:
            return (0, int(match.group('width')), int(match.group('height')), cleaned_value.lower())
        return (1, cleaned_value.lower())

    if sorting_mode == 'screen_size':
        match = SCREEN_SIZE_RE.match(cleaned_value)
        if match:
            decimal_value = _parse_decimal(match.group('number'))
            if decimal_value is not None:
                return (0, decimal_value, cleaned_value.lower())
        return (1, cleaned_value.lower())

    if sorting_mode == 'numeric_unit':
        match = NUMERIC_UNIT_RE.match(cleaned_value)
        if match:
            decimal_value = _parse_decimal(match.group('number'))
            unit_key = (match.group('unit') or '').lower()
            if decimal_value is not None:
                multiplier = UNIT_MULTIPLIERS.get(unit_key, Decimal('1'))
                return (0, decimal_value * multiplier, unit_key, cleaned_value.lower())
        return (1, cleaned_value.lower())

    if sorting_mode == 'alpha':
        return (cleaned_value.lower(),)

    # Fallback без sorting_mode: автоопределение по содержимому
    match = NUMERIC_UNIT_RE.match(cleaned_value)
    if match:
        decimal_value = _parse_decimal(match.group('number'))
        unit_key = (match.group('unit') or '').lower()
        if decimal_value is not None:
            multiplier = UNIT_MULTIPLIERS.get(unit_key, Decimal('1'))
            return (0, decimal_value * multiplier, unit_key, cleaned_value.lower())
    match = SCREEN_SIZE_RE.match(cleaned_value)
    if match:
        decimal_value = _parse_decimal(match.group('number'))
        if decimal_value is not None:
            return (0, decimal_value, cleaned_value.lower())
    if lowered in BOOLEAN_TRUE_VALUES:
        return (0, 0, cleaned_value.lower())
    if lowered in BOOLEAN_FALSE_VALUES:
        return (0, 1, cleaned_value.lower())
    return (1, cleaned_value.lower())
