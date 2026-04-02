from __future__ import annotations

import re
from dataclasses import dataclass


SPACE_RE = re.compile(r'\s+')
GB_RE = re.compile(r'(?:(?<=\d)\s*)?(?:g\s*b|г\s*б)\b', re.IGNORECASE)
TB_RE = re.compile(r'(?:(?<=\d)\s*)?(?:t\s*b|т\s*б)\b', re.IGNORECASE)
UNIT_VALUE_RE = re.compile(r'^(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>gb|tb)$', re.IGNORECASE)


@dataclass(frozen=True)
class NormalizedCharacteristicValue:
    cleaned_value: str
    normalized_key: str
    suggested_display: str
    number_value: str
    unit_key: str
    safe_merge_key: str


def _collapse_spaces(value: str) -> str:
    return SPACE_RE.sub(' ', value).strip()


def normalize_characteristic_value(raw_value: str) -> NormalizedCharacteristicValue:
    cleaned_value = _collapse_spaces(raw_value or '')
    lowered = cleaned_value.lower()
    lowered = GB_RE.sub(' gb', lowered)
    lowered = TB_RE.sub(' tb', lowered)
    normalized_key = _collapse_spaces(lowered)

    match = UNIT_VALUE_RE.match(normalized_key)
    number_value = ''
    unit_key = ''
    if match:
        number = match.group('number')
        unit_key = match.group('unit').lower()
        number_value = number.replace(',', '.')
        unit = unit_key.upper().replace('GB', 'ГБ').replace('TB', 'ТБ')
        suggested_display = f'{number} {unit}'
    else:
        suggested_display = cleaned_value

    return NormalizedCharacteristicValue(
        cleaned_value=cleaned_value,
        normalized_key=normalized_key,
        suggested_display=suggested_display,
        number_value=number_value,
        unit_key=unit_key,
        safe_merge_key=f'{number_value}:{unit_key}' if number_value and unit_key else normalized_key,
    )
