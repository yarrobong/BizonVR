import json
import logging

from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import Payment
from ..services import is_valid_payment_status_transition, normalize_np_status, verify_ipn_signature
from orders.models import Order
from orders.services import sync_order_state_side_effects

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(['POST'])
def webhook_view(request):
    """
    Webhook платёжного провайдера.
    Проверяем подпись, обновляем Payment и Order.
    """
    signature_header = ''.join(['x-', 'now', 'payments', '-sig'])
    signature = request.headers.get(signature_header, '')
    try:
        body_raw = request.body.decode('utf-8') if request.body else '{}'
    except UnicodeDecodeError:
        return HttpResponseBadRequest('Invalid JSON', status=400)

    if not verify_ipn_signature(body_raw, signature):
        return HttpResponseBadRequest('Invalid signature', status=400)

    try:
        data = json.loads(body_raw)
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON', status=400)
    if not isinstance(data, dict):
        return HttpResponseBadRequest('Invalid JSON payload', status=400)

    payment_id = data.get('payment_id')
    order_id = data.get('order_id')
    raw_np_status = data.get('payment_status')
    np_status = raw_np_status.lower() if isinstance(raw_np_status, str) else ''

    if not order_id or not payment_id:
        return JsonResponse({'ok': False, 'error': 'missing payment_id or order_id'}, status=400)

    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'invalid order_id'}, status=400)

    if np_status not in {'waiting', 'confirming', 'sent', 'finished', 'failed', 'refunded', 'expired', 'partially_paid'}:
        return JsonResponse({'ok': False, 'error': 'invalid payment_status'}, status=400)

    order_for_side_effects = None
    previous_payment_status = None
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related('order').filter(
            order_id=order_id,
            external_id=str(payment_id),
        ).first()
        if not payment:
            return JsonResponse({'ok': False, 'error': 'payment not found'}, status=404)

        target_status = normalize_np_status(np_status)
        if not is_valid_payment_status_transition(payment.status, target_status):
            return JsonResponse({'ok': False, 'error': 'invalid payment status transition'}, status=409)

        order = None
        if np_status == 'finished':
            order = Order.objects.select_for_update().get(pk=payment.order_id)
            if order.payment_status == Order.PAYMENT_STATUS_REFUNDED:
                return JsonResponse({'ok': False, 'error': 'order payment already refunded'}, status=409)

        payment.ipn_data = data
        payment.status = target_status
        payment.save(update_fields=['status', 'ipn_data', 'updated_at'])

        if np_status == 'finished':
            previous_payment_status = order.payment_status
            if order.payment_status != order.PAYMENT_STATUS_PAID:
                order.payment_status = Order.PAYMENT_STATUS_PAID
                order.save(update_fields=['payment_status', 'updated_at'])
                order_for_side_effects = order

    if order_for_side_effects is not None:
        try:
            sync_order_state_side_effects(
                order_for_side_effects,
                previous_status=order_for_side_effects.status,
                previous_payment_status=previous_payment_status,
            )
        except Exception:
            logger.exception(
                'Payment webhook side effects failed for order %s.',
                order_for_side_effects.pk,
            )

    return JsonResponse({'ok': True})
