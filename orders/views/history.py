from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from ..models import Order


@login_required
def order_list_view(request):
    """Страница «Мои заказы»: список заказов пользователя."""
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        orders = orders.filter(status=status_filter)
    return render(request, 'orders/order_list.html', {
        'orders': orders,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
    })


@login_required
def order_detail_view(request, pk):
    """Детали заказа (только свой)."""
    order = get_object_or_404(Order, pk=pk, user=request.user)
    return render(request, 'orders/order_detail.html', {
        'order': order,
        'is_guest_order': False,
        'test_order_no_payment': getattr(settings, 'TEST_ORDER_NO_PAYMENT', False),
    })
