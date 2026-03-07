from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

from ..models import Order


def order_guest_lookup_view(request):
    """Старый guest entrypoint: статус заказа доступен только после входа."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    return redirect('orders:order_list')


def order_guest_view(request, order_id):
    """Старый guest entrypoint: после входа открываем только собственный заказ."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if Order.objects.filter(pk=order_id, user=request.user).exists():
        return redirect('orders:order_detail', pk=order_id)
    return redirect('orders:order_list')
