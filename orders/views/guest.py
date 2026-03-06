from django.conf import settings
from django.shortcuts import redirect, render

from ..models import Order
from .utils import _normalize_phone


def order_guest_lookup_view(request):
    """
    Страница «Проверить заказ» для гостя: форма «Номер заказа + телефон».
    После проверки редирект на страницу заказа.
    """
    if request.user.is_authenticated:
        return redirect('orders:order_list')
    if request.method == 'POST':
        order_id = request.POST.get('order_id', '').strip()
        phone = request.POST.get('phone', '').strip()
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return render(request, 'orders/order_guest_lookup.html', {
                'error': 'Введите корректный номер заказа.',
                'order_id': request.POST.get('order_id', ''),
                'phone': request.POST.get('phone', ''),
            })
        order = Order.objects.filter(pk=order_id, user__isnull=True).first()
        if not order:
            return render(request, 'orders/order_guest_lookup.html', {
                'error': 'Заказ не найден или доступен только для авторизованных пользователей.',
                'order_id': order_id,
                'phone': phone,
            })
        if _normalize_phone(phone) != _normalize_phone(order.phone):
            return render(request, 'orders/order_guest_lookup.html', {
                'error': 'Телефон не совпадает с указанным в заказе.',
                'order_id': order_id,
                'phone': phone,
            })
        guest_ids = request.session.get('guest_order_ids', [])
        if order_id not in guest_ids:
            guest_ids = list(guest_ids) + [order_id]
            request.session['guest_order_ids'] = guest_ids
            request.session.modified = True
        return redirect('orders:order_guest', order_id=order_id)
    return render(request, 'orders/order_guest_lookup.html', {})


def order_guest_view(request, order_id):
    """
    Просмотр заказа гостем: по номеру заказа, если он уже «верифицирован» в сессии
    (после ввода телефона на странице «Проверить заказ» или после оформления).
    """
    if request.user.is_authenticated:
        return redirect('orders:order_detail', pk=order_id)
    order = Order.objects.filter(pk=order_id, user__isnull=True).first()
    if not order:
        return redirect('orders:order_guest_lookup')
    guest_ids = request.session.get('guest_order_ids', [])
    if order_id in guest_ids:
        return render(request, 'orders/order_detail.html', {
            'order': order,
            'is_guest_order': True,
            'test_order_no_payment': getattr(settings, 'TEST_ORDER_NO_PAYMENT', False),
        })

    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        if _normalize_phone(phone) == _normalize_phone(order.phone):
            guest_ids = list(guest_ids) + [order_id]
            request.session['guest_order_ids'] = guest_ids
            request.session.modified = True
            return redirect('orders:order_guest', order_id=order_id)
        return render(request, 'orders/order_guest_verify.html', {
            'order_id': order_id,
            'error': 'Телефон не совпадает с указанным в заказе.',
        })
    return render(request, 'orders/order_guest_verify.html', {'order_id': order_id})
