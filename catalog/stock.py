"""Helpers for public stock presentation."""

from __future__ import annotations


PUBLIC_STOCK_HIGH_THRESHOLD = 5


def public_stock_status(quantity):
    """Return a machine-readable stock status for public UI."""
    qty = int(quantity or 0)
    if qty >= PUBLIC_STOCK_HIGH_THRESHOLD:
        return {
            'code': 'in_stock_high',
            'label': 'Много',
        }
    if qty > 0:
        return {
            'code': 'in_stock_low',
            'label': 'Мало',
        }
    return {
        'code': 'on_request',
        'label': 'Под заказ',
    }


def public_product_stock_status(product, quantity):
    """Return a public availability status for a concrete product."""
    if getattr(product, 'is_game_pack', False):
        return {
            'code': 'digital_pack',
            'label': 'Цифровой пакет',
        }
    if getattr(product, 'is_game_product', False):
        return {
            'code': 'in_stock_high',
            'label': 'В наличии',
        }
    return public_stock_status(quantity)
