"""
История заказов (Фаза 3). Оформление заказа — Фаза 4. Гостевой заказ — Фаза 6.
"""
import re
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from django.conf import settings
from django.db.models import Sum

from catalog.models import City, PickupPoint, Product, ProductStock

from .forms import CheckoutForm, PurchaseRequestForm
from .models import Order, OrderItem, PromoCode, PurchaseRequest


def _get_stock_in_city(city_id, product_id):
    """Суммарный остаток товара по городу."""
    if not city_id:
        return None
    total = (
        ProductStock.objects
        .filter(product_id=product_id, pickup_point__city_id=city_id)
        .aggregate(s=Sum('quantity'))
    )
    return total['s'] or 0


def _get_stock_at_pickup_point(pickup_point_id, product_id):
    """Остаток товара в точке выдачи."""
    if not pickup_point_id:
        return None
    stock = ProductStock.objects.filter(
        product_id=product_id,
        pickup_point_id=pickup_point_id,
    ).first()
    return stock.quantity if stock else 0


def _get_stock_total(product_id):
    """Суммарный остаток товара по всей России."""
    total = (
        ProductStock.objects
        .filter(product_id=product_id)
        .aggregate(s=Sum('quantity'))
    )
    return total['s'] or 0


def _normalize_phone(phone):
    """Оставляем только цифры для сравнения."""
    if not phone:
        return ''
    return re.sub(r'\D', '', str(phone).strip())


def _get_cart_from_session(request):
    """Корзина из сессии; возвращает список dict с ключами product_id, name, price, quantity, subtotal."""
    return request.session.get('cart_items', []) or []


def _discount_for_promo(subtotal, promo):
    """Скидка по промокоду: не больше суммы заказа. promo — PromoCode или None."""
    if not promo or subtotal <= 0:
        return Decimal('0')
    return min(promo.discount_amount, subtotal)


@ratelimit(key='ip', rate='15/m', method='POST')
def checkout_view(request):
    """
    ВРЕМЕННО: Заявка на покупку. Клиент оставляет телефон и Telegram,
    мы связываемся для оформления заказа.
    """
    cart_items = _get_cart_from_session(request)

    if request.method == 'GET':
        if not cart_items:
            return render(request, 'orders/checkout.html', {
                'cart_items': [],
                'cart_total': 0,
                'form': PurchaseRequestForm(),
                'cart_empty': True,
                'request_mode': True,
            })
        initial = {}
        if request.user.is_authenticated:
            try:
                profile = request.user.profile
                initial['phone'] = profile.phone or ''
            except Exception:
                pass
        form = PurchaseRequestForm(initial=initial)
        cart_total = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
        return render(request, 'orders/checkout.html', {
            'cart_items': cart_items,
            'cart_total': cart_total,
            'form': form,
            'cart_empty': False,
            'request_mode': True,
        })

    # POST
    form = PurchaseRequestForm(request.POST)
    cart_items = _get_cart_from_session(request)
    if not cart_items:
        return redirect('orders:checkout')

    if not form.is_valid():
        cart_total = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
        return render(request, 'orders/checkout.html', {
            'cart_items': cart_items,
            'cart_total': cart_total,
            'form': form,
            'cart_empty': False,
            'request_mode': True,
        })

    # Сохраняем заявку
    cart_total = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
    items_data = [
        {
            'product_id': item.get('product_id'),
            'name': item.get('name', ''),
            'price': float(item.get('price', 0)),
            'quantity': item.get('quantity', 1),
            'subtotal': float(item.get('subtotal', 0)),
        }
        for item in cart_items
    ]
    req = PurchaseRequest.objects.create(
        phone=form.cleaned_data['phone'].strip(),
        telegram=form.cleaned_data['telegram'].strip(),
        items=items_data,
        total=cart_total,
    )

    request.session['cart_items'] = []
    request.session.modified = True

    return redirect('orders:request_created', request_id=req.pk)


def request_created_view(request, request_id):
    """Страница «Заявка отправлена»."""
    req = PurchaseRequest.objects.filter(pk=request_id).first()
    if not req:
        return redirect('catalog:product_list')
    return render(request, 'orders/request_created.html', {'request': req})


def order_created_view(request, order_id):
    """Страница «Заказ оформлен» для гостя (без входа)."""
    order = Order.objects.filter(pk=order_id).first()
    if not order:
        return redirect('catalog:product_list')
    # Сохраняем в сессии, чтобы гость мог потом открыть заказ по ссылке guest/<id>/
    guest_ids = request.session.get('guest_order_ids', [])
    if order_id not in guest_ids and order.user_id is None:
        guest_ids = list(guest_ids) + [order_id]
        request.session['guest_order_ids'] = guest_ids
        request.session.modified = True
    return render(request, 'orders/order_created.html', {'order': order})


@login_required
def order_list_view(request):
    """Страница «Мои заказы»: список заказов пользователя."""
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        orders = orders.filter(status=status_filter)
    return render(request, 'orders/order_list.html', {
        'orders': orders,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
    })


@login_required
def order_detail_view(request, pk):
    """Детали заказа (только свой)."""
    order = get_object_or_404(Order, pk=pk, user=request.user)
    return render(request, 'orders/order_detail.html', {
        'order': order,
        'is_guest_order': False,
        'test_order_no_payment': getattr(settings, 'TEST_ORDER_NO_PAYMENT', False),
    })


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

    # Требуется ввод телефона
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
