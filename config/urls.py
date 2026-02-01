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

from config.views import home_view, serve_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('orders/', include('orders.urls')),
    path('payments/', include('payments.urls')),
    path('catalog/', include('catalog.urls')),
    path('', home_view, name='home'),
]

# Медиа: в DEBUG — встроенный static(); при SERVE_MEDIA=1 — свой view (serve при DEBUG=False отдаёт 404)
if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif config('SERVE_MEDIA', default=False, cast=bool):
    urlpatterns += [re_path(r'^media/(?P<path>.*)$', serve_media)]
