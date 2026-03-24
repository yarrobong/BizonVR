from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from accounts.models import SavedAddress
from accounts.services import ensure_profile, get_user_phone
from catalog.cart_services import clear_cart, get_cart_items
from catalog.models import Product, ProductVariant
from catalog.views.common import _get_stock_total
from config.legal_consent import build_legal_acceptance_payload
from config.legal_consent import get_legal_bundle_version

from ..forms import CheckoutForm
from ..models import Order, OrderItem, PromoCode, resolve_order_item_image_url
from ..services import build_order_status_summary, issue_guest_access, send_order_event_notifications, sync_order_state_side_effects
from .utils import _discount_for_promo


def _split_contact_name(full_name):
    parts = [part for part in (full_name or '').strip().split() if part]
    if not parts:
        return '', ''
    return parts[0], ' '.join(parts[1:])


def _get_saved_addresses(user):
    return list(
        SavedAddress.objects.filter(user=user)
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
    initial = {
        'country': 'Россия',
        'payment_method': Order.PAYMENT_METHOD_SBP,
        'contact_channel': Order.CONTACT_CHANNEL_CALL,
        'delivery_type': Order.DELIVERY_CDEK_PVZ,
        'recipient_is_customer': True,
    }
    if not request.user.is_authenticated:
        return initial

    profile = ensure_profile(request.user)
    first_name, last_name = _split_contact_name(profile.contact_name)
    initial['first_name'] = first_name
    initial['last_name'] = last_name
    initial['phone'] = get_user_phone(request.user, profile)
    initial['email'] = (request.user.email or '').strip()
    initial['business_phone'] = initial['phone']

    if saved_address:
        saved_first_name, saved_last_name = _split_contact_name(saved_address.recipient_name)
        initial.update({
            'first_name': saved_first_name or initial.get('first_name', ''),
            'last_name': saved_last_name or initial.get('last_name', ''),
            'phone': saved_address.phone or initial.get('phone', ''),
            'email': saved_address.email or initial.get('email', ''),
            'address_line': saved_address.address,
            'city_text': saved_address.city,
            'comment': saved_address.comment,
            'recipient_name': saved_address.recipient_name or '',
            'recipient_phone': saved_address.phone or '',
            'recipient_is_customer': True,
        })

    return initial


def _sync_profile_from_checkout(user, cleaned_data):
    profile = ensure_profile(user)
    update_fields = []

    contact_name = ' '.join(
        part for part in [
            (cleaned_data.get('first_name') or '').strip(),
            (cleaned_data.get('last_name') or '').strip(),
        ]
        if part
    ).strip()
    existing_name = ' '.join((profile.contact_name or '').split())
    if contact_name and (
        not existing_name
        or len(contact_name.split()) >= len(existing_name.split())
    ) and contact_name != existing_name:
        profile.contact_name = contact_name
        update_fields.append('contact_name')

    if not profile.privacy_agreed_at:
        profile.privacy_agreed_at = timezone.now()
        profile.privacy_policy_version = get_legal_bundle_version()
        update_fields.extend(['privacy_agreed_at', 'privacy_policy_version'])

    if update_fields:
        profile.save(update_fields=update_fields)

    email = (cleaned_data.get('email') or '').strip().lower()
    if email and user.email != email:
        user.email = email
        user.save(update_fields=['email'])


def _build_checkout_context(request, form, cart_items, saved_addresses, selected_saved_address):
    lines, _ = _build_checkout_lines(cart_items)
    cart_total = sum(Decimal(str(item.get('subtotal', 0))) for item in cart_items)
    return {
        'cart_items': cart_items,
        'cart_total': cart_total,
        'online_total': cart_total,
        'grand_total': cart_total,
        'form': form,
        'cart_empty': not cart_items,
        'request_mode': False,
        'saved_addresses': saved_addresses,
        'selected_saved_address_id': selected_saved_address.pk if selected_saved_address else None,
        'selected_saved_address': selected_saved_address,
        'is_authenticated_checkout': request.user.is_authenticated,
        'checkout_step': _get_checkout_step(form),
    }


def _get_checkout_step(form):
    if not getattr(form, 'errors', None):
        return 1

    step_fields = {
        1: {'first_name', 'last_name', 'phone', 'email', 'contact_channel', 'contact_handle'},
        2: {'delivery_type', 'city_text', 'address_line', 'delivery_comment'},
        3: {'recipient_is_customer', 'recipient_name', 'recipient_phone'},
        4: {'payment_method'},
        5: {'promo_code', 'comment', 'agree_personal_data', 'agree_offer', '__all__'},
    }
    errored_fields = set(form.errors.keys())
    for step, fields in step_fields.items():
        if errored_fields & fields:
            return step
    return 1


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
    """Оформление заказа для гостя или авторизованного пользователя."""
    cart_items = get_cart_items(request)
    saved_addresses = _get_saved_addresses(request.user) if request.user.is_authenticated else []
    selected_saved_address = _get_selected_saved_address(request, saved_addresses) if request.user.is_authenticated else None

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
    payment_status = (
        Order.PAYMENT_STATUS_PAID
        if getattr(settings, 'TEST_ORDER_NO_PAYMENT', False)
        else Order.PAYMENT_STATUS_UNPAID
    )

    with transaction.atomic():
        order = Order.objects.create(
            user=request.user if request.user.is_authenticated else None,
            status=Order.STATUS_NEW,
            total=subtotal,
            promo_code=promo,
            promo_discount=promo_discount,
            payment_method=form.cleaned_data['payment_method'],
            contact_channel=form.cleaned_data['contact_channel'],
            contact_handle=(form.cleaned_data.get('contact_handle') or '').strip(),
            payment_status=payment_status,
            delivery_type=form.cleaned_data['delivery_type'],
            city=None,
            pickup_point=None,
            phone=form.cleaned_data['phone'].strip(),
            email=form.cleaned_data.get('email', '').strip(),
            first_name=form.cleaned_data['first_name'].strip(),
            last_name=form.cleaned_data.get('last_name', '').strip(),
            recipient_name=(form.cleaned_data.get('recipient_name') or '').strip(),
            recipient_phone=(form.cleaned_data.get('recipient_phone') or '').strip(),
            recipient_is_customer=bool(form.cleaned_data.get('recipient_is_customer')),
            country=(form.cleaned_data.get('country') or '').strip(),
            city_text=(form.cleaned_data.get('city_text') or '').strip(),
            postal_code=(form.cleaned_data.get('postal_code') or '').strip(),
            address_line=(form.cleaned_data.get('address_line') or '').strip(),
            address=(form.cleaned_data.get('address_line') or '').strip(),
            delivery_comment=(form.cleaned_data.get('delivery_comment') or '').strip(),
            business_company_name=(form.cleaned_data.get('business_company_name') or '').strip(),
            business_inn=(form.cleaned_data.get('business_inn') or '').strip(),
            business_kpp=(form.cleaned_data.get('business_kpp') or '').strip(),
            business_checking_account=(form.cleaned_data.get('business_checking_account') or '').strip(),
            business_bank_name=(form.cleaned_data.get('business_bank_name') or '').strip(),
            business_bik=(form.cleaned_data.get('business_bik') or '').strip(),
            business_correspondent_account=(form.cleaned_data.get('business_correspondent_account') or '').strip(),
            business_phone=(form.cleaned_data.get('business_phone') or '').strip(),
            business_telegram=(form.cleaned_data.get('business_telegram') or '').strip(),
            business_whatsapp=(form.cleaned_data.get('business_whatsapp') or '').strip(),
            delivery_cost=Decimal('0'),
            comment=(form.cleaned_data.get('comment') or '').strip(),
            **build_legal_acceptance_payload(request),
        )
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                product=line['product'],
                product_name=line['product'].name,
                product_image_url=resolve_order_item_image_url(product=line['product'], variant=line['variant']),
                variant=line['variant'],
                quantity=line['quantity'],
                price=line['price'],
                is_on_request=line['is_on_request'],
                variant_name=line['variant_name'],
            )
            for line in lines
        ])
        from manager_portal.services import ensure_website_order_workflow

        ensure_website_order_workflow(order)
        if order.is_guest_order:
            issue_guest_access(order)

    clear_cart(request)
    if request.user.is_authenticated:
        _sync_profile_from_checkout(request.user, form.cleaned_data)

    send_order_event_notifications(order, 'order_created', request=request)
    sync_order_state_side_effects(order, previous_status='', previous_payment_status='', request=request)

    params = {}
    if order.is_guest_order:
        params['access'] = order.guest_access_token
    success_url = reverse('orders:order_created', kwargs={'order_id': order.pk})
    if params:
        success_url = f'{success_url}?{urlencode(params)}'
    return redirect(success_url)


def request_created_view(request, request_id):
    """Нейтральная legacy-страница после заявки без раскрытия данных по id."""
    return render(request, 'orders/request_created.html')


def order_created_view(request, order_id):
    """Страница успешного создания заказа; гостю нужна защищённая ссылка."""
    order = None
    access_token = (request.GET.get('access') or '').strip()

    if request.user.is_authenticated:
        order = Order.objects.filter(pk=order_id, user=request.user).prefetch_related('items__product').first()
    elif access_token:
        candidate = Order.objects.filter(pk=order_id, user__isnull=True).prefetch_related('items__product').first()
        if candidate and candidate.is_guest_access_valid(access_token):
            order = candidate

    return render(request, 'orders/order_created.html', {
        'order': order,
        'order_summary': build_order_status_summary(order) if order else None,
        'access_token': access_token if order and order.is_guest_order else '',
        'test_order_no_payment': getattr(settings, 'TEST_ORDER_NO_PAYMENT', False),
    })
