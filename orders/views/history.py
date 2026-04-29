from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from accounts.views.profile import build_account_sidebar_context

from ..models import Order
from ..services import build_order_status_summary


@login_required
def order_list_view(request):
    """Страница «Мои заказы»: список заказов пользователя."""
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product').order_by('-created_at')
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        orders = orders.filter(status=status_filter)
    status_rows = (
        Order.objects.filter(user=request.user)
        .values('status')
        .annotate(total=Count('id'))
    )
    status_counters = {row['status']: row['total'] for row in status_rows}
    order_rows = [
        {
            'instance': order,
            'summary': build_order_status_summary(order),
        }
        for order in orders
    ]
    active_orders_count = sum(
        total for status, total in status_counters.items()
        if status not in {Order.STATUS_DONE, Order.STATUS_CANCELLED}
    )
    context = {
        'order_rows': order_rows,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
        'total_orders_count': sum(status_counters.values()),
        'active_orders_count': active_orders_count,
        'new_orders_count': status_counters.get(Order.STATUS_NEW, 0),
        'delivery_orders_count': (
            status_counters.get(Order.STATUS_CONFIRMED, 0)
            + status_counters.get(Order.STATUS_SHIPPING, 0)
            + status_counters.get(Order.STATUS_READY_FOR_PICKUP, 0)
        ),
    }
    context.update(build_account_sidebar_context(request, active_tab='orders'))
    return render(request, 'orders/order_list.html', context)


@login_required
def order_detail_view(request, pk):
    """Детали заказа (только свой)."""
    order = get_object_or_404(Order, pk=pk, user=request.user)
    context = {
        'order': order,
        'order_summary': build_order_status_summary(order),
        'is_guest_order': False,
        'guest_access_token': '',
    }
    context.update(build_account_sidebar_context(request, active_tab='orders'))
    return render(request, 'orders/order_detail.html', context)
