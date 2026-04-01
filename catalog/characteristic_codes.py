from __future__ import annotations

from django.utils.text import slugify


CYRILLIC_TO_LATIN = {
    'а': 'a',
    'б': 'b',
    'в': 'v',
    'г': 'g',
    'д': 'd',
    'е': 'e',
    'ё': 'e',
    'ж': 'zh',
    'з': 'z',
    'и': 'i',
    'й': 'y',
    'к': 'k',
    'л': 'l',
    'м': 'm',
    'н': 'n',
    'о': 'o',
    'п': 'p',
    'р': 'r',
    'с': 's',
    'т': 't',
    'у': 'u',
    'ф': 'f',
    'х': 'h',
    'ц': 'ts',
    'ч': 'ch',
    'ш': 'sh',
    'щ': 'sch',
    'ъ': '',
    'ы': 'y',
    'ь': '',
    'э': 'e',
    'ю': 'yu',
    'я': 'ya',
}


def transliterate_for_code(value: str) -> str:
    text = (value or '').strip().lower()
    return ''.join(CYRILLIC_TO_LATIN.get(char, char) for char in text)


def build_characteristic_code_base(source_name: str) -> str:
    transliterated = transliterate_for_code(source_name)
    return slugify(transliterated, allow_unicode=False) or 'characteristic'


def generate_unique_characteristic_code(source_name: str, *, exclude_pk: int | None = None) -> str:
    from .models import CharacteristicDefinition

    base_code = build_characteristic_code_base(source_name)
    candidate = base_code
    suffix = 2
    while True:
        queryset = CharacteristicDefinition.objects.filter(code=candidate)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return candidate
        candidate = f'{base_code}-{suffix}'
        suffix += 1
