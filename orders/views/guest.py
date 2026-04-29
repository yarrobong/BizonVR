from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect, render

from accounts.services import (
    normalize_email,
)
from ..models import Order
from ..services import build_order_status_summary, claim_guest_orders_for_user


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


def order_guest_detail_view(request, token):
    order = Order.objects.filter(guest_access_token=token).prefetch_related('items__product').first()
    if not order:
        raise Http404('Order not found')

    if not order.is_guest_order:
        if request.user.is_authenticated and order.user_id == request.user.id:
            return redirect('orders:order_detail', pk=order.pk)
        raise Http404('Order not available')

    if not order.is_guest_access_valid(token):
        raise Http404('Guest access expired')

    claim_login_url = redirect_to_login(request.get_full_path(), login_url='accounts:login').url
    can_claim_after_login = False

    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        verified_email = normalize_email(request.user.email or '')
        order_email = normalize_email(order.email or '')
        if profile and profile.email_verified_at and verified_email and verified_email == order_email:
            claim_guest_orders_for_user(
                request.user,
                verified_email=order.email,
            )
            return redirect('orders:order_detail', pk=order.pk)
        can_claim_after_login = bool(profile and profile.email_verified_at and order_email)

    return render(request, 'orders/order_detail.html', {
        'order': order,
        'order_summary': build_order_status_summary(order),
        'is_guest_order': True,
        'guest_access_token': token,
        'claim_login_url': claim_login_url,
        'can_claim_after_login': can_claim_after_login,
    })
