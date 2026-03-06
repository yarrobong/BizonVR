from .contacts import contacts_view
from .debug import debug_cities_view
from .home import home_view
from .legal_pages import (
    cookies_policy_view,
    oferta_view,
    pd_consent_view,
    privacy_view,
    sales_terms_view,
    service_request_terms_view,
    user_agreement_view,
)
from .static_pages import arenda_view, favicon_view, robots_txt_view, serve_media, uslugi_view

__all__ = [
    'arenda_view',
    'contacts_view',
    'cookies_policy_view',
    'debug_cities_view',
    'favicon_view',
    'home_view',
    'oferta_view',
    'pd_consent_view',
    'privacy_view',
    'robots_txt_view',
    'sales_terms_view',
    'service_request_terms_view',
    'serve_media',
    'user_agreement_view',
    'uslugi_view',
]
