"""
Платежи NowPayments (Фаза 5): создание инвойса, webhook IPN, страница ожидания.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from orders.models import Order

from .models import Payment
from .services import create_payment as np_create_payment, normalize_np_status, verify_ipn_signature


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

    # Уже есть активный платёж — редирект на него
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

    # POST: создать платёж в NowPayments
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


@csrf_exempt
@require_http_methods(['POST'])
def webhook_view(request):
    """
    IPN callback от NowPayments.
    Проверяем подпись x-nowpayments-sig, обновляем Payment и Order.
    """
    signature = request.headers.get('x-nowpayments-sig', '')
    body_raw = request.body.decode('utf-8') if request.body else '{}'

    if not verify_ipn_signature(body_raw, signature):
        return HttpResponseBadRequest('Invalid signature', status=400)

    import json
    try:
        data = json.loads(body_raw)
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON', status=400)

    payment_id = data.get('payment_id')
    order_id = data.get('order_id')
    np_status = (data.get('payment_status') or '').lower()

    if not order_id:
        return JsonResponse({'ok': False, 'error': 'missing order_id'}, status=400)

    payment = Payment.objects.filter(
        order_id=int(order_id),
        external_id=str(payment_id),
    ).first()
    if not payment:
        return JsonResponse({'ok': False, 'error': 'payment not found'}, status=404)

    payment.ipn_data = data
    payment.status = normalize_np_status(np_status)
    payment.save(update_fields=['status', 'ipn_data', 'updated_at'])

    if np_status == 'finished':
        order = payment.order
        if order.status == Order.STATUS_NEW:
            order.status = Order.STATUS_PAID
            order.save(update_fields=['status', 'updated_at'])
            from orders.services import apply_partner_bonus_for_order, decrease_stock_for_order
            apply_partner_bonus_for_order(order)
            decrease_stock_for_order(order)

    return JsonResponse({'ok': True})
