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

from .forms import CheckoutForm
from .models import Order, OrderItem, PromoCode


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
    Страница оформления заказа. GET — форма, POST — создание заказа из корзины.
    Для авторизованных подставляются контакты из профиля.
    """
    cart_items = _get_cart_from_session(request)

    selected_city_id = request.session.get('selected_city_id')
    selected_city = City.objects.filter(pk=selected_city_id).first() if selected_city_id else None
    pickup_points = list(PickupPoint.objects.filter(city=selected_city).order_by('order', 'name')) if selected_city else []

    if request.method == 'GET':
        if not cart_items:
            return render(request, 'orders/checkout.html', {
                'cart_items': [],
                'cart_total': 0,
                'form': CheckoutForm(),
                'cart_empty': True,
                'selected_city': selected_city,
                'pickup_points': pickup_points,
            })
        initial = {}
        if request.user.is_authenticated:
            try:
                profile = request.user.profile
                initial['phone'] = profile.phone or ''
            except Exception:
                pass
            initial['first_name'] = request.user.first_name or ''
            initial['last_name'] = request.user.last_name or ''
            initial['email'] = request.user.email or ''
        form = CheckoutForm(initial=initial, selected_city=selected_city)
        cart_subtotal = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
        cart_discount = Decimal('0')
        cart_total_to_pay = cart_subtotal
        return render(request, 'orders/checkout.html', {
            'cart_items': cart_items,
            'cart_subtotal': cart_subtotal,
            'cart_discount': cart_discount,
            'cart_total_to_pay': cart_total_to_pay,
            'form': form,
            'cart_empty': False,
            'selected_city': selected_city,
            'pickup_points': pickup_points,
        })

    # POST
    form = CheckoutForm(request.POST, selected_city=selected_city)
    cart_items = _get_cart_from_session(request)
    if not cart_items:
        return redirect('orders:checkout')

    if not form.is_valid():
        cart_subtotal = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
        promo_code_str = (request.POST.get('promo_code') or '').strip()
        promo = PromoCode.objects.filter(code__iexact=promo_code_str, is_active=True).first() if promo_code_str else None
        cart_discount = _discount_for_promo(cart_subtotal, promo)
        cart_total_to_pay = cart_subtotal - cart_discount
        return render(request, 'orders/checkout.html', {
            'cart_items': cart_items,
            'cart_subtotal': cart_subtotal,
            'cart_discount': cart_discount,
            'cart_total_to_pay': cart_total_to_pay,
            'form': form,
            'cart_empty': False,
            'selected_city': selected_city,
            'pickup_points': pickup_points,
        })

    # Для гостя email обязателен для связи
    if not request.user.is_authenticated and not (form.cleaned_data.get('email') or '').strip():
        form.add_error('email', 'Укажите email для связи с вами.')
        cart_subtotal = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
        promo_code_str = form.cleaned_data.get('promo_code') or ''
        promo = PromoCode.objects.filter(code__iexact=promo_code_str, is_active=True).first() if promo_code_str else None
        cart_discount = _discount_for_promo(cart_subtotal, promo)
        cart_total_to_pay = cart_subtotal - cart_discount
        return render(request, 'orders/checkout.html', {
            'cart_items': cart_items,
            'cart_subtotal': cart_subtotal,
            'cart_discount': cart_discount,
            'cart_total_to_pay': cart_total_to_pay,
            'form': form,
            'cart_empty': False,
            'selected_city': selected_city,
            'pickup_points': pickup_points,
        })

    # Проверка остатков по городу или точке выдачи
    pickup_point = form.cleaned_data.get('pickup_point')
    stock_errors = []
    for item in cart_items:
        product_id = item.get('product_id')
        quantity = item.get('quantity', 1)
        if pickup_point:
            stock = _get_stock_at_pickup_point(pickup_point.pk, product_id)
        elif selected_city_id:
            stock = _get_stock_in_city(selected_city_id, product_id)
        else:
            stock = None
        if stock is not None and quantity > stock:
            product = Product.objects.filter(pk=product_id).first()
            name = product.name if product else f'Товар #{product_id}'
            stock_errors.append(f'{name}: в наличии {stock} шт., в заказе {quantity}.')
    if stock_errors:
        form.add_error(None, 'Недостаточно товара в выбранном городе/точке: ' + ' '.join(stock_errors))
        cart_subtotal = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
        promo_code_str = form.cleaned_data.get('promo_code') or ''
        promo = PromoCode.objects.filter(code__iexact=promo_code_str, is_active=True).first() if promo_code_str else None
        cart_discount = _discount_for_promo(cart_subtotal, promo)
        cart_total_to_pay = cart_subtotal - cart_discount
        return render(request, 'orders/checkout.html', {
            'cart_items': cart_items,
            'cart_subtotal': cart_subtotal,
            'cart_discount': cart_discount,
            'cart_total_to_pay': cart_total_to_pay,
            'form': form,
            'cart_empty': False,
            'selected_city': selected_city,
            'pickup_points': pickup_points,
        })

    # Создаём заказ: цены берём из БД для актуальности
    total = Decimal('0')
    order_items_data = []
    for item in cart_items:
        product_id = item.get('product_id')
        quantity = item.get('quantity', 1)
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if not product:
            continue
        price = product.price
        subtotal = price * quantity
        total += subtotal
        order_items_data.append({'product': product, 'quantity': quantity, 'price': price})

    if not order_items_data:
        return redirect('orders:checkout')

    promo_code_str = (form.cleaned_data.get('promo_code') or '').strip()
    promo = PromoCode.objects.filter(code__iexact=promo_code_str, is_active=True).first() if promo_code_str else None
    promo_discount = _discount_for_promo(total, promo)

    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        status=Order.STATUS_NEW,
        total=total,
        promo_code=promo,
        promo_discount=promo_discount,
        city=selected_city,
        pickup_point=pickup_point,
        phone=form.cleaned_data['phone'].strip(),
        email=(form.cleaned_data.get('email') or '').strip(),
        first_name=(form.cleaned_data.get('first_name') or '').strip(),
        last_name=(form.cleaned_data.get('last_name') or '').strip(),
        address=(form.cleaned_data.get('address') or '').strip(),
        delivery_type=form.cleaned_data.get('delivery_type') or Order.DELIVERY_COURIER,
        comment=(form.cleaned_data.get('comment') or '').strip(),
    )
    for data in order_items_data:
        OrderItem.objects.create(
            order=order,
            product=data['product'],
            quantity=data['quantity'],
            price=data['price'],
        )

    request.session['cart_items'] = []
    request.session.modified = True

    # Тестовый режим: заказ сразу «Оплачен», бонус партнёру и списание остатков
    if getattr(settings, 'TEST_ORDER_NO_PAYMENT', False):
        order.status = Order.STATUS_PAID
        order.save(update_fields=['status'])
        from .services import apply_partner_bonus_for_order, decrease_stock_for_order
        apply_partner_bonus_for_order(order)
        decrease_stock_for_order(order)

    if request.user.is_authenticated:
        return redirect('orders:order_detail', pk=order.pk)
    return redirect('orders:order_created', order_id=order.pk)


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
