from decimal import Decimal

from django.conf import settings

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from orders.models import Order
from orders.services import build_guest_order_url

from ..models import Payment
from ..services import create_payment as np_create_payment, normalize_np_status


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


def _build_order_detail_url(order, *, request=None, guest_access_token=''):
    if order.user_id:
        path = reverse('orders:order_detail', kwargs={'pk': order.pk})
        if request is None:
            return path
        return request.build_absolute_uri(path)

    token = guest_access_token or order.guest_access_token
    if request is None:
        return reverse('orders:guest_order_detail', kwargs={'token': token})
    return build_guest_order_url(order, request=request)


def _build_payment_wait_url(order, *, guest_access_token=''):
    path = reverse('payments:payment_wait', kwargs={'order_id': order.pk})
    if guest_access_token:
        return f'{path}?access={guest_access_token}'
    return path


def _get_active_payment_profile():
    try:
        from manager_portal.models import ContractCompanyProfile
    except Exception:
        return None
    return ContractCompanyProfile.objects.filter(is_active=True).order_by('-updated_at', '-id').first()


def _build_payment_page_context(order, *, guest_access_token='', order_url=''):
    profile = _get_active_payment_profile()
    card_number = (getattr(profile, 'card_number', '') or '').strip()
    sbp_phone = (getattr(profile, 'sbp_phone', '') or '').strip()
    recipient_name = (
        getattr(profile, 'company_name', '')
        or getattr(profile, 'name', '')
        or getattr(settings, 'LEGAL_OPERATOR_SHORT_NAME', '')
    ).strip()

    method_hint = {
        Order.PAYMENT_METHOD_BANK_CARD: 'Оплатите заказ переводом на банковскую карту по реквизитам ниже.',
        Order.PAYMENT_METHOD_SBP: 'Оплатите заказ переводом по СБП по реквизитам ниже.',
        Order.PAYMENT_METHOD_MANAGER_PAYMENT: 'Для оплаты от юридического лица свяжитесь с менеджером и согласуйте реквизиты и документы.',
    }.get(order.payment_method, 'Следуйте инструкции по оплате ниже.')

    return {
        'order': order,
        'order_url': order_url,
        'guest_access_token': guest_access_token,
        'payment_method_code': order.payment_method,
        'payment_method_label': order.get_payment_method_display(),
        'payment_method_hint': method_hint,
        'payment_recipient_name': recipient_name,
        'payment_card_number': card_number,
        'payment_sbp_phone': sbp_phone,
        'payment_contact_phone': getattr(settings, 'SITE_CONTACT_PHONE', '').strip(),
        'payment_contact_phone_href': getattr(settings, 'SITE_CONTACT_PHONE_HREF', '').strip(),
        'payment_contact_email': getattr(settings, 'SITE_CONTACT_EMAIL', '').strip(),
        'payment_contact_telegram': getattr(settings, 'SITE_CONTACT_TELEGRAM', '').strip(),
        'payment_contact_telegram_handle': getattr(settings, 'SITE_CONTACT_TELEGRAM_HANDLE', '').strip(),
        'is_manual_payment': order.payment_method in {
            Order.PAYMENT_METHOD_BANK_CARD,
            Order.PAYMENT_METHOD_SBP,
            Order.PAYMENT_METHOD_MANAGER_PAYMENT,
        },
        'is_legacy_provider_payment': order.payment_method == Order.PAYMENT_METHOD_ONLINE,
    }


@require_http_methods(['GET', 'POST'])
def create_payment_view(request, order_id):
    """
    Открыть страницу оплаты заказа.
    Доступ: свой заказ или guest-заказ по защищённому токену.
    """
    order, access_result = _get_payment_order_access(request, order_id)
    if order is None:
        return redirect(access_result)
    guest_access_token = access_result
    order_url = _build_order_detail_url(order, guest_access_token=guest_access_token)

    if order.payment_status == Order.PAYMENT_STATUS_PAID:
        return redirect(order_url)
    if order.payment_method in {
        Order.PAYMENT_METHOD_BANK_CARD,
        Order.PAYMENT_METHOD_SBP,
        Order.PAYMENT_METHOD_MANAGER_PAYMENT,
    }:
        return render(
            request,
            'payments/create_payment.html',
            _build_payment_page_context(
                order,
                guest_access_token=guest_access_token,
                order_url=order_url,
            ),
        )
    if order.status != Order.STATUS_NEW:
        return redirect(order_url)
    if order.payment_method == Order.PAYMENT_METHOD_CASH_ON_DELIVERY:
        return redirect(order_url)

    pending = order.payments.filter(status__in=[
        Payment.STATUS_PENDING,
        Payment.STATUS_WAITING,
        Payment.STATUS_CONFIRMING,
        Payment.STATUS_SENT,
    ]).first()
    if pending and pending.pay_url:
        return redirect(pending.pay_url)
    if pending:
        return redirect(_build_payment_wait_url(order, guest_access_token=guest_access_token))

    if request.method == 'GET':
        return render(
            request,
            'payments/create_payment.html',
            _build_payment_page_context(
                order,
                guest_access_token=guest_access_token,
                order_url=order_url,
            ),
        )

    order_detail_url = _build_order_detail_url(order, request=request, guest_access_token=guest_access_token)
    success_url = order_detail_url
    cancel_url = order_detail_url
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
            'guest_access_token': guest_access_token,
            'order_url': order_url,
            'payment_method_label': order.get_payment_method_display(),
            'is_legacy_provider_payment': True,
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
    return redirect(_build_payment_wait_url(order, guest_access_token=guest_access_token))


def payment_wait_view(request, order_id):
    """Страница «Ожидание оплаты»: инструкция и статус; при успехе webhook — редирект/обновление."""
    order, access_result = _get_payment_order_access(request, order_id)
    if order is None:
        return redirect(access_result)
    guest_access_token = access_result

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
        'guest_access_token': guest_access_token,
        'order_url': _build_order_detail_url(order, guest_access_token=guest_access_token),
    })
