from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect, render

from accounts.forms import EmailLoginRequestForm, EmailLoginVerifyForm
from accounts.models import EmailLoginCode
from accounts.security import (
    check_send_email_rate_limits,
    check_verify_email_code_rate_limits,
    mark_send_email_success,
)
from accounts.services import (
    create_and_send_email_login_code,
    normalize_email,
    resolve_or_create_user_for_order_claim,
    verify_email_login_code,
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

    claim_request_form = EmailLoginRequestForm(initial={'email': order.email})
    claim_verify_form = EmailLoginVerifyForm(initial={'email': order.email})
    claim_email_sent = False
    claim_error = ''

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'send_claim_email_code':
            claim_request_form = EmailLoginRequestForm(request.POST)
            if claim_request_form.is_valid():
                email = claim_request_form.cleaned_data['email']
                if email != normalize_email(order.email):
                    claim_request_form.add_error('email', 'Используйте email, указанный в заказе.')
                else:
                    ok_rate, rate_error = check_send_email_rate_limits(request, email, endpoint='order-claim-email')
                    if not ok_rate:
                        claim_request_form.add_error('email', rate_error)
                    else:
                        ok, error = create_and_send_email_login_code(
                            email,
                            purpose=EmailLoginCode.PURPOSE_ORDER_CLAIM,
                            require_existing_user=False,
                        )
                        if ok:
                            mark_send_email_success(request, email, endpoint='order-claim-email')
                            claim_email_sent = True
                        else:
                            claim_request_form.add_error('email', error)
        elif action == 'verify_claim_email_code':
            claim_verify_form = EmailLoginVerifyForm(request.POST)
            if claim_verify_form.is_valid():
                email = claim_verify_form.cleaned_data['email']
                code = claim_verify_form.cleaned_data['code']
                if email != normalize_email(order.email):
                    claim_verify_form.add_error('email', 'Используйте email, указанный в заказе.')
                else:
                    ok_rate, rate_error = check_verify_email_code_rate_limits(
                        request,
                        email,
                        endpoint='order-claim-email-verify',
                    )
                    if not ok_rate:
                        claim_verify_form.add_error('code', rate_error)
                    else:
                        ok, error = verify_email_login_code(
                            email,
                            code,
                            purpose=EmailLoginCode.PURPOSE_ORDER_CLAIM,
                            consume=True,
                        )
                        if not ok:
                            claim_verify_form.add_error('code', error)
                        else:
                            user = resolve_or_create_user_for_order_claim(order.email, order.phone)
                            claim_guest_orders_for_user(
                                user,
                                verified_email=order.email,
                                verified_phone=order.phone,
                            )
                            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                            return redirect('orders:order_detail', pk=order.pk)
        else:
            claim_error = 'Неизвестное действие.'

    return render(request, 'orders/order_detail.html', {
        'order': order,
        'order_summary': build_order_status_summary(order),
        'is_guest_order': True,
        'guest_access_token': token,
        'test_order_no_payment': getattr(settings, 'TEST_ORDER_NO_PAYMENT', False),
        'claim_request_form': claim_request_form,
        'claim_verify_form': claim_verify_form,
        'claim_email_sent': claim_email_sent,
        'claim_error': claim_error,
    })
