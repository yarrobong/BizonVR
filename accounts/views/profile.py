from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from catalog.cart_services import get_compare_product_ids
from catalog.models import Favorite, Product
from orders.models import Order

from ..forms import (
    EmailVerificationConfirmForm,
    EmailVerificationRequestForm,
    PhoneChangeConfirmForm,
    PhoneChangeRequestForm,
    ProfileUpdateForm,
    SavedAddressForm,
)
from ..models import BalanceTransaction, CommercialProposalContact, Profile, SavedAddress
from ..security import check_send_code_rate_limits, check_verify_code_rate_limits, get_client_ip, mark_send_code_success
from ..services import (
    confirm_email_verification,
    create_and_send_code,
    create_and_send_email_code,
    get_pending_email_verification,
    normalize_phone,
    verify_sms_code,
)

User = get_user_model()
PHONE_CHANGE_SESSION_KEY = 'accounts:profile:phone_change_pending'
PROFILE_PENDING_ALERTS_SESSION_KEY = 'accounts:profile:pending_alerts'


def _format_phone(phone: str) -> str:
    digits = normalize_phone(phone or '')
    if len(digits) == 10:
        return f'+7 ({digits[:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}'
    return phone or ''


def _consume_pending_alerts(request):
    pending_alerts = request.session.pop(PROFILE_PENDING_ALERTS_SESSION_KEY, [])
    if pending_alerts:
        request.session.modified = True
    return [
        alert for alert in pending_alerts
        if isinstance(alert, dict) and alert.get('level') and alert.get('text')
    ]


def _status_description(status, count):
    if count:
        descriptions = {
            Order.STATUS_NEW: 'Требуют подтверждения или оплаты.',
            Order.STATUS_PAID: 'Оплата подтверждена, заказ готовится к отгрузке.',
            Order.STATUS_SHIPPING: 'Заказы в пути или ожидают выдачи.',
            Order.STATUS_DONE: 'Выполненные заказы и история покупок.',
            Order.STATUS_CANCELLED: 'Отменённые заказы и незавершённые покупки.',
        }
        return descriptions.get(status, 'Быстрый переход к заказам в этом статусе.')

    empty_descriptions = {
        Order.STATUS_NEW: 'Новых заказов пока нет.',
        Order.STATUS_PAID: 'Оплаченные заказы появятся здесь.',
        Order.STATUS_SHIPPING: 'Когда отправим заказ, он появится здесь.',
        Order.STATUS_DONE: 'История выполненных заказов появится здесь.',
        Order.STATUS_CANCELLED: 'Отменённых заказов пока нет.',
    }
    return empty_descriptions.get(status, 'Когда появятся заказы, здесь будет быстрый переход.')


def _build_status_stats(user):
    rows = (
        Order.objects
        .filter(user=user)
        .values('status')
        .annotate(total=Count('id'))
    )
    counters = {row['status']: row['total'] for row in rows}
    stats = []
    for status, label in Order.STATUS_CHOICES:
        count = counters.get(status, 0)
        stats.append({
            'status': status,
            'label': label,
            'count': count,
            'url': f"{reverse('orders:order_list')}?status={status}",
            'description': _status_description(status, count),
        })
    return stats


def _summarize_order(order):
    items = list(order.items.all())
    first_item = items[0] if items else None
    first_item_name = first_item.product.name if first_item else 'Состав заказа уточняется'
    if first_item and first_item.variant_name:
        first_item_name = f'{first_item_name}, {first_item.variant_name}'

    item_count = sum(item.quantity for item in items)
    if item_count > 1:
        items_caption = f'Ещё позиций: {item_count - 1}'
    elif item_count == 1:
        items_caption = '1 позиция в заказе'
    else:
        items_caption = 'Состав заказа пока не указан'

    delivery_label = order.get_delivery_type_display() if order.delivery_type else 'Способ доставки уточняется'
    destination = order.address or (order.pickup_point.address if order.pickup_point_id and order.pickup_point else '')

    return {
        'instance': order,
        'first_item_name': first_item_name,
        'items_caption': items_caption,
        'delivery_label': delivery_label,
        'destination': destination,
        'recipient_name': ' '.join(part for part in [order.last_name, order.first_name] if part).strip(),
    }


def _saved_address_initial(address=None):
    if not address:
        return {}
    return {
        'label': address.label,
        'recipient_name': address.recipient_name,
        'phone': _format_phone(address.phone),
        'email': address.email,
        'delivery_type': address.delivery_type,
        'pickup_point': address.pickup_point_id,
        'address': address.address,
        'comment': address.comment,
        'is_default': address.is_default,
    }


def _ensure_default_saved_address(user, exclude_pk=None):
    addresses = list(
        SavedAddress.objects.filter(user=user)
        .exclude(pk=exclude_pk)
        .order_by('-is_default', '-updated_at', '-id')
    )
    if not addresses:
        return None
    current_default = next((address for address in addresses if address.is_default), None)
    if current_default:
        return current_default
    default_address = addresses[0]
    SavedAddress.objects.filter(user=user, pk=default_address.pk).update(is_default=True)
    default_address.is_default = True
    return default_address


def _set_default_saved_address(user, address):
    SavedAddress.objects.filter(user=user, is_default=True).exclude(pk=address.pk).update(is_default=False)
    if not address.is_default:
        SavedAddress.objects.filter(pk=address.pk, user=user).update(is_default=True)
        address.is_default = True
    return address


def _get_compare_products_preview(request):
    compare_ids = get_compare_product_ids(request)
    if not compare_ids:
        return [], 0
    products_map = (
        Product.objects.filter(pk__in=compare_ids, is_active=True)
        .select_related('category')
        .prefetch_related('characteristics', 'images', 'tags', 'variants')
        .in_bulk()
    )
    products = [products_map[pid] for pid in compare_ids if pid in products_map]
    return products[:4], len(compare_ids)


def _build_profile_completion(profile, saved_addresses, orders_total, favorites_count, pending_phone_change):
    steps = [
        {
            'label': 'Получатель указан',
            'done': bool(profile.contact_name),
            'hint': 'Имя получателя будет подставляться в заказы и доставку.',
        },
        {
            'label': 'Email подтверждён',
            'done': bool(profile.email_verified_at),
            'hint': 'Подтверждённый email нужен для писем по аккаунту и документам.',
        },
        {
            'label': 'Адрес сохранён',
            'done': bool(saved_addresses),
            'hint': 'Сохранённый адрес ускоряет checkout и повторные покупки.',
        },
        {
            'label': 'Есть история заказов',
            'done': orders_total > 0,
            'hint': 'Здесь появятся детали заказов, документы и статусы.',
        },
        {
            'label': 'Собран shortlist',
            'done': favorites_count > 0,
            'hint': 'Избранное помогает быстро вернуться к выбранным товарам.',
        },
    ]
    completed = sum(1 for step in steps if step['done'])
    percent = int((completed / len(steps)) * 100) if steps else 0

    if pending_phone_change:
        summary = 'Осталось подтвердить новый номер по SMS.'
    elif not profile.email_verified_at:
        summary = 'Подтвердите email, чтобы получать письма по аккаунту и заказам на проверенный адрес.'
    elif percent == 100:
        summary = 'Кабинет заполнен и готов к повторным заказам.'
    elif percent >= 50:
        summary = 'Основные данные уже на месте, можно закрыть оставшиеся шаги.'
    else:
        summary = 'Заполните ключевые данные, чтобы сократить путь до оформления заказа.'

    return {
        'steps': steps,
        'completed': completed,
        'total': len(steps),
        'percent': percent,
        'summary': summary,
    }


def _build_priority_actions(profile, saved_addresses, active_orders_count, favorites_count, pending_phone_change):
    actions = []

    if not profile.contact_name:
        actions.append({
            'title': 'Добавить данные получателя',
            'description': 'Укажите ФИО, чтобы не вводить его заново при каждом заказе.',
            'href': '#profile',
            'variant': 'accent',
            'icon': 'user',
        })
    if not saved_addresses:
        actions.append({
            'title': 'Сохранить адрес доставки',
            'description': 'Сделайте один готовый сценарий доставки для checkout в один клик.',
            'href': '#delivery',
            'variant': 'default',
            'icon': 'map-pin',
        })
    if pending_phone_change:
        actions.append({
            'title': 'Подтвердить новый номер',
            'description': 'Смена логина завершится после ввода SMS-кода.',
            'href': '#security',
            'variant': 'default',
            'icon': 'shield-check',
        })
    if not profile.email_verified_at:
        actions.append({
            'title': 'Подтвердить email',
            'description': 'Проверенный email пригодится для уведомлений и документов.',
            'href': '#security',
            'variant': 'default',
            'icon': 'mail-check',
        })
    if active_orders_count:
        actions.append({
            'title': 'Проверить активные заказы',
            'description': 'Откройте новые, оплаченные и отгружаемые заказы без лишнего поиска.',
            'href': reverse('orders:order_list'),
            'variant': 'default',
            'icon': 'package',
        })
    if favorites_count == 0:
        actions.append({
            'title': 'Собрать избранное',
            'description': 'Сохраните интересующие модели, чтобы вернуться к ним позже.',
            'href': reverse('catalog:product_list'),
            'variant': 'default',
            'icon': 'heart',
        })

    if not actions:
        actions = [
            {
                'title': 'Открыть историю заказов',
                'description': 'Быстрый переход ко всем заказам и деталям доставки.',
                'href': reverse('orders:order_list'),
                'variant': 'accent',
                'icon': 'history',
            },
            {
                'title': 'Проверить избранное',
                'description': 'Вернитесь к сохранённым товарам и сравнению характеристик.',
                'href': reverse('catalog:favorites'),
                'variant': 'default',
                'icon': 'sparkles',
            },
            {
                'title': 'Связаться с менеджером',
                'description': 'Если нужна помощь по заказу, оплате или подбору VR-решения.',
                'href': reverse('contacts'),
                'variant': 'default',
                'icon': 'message-circle',
            },
        ]

    return actions[:3]


def _build_customer_segment(orders_total, active_orders_count):
    if orders_total >= 5:
        return (
            'Постоянный клиент',
            'Есть устойчивая история заказов, сохранённые сценарии и быстрый повторный путь к покупке.',
        )
    if active_orders_count:
        return (
            'Клиент в процессе сделки',
            'Сейчас важнее всего отслеживать статусы заказов и подготовить данные для следующих покупок.',
        )
    if orders_total > 0:
        return (
            'Возвращается за покупками',
            'Уже есть история заказов, поэтому кабинет можно использовать как рабочую панель повторных заказов.',
        )
    return (
        'Новый клиент',
        'Сначала стоит заполнить профиль и сохранить адрес, чтобы сократить путь до первого оформления заказа.',
    )


def _build_profile_context(
    request,
    profile,
    alerts=None,
    profile_form=None,
    email_request_form=None,
    email_confirm_form=None,
    phone_request_form=None,
    phone_confirm_form=None,
    address_form=None,
    editing_address=None,
):
    try:
        cp_contact = request.user.cp_contact
    except CommercialProposalContact.DoesNotExist:
        cp_contact = None
    pending_phone = request.session.get(PHONE_CHANGE_SESSION_KEY, '')
    pending_email_verification = get_pending_email_verification(request.user)
    confirmed_email = (request.user.email or '').strip()

    if profile_form is None:
        profile_form = ProfileUpdateForm(initial={'contact_name': profile.contact_name or ''})
    if email_request_form is None:
        email_request_form = EmailVerificationRequestForm(
            current_user=request.user,
            email_locked=bool(profile.email_verified_at),
            initial={'email': confirmed_email or (pending_email_verification.email if pending_email_verification else '')},
        )
    if email_confirm_form is None:
        email_confirm_form = EmailVerificationConfirmForm(
            current_user=request.user,
            email_locked=bool(profile.email_verified_at),
            initial={'email': pending_email_verification.email if pending_email_verification else confirmed_email},
        )
    if phone_request_form is None:
        phone_request_form = PhoneChangeRequestForm(current_user=request.user, initial={
            'new_phone': pending_phone or '',
        })
    if phone_confirm_form is None:
        phone_confirm_form = PhoneChangeConfirmForm(current_user=request.user, initial={
            'new_phone': pending_phone or '',
        })
    if address_form is None:
        address_form = SavedAddressForm(initial=_saved_address_initial(editing_address))

    last_orders = list(
        Order.objects
        .filter(user=request.user)
        .prefetch_related('items__product')
        .select_related('city', 'pickup_point')
        .order_by('-created_at')[:5]
    )
    saved_addresses = list(
        SavedAddress.objects.filter(user=request.user)
        .select_related('pickup_point__city')
        .order_by('-is_default', '-updated_at', '-id')
    )
    default_saved_address = next((address for address in saved_addresses if address.is_default), None)
    compare_products_preview, compare_count = _get_compare_products_preview(request)
    order_stats = _build_status_stats(request.user)
    active_orders_count = sum(
        item['count'] for item in order_stats
        if item['status'] not in {Order.STATUS_DONE, Order.STATUS_CANCELLED}
    )
    favorites_count = Favorite.objects.filter(user=request.user).count()
    saved_addresses_count = len(saved_addresses)
    last_activity_at = max(
        [
            dt for dt in [
                request.user.last_login,
                last_orders[0].updated_at if last_orders else None,
                cp_contact.updated_at if cp_contact else None,
                saved_addresses[0].updated_at if saved_addresses else None,
            ] if dt is not None
        ],
        default=None,
    )
    recent_orders = [_summarize_order(order) for order in last_orders]
    primary_contact_phone = (cp_contact.phone if cp_contact and cp_contact.phone else profile.phone or request.user.username)
    primary_contact_email = cp_contact.email if cp_contact and cp_contact.email else confirmed_email
    profile_completion = _build_profile_completion(
        profile=profile,
        saved_addresses=saved_addresses,
        orders_total=sum(item['count'] for item in order_stats),
        favorites_count=favorites_count,
        pending_phone_change=pending_phone,
    )
    priority_actions = _build_priority_actions(
        profile=profile,
        saved_addresses=saved_addresses,
        active_orders_count=active_orders_count,
        favorites_count=favorites_count,
        pending_phone_change=pending_phone,
    )
    customer_segment, customer_segment_description = _build_customer_segment(
        orders_total=sum(item['count'] for item in order_stats),
        active_orders_count=active_orders_count,
    )

    return {
        'user': request.user,
        'profile': profile,
        'phone_display': _format_phone(profile.phone or request.user.username),
        'primary_contact_phone': _format_phone(primary_contact_phone),
        'primary_contact_email': primary_contact_email,
        'alerts': alerts or [],
        'profile_form': profile_form,
        'email_request_form': email_request_form,
        'email_confirm_form': email_confirm_form,
        'pending_email_verification': pending_email_verification,
        'confirmed_email': confirmed_email,
        'phone_request_form': phone_request_form,
        'phone_confirm_form': phone_confirm_form,
        'pending_phone_change': pending_phone,
        'address_form': address_form,
        'editing_address': editing_address,
        'saved_addresses': saved_addresses,
        'default_saved_address': default_saved_address,
        'compare_products_preview': compare_products_preview,
        'compare_count': compare_count,
        'order_stats': order_stats,
        'orders_total': sum(item['count'] for item in order_stats),
        'active_orders_count': active_orders_count,
        'favorites_count': favorites_count,
        'saved_addresses_count': saved_addresses_count,
        'last_activity_at': last_activity_at,
        'account_status': 'Аккаунт активен' if request.user.is_active else 'Аккаунт ограничен',
        'last_orders': last_orders,
        'recent_orders': recent_orders,
        'profile_completion': profile_completion,
        'priority_actions': priority_actions,
        'customer_segment': customer_segment,
        'customer_segment_description': customer_segment_description,
    }


@require_http_methods(['GET', 'POST'])
def profile_view(request):
    """Личный кабинет: данные профиля, заказы, смена номера, адресная книга."""
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    Profile.objects.get_or_create(user=request.user, defaults={'phone': request.user.username})
    profile = request.user.profile
    alerts = _consume_pending_alerts(request)

    profile_form = None
    email_request_form = None
    email_confirm_form = None
    phone_request_form = None
    phone_confirm_form = None
    address_form = None
    editing_address = None

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'save_profile':
            profile_form = ProfileUpdateForm(request.POST)
            if profile_form.is_valid():
                profile.contact_name = profile_form.cleaned_data['contact_name']
                profile.save(update_fields=['contact_name'])
                alerts.append({'level': 'success', 'text': 'Данные профиля сохранены.'})
            else:
                alerts.append({'level': 'error', 'text': 'Не удалось сохранить профиль. Проверьте поля формы.'})

        elif action == 'save_address':
            address_id = (request.POST.get('address_id') or '').strip()
            if address_id:
                editing_address = SavedAddress.objects.filter(pk=address_id, user=request.user).select_related('pickup_point__city').first()
                if editing_address is None:
                    address_form = SavedAddressForm(request.POST)
                    alerts.append({'level': 'error', 'text': 'Адрес не найден.'})
                    context = _build_profile_context(
                        request=request,
                        profile=profile,
                        alerts=alerts,
                        profile_form=profile_form,
                        email_request_form=email_request_form,
                        email_confirm_form=email_confirm_form,
                        phone_request_form=phone_request_form,
                        phone_confirm_form=phone_confirm_form,
                        address_form=address_form,
                        editing_address=None,
                    )
                    return render(request, 'accounts/profile.html', context)
            address_form = SavedAddressForm(request.POST)
            if address_form.is_valid():
                with transaction.atomic():
                    address = editing_address or SavedAddress(user=request.user)
                    address.label = address_form.cleaned_data['label']
                    address.recipient_name = address_form.cleaned_data['recipient_name']
                    address.phone = address_form.cleaned_data['phone']
                    address.email = address_form.cleaned_data['email']
                    address.delivery_type = address_form.cleaned_data['delivery_type']
                    address.pickup_point = address_form.cleaned_data['pickup_point']
                    address.address = address_form.cleaned_data['address']
                    address.comment = address_form.cleaned_data['comment']
                    has_other_addresses = SavedAddress.objects.filter(user=request.user).exclude(pk=address.pk).exists()
                    address.is_default = bool(address_form.cleaned_data.get('is_default')) or not has_other_addresses
                    address.save()

                    if address.is_default:
                        _set_default_saved_address(request.user, address)
                    else:
                        _ensure_default_saved_address(request.user, exclude_pk=address.pk)

                address_form = SavedAddressForm()
                editing_address = None
                alerts.append({'level': 'success', 'text': 'Адрес сохранён.'})
            else:
                alerts.append({'level': 'error', 'text': 'Не удалось сохранить адрес. Проверьте поля формы.'})

        elif action == 'send_email_code':
            email_request_form = EmailVerificationRequestForm(
                request.POST,
                current_user=request.user,
                email_locked=bool(profile.email_verified_at),
            )
            if profile.email_verified_at:
                alerts.append({'level': 'error', 'text': 'Email уже подтверждён и не требует повторной верификации.'})
            elif email_request_form.is_valid():
                email = email_request_form.cleaned_data['email']
                ok, error = create_and_send_email_code(request.user, email)
                if ok:
                    email_confirm_form = EmailVerificationConfirmForm(
                        current_user=request.user,
                        initial={'email': email},
                    )
                    alerts.append({'level': 'success', 'text': 'Письмо с кодом подтверждения отправлено.'})
                else:
                    email_request_form.add_error('email', error)
                    alerts.append({'level': 'error', 'text': 'Не удалось отправить письмо с кодом.'})
            else:
                alerts.append({'level': 'error', 'text': 'Проверьте email для отправки кода.'})

        elif action == 'confirm_email_code':
            email_confirm_form = EmailVerificationConfirmForm(
                request.POST,
                current_user=request.user,
                email_locked=bool(profile.email_verified_at),
            )
            if profile.email_verified_at:
                alerts.append({'level': 'error', 'text': 'Email уже подтверждён.'})
            elif email_confirm_form.is_valid():
                email = email_confirm_form.cleaned_data['email']
                code = email_confirm_form.cleaned_data['code']
                ok, error = confirm_email_verification(request.user, email, code)
                if ok:
                    profile.refresh_from_db(fields=['email_verified_at'])
                    request.user.refresh_from_db(fields=['email'])
                    email_request_form = EmailVerificationRequestForm(
                        current_user=request.user,
                        email_locked=True,
                        initial={'email': request.user.email},
                    )
                    email_confirm_form = EmailVerificationConfirmForm(
                        current_user=request.user,
                        email_locked=True,
                        initial={'email': request.user.email},
                    )
                    alerts.append({'level': 'success', 'text': 'Email успешно подтверждён.'})
                else:
                    target_field = 'email' if 'email' in error.lower() else 'code'
                    email_confirm_form.add_error(target_field, error)
                    alerts.append({'level': 'error', 'text': 'Не удалось подтвердить email.'})
            else:
                alerts.append({'level': 'error', 'text': 'Проверьте код подтверждения email.'})

        elif action == 'delete_address':
            address_id = (request.POST.get('address_id') or '').strip()
            address = SavedAddress.objects.filter(pk=address_id, user=request.user).first()
            if address:
                was_default = address.is_default
                address.delete()
                if was_default:
                    _ensure_default_saved_address(request.user)
                alerts.append({'level': 'success', 'text': 'Адрес удалён.'})
            else:
                alerts.append({'level': 'error', 'text': 'Адрес не найден.'})

        elif action == 'set_default_address':
            address_id = (request.POST.get('address_id') or '').strip()
            address = SavedAddress.objects.filter(pk=address_id, user=request.user).first()
            if address:
                with transaction.atomic():
                    _set_default_saved_address(request.user, address)
                alerts.append({'level': 'success', 'text': 'Адрес по умолчанию обновлён.'})
            else:
                alerts.append({'level': 'error', 'text': 'Адрес не найден.'})

        elif action == 'send_phone_code':
            phone_request_form = PhoneChangeRequestForm(request.POST, current_user=request.user)
            if phone_request_form.is_valid():
                new_phone = phone_request_form.cleaned_data['new_phone']
                ok_rate, rate_error = check_send_code_rate_limits(request, new_phone)
                if not ok_rate:
                    phone_request_form.add_error('new_phone', rate_error)
                    alerts.append({'level': 'error', 'text': 'Не удалось отправить код на новый номер.'})
                else:
                    ok, error = create_and_send_code(new_phone, client_ip=get_client_ip(request))
                    if ok:
                        mark_send_code_success(request, new_phone)
                        request.session[PHONE_CHANGE_SESSION_KEY] = new_phone
                        request.session.modified = True
                        phone_confirm_form = PhoneChangeConfirmForm(
                            current_user=request.user,
                            initial={'new_phone': new_phone},
                        )
                        alerts.append({'level': 'success', 'text': 'Код отправлен на новый номер.'})
                    else:
                        phone_request_form.add_error('new_phone', error)
                        alerts.append({'level': 'error', 'text': 'Не удалось отправить код на новый номер.'})
            else:
                alerts.append({'level': 'error', 'text': 'Проверьте номер телефона для отправки кода.'})

        elif action == 'confirm_phone_code':
            phone_confirm_form = PhoneChangeConfirmForm(request.POST, current_user=request.user)
            pending_phone = request.session.get(PHONE_CHANGE_SESSION_KEY, '')

            if phone_confirm_form.is_valid():
                new_phone = phone_confirm_form.cleaned_data['new_phone']
                code = phone_confirm_form.cleaned_data['code']
                if not pending_phone:
                    phone_confirm_form.add_error(None, 'Сначала запросите код для нового номера.')
                elif normalize_phone(pending_phone) != new_phone:
                    phone_confirm_form.add_error('new_phone', 'Номер не совпадает с номером, для которого отправлен код.')
                else:
                    ok_rate, rate_error = check_verify_code_rate_limits(request, new_phone, endpoint='profile-phone-confirm')
                    if not ok_rate:
                        phone_confirm_form.add_error('code', rate_error)
                    else:
                        ok, error = verify_sms_code(new_phone, code, consume=True)
                        if not ok:
                            phone_confirm_form.add_error('code', error)
                        elif User.objects.filter(username=new_phone).exclude(pk=request.user.pk).exists():
                            phone_confirm_form.add_error('new_phone', 'Этот номер уже используется другим аккаунтом.')
                        else:
                            try:
                                with transaction.atomic():
                                    locked_user = User.objects.select_for_update().get(pk=request.user.pk)
                                    Profile.objects.select_for_update().filter(user=locked_user).first()

                                    if User.objects.filter(username=new_phone).exclude(pk=locked_user.pk).exists():
                                        raise IntegrityError('duplicate username')

                                    locked_user.username = new_phone
                                    locked_user.save(update_fields=['username'])
                                    Profile.objects.filter(user=locked_user).update(phone=new_phone)
                            except IntegrityError:
                                phone_confirm_form.add_error('new_phone', 'Не удалось сменить номер: номер уже занят.')
                            else:
                                profile.phone = new_phone
                                request.user.username = new_phone
                                request.session.pop(PHONE_CHANGE_SESSION_KEY, None)
                                request.session.modified = True
                                phone_request_form = PhoneChangeRequestForm(current_user=request.user)
                                phone_confirm_form = PhoneChangeConfirmForm(current_user=request.user)
                                alerts.append({'level': 'success', 'text': 'Номер телефона успешно обновлён.'})

            if phone_confirm_form.errors:
                alerts.append({'level': 'error', 'text': 'Не удалось подтвердить смену номера.'})

        else:
            alerts.append({'level': 'error', 'text': 'Неизвестное действие формы.'})

    if request.method == 'GET':
        edit_address_id = (request.GET.get('edit_address') or '').strip()
        if edit_address_id:
            editing_address = SavedAddress.objects.filter(
                pk=edit_address_id,
                user=request.user,
            ).select_related('pickup_point__city').first()
            if editing_address:
                address_form = SavedAddressForm(initial=_saved_address_initial(editing_address))

    context = _build_profile_context(
        request=request,
        profile=profile,
        alerts=alerts,
        profile_form=profile_form,
        email_request_form=email_request_form,
        email_confirm_form=email_confirm_form,
        phone_request_form=phone_request_form,
        phone_confirm_form=phone_confirm_form,
        address_form=address_form,
        editing_address=editing_address,
    )
    return render(request, 'accounts/profile.html', context)


@require_GET
def balance_history_view(request):
    """История операций по балансу."""
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    Profile.objects.get_or_create(user=request.user, defaults={'phone': request.user.username})
    transactions = BalanceTransaction.objects.filter(user=request.user)[:100]
    return render(request, 'accounts/balance_history.html', {
        'profile': request.user.profile,
        'user': request.user,
        'transactions': transactions,
    })
