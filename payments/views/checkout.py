from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from orders.models import Order

from ..models import Payment
from ..services import create_payment as np_create_payment, normalize_np_status


@login_required
@require_http_methods(['GET', 'POST'])
def create_payment_view(request, order_id):
    """
    Создать платёж NowPayments для заказа и редирект на страницу оплаты.
    Доступ только к своим заказам со статусом «новый».
    """
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    if order.status != Order.STATUS_NEW:
        return redirect('orders:order_detail', pk=order_id)

    pending = order.payments.filter(status__in=[
        Payment.STATUS_PENDING,
        Payment.STATUS_WAITING,
        Payment.STATUS_CONFIRMING,
        Payment.STATUS_SENT,
    ]).first()
    if pending and pending.pay_url:
        return redirect(pending.pay_url)
    if pending:
        return redirect('payments:payment_wait', order_id=order_id)

    if request.method == 'GET':
        return render(request, 'payments/create_payment.html', {'order': order})

    order_detail_url = reverse('orders:order_detail', kwargs={'pk': order_id})
    success_url = request.build_absolute_uri(order_detail_url)
    cancel_url = request.build_absolute_uri(order_detail_url)
    ipn_url = request.build_absolute_uri(reverse('payments:webhook'))

    data, err = np_create_payment(
        order,
        success_url=success_url,
        cancel_url=cancel_url,
        ipn_callback_url=ipn_url,
    )
    if err:
        return render(request, 'payments/create_payment.html', {
            'order': order,
            'error': err,
        })

    payment = Payment.objects.create(
        order=order,
        external_id=str(data.get('payment_id', '')),
        price_amount=order.total_to_pay,
        price_currency=data.get('price_currency', 'usd'),
        pay_amount=Decimal(str(data['pay_amount'])) if data.get('pay_amount') is not None else None,
        pay_currency=data.get('pay_currency', ''),
        pay_address=data.get('pay_address', ''),
        pay_url=data.get('invoice_url') or data.get('pay_url', ''),
        status=normalize_np_status(data.get('payment_status')),
    )

    if payment.pay_url:
        return redirect(payment.pay_url)
    return redirect('payments:payment_wait', order_id=order_id)


@login_required
def payment_wait_view(request, order_id):
    """Страница «Ожидание оплаты»: инструкция и статус; при успехе webhook — редирект/обновление."""
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    payment = order.payments.filter(
        status__in=[
            Payment.STATUS_PENDING,
            Payment.STATUS_WAITING,
            Payment.STATUS_CONFIRMING,
            Payment.STATUS_SENT,
        ]
    ).order_by('-created_at').first()

    return render(request, 'payments/payment_wait.html', {
        'order': order,
        'payment': payment,
    })
