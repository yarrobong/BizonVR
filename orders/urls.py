from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.order_list_view, name='order_list'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('request-created/<int:request_id>/', views.request_created_view, name='request_created'),
    path('created/<int:order_id>/', views.order_created_view, name='order_created'),
    path('guest/access/<str:token>/', views.order_guest_detail_view, name='guest_order_detail'),
    path('guest/', views.order_guest_lookup_view, name='order_guest_lookup'),
    path('guest/<int:order_id>/', views.order_guest_view, name='order_guest'),
    path('<int:pk>/', views.order_detail_view, name='order_detail'),
]
