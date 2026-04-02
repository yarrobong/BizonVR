from __future__ import annotations

import re
from collections import defaultdict


SOURCE_TOKEN_RE = re.compile(r'[\w\d]+', re.UNICODE)
RUSSIAN_SUFFIXES = (
    'иями', 'ями', 'ами', 'его', 'ого', 'ему', 'ому', 'ыми', 'ими',
    'ая', 'яя', 'ое', 'ее', 'ые', 'ие', 'ой', 'ий', 'ый', 'ую', 'юю',
    'ам', 'ям', 'ах', 'ях', 'ом', 'ем', 'ов', 'ев', 'ей', 'а', 'я', 'ы', 'и', 'е', 'о', 'у', 'ю', 'ь',
)


def _stem_source_token(token: str) -> str:
    candidate = (token or '').strip().lower().replace('ё', 'е')
    for suffix in RUSSIAN_SUFFIXES:
        if len(candidate) > len(suffix) + 2 and candidate.endswith(suffix):
            return candidate[:-len(suffix)]
    return candidate


def normalize_source_name_tokens(raw_source_name: str) -> tuple[str, ...]:
    tokens = []
    for token in SOURCE_TOKEN_RE.findall((raw_source_name or '').lower().replace('ё', 'е')):
        stem = _stem_source_token(token)
        if len(stem) >= 3:
            tokens.append(stem)
    return tuple(sorted(set(tokens)))


def get_definition_source_names(definition) -> tuple[str, ...]:
    source_names = []
    primary_source = (definition.source_name or '').strip()
    if primary_source:
        source_names.append(primary_source)
    source_aliases = getattr(definition, 'active_source_aliases', None)
    if source_aliases is None:
        source_aliases = definition.source_aliases.filter(is_active=True).order_by('sort_order', 'id')
    for alias in source_aliases:
        raw_source_name = (alias.raw_source_name or '').strip()
        if raw_source_name:
            source_names.append(raw_source_name)
    return tuple(dict.fromkeys(source_names))


def get_definition_remove_keys(definition) -> tuple[str, ...]:
    keys = [f'char_{definition.code}']
    keys.extend(f'char_{source_name}' for source_name in get_definition_source_names(definition))
    return tuple(dict.fromkeys(keys))


def map_definitions_by_source_name(definitions) -> dict[str, object]:
    mapping = {}
    for definition in definitions:
        for source_name in get_definition_source_names(definition):
            mapping[source_name] = definition
    return mapping


def source_name_similarity_score(left: str, right: str) -> int:
    left_tokens = set(normalize_source_name_tokens(left))
    right_tokens = set(normalize_source_name_tokens(right))
    if not left_tokens or not right_tokens:
        return 0
    shared = left_tokens & right_tokens
    return len(shared)


def build_source_name_groups(source_names: list[str]) -> dict[tuple[str, ...], list[str]]:
    grouped = defaultdict(list)
    for source_name in source_names:
        grouped[normalize_source_name_tokens(source_name)].append(source_name)
    return grouped
