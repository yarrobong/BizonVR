"""
Сервисы заказов: начисление бонуса партнёру при оплате заказа по промокоду;
списание остатков с точек выдачи при оплате.
"""
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.services import normalize_email, normalize_phone

ORDER_STATUS_PRESENTATIONS = {
    'new': {
        'label': 'Ждёт подтверждения',
        'description': 'Заказ получен. Проверяем детали, наличие и способ получения.',
        'next_step': 'Дальше: менеджер проверит наличие, доставку и итоговую сумму и свяжется с вами в течение дня.',
        'badge_class': 'border-amber-400/20 bg-amber-500/10 text-amber-200',
        'tone': 'warning',
        'important_sms': True,
    },
    'confirmed': {
        'description': 'Заказ подтверждён магазином и готовится к следующему этапу.',
        'next_step': 'Дальше: ожидается оплата или подготовка к отгрузке.',
        'badge_class': 'border-cyan-400/20 bg-cyan-500/10 text-cyan-200',
        'tone': 'info',
        'important_sms': True,
    },
    'shipping': {
        'description': 'Заказ передан в доставку или находится в пути.',
        'next_step': 'Дальше: дождитесь выдачи или доставки по адресу.',
        'badge_class': 'border-accent/20 bg-accent/10 text-accent',
        'tone': 'accent',
        'important_sms': True,
    },
    'ready_for_pickup': {
        'description': 'Заказ собран и уже доступен к получению.',
        'next_step': 'Дальше: можно приехать в точку выдачи или согласовать время получения.',
        'badge_class': 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
        'tone': 'success',
        'important_sms': True,
    },
    'done': {
        'description': 'Заказ завершён и сохранён в истории покупок.',
        'next_step': 'Дальше: при необходимости можно вернуться к повторной покупке или сервису.',
        'badge_class': 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
        'tone': 'success',
        'important_sms': False,
    },
    'cancelled': {
        'description': 'Заказ отменён. При необходимости поможем оформить новый.',
        'next_step': 'Дальше: можно связаться с магазином или оформить заказ заново.',
        'badge_class': 'border-white/10 bg-white/5 text-gray-300',
        'tone': 'muted',
        'important_sms': True,
    },
}

PAYMENT_STATUS_PRESENTATIONS = {
    'unpaid': {
        'description': 'Оплачивать сейчас не нужно. Реквизиты или счёт отправит менеджер после подтверждения заказа.',
        'badge_class': 'border-white/10 bg-white/5 text-gray-300',
    },
    'pending_confirmation': {
        'description': 'Платёж ожидает подтверждения магазином.',
        'badge_class': 'border-amber-400/20 bg-amber-500/10 text-amber-200',
    },
    'paid': {
        'description': 'Оплата получена и зафиксирована.',
        'badge_class': 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
    },
    'refunded': {
        'description': 'Платёж возвращён.',
        'badge_class': 'border-white/10 bg-white/5 text-gray-300',
    },
}

ORDER_EVENT_PRESENTATIONS = {
    'order_created': {
        'label': 'Заказ принят',
        'description': 'Мы получили заказ. Менеджер проверит наличие, доставку и итоговую сумму, свяжется с вами в течение дня и пришлёт реквизиты или счёт. Сейчас оплачивать ничего не нужно.',
        'sms_text': 'BizonVR: заказ #{order_id} принят. Свяжемся с вами в течение дня.',
        'badge_class': ORDER_STATUS_PRESENTATIONS['new']['badge_class'],
    },
    'order_confirmed': {
        'label': 'Заказ подтверждён магазином',
        'description': 'Менеджер подтвердил заказ и уточнил наличие.',
        'sms_text': 'BizonVR: заказ #{order_id} подтверждён.',
        'badge_class': ORDER_STATUS_PRESENTATIONS['confirmed']['badge_class'],
    },
    'payment_received': {
        'label': 'Оплата получена',
        'description': 'Мы зафиксировали оплату по заказу.',
        'sms_text': 'BizonVR: оплата по заказу #{order_id} получена.',
        'badge_class': PAYMENT_STATUS_PRESENTATIONS['paid']['badge_class'],
    },
    'order_shipped': {
        'label': 'Заказ передан в доставку',
        'description': 'Заказ передан в доставку.',
        'sms_text': 'BizonVR: заказ #{order_id} отправлен.',
        'badge_class': ORDER_STATUS_PRESENTATIONS['shipping']['badge_class'],
    },
    'order_ready_for_pickup': {
        'label': 'Заказ готов к выдаче',
        'description': 'Заказ можно получать в точке выдачи.',
        'sms_text': 'BizonVR: заказ #{order_id} готов к выдаче.',
        'badge_class': ORDER_STATUS_PRESENTATIONS['ready_for_pickup']['badge_class'],
    },
    'order_cancelled': {
        'label': 'Заказ отменён',
        'description': 'Заказ отменён. Если нужна помощь, свяжитесь с магазином.',
        'sms_text': 'BizonVR: заказ #{order_id} отменён.',
        'badge_class': ORDER_STATUS_PRESENTATIONS['cancelled']['badge_class'],
    },
}


def build_order_status_summary(order):
    status_meta = ORDER_STATUS_PRESENTATIONS.get(order.status, ORDER_STATUS_PRESENTATIONS['new'])
    payment_meta = PAYMENT_STATUS_PRESENTATIONS.get(
        order.payment_status,
        PAYMENT_STATUS_PRESENTATIONS['unpaid'],
    )
    return {
        'status': order.status,
        'status_label': status_meta.get('label') or order.get_status_display(),
        'status_description': status_meta['description'],
        'status_next_step': status_meta['next_step'],
        'status_badge_class': status_meta['badge_class'],
        'status_tone': status_meta['tone'],
        'payment_status': order.payment_status,
        'payment_label': order.get_payment_status_display(),
        'payment_description': payment_meta['description'],
        'payment_badge_class': payment_meta['badge_class'],
        'is_sms_status': bool(status_meta.get('important_sms')),
    }


def get_order_event_presentation(event):
    return ORDER_EVENT_PRESENTATIONS.get(event, {})


def apply_partner_bonus_for_order(order):
    """
    Начислить бонус партнёру за заказ, оплаченный по промокоду.
    Вызывать при переходе заказа в статус «Оплачен» (webhook или тестовый режим).
    Идемпотентно: повторный вызов не дублирует начисление.
    """
    if order.payment_status != 'paid':
        return
    if order.partner_bonus_applied:
        return
    promo = order.promo_code
    if not promo or not promo.partner_user_id or not promo.partner_bonus or promo.partner_bonus <= 0:
        return

    from accounts.models import BalanceTransaction
    from accounts.services import ensure_profile

    with transaction.atomic():
        order.refresh_from_db()
        if order.partner_bonus_applied:
            return
        profile = ensure_profile(promo.partner_user)
        BalanceTransaction.objects.create(
            user=promo.partner_user,
            kind=BalanceTransaction.TYPE_PROMO_BONUS,
            amount=promo.partner_bonus,
            order=order,
        )
        profile.balance += promo.partner_bonus
        profile.save(update_fields=['balance'])
        order.partner_bonus_applied = True
        order.save(update_fields=['partner_bonus_applied'])


def decrease_stock_for_order(order):
    """
    Списать остатки по заказу при переходе в статус «Оплачен».
    Если у заказа указана точка выдачи — списываем с неё; иначе — с одной из точек города.
    Идемпотентно: не списывает повторно (order.stock_decreased).
    """
    if order.payment_status != 'paid':
        return
    if order.stock_decreased:
        return

    from catalog.models import ProductStock, PickupPoint

    with transaction.atomic():
        order.refresh_from_db()
        if order.stock_decreased:
            return
        try:
            from manager_portal.services import consume_inventory_for_order
        except Exception:
            consume_inventory_for_order = None
        if consume_inventory_for_order and consume_inventory_for_order(order):
            order.stock_decreased = True
            order.save(update_fields=['stock_decreased'])
            return
        for item in order.items.select_related('product').all():
            if item.is_on_request or not item.product_id:
                continue
            product_id = item.product_id
            qty = item.quantity
            if order.pickup_point_id:
                ProductStock.objects.filter(
                    product_id=product_id,
                    pickup_point_id=order.pickup_point_id,
                ).update(quantity=F('quantity') - qty)
            elif order.city_id:
                points = list(
                    PickupPoint.objects.filter(city_id=order.city_id)
                    .order_by('order', 'id')
                )
                for point in points:
                    stock = ProductStock.objects.filter(
                        product_id=product_id,
                        pickup_point_id=point.pk,
                    ).first()
                    if stock and stock.quantity >= qty:
                        ProductStock.objects.filter(pk=stock.pk).update(
                            quantity=F('quantity') - qty
                        )
                        break
                    elif stock and stock.quantity > 0:
                        take = min(qty, stock.quantity)
                        ProductStock.objects.filter(pk=stock.pk).update(
                            quantity=F('quantity') - take
                        )
                        qty -= take
                        if qty <= 0:
                            break
        order.stock_decreased = True
        order.save(update_fields=['stock_decreased'])


def issue_guest_access(order, *, ttl_days=30):
    order.refresh_guest_access(ttl_days=ttl_days)
    order.save(update_fields=['guest_access_token', 'guest_access_expires_at'])
    return order.guest_access_token


def build_guest_order_url(order, request=None):
    token = quote(order.guest_access_token or '')
    path = reverse('orders:guest_order_detail', kwargs={'token': token})
    if request is not None:
        return request.build_absolute_uri(path)
    return f"{getattr(settings, 'SITE_URL', '').rstrip('/')}{path}"


def claim_guest_orders_for_user(user, *, verified_email=''):
    from .models import Order

    email = normalize_email(verified_email)
    if not email:
        return 0
    queryset = Order.objects.filter(user__isnull=True, email__iexact=email)

    matched_ids = []
    for order in queryset.only('id', 'email', 'phone'):
        email_matches = bool(email and normalize_email(order.email) == email)
        if email_matches:
            matched_ids.append(order.pk)

    if not matched_ids:
        return 0
    return Order.objects.filter(pk__in=matched_ids, user__isnull=True).update(user=user)


def send_order_event_notifications(order, event, *, request=None):
    from .models import OrderNotificationLog

    event_meta = get_order_event_presentation(event)
    if not event_meta:
        return
    if order.email:
        _, created = OrderNotificationLog.objects.get_or_create(
            order=order,
            event=event,
            channel=OrderNotificationLog.CHANNEL_EMAIL,
        )
        if created:
            _send_order_event_email(order, event, request=request)


def sync_order_state_side_effects(order, *, previous_status=None, previous_payment_status=None, request=None):
    previous_status = previous_status or ''
    previous_payment_status = previous_payment_status or ''

    if previous_payment_status != order.payment_status and order.payment_status == order.PAYMENT_STATUS_PAID:
        apply_partner_bonus_for_order(order)
        send_order_event_notifications(order, 'payment_received', request=request)

    if previous_status != order.status:
        try:
            from manager_portal.services import (
                ensure_manager_client_for_order,
                ensure_order_reservations,
                release_order_reservations,
            )
        except Exception:
            ensure_manager_client_for_order = None
            ensure_order_reservations = None
            release_order_reservations = None

        if order.status == order.STATUS_CONFIRMED:
            if ensure_manager_client_for_order and ensure_order_reservations:
                client_resolution = ensure_manager_client_for_order(order)
                ensure_order_reservations(
                    order,
                    client_resolution['client'],
                    author=getattr(request, 'user', None) if request is not None else None,
                    strict=False,
                    comment='Автоматический резерв после подтверждения заказа.',
                )
            send_order_event_notifications(order, 'order_confirmed', request=request)
        elif order.status == order.STATUS_SHIPPING:
            send_order_event_notifications(order, 'order_shipped', request=request)
        elif order.status == order.STATUS_READY_FOR_PICKUP:
            send_order_event_notifications(order, 'order_ready_for_pickup', request=request)
        elif order.status == order.STATUS_CANCELLED:
            if release_order_reservations:
                release_order_reservations(
                    order,
                    author=getattr(request, 'user', None) if request is not None else None,
                )
            send_order_event_notifications(order, 'order_cancelled', request=request)

    try:
        from manager_portal.services import sync_order_workflow_state
    except Exception:
        sync_order_workflow_state = None
    if sync_order_workflow_state:
        sync_order_workflow_state(order, previous_status=previous_status)


def _build_order_email_context(order, event, request=None):
    items = list(order.items.select_related('product').all())
    event_meta = get_order_event_presentation(event)
    return {
        'brand': getattr(settings, 'SITE_BRAND', 'BizonVR'),
        'event_title': event_meta['label'],
        'event_description': event_meta['description'],
        'event_badge_class': event_meta['badge_class'],
        'order': order,
        'items': items,
        'order_summary': build_order_status_summary(order),
        'shop_email': getattr(settings, 'SITE_CONTACT_EMAIL', '').strip(),
        'shop_phone': getattr(settings, 'SITE_CONTACT_PHONE', '').strip(),
        'order_url': _build_order_url_for_email(order, request=request),
    }


def _build_order_url_for_email(order, *, request=None):
    if order.user_id:
        path = reverse('orders:order_detail', kwargs={'pk': order.pk})
        if request is not None:
            return request.build_absolute_uri(path)
        return f"{getattr(settings, 'SITE_URL', '').rstrip('/')}{path}"
    return ''


def _send_order_event_email(order, event, *, request=None):
    context = _build_order_email_context(order, event, request=request)
    subject = f"{context['event_title']} #{order.pk}"
    text_body = render_to_string('emails/order_event.txt', context)
    html_body = render_to_string('emails/order_event.html', context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[order.email],
    )
    message.attach_alternative(html_body, 'text/html')
    message.send(fail_silently=False)


def _send_order_event_sms(order, event):
    template = get_order_event_presentation(event).get('sms_text')
    if not template:
        return
    send_sms_message(order.phone, template.format(order_id=order.pk))
