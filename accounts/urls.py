from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('password-reset/', views.password_reset_request_view, name='password_reset_request'),
    path('password-reset/verify/', views.password_reset_phone_verify_view, name='password_reset_phone_verify'),
    path('password-reset/set-password/', views.password_reset_set_password_view, name='password_reset_set_password'),
    path('password-reset/confirm/<uidb64>/<token>/', views.password_reset_confirm_view, name='password_reset_confirm'),
    path('send-code/', views.send_code_view, name='send_code'),
    path('resend-code/', views.resend_code_view, name='resend_code'),
    path('verify/', views.verify_code_view, name='verify_code'),
    path('complete-registration/', views.complete_registration_view, name='complete_registration'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/balance/', views.balance_history_view, name='balance_history'),
]
