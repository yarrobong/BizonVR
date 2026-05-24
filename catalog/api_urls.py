from django.urls import path

from .views.api import catalog_bundle_detail_view, catalog_item_detail_view, catalog_items_view

app_name = 'catalog_api'

urlpatterns = [
    path('catalog/items', catalog_items_view, name='items'),
    path('catalog/items/<path:item_id>', catalog_item_detail_view, name='item_detail'),
    path('catalog/bundles/<path:bundle_id>', catalog_bundle_detail_view, name='bundle_detail'),
]
