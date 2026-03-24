"""MVP-рекомендации для PDP: правила, совместимость, исключения, ранжирование."""
from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Set

from django.db.models import Count, Sum

from orders.models import Order, OrderItem

from .cart_services import get_cart_items
from .models import Product, ProductBundleItem, ProductStock, ProductVariant


COMPATIBILITY_KEYS = {
    'compatibility', 'совместимость', 'device', 'устройство', 'устройства', 'для устройства'
}

DEVICE_ALIASES = {
    'meta quest 3s': 'quest 3s',
    'oculus quest 3s': 'quest 3s',
    'quest3s': 'quest 3s',
    'meta quest 3': 'quest 3',
    'oculus quest 3': 'quest 3',
    'quest3': 'quest 3',
    'meta quest 2': 'quest 2',
    'oculus quest 2': 'quest 2',
    'quest2': 'quest 2',
    'quest pro': 'quest pro',
    'pico 4 ultra': 'pico 4 ultra',
    'pico4 ultra': 'pico 4 ultra',
    'pico 4': 'pico 4',
    'pico4': 'pico 4',
}

SIGNAL_TOKEN_IGNORED = {
    'vr', 'для', 'with', 'and', 'the', 'plus', 'lite', 'pack',
    'метров', 'метр', 'м', 'на', 'под', 'из', 'в', 'во', 'с', 'со', 'к', 'по',
    'для', 'и', 'или', 'другие', 'другой', 'other', 'others',
    'комплект', 'комплекты', 'набор', 'наборы',
    'кабель', 'кабели', 'кейс', 'кейсы', 'чехол', 'чехлы',
    'крепление', 'крепления', 'маска', 'маски', 'защита',
    'аккумулятор', 'акб', 'станция', 'зарядная', 'роутер', 'телевизор',
    'аттракцион', 'шлем', 'headset', 'strap', 'cover', 'case', 'battery', 'station',
}
LEXICAL_TOKEN_IGNORED = {
    'для', 'with', 'and', 'the', 'метров', 'метр', 'м',
    'на', 'под', 'из', 'в', 'во', 'с', 'со', 'к', 'по', 'и', 'или',
    'красный', 'синий', 'black', 'white', 'red', 'blue',
}
USELESS_DEVICE_TOKENS = {'другие', 'другое', 'и другие', 'other', 'others'}
SAME_CATEGORY_LEXICAL_THRESHOLD = 0.22
CROSS_CATEGORY_LEXICAL_THRESHOLD = 0.3


@lru_cache(maxsize=1)
def load_rules_config() -> dict:
    cfg_path = Path(__file__).with_name('recommendation_rules.json')
    if not cfg_path.exists():
        return {
            'default_max_per_section': 6,
            'alternatives_limit': 5,
            'sections': {
                'frequently_bought': {
                    'title': 'С этим часто покупают',
                    'badge': 'Часто берут вместе',
                    'enabled': True,
                },
                'similar_products': {
                    'title': 'Похожие',
                    'badge': 'Похожие',
                    'enabled': True,
                },
            },
        }
    with cfg_path.open('r', encoding='utf-8') as fh:
        return json.load(fh)


def _normalize_text(text: str) -> str:
    s = (text or '').strip().lower()
    s = s.replace('ё', 'е')
    return re.sub(r'\s+', ' ', s)


DEVICE_NAME_PHRASES = tuple(
    sorted(
        {_normalize_text(key) for key in DEVICE_ALIASES} | {_normalize_text(value) for value in DEVICE_ALIASES.values()},
        key=len,
        reverse=True,
    )
)


def _normalize_device_token(token: str) -> str:
    t = _normalize_text(token)
    t = re.sub(r'[()\[\],;:+]+', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return DEVICE_ALIASES.get(t, t)


def _split_multi_values(raw_value: str) -> List[str]:
    if not raw_value:
        return []
    parts = re.split(r'\s*(?:\\|/|\||,|;|&|\+|\band\b|\bи\b)\s*', raw_value, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p.strip()]
    return parts or [raw_value.strip()]


def _characteristics_map(product: Product) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = defaultdict(list)
    for ch in product.characteristics.all():
        key = _normalize_text(ch.name)
        val = (ch.value or '').strip()
        if key and val:
            result[key].append(val)
    return result


def _extract_devices(product: Product) -> Set[str]:
    devices: Set[str] = set()
    ch_map = _characteristics_map(product)
    for key, values in ch_map.items():
        if key in COMPATIBILITY_KEYS or 'совместим' in key or 'compat' in key:
            for raw in values:
                for token in _split_multi_values(raw):
                    normalized = _normalize_device_token(token)
                    if normalized and normalized not in USELESS_DEVICE_TOKENS:
                        devices.add(normalized)
    return devices


def _tokenize(text: str) -> List[str]:
    return re.findall(r'[a-zа-я0-9]+', _normalize_text(text))


def _extract_name_signal_tokens(product: Product) -> Set[str]:
    normalized_name = _normalize_text(product.name)
    tokens: Set[str] = set()

    for phrase in DEVICE_NAME_PHRASES:
        if re.search(rf'(?<!\w){re.escape(phrase)}(?!\w)', normalized_name):
            tokens.add(DEVICE_ALIASES.get(phrase, phrase))

    for token in _tokenize(product.name):
        if token.isdigit() or len(token) < 2 or token in SIGNAL_TOKEN_IGNORED:
            continue
        tokens.add(token)
    return tokens


def _extract_lexical_tokens(text: str) -> Set[str]:
    tokens = set()
    for token in _tokenize(text):
        if token.isdigit() or len(token) < 2 or token in LEXICAL_TOKEN_IGNORED:
            continue
        tokens.add(token)
    return tokens


def _lexical_similarity(current_name: str, candidate_name: str) -> float:
    current_tokens = _extract_lexical_tokens(current_name)
    candidate_tokens = _extract_lexical_tokens(candidate_name)
    token_overlap = 0.0
    if current_tokens and candidate_tokens:
        token_overlap = len(current_tokens & candidate_tokens) / max(len(current_tokens), len(candidate_tokens))
    sequence_ratio = SequenceMatcher(None, _normalize_text(current_name), _normalize_text(candidate_name)).ratio()
    return max(token_overlap, sequence_ratio * 0.55)


def _rank_similar_candidates(entries: List[dict], total_map: dict) -> List[Product]:
    ranked = sorted(
        entries,
        key=lambda entry: (
            entry['level'],
            -entry['score'],
            0 if _is_in_stock(entry['product'].pk, total_map) else 1,
            -(entry['product'].views_count or 0),
            entry['product'].pk,
        ),
    )
    return [entry['product'] for entry in ranked]


def _bundle_excluded_product_ids(product: Product) -> Set[int]:
    bundle_ids = (
        ProductBundleItem.objects.filter(product=product)
        .values_list('bundle_id', flat=True)
        .distinct()
    )
    if not bundle_ids:
        return set()
    return set(
        ProductBundleItem.objects.filter(bundle_id__in=bundle_ids)
        .exclude(product=product)
        .values_list('product_id', flat=True)
    )


def _cart_product_ids(request) -> Set[int]:
    if not request:
        return set()
    return {item.get('product_id') for item in get_cart_items(request) if item.get('product_id')}


def _stock_maps(product_ids: Iterable[int]):
    ids = list(product_ids)
    if not ids:
        return {}
    total_rows = (
        ProductStock.objects
        .filter(product_id__in=ids)
        .values('product_id')
        .annotate(total=Sum('quantity'))
    )
    return {row['product_id']: int(row['total'] or 0) for row in total_rows}


def _is_in_stock(product_id: int, total_map: dict) -> bool:
    return total_map.get(product_id, 0) > 0


def _compatible(current_devices: Set[str], candidate_devices: Set[str]) -> bool:
    if not current_devices:
        return True
    if not candidate_devices:
        # Если у кандидата нет явной совместимости, оставляем для rules-map (MVP fallback).
        return True
    return bool(current_devices & candidate_devices)


def _co_purchase_scores(product: Product) -> Dict[int, float]:
    order_ids = (
        OrderItem.objects
        .filter(product=product)
        .exclude(order__status=Order.STATUS_CANCELLED)
        .values_list('order_id', flat=True)
        .distinct()
    )
    if not order_ids:
        return {}
    rows = (
        OrderItem.objects
        .filter(order_id__in=order_ids)
        .exclude(product=product)
        .values('product_id')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')
    )
    max_cnt = max((row['cnt'] for row in rows), default=0)
    if not max_cnt:
        return {}
    return {row['product_id']: row['cnt'] / max_cnt for row in rows}


def _build_first_variant_map(product_ids: Iterable[int]) -> Dict[int, int]:
    ids = list(product_ids)
    if not ids:
        return {}
    variants = ProductVariant.objects.filter(product_id__in=ids).order_by('product_id', 'order', 'id')
    first: Dict[int, int] = {}
    for v in variants:
        if v.product_id not in first:
            first[v.product_id] = v.pk
    return first


def build_pdp_recommendations(request, product: Product) -> dict:
    cfg = load_rules_config()
    max_per_section = int(cfg.get('default_max_per_section', 6))
    alternatives_limit = int(cfg.get('alternatives_limit', 5))

    current_devices = _extract_devices(product)
    current_name_tokens = _extract_name_signal_tokens(product)

    excluded_ids = {product.pk}
    excluded_ids.update(_cart_product_ids(request))
    excluded_ids.update(_bundle_excluded_product_ids(product))

    candidates = list(
        Product.objects.filter(is_active=True)
        .exclude(pk__in=excluded_ids)
        .select_related('category')
        .prefetch_related('characteristics', 'variants')
    )

    if not candidates:
        return {
            'sections': [],
            'product_stock_total': {},
            'recommended_variant_ids': {},
        }

    compat_filtered: List[Product] = []
    co_purchase = _co_purchase_scores(product)

    for candidate in candidates:
        c_devices = _extract_devices(candidate)
        if not _compatible(current_devices, c_devices):
            continue
        compat_filtered.append(candidate)

    all_candidate_ids = [p.pk for p in compat_filtered]
    total_map = _stock_maps(all_candidate_ids)

    sections = []

    # 1) Часто покупают вместе
    if cfg.get('sections', {}).get('frequently_bought', {}).get('enabled', True):
        freq_candidates = [p for p in compat_filtered if p.pk in co_purchase]
        freq_sorted = sorted(
            freq_candidates,
            key=lambda p: (
                0 if _is_in_stock(p.pk, total_map) else 1,
                -co_purchase.get(p.pk, 0),
                -(p.views_count or 0),
            ),
        )
        freq_products = freq_sorted[:max_per_section]
        if freq_products:
            sections.append({
                'key': 'frequently_bought',
                'title': cfg['sections'].get('frequently_bought', {}).get('title', 'С этим часто покупают'),
                'badge': cfg['sections'].get('frequently_bought', {}).get('badge', 'Часто берут вместе'),
                'products': freq_products,
            })

    # 2) Похожие товары
    if cfg.get('sections', {}).get('similar_products', {}).get('enabled', True):
        early_entries = []
        late_entries = []
        last_resort_entries = []
        for candidate in compat_filtered:
            candidate_devices = _extract_devices(candidate)
            compatibility_overlap = current_devices & candidate_devices
            name_token_overlap = current_name_tokens & _extract_name_signal_tokens(candidate)
            lexical_score = _lexical_similarity(product.name, candidate.name)

            if candidate.category_id == product.category_id:
                if compatibility_overlap:
                    early_entries.append({
                        'level': 1,
                        'score': len(compatibility_overlap) * 10 + len(name_token_overlap) * 2 + lexical_score,
                        'product': candidate,
                    })
                elif name_token_overlap:
                    early_entries.append({
                        'level': 2,
                        'score': len(name_token_overlap) * 10 + lexical_score,
                        'product': candidate,
                    })
                elif lexical_score >= SAME_CATEGORY_LEXICAL_THRESHOLD:
                    early_entries.append({
                        'level': 3,
                        'score': lexical_score,
                        'product': candidate,
                    })
            elif compatibility_overlap and (
                name_token_overlap or lexical_score >= CROSS_CATEGORY_LEXICAL_THRESHOLD
            ):
                late_entries.append({
                    'level': 4,
                    'score': len(compatibility_overlap) * 10 + len(name_token_overlap) * 2 + lexical_score,
                    'product': candidate,
                })
            elif compatibility_overlap:
                last_resort_entries.append({
                    'level': 5,
                    'score': len(compatibility_overlap),
                    'product': candidate,
                })

        similar_products = _rank_similar_candidates(early_entries, total_map)[:alternatives_limit]
        if len(similar_products) < alternatives_limit:
            remaining = alternatives_limit - len(similar_products)
            similar_products.extend(_rank_similar_candidates(late_entries, total_map)[:remaining])
        if len(similar_products) < alternatives_limit:
            remaining = alternatives_limit - len(similar_products)
            similar_products.extend(_rank_similar_candidates(last_resort_entries, total_map)[:remaining])

        if similar_products:
            sections.append({
                'key': 'similar_products',
                'title': cfg['sections'].get('similar_products', {}).get('title', 'Похожие'),
                'badge': cfg['sections'].get('similar_products', {}).get('badge', 'Похожие'),
                'products': similar_products,
            })

    # Пустые секции не рендерим
    sections = [s for s in sections if s.get('products')]

    final_ids: List[int] = []
    for sec in sections:
        for p in sec['products']:
            if p.pk not in final_ids:
                final_ids.append(p.pk)

    final_total_map = _stock_maps(final_ids)
    variant_ids = _build_first_variant_map(final_ids)

    return {
        'sections': sections,
        'product_stock_total': final_total_map,
        'recommended_variant_ids': variant_ids,
    }
