"""MVP-рекомендации для PDP: правила, совместимость, исключения, ранжирование."""
from __future__ import annotations

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
PRODUCT_TYPE_KEYS = {'type', 'тип', 'product_type', 'тип товара'}

TYPE_KEYWORDS = {
    'headset': ('шлем', 'headset'),
    'strap': ('креплен', 'strap', 'head strap', 'ремень'),
    'battery': ('аккумулятор', 'battery', 'power bank'),
    'dock': ('док', 'dock', 'dock station', 'станц'),
    'protection': ('защит', 'маска', 'cover', 'grip', 'линза', 'интерфейс'),
    'case': ('кейс', 'чехол', 'case', 'bag'),
    'cable': ('кабель', 'cable', 'link'),
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


@lru_cache(maxsize=1)
def load_rules_config() -> dict:
    cfg_path = Path(__file__).with_name('recommendation_rules.json')
    if not cfg_path.exists():
        return {
            'default_max_per_section': 6,
            'alternatives_limit': 5,
            'sections': {},
            'type_rules': {'default': {'target_types': ['accessory'], 'per_type_limit': 2}},
        }
    with cfg_path.open('r', encoding='utf-8') as fh:
        return json.load(fh)


def _normalize_text(text: str) -> str:
    s = (text or '').strip().lower()
    s = s.replace('ё', 'е')
    return re.sub(r'\s+', ' ', s)


def _normalize_device_token(token: str) -> str:
    t = _normalize_text(token)
    t = re.sub(r'[()\[\],;:+]+', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return DEVICE_ALIASES.get(t, t)


def _split_multi_values(raw_value: str) -> List[str]:
    if not raw_value:
        return []
    value = raw_value.replace('\\', '/').replace('|', '/').replace(',', '/').replace(';', '/')
    parts = [p.strip() for p in value.split('/') if p.strip()]
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
                    if normalized:
                        devices.add(normalized)
    return devices


def _normalize_product_type(raw_type: str) -> str:
    txt = _normalize_text(raw_type)
    if not txt:
        return 'accessory'
    for normalized, keywords in TYPE_KEYWORDS.items():
        if any(k in txt for k in keywords):
            return normalized
    return 'accessory'


def _extract_product_type(product: Product) -> str:
    ch_map = _characteristics_map(product)
    for key, values in ch_map.items():
        if key in PRODUCT_TYPE_KEYS:
            for val in values:
                normalized = _normalize_product_type(val)
                if normalized:
                    return normalized
    haystack = f"{product.name} {product.category.name if product.category_id else ''}"
    return _normalize_product_type(haystack)


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


def _stock_maps(product_ids: Iterable[int], selected_city_id: int | None):
    ids = list(product_ids)
    if not ids:
        return {}, {}
    total_rows = (
        ProductStock.objects
        .filter(product_id__in=ids)
        .values('product_id')
        .annotate(total=Sum('quantity'))
    )
    total_map = {row['product_id']: int(row['total'] or 0) for row in total_rows}
    city_map = {}
    if selected_city_id:
        city_rows = (
            ProductStock.objects
            .filter(product_id__in=ids, pickup_point__city_id=selected_city_id)
            .values('product_id')
            .annotate(total=Sum('quantity'))
        )
        city_map = {row['product_id']: int(row['total'] or 0) for row in city_rows}
    return total_map, city_map


def _is_in_stock(product_id: int, selected_city_id: int | None, city_map: dict, total_map: dict) -> bool:
    if selected_city_id:
        return city_map.get(product_id, 0) > 0 or total_map.get(product_id, 0) > 0
    return total_map.get(product_id, 0) > 0


def _rank_mvp(products: List[Product], selected_city_id: int | None, city_map: dict, total_map: dict) -> List[Product]:
    return sorted(
        products,
        key=lambda p: (
            0 if _is_in_stock(p.pk, selected_city_id, city_map, total_map) else 1,
            -(p.views_count or 0),
            -float(p.price),
            p.pk,
        ),
    )


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
    selected_city_id = request.session.get('selected_city_id') if request else None

    current_type = _extract_product_type(product)
    current_devices = _extract_devices(product)

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
            'product_stock_in_city': {},
            'recommended_variant_ids': {},
        }

    by_type: Dict[str, List[Product]] = defaultdict(list)
    compat_filtered: List[Product] = []
    candidate_devices_map: Dict[int, Set[str]] = {}
    co_purchase = _co_purchase_scores(product)

    for candidate in candidates:
        c_devices = _extract_devices(candidate)
        candidate_devices_map[candidate.pk] = c_devices
        if not _compatible(current_devices, c_devices):
            continue
        compat_filtered.append(candidate)
        c_type = _extract_product_type(candidate)
        by_type[c_type].append(candidate)

    all_candidate_ids = [p.pk for p in compat_filtered]
    total_map, city_map = _stock_maps(all_candidate_ids, selected_city_id)

    sections = []

    # 1) Часто покупают вместе
    if cfg.get('sections', {}).get('frequently_bought', {}).get('enabled', True):
        freq_candidates = [p for p in compat_filtered if p.pk in co_purchase]
        freq_sorted = sorted(
            freq_candidates,
            key=lambda p: (
                0 if _is_in_stock(p.pk, selected_city_id, city_map, total_map) else 1,
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

    # 2) Совместимые аксессуары по rules-map
    if cfg.get('sections', {}).get('compatible_accessories', {}).get('enabled', True):
        type_cfg = cfg.get('type_rules', {}).get(current_type) or cfg.get('type_rules', {}).get('default', {})
        target_types = type_cfg.get('target_types', [])
        per_type_limit = int(type_cfg.get('per_type_limit', 2))

        selected = []
        selected_ids = set()
        for target_type in target_types:
            pool = _rank_mvp(by_type.get(target_type, []), selected_city_id, city_map, total_map)
            taken = 0
            for item in pool:
                if item.pk in selected_ids:
                    continue
                selected.append(item)
                selected_ids.add(item.pk)
                taken += 1
                if taken >= per_type_limit:
                    break
            if len(selected) >= max_per_section:
                break

        if len(selected) < max_per_section:
            fallback_pool = _rank_mvp(compat_filtered, selected_city_id, city_map, total_map)
            for item in fallback_pool:
                if item.pk in selected_ids:
                    continue
                selected.append(item)
                selected_ids.add(item.pk)
                if len(selected) >= max_per_section:
                    break

        if selected:
            sections.append({
                'key': 'compatible_accessories',
                'title': cfg['sections'].get('compatible_accessories', {}).get('title', 'Аксессуары, которые подходят'),
                'badge': cfg['sections'].get('compatible_accessories', {}).get('badge', 'Совместимо'),
                'products': selected,
            })

    # 3) Альтернативы
    if cfg.get('sections', {}).get('alternatives', {}).get('enabled', True):
        alt_pool = [
            p for p in compat_filtered
            if (_extract_product_type(p) == current_type or p.category_id == product.category_id)
        ]
        alt_sorted = _rank_mvp(alt_pool, selected_city_id, city_map, total_map)
        alt_products = alt_sorted[:alternatives_limit]
        if alt_products:
            sections.append({
                'key': 'alternatives',
                'title': cfg['sections'].get('alternatives', {}).get('title', 'Альтернативы'),
                'badge': cfg['sections'].get('alternatives', {}).get('badge', 'Альтернатива'),
                'products': alt_products,
            })

    # Пустые секции не рендерим
    sections = [s for s in sections if s.get('products')]

    final_ids: List[int] = []
    for sec in sections:
        for p in sec['products']:
            if p.pk not in final_ids:
                final_ids.append(p.pk)

    final_total_map, final_city_map = _stock_maps(final_ids, selected_city_id)
    variant_ids = _build_first_variant_map(final_ids)

    return {
        'sections': sections,
        'product_stock_total': final_total_map,
        'product_stock_in_city': final_city_map,
        'recommended_variant_ids': variant_ids,
    }
