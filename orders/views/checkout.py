from decimal import Decimal
import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from accounts.models import SavedAddress
from accounts.services import ensure_profile, get_user_phone
from catalog.cart_services import (
    clear_buy_now_checkout_items,
    enrich_cart_items,
    get_buy_now_checkout_items,
    get_cart_items,
    remove_cart_items,
)
from catalog.models import City, Product, ProductVariant
from catalog.pricing import (
    PURCHASE_MODE_ON_REQUEST,
    PURCHASE_MODE_REQUEST_ONLY,
    has_explicit_on_request_price,
    normalize_purchase_mode,
    resolve_in_stock_price,
    resolve_on_request_price,
    resolve_public_purchase_mode,
)
from catalog.views.common import _get_stock_total
from config.crm_leads import send_crm_lead_email
from config.legal_consent import build_legal_acceptance_payload
from config.legal_consent import get_legal_bundle_version
from config.utils.spam_protection import is_spam_request

from ..forms import CheckoutForm, PurchaseRequestForm
from ..models import Order, OrderItem, PromoCode, PurchaseRequest, resolve_order_item_image_url
from ..services import build_order_status_summary, issue_guest_access, send_order_event_notifications, sync_order_state_side_effects
from .utils import _discount_for_promo

CHECKOUT_APPLIED_PROMOS_SESSION_KEY = 'checkout_applied_promos'


def _float_or_none(value):
    return float(value) if value is not None else None


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
        'payment_method': Order.PAYMENT_METHOD_MANAGER_CONTACT,
        'contact_channel': Order.CONTACT_CHANNEL_CALL,
        'delivery_type': Order.DELIVERY_CDEK_PVZ,
        'recipient_is_customer': True,
    }
    if not request.user.is_authenticated:
        return initial

    profile = ensure_profile(request.user)
    initial['first_name'] = (profile.contact_name or '').strip()
    initial['last_name'] = ''
    initial['phone'] = get_user_phone(request.user, profile)
    initial['email'] = (request.user.email or '').strip()
    initial['business_phone'] = initial['phone']

    if saved_address:
        saved_first_name, saved_last_name = _split_checkout_name(saved_address.recipient_name)
        initial.update({
            'saved_address_id': saved_address.pk,
            'first_name': saved_first_name or initial.get('first_name', ''),
            'last_name': saved_last_name,
            'phone': saved_address.phone or initial.get('phone', ''),
            'email': saved_address.email or initial.get('email', ''),
            'city_text': saved_address.city,
            'address_line': saved_address.address,
            'delivery_comment': saved_address.comment,
            'recipient_name': saved_address.recipient_name or '',
            'recipient_phone': saved_address.phone or '',
            'recipient_is_customer': True,
        })

    return initial


def _use_saved_address_delivery(form, selected_saved_address):
    if selected_saved_address is None:
        return False
    office_snapshot = _extract_bound_office_snapshot(form)
    return not bool(office_snapshot)


def _split_checkout_name(value):
    parts = (value or '').strip().split(maxsplit=1)
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], parts[1]


def _normalize_checkout_source(value):
    return 'buy_now' if (value or '').strip() == 'buy_now' else 'cart'


def _build_checkout_url_for_source(items_source):
    url = reverse('orders:checkout')
    if items_source == 'buy_now':
        return f'{url}?mode=buy_now'
    return url


def _get_checkout_promo_session_map(request):
    value = request.session.get(CHECKOUT_APPLIED_PROMOS_SESSION_KEY)
    return value if isinstance(value, dict) else {}


def _set_checkout_promo_code(request, items_source, code):
    promo_map = dict(_get_checkout_promo_session_map(request))
    if code:
        promo_map[items_source] = str(code).strip()
    else:
        promo_map.pop(items_source, None)

    if promo_map:
        request.session[CHECKOUT_APPLIED_PROMOS_SESSION_KEY] = promo_map
    else:
        request.session.pop(CHECKOUT_APPLIED_PROMOS_SESSION_KEY, None)
    request.session.modified = True


def _resolve_checkout_promo(request, items_source, *, clear_invalid=False):
    promo_map = _get_checkout_promo_session_map(request)
    raw_code = str(promo_map.get(items_source) or '').strip()
    if not raw_code:
        return None, ''

    promo = PromoCode.objects.filter(code__iexact=raw_code, is_active=True).first()
    if promo is not None:
        return promo, ''

    if clear_invalid:
        _set_checkout_promo_code(request, items_source, None)
    return None, raw_code


def _sync_profile_from_checkout(user, cleaned_data):
    profile = ensure_profile(user)
    update_fields = []

    contact_name = ' '.join(
        part
        for part in [
            (cleaned_data.get('first_name') or '').strip(),
            (cleaned_data.get('last_name') or '').strip(),
        ]
        if part
    )
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


def _build_checkout_pricing_context(request, cart_items, items_source, *, promo_input_value='', promo_error=''):
    lines, unavailable_lines = _build_checkout_lines(cart_items)
    display_items = enrich_cart_items(cart_items)
    applied_promo, _ = _resolve_checkout_promo(request, items_source, clear_invalid=True)
    cart_total = sum(line['price'] * line['quantity'] for line in lines)
    promo_discount = _discount_for_promo(cart_total, applied_promo)
    grand_total = cart_total - promo_discount

    if applied_promo and not promo_error:
        promo_input_value = applied_promo.code

    return {
        'cart_items': display_items,
        'cart_total': cart_total,
        'online_total': grand_total,
        'grand_total': grand_total,
        'has_checkout_items': bool(lines),
        'checkout_unavailable_lines': unavailable_lines,
        'applied_promo': applied_promo,
        'promo_discount': promo_discount,
        'promo_error': promo_error,
        'promo_input_value': promo_input_value,
        'promo_discount_label': f'Скидка ({applied_promo.code})' if applied_promo else 'Скидка',
        'checkout_items_source': items_source,
        'checkout_promo_apply_url': reverse('orders:checkout_promo'),
    }


def _build_checkout_context(
    request,
    form,
    cart_items,
    saved_addresses,
    selected_saved_address,
    items_source,
    *,
    promo_input_value='',
    promo_error='',
):
    pricing_context = _build_checkout_pricing_context(
        request,
        cart_items,
        items_source,
        promo_input_value=promo_input_value,
        promo_error=promo_error,
    )
    checkout_mode = 'buy_now' if items_source == 'buy_now' else ''
    session_city = _get_session_selected_city(request)
    use_saved_address_delivery = _use_saved_address_delivery(form, selected_saved_address)
    show_cdek_widget = _is_cdek_widget_enabled() and not use_saved_address_delivery
    return {
        'form': form,
        'cart_empty': not cart_items,
        'request_mode': False,
        'saved_addresses': saved_addresses,
        'selected_saved_address_id': selected_saved_address.pk if selected_saved_address else None,
        'selected_saved_address': selected_saved_address,
        'is_authenticated_checkout': request.user.is_authenticated,
        'checkout_mode': checkout_mode,
        'is_buy_now_checkout': checkout_mode == 'buy_now',
        'hide_footer_products': True,
        'checkout_step': _get_checkout_step(form),
        'use_saved_address_delivery': use_saved_address_delivery,
        'show_cdek_widget': show_cdek_widget,
        'cdek_widget_enabled': show_cdek_widget,
        'form_started_at': int(time.time()),
        'cdek_widget_config': (
            _build_cdek_widget_config(
                request,
                form,
                selected_saved_address=selected_saved_address,
                session_city=session_city,
            )
            if show_cdek_widget else {}
        ),
        **pricing_context,
    }


def _get_checkout_step(form):
    if not getattr(form, 'errors', None):
        return 1

    step_fields = {
        1: {'first_name', 'phone', 'contact_handle'},
        2: {'city_text', 'address_line', 'cdek_office_snapshot_raw'},
        3: {'recipient_is_customer', 'recipient_name', 'recipient_phone'},
        4: {'agree_personal_data', 'agree_offer', '__all__'},
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
        purchase_mode = normalize_purchase_mode(item.get('purchase_mode'))
        is_on_request = purchase_mode == PURCHASE_MODE_ON_REQUEST
        in_stock_price = resolve_in_stock_price(product, variant)
        on_request_price = resolve_on_request_price(product, variant)
        item_price = Decimal(str(item.get('price', 0) or 0))
        if is_on_request:
            if not product.allow_order_on_request or on_request_price is None:
                unavailable_lines.append(item.get('name') or product.name)
                continue
            item_price = Decimal(str(on_request_price))
        elif in_stock_price is None:
            unavailable_lines.append(item.get('name') or product.name)
            continue
        elif stock_total < quantity or stock_total <= 0:
            if product.allow_order_on_request and has_explicit_on_request_price(product, variant):
                is_on_request = True
                purchase_mode = PURCHASE_MODE_ON_REQUEST
            else:
                unavailable_lines.append(item.get('name') or product.name)
                continue
        else:
            item_price = Decimal(str(item.get('price', in_stock_price) or in_stock_price))

        if is_on_request and (stock_total < quantity or stock_total <= 0):
            item_price = Decimal(str(on_request_price))

        lines.append({
            'product': product,
            'variant': variant,
            'quantity': quantity,
            'price': item_price,
            'variant_name': item.get('variant_name') or (variant.name if variant else ''),
            'is_on_request': is_on_request,
            'purchase_mode': purchase_mode,
            'bundle_id': item.get('bundle_id'),
        })

    return lines, unavailable_lines


def _get_checkout_items_source(request):
    checkout_mode = (request.GET.get('mode') or '').strip()
    if checkout_mode == 'buy_now':
        buy_now_items = get_buy_now_checkout_items(request)
        if buy_now_items:
            return buy_now_items, 'buy_now'
    return get_cart_items(request), 'cart'


def _get_session_selected_city(request):
    city_id = request.session.get('selected_city_id')
    if not city_id:
        return None
    try:
        return City.objects.filter(pk=int(city_id)).only('name').first()
    except (TypeError, ValueError):
        return None


def _is_cdek_widget_enabled():
    return bool(
        getattr(settings, 'CDEK_WIDGET_ACCOUNT', '').strip()
        and getattr(settings, 'CDEK_WIDGET_PASSWORD', '').strip()
    )


def _extract_bound_office_snapshot(form):
    if not getattr(form, 'is_bound', False):
        return {}
    raw_value = (form.data.get('cdek_office_snapshot_raw') or '').strip()
    if not raw_value:
        return {}
    try:
        import json
        parsed = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_cdek_default_location(form, *, selected_saved_address, session_city):
    office_snapshot = _extract_bound_office_snapshot(form)
    if office_snapshot.get('location'):
        return office_snapshot['location']
    if office_snapshot.get('address'):
        return office_snapshot['address']
    if office_snapshot.get('city'):
        return office_snapshot['city']
    if selected_saved_address and (selected_saved_address.city or '').strip():
        return selected_saved_address.city.strip()
    if session_city and (session_city.name or '').strip():
        return session_city.name.strip()
    # Координаты Екатеринбурга как безопасный fallback:
    # Leaflet ожидает центр карты ещё до загрузки офисов CDEK.
    return [60.597465, 56.838011]


def _resolve_cdek_default_city(form, *, selected_saved_address, session_city):
    office_snapshot = _extract_bound_office_snapshot(form)
    if office_snapshot.get('city'):
        return str(office_snapshot['city']).strip()
    if selected_saved_address and (selected_saved_address.city or '').strip():
        return selected_saved_address.city.strip()
    if session_city and (session_city.name or '').strip():
        return session_city.name.strip()
    return 'Екатеринбург'


def _build_cdek_widget_config(request, form, *, selected_saved_address, session_city):
    office_snapshot = _extract_bound_office_snapshot(form)
    return {
        'enabled': _is_cdek_widget_enabled(),
        'servicePath': request.build_absolute_uri(reverse('orders:cdek_widget_service')),
        'defaultLocation': _resolve_cdek_default_location(
            form,
            selected_saved_address=selected_saved_address,
            session_city=session_city,
        ),
        'defaultCity': _resolve_cdek_default_city(
            form,
            selected_saved_address=selected_saved_address,
            session_city=session_city,
        ),
        'defaultCityCode': office_snapshot.get('city_code') if office_snapshot.get('city_code') else None,
        'forceFilters': {
            'type': 'PVZ',
        },
        'hideFilters': {
            'have_cashless': True,
            'have_cash': True,
            'is_dressing_room': True,
            'type': True,
        },
        'hideDeliveryOptions': {
            'door': True,
            'office': False,
        },
        'canChoose': True,
        'lang': 'rus',
        'currency': 'RUB',
    }


@ratelimit(key='ip', rate='15/m', method='POST')
def checkout_view(request):
    """Оформление заказа для гостя или авторизованного пользователя."""
    cart_items, items_source = _get_checkout_items_source(request)
    saved_addresses = _get_saved_addresses(request.user) if request.user.is_authenticated else []
    selected_saved_address = _get_selected_saved_address(request, saved_addresses) if request.user.is_authenticated else None

    if request.method == 'GET':
        initial = _get_checkout_initial(request, selected_saved_address)
        form = CheckoutForm(initial=initial, user=request.user)
        return render(
            request,
            'orders/checkout.html',
            _build_checkout_context(
                request,
                form,
                cart_items,
                saved_addresses,
                selected_saved_address,
                items_source,
            ),
        )

    form = CheckoutForm(request.POST, user=request.user)
    cart_items, items_source = _get_checkout_items_source(request)
    if not cart_items:
        return redirect('orders:checkout')

    if not form.is_valid():
        return render(
            request,
            'orders/checkout.html',
            _build_checkout_context(
                request,
                form,
                cart_items,
                saved_addresses,
                selected_saved_address,
                items_source,
            ),
        )

    lines, unavailable_lines = _build_checkout_lines(cart_items)
    if not lines:
        form.add_error(None, 'В заявке не осталось доступных позиций для оформления.')
        return render(
            request,
            'orders/checkout.html',
            _build_checkout_context(
                request,
                form,
                cart_items,
                saved_addresses,
                selected_saved_address,
                items_source,
            ),
        )

    promo, invalid_promo_code = _resolve_checkout_promo(request, items_source, clear_invalid=True)
    if invalid_promo_code:
        return render(
            request,
            'orders/checkout.html',
            _build_checkout_context(
                request,
                form,
                cart_items,
                saved_addresses,
                selected_saved_address,
                items_source,
                promo_input_value=invalid_promo_code,
                promo_error='Промокод больше недействителен. Примените новый код, если он у вас есть.',
            ),
        )

    if promo is None:
        promo_code = (form.cleaned_data.get('promo_code') or '').strip()
        if promo_code:
            promo = PromoCode.objects.filter(code__iexact=promo_code, is_active=True).first()
    if is_spam_request(request):
        return render(request, 'orders/request_created.html')

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
            cdek_office_snapshot=form.cleaned_data.get('cdek_office_snapshot') or {},
            cdek_tariff_snapshot=form.cleaned_data.get('cdek_tariff_snapshot') or {},
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

        if items_source == 'buy_now':
            clear_buy_now_checkout_items(request)
        else:
            remove_cart_items(request, lines)
    _set_checkout_promo_code(request, items_source, None)
    if request.user.is_authenticated:
        _sync_profile_from_checkout(request.user, form.cleaned_data)

    order_items = list(order.items.all())
    send_crm_lead_email(
        request=request,
        form_type='Checkout',
        name=' '.join(part for part in [order.first_name, order.last_name] if part),
        phone=order.phone,
        email=order.email,
        city=order.city_text,
        product_or_service=', '.join(
            item.product_name + (f' ({item.variant_name})' if item.variant_name else '')
            for item in order_items
        ),
        comment=order.comment,
        created_at=order.created_at,
    )

    send_order_event_notifications(order, 'order_created', request=request)
    sync_order_state_side_effects(order, previous_status='', previous_payment_status='', request=request)

    params = {}
    if order.is_guest_order:
        params['access'] = order.guest_access_token
    success_url = reverse('orders:order_created', kwargs={'order_id': order.pk})
    if params:
        success_url = f'{success_url}?{urlencode(params)}'
    return redirect(success_url)


@require_POST
@ratelimit(key='ip', rate='30/m', method='POST')
def checkout_promo_view(request):
    items_source = _normalize_checkout_source(request.POST.get('checkout_mode'))
    if items_source == 'buy_now':
        cart_items = get_buy_now_checkout_items(request)
    else:
        cart_items = get_cart_items(request)
    saved_addresses = _get_saved_addresses(request.user) if request.user.is_authenticated else []
    selected_saved_address = _get_selected_saved_address(request, saved_addresses) if request.user.is_authenticated else None

    promo_action = (request.POST.get('promo_action') or 'apply').strip().lower()
    promo_input_value = (request.POST.get('promo_code_input') or '').strip()
    promo_error = ''

    if not cart_items:
        _set_checkout_promo_code(request, items_source, None)
        promo_error = 'Добавьте товары в корзину, чтобы применить промокод.'
    elif promo_action == 'remove' or not promo_input_value:
        _set_checkout_promo_code(request, items_source, None)
        promo_input_value = ''
    else:
        promo = PromoCode.objects.filter(code__iexact=promo_input_value, is_active=True).first()
        if promo is None:
            promo_error = 'Промокод не найден или недействителен.'
        else:
            _set_checkout_promo_code(request, items_source, promo.code)
            promo_input_value = promo.code

    if request.headers.get('HX-Request') != 'true':
        return redirect(_build_checkout_url_for_source(items_source))

    form = CheckoutForm(initial=_get_checkout_initial(request, selected_saved_address), user=request.user)
    context = _build_checkout_context(
        request,
        form,
        cart_items,
        saved_addresses,
        selected_saved_address,
        items_source,
        promo_input_value=promo_input_value if promo_error else '',
        promo_error=promo_error,
    )
    return render(request, 'orders/partials/checkout_promo_response.html', context)


def request_created_view(request, request_id):
    """Нейтральная legacy-страница после заявки без раскрытия данных по id."""
    return render(request, 'orders/request_created.html')


def _build_purchase_request_source_path(product, variant=None):
    url = product.get_absolute_url()
    if variant is not None:
        url = f'{url}?{urlencode({"variant": variant.pk})}'
    return url


def _render_purchase_request_product_page(request, product, *, form, variant=None, status=400):
    from catalog.views.products import ProductDetailView

    view = ProductDetailView()
    view.request = request
    view.args = ()
    view.kwargs = {'slug': product.slug}
    view.object = product
    context = view.get_context_data(object=product, purchase_request_form=form)
    if variant is not None:
        context['product_detail_data']['initialVariantId'] = variant.pk
    return render(request, view.template_name, context, status=status)


@require_POST
@ratelimit(key='ip', rate='15/m', method='POST')
def purchase_request_create_view(request):
    form = PurchaseRequestForm(request.POST)

    raw_product_id = request.POST.get('product_id')
    raw_variant_id = request.POST.get('variant_id')
    product = None
    variant = None

    try:
        product_id = int(raw_product_id)
    except (TypeError, ValueError):
        product_id = None
    if product_id:
        product = Product.objects.filter(pk=product_id, is_active=True).first()

    try:
        variant_id = int(raw_variant_id) if raw_variant_id else None
    except (TypeError, ValueError):
        variant_id = None
    if product and variant_id:
        variant = ProductVariant.objects.filter(product_id=product.pk, pk=variant_id).first()

    if product is None:
        messages.error(request, 'Не удалось определить товар для заявки. Попробуйте открыть карточку товара ещё раз.')
        return redirect('catalog:product_list')

    if raw_variant_id and variant is None:
        form.add_error(None, 'Не удалось определить выбранный вариант товара.')
        return _render_purchase_request_product_page(request, product, form=form, status=400)

    if not form.is_valid():
        return _render_purchase_request_product_page(request, product, form=form, variant=variant, status=400)

    stock_total = _get_stock_total(product.pk, variant.pk if variant else None)
    public_purchase_mode = resolve_public_purchase_mode(product, variant, stock_total=stock_total)
    if public_purchase_mode != PURCHASE_MODE_REQUEST_ONLY:
        form.add_error(None, 'Эту позицию можно оформить через корзину. Заявка нужна только для товаров без наличия и цены под заказ.')
        return _render_purchase_request_product_page(request, product, form=form, variant=variant, status=400)
    if is_spam_request(request):
        return redirect('orders:request_created', request_id=0)

    source_path = (form.cleaned_data.get('source_path') or '').strip() or _build_purchase_request_source_path(product, variant)
    item_snapshot = {
        'product_id': product.pk,
        'variant_id': variant.pk if variant else None,
        'name': product.name,
        'variant_name': variant.name if variant else '',
        'requested_mode': 'request_only',
        'stock_total': stock_total,
        'price_in_stock': _float_or_none(resolve_in_stock_price(product, variant)),
        'price_on_request': _float_or_none(resolve_on_request_price(product, variant)),
        'source_path': source_path,
    }
    purchase_request = PurchaseRequest.objects.create(
        phone=form.cleaned_data['phone'],
        telegram=form.cleaned_data.get('telegram', ''),
        items=[item_snapshot],
        total=Decimal('0'),
        **build_legal_acceptance_payload(request),
    )
    send_crm_lead_email(
        request=request,
        form_type='Карточка товара',
        phone=purchase_request.phone,
        product_or_service=(
            product.name + (f' ({variant.name})' if variant else '')
        ),
        comment=f'Telegram: {purchase_request.telegram}' if purchase_request.telegram else '',
        page_url=source_path,
        created_at=purchase_request.created_at,
    )
    return redirect('orders:request_created', request_id=purchase_request.pk)


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
    })
