from django.urls import path

from . import views

app_name = 'operations'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('deals/', views.deal_list_view, name='deal_list'),
    path('history/', views.history_view, name='history'),
    path('deals/<int:pk>/', views.deal_detail_view, name='deal_detail'),
    path('deals/<int:pk>/reserve/', views.reservation_form_view, name='deal_reserve_create'),
    path('deals/<int:pk>/shipments/<int:shipment_pk>/send/', views.shipment_dispatch_form_view, name='deal_shipment_dispatch'),
    path('deals/<int:pk>/delivery/', views.deal_delivery_edit_view, name='deal_delivery_edit'),
    path('deals/<int:pk>/cargo/receive/', views.cargo_receive_view, name='deal_cargo_receive'),
    path('deals/<int:pk>/cargo/create/', views.cargo_form_view, name='deal_cargo_create'),
    path('deals/<int:pk>/purchase/<int:item_pk>/', views.purchase_form_view, name='purchase_form'),
    path('bitrix/deal-in-work/', views.bitrix_deal_in_work_view, name='bitrix_deal_in_work'),
]
