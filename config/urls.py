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
from decouple import config
from django.contrib import admin
from django.urls import path, include, re_path

from config.views import contacts_view, favicon_view, home_view, privacy_view, serve_media

urlpatterns = [
    path('favicon.ico', favicon_view),
    path('admin/', admin.site.urls),
    path('contacts/', contacts_view, name='contacts'),
    path('privacy/', privacy_view, name='privacy'),
    path('page/oferta/', privacy_view, name='oferta'),
    path('accounts/', include('accounts.urls')),
    path('orders/', include('orders.urls')),
    path('payments/', include('payments.urls')),
    path('catalog/', include('catalog.urls')),
    path('', home_view, name='home'),
]
# Медиа: в DEBUG или SERVE_MEDIA=1 — раздаём через serve_media
if settings.DEBUG or config('SERVE_MEDIA', default=False, cast=bool):
    urlpatterns = [re_path(r'^media/(?P<path>.*)$', serve_media)] + urlpatterns
