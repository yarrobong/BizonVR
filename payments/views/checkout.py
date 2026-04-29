from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from orders.models import Order


def _get_payment_order_access(request, order_id):
    access_token = (request.POST.get('access') or request.GET.get('access') or '').strip()
    guest_access = ''

    if request.user.is_authenticated:
        owned_order = Order.objects.filter(pk=order_id, user=request.user).first()
        if owned_order is not None:
            return owned_order, guest_access

    guest_order = Order.objects.filter(pk=order_id, user__isnull=True).first()
    if guest_order is not None:
        if access_token and guest_order.is_guest_access_valid(access_token):
            return guest_order, access_token
        if access_token:
            raise Http404('Guest access expired')

    if request.user.is_authenticated:
        raise Http404('Order not found')
    login_url = reverse('accounts:login')
    return None, f'{login_url}?next={request.get_full_path()}'
def _build_public_order_redirect_url(order, *, guest_access_token=''):
    if order.user_id:
        return reverse('orders:order_detail', kwargs={'pk': order.pk})
    path = reverse('orders:order_created', kwargs={'order_id': order.pk})
    if guest_access_token:
        return f'{path}?access={guest_access_token}'
    return path


@require_http_methods(['GET', 'POST'])
def create_payment_view(request, order_id):
    """
    Legacy entrypoint публичной оплаты.
    В manager-only flow не создаёт Payment и возвращает пользователя к заказу.
    Доступ: свой заказ или guest-заказ по защищённому токену.
    """
    order, access_result = _get_payment_order_access(request, order_id)
    if order is None:
        return redirect(access_result)
    guest_access_token = access_result
    return redirect(_build_public_order_redirect_url(order, guest_access_token=guest_access_token))


def payment_wait_view(request, order_id):
    """Legacy экран ожидания оплаты: в публичном flow возвращает пользователя к заказу."""
    order, access_result = _get_payment_order_access(request, order_id)
    if order is None:
        return redirect(access_result)
    guest_access_token = access_result
    return redirect(_build_public_order_redirect_url(order, guest_access_token=guest_access_token))
