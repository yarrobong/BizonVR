from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('order/<int:order_id>/create/', views.create_payment_view, name='create_payment'),
    path('order/<int:order_id>/wait/', views.payment_wait_view, name='payment_wait'),
    path('webhook/', views.webhook_view, name='webhook'),
]
