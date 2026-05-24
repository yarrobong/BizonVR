"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include, re_path

from config.env import config_bool, is_runserver_command
from config.views import (
    arenda_view,
    compact_vr_view,
    conference_attractions_view,
    contacts_view,
    cookies_policy_view,
    debug_cities_view,
    favicon_view,
    home_view,
    invest_2_view,
    invest_2_new_view,
    invest_view,
    oferta_view,
    pd_consent_view,
    privacy_view,
    robots_txt_view,
    sales_terms_view,
    service_request_terms_view,
    serve_media,
    not_found_view,
    solution_landing_view,
    solutions_index_view,
    user_agreement_view,
    uslugi_view,
)
from config.sitemaps import BundleSitemap, ProductSitemap, SolutionLandingSitemap, SolutionsHubSitemap, StaticViewSitemap
from catalog.views import vr_attractions_yml_feed_view

handler403 = 'config.views.permission_denied_view'
handler404 = 'config.views.not_found_view'

urlpatterns = [
    path('favicon.ico', favicon_view),
    path('robots.txt', robots_txt_view),
    path('feeds/vr-attractions.yml', vr_attractions_yml_feed_view, name='vr_attractions_yml_feed'),
    path('admin/', admin.site.urls),
    path('arenda/', arenda_view, name='arenda'),
    path('compact-vr/', compact_vr_view, name='compact_vr'),
    path('conference-attractions/', conference_attractions_view, name='conference_attractions'),
    re_path(r'^conference-attractions/(?P<path>.+)$', conference_attractions_view),
    path('invest/', invest_view, name='invest'),
    re_path(r'^invest/(?P<path>.+)$', invest_view),
    path('invest-2/', invest_2_view, name='invest_2'),
    re_path(r'^invest-2/(?P<path>.+)$', invest_2_view),
    path('invest-2-new/', invest_2_new_view, name='invest_2_new'),
    re_path(r'^invest-2-new/(?P<path>.+)$', invest_2_new_view),
    path('solutions/', solutions_index_view, name='solutions_index'),
    path('solutions/<slug:slug>/', solution_landing_view, name='solution_landing'),
    path('solutions/<slug:slug>/<path:path>', solution_landing_view, name='solution_landing_asset'),
    path('uslugi/', uslugi_view, name='uslugi'),
    path('contacts/', contacts_view, name='contacts'),
    path('privacy/', privacy_view, name='privacy'),
    path('page/oferta/', oferta_view, name='oferta'),
    path('page/user-agreement/', user_agreement_view, name='user_agreement'),
    path('page/pd-consent/', pd_consent_view, name='pd_consent'),
    path('page/cookies/', cookies_policy_view, name='cookies_policy'),
    path('page/sales-terms/', sales_terms_view, name='sales_terms'),
    path('page/service-request-terms/', service_request_terms_view, name='service_request_terms'),
    path('accounts/', include('accounts.urls')),
    path('orders/', include('orders.urls')),
    path('payments/', include('payments.urls')),
    path('catalog/', include('catalog.urls')),
    path('api/v1/', include('catalog.api_urls')),
    path('manager/', include('manager_portal.urls')),
    path('', home_view, name='home'),
    path(
        'sitemap.xml',
        sitemap,
        {
            'sitemaps': {
                'static': StaticViewSitemap,
                'solutions_hub': SolutionsHubSitemap,
                'solutions': SolutionLandingSitemap,
                'products': ProductSitemap,
                'bundles': BundleSitemap,
            }
        },
        name='django_sitemap',
    ),
]
if settings.DEBUG:
    urlpatterns.append(path('debug-cities/', debug_cities_view, name='debug_cities'))
# Медиа: в DEBUG или SERVE_MEDIA=1 — раздаём через serve_media
# Локальный runserver тоже должен видеть MEDIA при prod-подобном DEBUG=False.
if settings.DEBUG or config_bool('SERVE_MEDIA', default=False) or is_runserver_command():
    urlpatterns = [re_path(r'^media/(?P<path>.*)$', serve_media)] + urlpatterns
