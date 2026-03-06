import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import Payment
from ..services import normalize_np_status, verify_ipn_signature


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
        if order.status == order.STATUS_NEW:
            order.status = order.STATUS_PAID
            order.save(update_fields=['status', 'updated_at'])
            from orders.services import apply_partner_bonus_for_order, decrease_stock_for_order

            apply_partner_bonus_for_order(order)
            decrease_stock_for_order(order)

    return JsonResponse({'ok': True})
