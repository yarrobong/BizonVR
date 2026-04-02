from .checkout import checkout_promo_view, checkout_view, order_created_view, request_created_view
from .cdek_widget import cdek_widget_service_view
from .guest import order_guest_detail_view, order_guest_lookup_view, order_guest_view
from .history import order_detail_view, order_list_view

__all__ = [
    'cdek_widget_service_view',
    'checkout_view',
    'checkout_promo_view',
    'order_created_view',
    'order_detail_view',
    'order_guest_detail_view',
    'order_guest_lookup_view',
    'order_guest_view',
    'order_list_view',
    'request_created_view',
]
