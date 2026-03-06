"""Helpers for public stock presentation."""

from __future__ import annotations


PUBLIC_STOCK_HIGH_THRESHOLD = 10


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
