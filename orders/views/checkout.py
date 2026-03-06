from decimal import Decimal

from django.shortcuts import redirect, render

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from catalog.cart_services import clear_cart, get_cart_items
from config.legal_consent import build_legal_acceptance_payload

from ..forms import PurchaseRequestForm
from ..models import Order, PurchaseRequest


@ratelimit(key='ip', rate='15/m', method='POST')
def checkout_view(request):
    """
    ВРЕМЕННО: Заявка на покупку. Клиент оставляет телефон и Telegram,
    мы связываемся для оформления заказа.
    """
    cart_items = get_cart_items(request)

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

    form = PurchaseRequestForm(request.POST)
    cart_items = get_cart_items(request)
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

    cart_total = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
    items_data = [
        {
            'product_id': item.get('product_id'),
            'variant_name': item.get('variant_name'),
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
        **build_legal_acceptance_payload(request),
    )

    clear_cart(request)

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
    guest_ids = request.session.get('guest_order_ids', [])
    if order_id not in guest_ids and order.user_id is None:
        guest_ids = list(guest_ids) + [order_id]
        request.session['guest_order_ids'] = guest_ids
        request.session.modified = True
    return render(request, 'orders/order_created.html', {'order': order})
