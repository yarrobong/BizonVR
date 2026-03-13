import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import Payment
from ..services import normalize_np_status, verify_ipn_signature
from orders.services import sync_order_state_side_effects


@csrf_exempt
@require_http_methods(['POST'])
def webhook_view(request):
    """
    Webhook платёжного провайдера.
    Проверяем подпись, обновляем Payment и Order.
    """
    signature_header = ''.join(['x-', 'now', 'payments', '-sig'])
    signature = request.headers.get(signature_header, '')
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
        previous_payment_status = order.payment_status
        if order.payment_status != order.PAYMENT_STATUS_PAID:
            order.payment_status = order.PAYMENT_STATUS_PAID
            order.save(update_fields=['payment_status', 'updated_at'])
            sync_order_state_side_effects(
                order,
                previous_status=order.status,
                previous_payment_status=previous_payment_status,
            )

    return JsonResponse({'ok': True})
