from decimal import Decimal

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.shortcuts import redirect, render

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from accounts.models import CommercialProposalContact, Profile, SavedAddress
from catalog.cart_services import clear_cart, get_cart_items
from catalog.models import Product, ProductVariant
from catalog.views.common import _get_stock_total
from config.legal_consent import build_legal_acceptance_payload

from ..forms import CheckoutForm
from ..models import Order, OrderItem, PromoCode
from ..services import apply_partner_bonus_for_order, decrease_stock_for_order
from .utils import _discount_for_promo


def _split_contact_name(full_name):
    parts = [part for part in (full_name or '').strip().split() if part]
    if not parts:
        return '', ''
    return parts[0], ' '.join(parts[1:])


def _get_saved_addresses(user):
    return list(
        SavedAddress.objects.filter(user=user)
        .select_related('pickup_point__city')
        .order_by('-is_default', '-updated_at', '-id')
    )


def _get_selected_saved_address(request, saved_addresses):
    if not saved_addresses:
        return None
    requested_id = (request.GET.get('saved_address') or '').strip()
    if requested_id.lower() == 'none':
        return None
    try:
        requested_id = int(requested_id)
    except (TypeError, ValueError):
        requested_id = None
    if requested_id is not None:
        for address in saved_addresses:
            if address.pk == requested_id:
                return address
    return next((address for address in saved_addresses if address.is_default), None)


def _get_checkout_initial(request, saved_address):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={'phone': request.user.username},
    )
    initial = {}
    first_name, last_name = _split_contact_name(profile.contact_name)
    initial['first_name'] = first_name
    initial['last_name'] = last_name
    initial['phone'] = profile.phone or request.user.username

    try:
        cp_contact = request.user.cp_contact
    except CommercialProposalContact.DoesNotExist:
        cp_contact = None
    if cp_contact and cp_contact.email:
        initial['email'] = cp_contact.email

    if saved_address:
        address_first_name, address_last_name = _split_contact_name(saved_address.recipient_name)
        initial.update({
            'first_name': address_first_name or initial.get('first_name', ''),
            'last_name': address_last_name or initial.get('last_name', ''),
            'phone': saved_address.phone or initial.get('phone', ''),
            'email': saved_address.email or initial.get('email', ''),
            'delivery_type': saved_address.delivery_type,
            'pickup_point': saved_address.pickup_point_id,
            'address': saved_address.address,
            'comment': saved_address.comment,
        })

    return initial


def _build_checkout_context(request, form, cart_items, saved_addresses, selected_saved_address):
    return {
        'cart_items': cart_items,
        'cart_total': sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items),
        'form': form,
        'cart_empty': not cart_items,
        'request_mode': False,
        'pickup_points': list(form.fields['pickup_point'].queryset),
        'saved_addresses': saved_addresses,
        'selected_saved_address_id': selected_saved_address.pk if selected_saved_address else None,
        'selected_saved_address': selected_saved_address,
    }


def _get_cart_catalog_objects(cart_items):
    product_ids = [item.get('product_id') for item in cart_items if item.get('product_id')]
    variant_ids = [item.get('variant_id') for item in cart_items if item.get('variant_id')]
    products = Product.objects.filter(pk__in=product_ids, is_active=True).in_bulk()
    variants = ProductVariant.objects.filter(pk__in=variant_ids, product_id__in=product_ids).select_related('product').in_bulk()
    return products, variants


def _build_checkout_lines(cart_items):
    products, variants = _get_cart_catalog_objects(cart_items)
    lines = []
    unavailable_lines = []

    for item in cart_items:
        product_id = item.get('product_id')
        variant_id = item.get('variant_id')
        quantity = int(item.get('quantity') or 0)
        product = products.get(product_id)
        variant = variants.get(variant_id) if variant_id else None

        if not product or quantity <= 0:
            continue
        if variant_id and not variant:
            unavailable_lines.append(item.get('name') or product.name)
            continue

        stock_total = _get_stock_total(product_id, variant_id)
        is_on_request = stock_total < quantity
        if is_on_request and not product.allow_order_on_request:
            unavailable_lines.append(item.get('name') or product.name)
            continue

        lines.append({
            'product': product,
            'variant': variant,
            'quantity': quantity,
            'price': Decimal(str(item.get('price', 0))),
            'variant_name': item.get('variant_name') or (variant.name if variant else ''),
            'is_on_request': is_on_request,
        })

    return lines, unavailable_lines


@ratelimit(key='ip', rate='15/m', method='POST')
def checkout_view(request):
    """Оформление заказа для авторизованного пользователя."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    cart_items = get_cart_items(request)
    saved_addresses = _get_saved_addresses(request.user)
    selected_saved_address = _get_selected_saved_address(request, saved_addresses)

    if request.method == 'GET':
        initial = _get_checkout_initial(request, selected_saved_address)
        form = CheckoutForm(initial=initial, user=request.user)
        return render(
            request,
            'orders/checkout.html',
            _build_checkout_context(request, form, cart_items, saved_addresses, selected_saved_address),
        )

    form = CheckoutForm(request.POST, user=request.user)
    cart_items = get_cart_items(request)
    if not cart_items:
        return redirect('orders:checkout')

    if not form.is_valid():
        return render(
            request,
            'orders/checkout.html',
            _build_checkout_context(request, form, cart_items, saved_addresses, selected_saved_address),
        )

    lines, unavailable_lines = _build_checkout_lines(cart_items)
    if unavailable_lines:
        form.add_error(
            None,
            'Недостаточно товара для оформления: ' + ', '.join(unavailable_lines) + '.',
        )
        return render(
            request,
            'orders/checkout.html',
            _build_checkout_context(request, form, cart_items, saved_addresses, selected_saved_address),
        )
    if not lines:
        return redirect('orders:checkout')

    promo = None
    promo_code = form.cleaned_data.get('promo_code') or ''
    if promo_code:
        promo = PromoCode.objects.filter(code__iexact=promo_code, is_active=True).first()

    subtotal = sum(line['price'] * line['quantity'] for line in lines)
    promo_discount = _discount_for_promo(subtotal, promo)
    pickup_point = form.cleaned_data.get('pickup_point')
    status = Order.STATUS_PAID if getattr(settings, 'TEST_ORDER_NO_PAYMENT', False) else Order.STATUS_NEW

    with transaction.atomic():
        order = Order.objects.create(
            user=request.user,
            status=status,
            total=subtotal,
            promo_code=promo,
            promo_discount=promo_discount,
            delivery_type=form.cleaned_data['delivery_type'],
            city=pickup_point.city if pickup_point and form.cleaned_data['delivery_type'] == Order.DELIVERY_PICKUP else None,
            pickup_point=pickup_point if form.cleaned_data['delivery_type'] == Order.DELIVERY_PICKUP else None,
            phone=form.cleaned_data['phone'].strip(),
            email=form.cleaned_data.get('email', '').strip(),
            first_name=form.cleaned_data['first_name'].strip(),
            last_name=form.cleaned_data.get('last_name', '').strip(),
            address=(form.cleaned_data.get('address') or '').strip(),
            comment=(form.cleaned_data.get('comment') or '').strip(),
            **build_legal_acceptance_payload(request),
        )
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                product=line['product'],
                quantity=line['quantity'],
                price=line['price'],
                is_on_request=line['is_on_request'],
                variant_name=line['variant_name'],
            )
            for line in lines
        ])

    clear_cart(request)

    if status == Order.STATUS_PAID:
        apply_partner_bonus_for_order(order)
        decrease_stock_for_order(order)

    return redirect('orders:order_detail', pk=order.pk)


def request_created_view(request, request_id):
    """Нейтральная legacy-страница после заявки без раскрытия данных по id."""
    return render(request, 'orders/request_created.html')


def order_created_view(request, order_id):
    """Нейтральная legacy-страница без доступа к заказу по голому id."""
    return render(request, 'orders/order_created.html')
