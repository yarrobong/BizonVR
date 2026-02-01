from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('', views.ProductListView.as_view(), name='product_list'),
    path('set-city/', views.set_city_view, name='set_city'),
    path('favorites/', views.favorite_list_view, name='favorites'),
    path('product/<slug:slug>/', views.ProductDetailView.as_view(), name='product_detail'),
    path('cart/', views.cart_page_view, name='cart'),
    path('cart/partial/', views.cart_partial, name='cart_partial'),
    path('cart/add/<int:product_id>/', views.add_to_cart_view, name='add_to_cart'),
    path('cart/update/', views.cart_update_view, name='cart_update'),
    path('favorite/<int:product_id>/', views.toggle_favorite_view, name='toggle_favorite'),
]
