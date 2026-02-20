"""Персонализированные рекомендации для блока «Еще товары» перед футером."""
from __future__ import annotations

from collections import defaultdict
from typing import List

from django.db.models import Count, F

from .cart_services import get_cart_items, get_favorite_product_ids
from .models import Product
from .recommendations import _co_purchase_scores

# 8 pages × max(15 home, 12 catalog) = 120
FOOTER_PRODUCTS_MAX_IDS = 120


def get_footer_recommended_product_ids(request) -> List[int]:
    """
    Возвращает список ID товаров в порядке приоритета для персонализации:
    1. Co-purchase (часто покупают вместе с корзиной/избранным)
    2. Похожие по категории (избранное/просмотренное)
    3. Популярные товары
    4. Остальные по дате создания
    """
    cart_ids = {
        item.get('product_id')
        for item in (get_cart_items(request) or [])
        if item.get('product_id')
    }
    favorite_ids = get_favorite_product_ids(request) or set()
    viewed_ids = request.session.get('viewed_product_ids', []) or []

    context_ids = list((cart_ids | favorite_ids | set(viewed_ids)))[:15]
    context_ids = [pid for pid in context_ids if pid]

    seen: set = set()
    result: List[int] = []

    def add_ids(ids_iter, limit: int = FOOTER_PRODUCTS_MAX_IDS):
        for pid in ids_iter:
            if pid not in seen and len(result) < limit:
                seen.add(pid)
                result.append(pid)

    # 1. Co-purchase по корзине и избранному
    if context_ids:
        context_products = list(
            Product.objects.filter(pk__in=context_ids, is_active=True).only('pk')
        )
        co_scores: dict = defaultdict(float)
        for product in context_products:
            for pid, score in _co_purchase_scores(product).items():
                if pid not in context_ids:
                    co_scores[pid] += score

        co_sorted = sorted(
            co_scores.items(),
            key=lambda x: -x[1],
        )
        add_ids(pid for pid, _ in co_sorted)

    # 2. Похожие по категории (из контекста)
    if context_ids and len(result) < FOOTER_PRODUCTS_MAX_IDS:
        category_ids = list(
            Product.objects.filter(pk__in=context_ids, is_active=True)
            .values_list('category_id', flat=True)
            .distinct()
        )
        if category_ids:
            similar_ids = (
                Product.objects.filter(
                    category_id__in=category_ids,
                    is_active=True,
                )
                .exclude(pk__in=seen)
                .order_by('-views_count', '-created_at')
                .values_list('pk', flat=True)[: FOOTER_PRODUCTS_MAX_IDS - len(result)]
            )
            add_ids(similar_ids)

    # 3. Популярные
    if len(result) < FOOTER_PRODUCTS_MAX_IDS:
        popular_ids = (
            Product.objects.filter(is_active=True)
            .exclude(pk__in=seen)
            .annotate(
                favorited_count=Count('favorited_by', distinct=True),
                cart_count=Count('cart_items', distinct=True),
            )
            .annotate(
                popularity=F('views_count') + F('favorited_count') * 5 + F('cart_count') * 3,
            )
            .order_by('-popularity', '-created_at')
            .values_list('pk', flat=True)[: FOOTER_PRODUCTS_MAX_IDS - len(result)]
        )
        add_ids(popular_ids)

    # 4. Fallback по дате
    if len(result) < FOOTER_PRODUCTS_MAX_IDS:
        fallback_ids = (
            Product.objects.filter(is_active=True)
            .exclude(pk__in=seen)
            .order_by('-created_at')
            .values_list('pk', flat=True)[: FOOTER_PRODUCTS_MAX_IDS - len(result)]
        )
        add_ids(fallback_ids)

    return result[:FOOTER_PRODUCTS_MAX_IDS]
