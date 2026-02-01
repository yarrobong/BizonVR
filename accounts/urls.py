from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('send-code/', views.send_code_view, name='send_code'),
    path('verify/', views.verify_code_view, name='verify_code'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/balance/', views.balance_history_view, name='balance_history'),
]
