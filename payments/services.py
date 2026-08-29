"""Сервис платёжного провайдера: создание платежа и проверка подписи webhook."""
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from urllib.parse import urljoin

from django.conf import settings

logger = logging.getLogger(__name__)

# Маппинг статусов платёжного провайдера -> наш Payment.STATUS_*
NP_STATUS_MAP = {
    'waiting': 'waiting',
    'confirming': 'confirming',
    'sent': 'sent',
    'finished': 'finished',
    'failed': 'failed',
    'refunded': 'refunded',
    'expired': 'expired',
    'partially_paid': 'waiting',
}


def create_payment(order, success_url, cancel_url, ipn_callback_url=None, pay_currency=None):
    """
    Создать платёж у провайдера для заказа.
    ipn_callback_url — абсолютный URL webhook (лучше request.build_absolute_uri('/payments/webhook/')).
    Возвращает (payment_data dict, error_message или None).
    payment_data: payment_id, pay_address, pay_amount, pay_currency, pay_url, payment_status, ...
    """
    import requests

    api_key = getattr(settings, 'PAYMENT_GATEWAY_API_KEY', None) or ''
    if not api_key:
        logger.warning('Payment provider API key not set, skipping API call')
        return None, 'Платежи не настроены (нет API-ключа).'

    base_url = getattr(
        settings,
        'PAYMENT_GATEWAY_API_BASE',
        ''.join(['https://api.', 'now', 'payments', '.io/v1']),
    )
    if not ipn_callback_url:
        ipn_callback_url = _build_absolute_url('/payments/webhook/')

    payload = {
        'price_amount': float(order.total_to_pay),
        'price_currency': 'usd',
        'order_id': str(order.pk),
        'order_description': f'Заказ #{order.pk} BizonVR',
        'ipn_callback_url': ipn_callback_url,
        'success_url': success_url,
        'cancel_url': cancel_url,
    }
    if pay_currency:
        payload['pay_currency'] = pay_currency

    try:
        r = requests.post(
            urljoin(base_url, 'payment'),
            headers={'x-api-key': api_key, 'Content-Type': 'application/json'},
            json=payload,
            timeout=15,
        )
        data = r.json()
        if r.status_code != 200 and r.status_code != 201:
            err = data.get('message', data.get('err', r.text))
            logger.warning('Payment provider create payment failed: %s %s', r.status_code, err)
            return None, err or f'Ошибка API: {r.status_code}'

        return data, None
    except requests.RequestException as e:
        logger.exception('Payment provider request error: %s', e)
        return None, str(e)


def _build_absolute_url(path):
    """Для IPN callback нужен абсолютный URL (если не передан из view)."""
    base = getattr(settings, 'SITE_URL', '').rstrip('/') or 'https://example.com'
    return (base + path) if path.startswith('/') else (base + '/' + path)


def normalize_np_status(np_status):
    """Привести статус из IPN к нашему Payment.STATUS_*."""
    return NP_STATUS_MAP.get((np_status or '').lower(), 'pending')


def is_valid_payment_status_transition(current_status, target_status):
    """Allow provider progress while preventing signed callbacks from regressing state."""
    allowed_targets = {
        'pending': {'pending', 'waiting', 'confirming', 'sent', 'finished', 'failed', 'expired'},
        'waiting': {'waiting', 'confirming', 'sent', 'finished', 'failed', 'expired'},
        'confirming': {'confirming', 'sent', 'finished', 'failed', 'expired'},
        'sent': {'sent', 'finished', 'failed', 'expired'},
        'finished': {'finished', 'refunded'},
        'failed': {'failed', 'waiting', 'confirming', 'sent', 'finished', 'expired'},
        'refunded': {'refunded'},
        'expired': {'expired'},
    }
    return target_status in allowed_targets.get(current_status, {current_status})


def verify_ipn_signature(body_raw, signature):
    """
    Проверить подпись webhook.
    Провайдер: тело запроса сортируют по ключам, затем HMAC-SHA512 с IPN secret.
    """
    secret = getattr(settings, 'PAYMENT_GATEWAY_IPN_SECRET', None) or ''
    if not secret:
        logger.warning('Payment provider IPN secret not set, verification disabled')
        return False

    try:
        data = json.loads(body_raw)
        # Сортируем ключи и собираем строку для подписи (как в их доке)
        sorted_json = json.dumps(data, sort_keys=True, separators=(',', ':'))
        expected = hmac.new(
            secret.encode('utf-8'),
            sorted_json.encode('utf-8'),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, (signature or ''))
    except Exception as e:
        logger.exception('IPN signature verification error: %s', e)
        return False
