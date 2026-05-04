from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from catalog.models import Favorite
from config.legal_consent import get_legal_bundle_version
from orders.models import Order

from ..forms import (
    EmailVerificationConfirmForm,
    EmailVerificationRequestForm,
    NotificationPreferencesForm,
    ProfileUpdateForm,
    SavedAddressForm,
)
from ..models import BalanceTransaction, CommercialProposalContact, Profile, SavedAddress
from ..security import (
    check_send_email_rate_limits,
    check_verify_email_code_rate_limits,
    mark_send_email_success,
)
from ..services import (
    ensure_profile,
    confirm_email_verification,
    create_and_send_email_code,
    get_or_create_notification_preferences,
    get_pending_email_verification,
    get_user_phone,
    normalize_phone,
)
from orders.services import build_order_status_summary

User = get_user_model()
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
            Order.STATUS_NEW: 'Требуют подтверждения менеджером.',
            Order.STATUS_CONFIRMED: 'Менеджер подтвердил заказ и готовит его к отгрузке.',
            Order.STATUS_SHIPPING: 'Заказы в пути или ожидают выдачи.',
            Order.STATUS_READY_FOR_PICKUP: 'Заказы готовы к выдаче в точке получения.',
            Order.STATUS_DONE: 'Выполненные заказы и история покупок.',
            Order.STATUS_CANCELLED: 'Отменённые заказы и незавершённые покупки.',
        }
        return descriptions.get(status, 'Быстрый переход к заказам в этом статусе.')

    empty_descriptions = {
        Order.STATUS_NEW: 'Новых заказов пока нет.',
        Order.STATUS_CONFIRMED: 'Подтверждённые заказы появятся здесь.',
        Order.STATUS_SHIPPING: 'Когда отправим заказ, он появится здесь.',
        Order.STATUS_READY_FOR_PICKUP: 'Готовые к выдаче заказы появятся здесь.',
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

    delivery_label = order.public_delivery_label
    destination = order.address or (order.pickup_point.address if order.pickup_point_id and order.pickup_point else '')

    return {
        'instance': order,
        'first_item_name': first_item_name,
        'items_caption': items_caption,
        'delivery_label': delivery_label,
        'destination': destination,
        'recipient_name': ' '.join(part for part in [order.last_name, order.first_name] if part).strip(),
        'status_summary': build_order_status_summary(order),
    }


def _saved_address_initial(address=None):
    if not address:
        return {}
    return {
        'label': address.label,
        'recipient_name': address.recipient_name,
        'phone': _format_phone(address.phone),
        'email': address.email,
        'city': address.city,
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


def _build_profile_completion(profile, saved_addresses, orders_total, favorites_count):
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
            'hint': 'Сохранённый адрес ускоряет оформление заказа и повторные покупки.',
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

    if not profile.email_verified_at:
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


def _build_profile_setup_checklist(profile, saved_addresses, notification_preferences):
    steps = [
        {
            'title': 'Добавить данные',
            'description': 'Укажите ФИО получателя для заказов и документов.',
            'href': f"{reverse('accounts:profile_settings')}#profile",
            'done': bool(profile.contact_name),
            'icon': 'user',
        },
        {
            'title': 'Сохранить адрес',
            'description': 'Добавьте основной сценарий доставки для быстрого checkout.',
            'href': f"{reverse('accounts:profile_settings')}#delivery",
            'done': bool(saved_addresses),
            'icon': 'map-pin',
        },
        {
            'title': 'Подтвердить email',
            'description': 'Проверенный email пригодится для сервисных писем и документов.',
            'href': f"{reverse('accounts:profile_settings')}#security",
            'done': bool(profile.email_verified_at),
            'icon': 'mail-check',
        },
        {
            'title': 'Настроить уведомления',
            'description': 'Проверьте каналы связи и оставьте только нужные уведомления.',
            'href': f"{reverse('accounts:profile_settings')}#notifications",
            'done': bool(
                notification_preferences.marketing_email_enabled
                or notification_preferences.back_in_stock_enabled
            ),
            'icon': 'bell',
        },
    ]
    completed = sum(1 for step in steps if step['done'])
    total = len(steps)
    percent = int((completed / total) * 100) if total else 0
    pending_steps = [step for step in steps if not step['done']]
    completed_steps = [step for step in steps if step['done']]
    progress_label = f'{completed} из {total} выполнено'

    if completed == total:
        summary = 'Все базовые шаги закрыты. Кабинет готов к быстрому оформлению.'
    else:
        summary = f'{progress_label}. Незавершённые шаги подняты выше, чтобы их можно было закрыть без поиска.'

    return {
        'steps': pending_steps + completed_steps,
        'pending_steps': pending_steps,
        'completed_steps': completed_steps,
        'completed': completed,
        'total': total,
        'percent': percent,
        'progress_label': progress_label,
        'summary': summary,
        'remaining': total - completed,
        'is_complete': completed == total,
    }


def _build_priority_actions(profile, saved_addresses, active_orders_count, favorites_count):
    actions = []

    if not profile.contact_name:
        actions.append({
            'title': 'Добавить данные получателя',
            'description': 'Укажите ФИО, чтобы не вводить его заново при каждом заказе.',
            'href': f"{reverse('accounts:profile_settings')}#profile",
            'variant': 'accent',
            'icon': 'user',
        })
    if not saved_addresses:
        actions.append({
            'title': 'Сохранить адрес доставки',
            'description': 'Сделайте один готовый сценарий доставки для оформления заказа в один клик.',
            'href': f"{reverse('accounts:profile_settings')}#delivery",
            'variant': 'default',
            'icon': 'map-pin',
        })
    if not profile.email_verified_at:
        actions.append({
            'title': 'Подтвердить email',
            'description': 'Проверенный email пригодится для уведомлений и документов.',
            'href': f"{reverse('accounts:profile_settings')}#security",
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


def _get_order_count(order_stats, status):
    for item in order_stats:
        if item['status'] == status:
            return item['count']
    return 0


def _build_active_order_summary(recent_orders):
    for order in recent_orders:
        if order['instance'].status not in {Order.STATUS_DONE, Order.STATUS_CANCELLED}:
            return order
    return None


def _build_overview_notifications(
    active_order_summary,
    default_saved_address,
    pending_email_verification,
    profile_completion,
):
    notifications = []

    if active_order_summary and active_order_summary['instance'].status == Order.STATUS_NEW:
        notifications.append({
            'title': f"Заказ №{active_order_summary['instance'].pk} ждёт следующего шага",
            'text': active_order_summary['status_summary']['status_next_step'],
            'href': reverse('orders:order_detail', kwargs={'pk': active_order_summary['instance'].pk}),
            'cta': 'Открыть заказ',
            'tone': 'warning',
        })

    if pending_email_verification:
        notifications.append({
            'title': 'Email ждёт подтверждения',
            'text': f"Код уже отправлен на {pending_email_verification.email}.",
            'href': f"{reverse('accounts:profile_settings')}#security",
            'cta': 'Подтвердить email',
            'tone': 'info',
        })

    if not default_saved_address:
        notifications.append({
            'title': 'Нет сохранённого адреса',
            'text': 'Добавьте основной адрес, чтобы не заполнять доставку вручную при каждом заказе.',
            'href': f"{reverse('accounts:profile_settings')}#delivery",
            'cta': 'Добавить адрес',
            'tone': 'muted',
        })

    if not notifications:
        notifications.append({
            'title': 'Кабинет готов к следующему заказу',
            'text': profile_completion['summary'],
            'href': reverse('orders:order_list'),
            'cta': 'К заказам',
            'tone': 'success',
        })

    return notifications[:3]


def _build_overview_actions(active_order_summary, orders_total):
    if active_order_summary and active_order_summary['instance'].status not in {Order.STATUS_DONE, Order.STATUS_CANCELLED}:
        primary_action = {
            'label': 'Открыть активный заказ',
            'href': reverse('orders:order_detail', kwargs={'pk': active_order_summary['instance'].pk}),
        }
    elif orders_total:
        primary_action = {
            'label': 'Открыть все заказы',
            'href': reverse('orders:order_list'),
        }
    else:
        primary_action = {
            'label': 'Перейти в каталог',
            'href': reverse('catalog:product_list'),
        }

    secondary_actions = [
        {
            'label': 'Связаться с поддержкой',
            'href': reverse('contacts'),
        },
        {
            'label': 'Редактировать профиль',
            'href': reverse('accounts:profile_settings'),
        },
    ]
    return primary_action, secondary_actions


def _build_overview_status_cards(order_stats, active_orders_count, profile_setup_checklist):
    requires_attention = _get_order_count(order_stats, Order.STATUS_NEW)
    return [
        {
            'label': 'Активные заказы',
            'value': active_orders_count,
            'description': 'В работе прямо сейчас.',
        },
        {
            'label': 'Нужно внимания',
            'value': requires_attention,
            'description': 'Новые заказы и первые шаги.',
        },
        {
            'label': 'Чек-лист профиля',
            'value': f"{profile_setup_checklist['completed']}/{profile_setup_checklist['total']}",
            'description': 'Базовые шаги для быстрого оформления.',
        },
    ]


def _build_account_quick_statuses(profile, has_password, default_saved_address):
    return [
        {
            'label': 'Email',
            'value': 'подтверждён' if profile.email_verified_at else 'не подтверждён',
            'tone': 'success' if profile.email_verified_at else 'warning',
        },
        {
            'label': 'Пароль',
            'value': 'установлен' if has_password else 'не установлен',
            'tone': 'success' if has_password else 'muted',
        },
        {
            'label': 'Основной адрес',
            'value': default_saved_address.label if default_saved_address else 'не добавлен',
            'tone': 'success' if default_saved_address else 'muted',
        },
    ]


def _build_profile_context(
    request,
    profile,
    alerts=None,
    profile_form=None,
    email_request_form=None,
    email_confirm_form=None,
    address_form=None,
    notification_form=None,
    editing_address=None,
    profile_edit_mode=False,
    address_edit_mode=False,
    security_edit_mode=False,
    notifications_edit_mode=False,
):
    try:
        cp_contact = request.user.cp_contact
    except CommercialProposalContact.DoesNotExist:
        cp_contact = None
    pending_email_verification = get_pending_email_verification(request.user)
    confirmed_email = (request.user.email or '').strip()

    if profile_form is None:
        profile_form = ProfileUpdateForm(
            initial={'contact_name': profile.contact_name or ''},
            require_privacy=not bool(profile.privacy_agreed_at),
        )
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
    if address_form is None:
        address_form = SavedAddressForm(initial=_saved_address_initial(editing_address))
    notification_preferences = get_or_create_notification_preferences(request.user)
    if notification_form is None:
        notification_form = NotificationPreferencesForm(initial={
            'marketing_email_enabled': notification_preferences.marketing_email_enabled,
            'back_in_stock_enabled': notification_preferences.back_in_stock_enabled,
        })

    last_orders = list(
        Order.objects
        .filter(user=request.user)
        .prefetch_related('items__product')
        .select_related('city', 'pickup_point')
        .order_by('-created_at')[:5]
    )
    saved_addresses = list(
        SavedAddress.objects.filter(user=request.user)
        .order_by('-is_default', '-updated_at', '-id')
    )
    default_saved_address = next((address for address in saved_addresses if address.is_default), None)
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
    primary_contact_phone = cp_contact.phone if cp_contact and cp_contact.phone else get_user_phone(request.user, profile)
    primary_contact_email = cp_contact.email if cp_contact and cp_contact.email else confirmed_email
    profile_completion = _build_profile_completion(
        profile=profile,
        saved_addresses=saved_addresses,
        orders_total=sum(item['count'] for item in order_stats),
        favorites_count=favorites_count,
    )
    profile_setup_checklist = _build_profile_setup_checklist(
        profile=profile,
        saved_addresses=saved_addresses,
        notification_preferences=notification_preferences,
    )
    priority_actions = _build_priority_actions(
        profile=profile,
        saved_addresses=saved_addresses,
        active_orders_count=active_orders_count,
        favorites_count=favorites_count,
    )
    customer_segment, customer_segment_description = _build_customer_segment(
        orders_total=sum(item['count'] for item in order_stats),
        active_orders_count=active_orders_count,
    )
    active_order_summary = _build_active_order_summary(recent_orders)
    overview_notifications = _build_overview_notifications(
        active_order_summary=active_order_summary,
        default_saved_address=default_saved_address,
        pending_email_verification=pending_email_verification,
        profile_completion=profile_completion,
    )
    overview_primary_action, overview_secondary_actions = _build_overview_actions(
        active_order_summary=active_order_summary,
        orders_total=sum(item['count'] for item in order_stats),
    )
    overview_status_cards = _build_overview_status_cards(
        order_stats=order_stats,
        active_orders_count=active_orders_count,
        profile_setup_checklist=profile_setup_checklist,
    )
    has_password = request.user.has_usable_password()
    account_quick_statuses = _build_account_quick_statuses(
        profile=profile,
        has_password=has_password,
        default_saved_address=default_saved_address,
    )

    return {
        'user': request.user,
        'profile': profile,
        'has_password': has_password,
        'phone_display': _format_phone(get_user_phone(request.user, profile)) or 'Телефон не указан',
        'primary_contact_phone': _format_phone(primary_contact_phone) or 'Телефон не указан',
        'primary_contact_email': primary_contact_email,
        'alerts': alerts or [],
        'profile_form': profile_form,
        'email_request_form': email_request_form,
        'email_confirm_form': email_confirm_form,
        'pending_email_verification': pending_email_verification,
        'confirmed_email': confirmed_email,
        'address_form': address_form,
        'notification_form': notification_form,
        'notification_preferences': notification_preferences,
        'editing_address': editing_address,
        'profile_edit_mode': profile_edit_mode,
        'address_edit_mode': address_edit_mode,
        'security_edit_mode': security_edit_mode,
        'notifications_edit_mode': notifications_edit_mode,
        'saved_addresses': saved_addresses,
        'default_saved_address': default_saved_address,
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
        'profile_setup_checklist': profile_setup_checklist,
        'priority_actions': priority_actions,
        'customer_segment': customer_segment,
        'customer_segment_description': customer_segment_description,
        'active_order_summary': active_order_summary,
        'overview_notifications': overview_notifications,
        'overview_primary_action': overview_primary_action,
        'overview_secondary_actions': overview_secondary_actions,
        'overview_status_cards': overview_status_cards,
        'account_quick_statuses': account_quick_statuses,
    }


def build_account_sidebar_context(request, active_tab):
    profile = ensure_profile(request.user)
    try:
        cp_contact = request.user.cp_contact
    except CommercialProposalContact.DoesNotExist:
        cp_contact = None

    pending_email_verification = get_pending_email_verification(request.user)
    order_rows = (
        Order.objects
        .filter(user=request.user)
        .values('status')
        .annotate(total=Count('id'))
    )
    order_counters = {row['status']: row['total'] for row in order_rows}
    orders_total = sum(order_counters.values())
    active_orders_count = sum(
        total for status, total in order_counters.items()
        if status not in {Order.STATUS_DONE, Order.STATUS_CANCELLED}
    )
    saved_addresses_count = SavedAddress.objects.filter(user=request.user).count()
    favorites_count = Favorite.objects.filter(user=request.user).count()
    completion = _build_profile_completion(
        profile=profile,
        saved_addresses=[None] * saved_addresses_count,
        orders_total=orders_total,
        favorites_count=favorites_count,
    )

    primary_email = (
        cp_contact.email
        if cp_contact and cp_contact.email
        else (request.user.email or '').strip() or (pending_email_verification.email if pending_email_verification else '')
    )
    profile_name = profile.contact_name or 'Профиль не заполнен'
    profile_state = 'Профиль заполнен частично' if profile.contact_name else 'Добавьте имя получателя'

    settings_href = reverse('accounts:profile_settings')
    navigation_items = [
        {
            'label': 'Обзор',
            'href': reverse('accounts:profile'),
            'active': active_tab == 'overview',
        },
        {
            'label': 'Заказы',
            'href': reverse('orders:order_list'),
            'active': active_tab == 'orders',
            'badge': active_orders_count or None,
        },
        {
            'label': 'Профиль и настройки',
            'href': settings_href,
            'active': active_tab == 'settings',
        },
    ]
    settings_sections = [
        {'label': 'Данные получателя', 'href': f'{settings_href}#profile', 'section_id': 'profile'},
        {'label': 'Адреса доставки', 'href': f'{settings_href}#delivery', 'section_id': 'delivery'},
        {'label': 'Доступ в аккаунт', 'href': f'{settings_href}#security', 'section_id': 'security'},
        {'label': 'Каналы связи', 'href': f'{settings_href}#communication', 'section_id': 'communication'},
        {'label': 'Уведомления', 'href': f'{settings_href}#notifications', 'section_id': 'notifications'},
        {'label': 'Документы и поддержка', 'href': f'{settings_href}#service', 'section_id': 'service'},
    ]
    service_items = [
        {'label': 'Документы', 'href': reverse('orders:order_list'), 'active': False},
        {'label': 'Гарантия', 'href': f"{reverse('sales_terms')}#sales-warranty", 'active': False},
        {'label': 'Поддержка', 'href': reverse('contacts'), 'active': False},
        {'label': 'Возвраты / обращения', 'href': reverse('contacts'), 'active': False},
    ]
    footer_items = [
        {
            'label': 'Избранное',
            'href': reverse('catalog:favorites'),
            'active': False,
            'badge': favorites_count or None,
        },
        {
            'label': 'Баланс',
            'href': reverse('accounts:balance_history'),
            'active': active_tab == 'balance',
            'badge': None,
        },
        {
            'label': 'Выйти',
            'href': reverse('accounts:logout'),
            'active': False,
            'is_form': True,
        },
    ]

    return {
        'active_account_tab': active_tab,
        'account_sidebar': {
            'profile_name': profile_name,
            'profile_state': profile_state,
            'phone': _format_phone(get_user_phone(request.user, profile)) or 'Телефон не указан',
            'email': primary_email or 'Email не указан',
            'completion_percent': completion['percent'],
            'edit_href': f'{settings_href}#profile',
            'navigation': navigation_items,
            'service': service_items,
            'footer': footer_items,
            'settings_sections': settings_sections if active_tab == 'settings' else [],
        },
    }


def _render_profile_settings(request):
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    profile = ensure_profile(request.user)
    alerts = _consume_pending_alerts(request)

    profile_form = None
    email_request_form = None
    email_confirm_form = None
    address_form = None
    notification_form = None
    editing_address = None
    profile_edit_mode = request.GET.get('edit_profile') == '1'
    address_edit_mode = request.GET.get('add_address') == '1'
    security_edit_mode = request.GET.get('edit_security') == '1'
    notifications_edit_mode = request.GET.get('edit_notifications') == '1'

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'save_profile':
            profile_form = ProfileUpdateForm(
                request.POST,
                require_privacy=not bool(profile.privacy_agreed_at),
            )
            if profile_form.is_valid():
                update_fields = []
                profile.contact_name = profile_form.cleaned_data['contact_name']
                update_fields.append('contact_name')
                if not profile.privacy_agreed_at:
                    profile.privacy_agreed_at = timezone.now()
                    profile.privacy_policy_version = get_legal_bundle_version()
                    update_fields.extend(['privacy_agreed_at', 'privacy_policy_version'])
                profile.save(update_fields=update_fields)
                alerts.append({'level': 'success', 'text': 'Данные профиля сохранены.'})
            else:
                profile_edit_mode = True
                alerts.append({'level': 'error', 'text': 'Не удалось сохранить профиль. Проверьте поля формы.'})

        elif action == 'save_address':
            address_id = (request.POST.get('address_id') or '').strip()
            if address_id:
                editing_address = SavedAddress.objects.filter(pk=address_id, user=request.user).first()
                if editing_address is None:
                    address_edit_mode = True
                    address_form = SavedAddressForm(request.POST)
                    alerts.append({'level': 'error', 'text': 'Адрес не найден.'})
                    context = _build_profile_context(
                        request=request,
                        profile=profile,
                        alerts=alerts,
                        profile_form=profile_form,
                        email_request_form=email_request_form,
                        email_confirm_form=email_confirm_form,
                        address_form=address_form,
                        editing_address=None,
                        profile_edit_mode=profile_edit_mode,
                        address_edit_mode=address_edit_mode,
                    )
                    context.update(build_account_sidebar_context(request, active_tab='settings'))
                    return render(request, 'accounts/profile_settings.html', context)
                address_edit_mode = True
            else:
                address_edit_mode = True
            address_form = SavedAddressForm(request.POST)
            if address_form.is_valid():
                with transaction.atomic():
                    address = editing_address or SavedAddress(user=request.user)
                    address.label = address_form.cleaned_data['label']
                    address.recipient_name = address_form.cleaned_data['recipient_name']
                    address.phone = address_form.cleaned_data['phone']
                    address.email = address_form.cleaned_data['email']
                    address.city = address_form.cleaned_data['city']
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
                address_edit_mode = False
                alerts.append({'level': 'success', 'text': 'Адрес сохранён.'})
            else:
                address_edit_mode = True
                alerts.append({'level': 'error', 'text': 'Не удалось сохранить адрес. Проверьте поля формы.'})

        elif action == 'send_email_code':
            security_edit_mode = True
            email_request_form = EmailVerificationRequestForm(
                request.POST,
                current_user=request.user,
                email_locked=bool(profile.email_verified_at),
            )
            if profile.email_verified_at:
                alerts.append({'level': 'error', 'text': 'Email уже подтверждён и не требует повторной верификации.'})
            elif email_request_form.is_valid():
                email = email_request_form.cleaned_data['email']
                ok_rate, rate_error = check_send_email_rate_limits(
                    request,
                    email,
                    endpoint='profile-email-code',
                )
                if ok_rate:
                    ok, error = create_and_send_email_code(request.user, email)
                else:
                    ok, error = False, rate_error
                if ok:
                    mark_send_email_success(request, email, endpoint='profile-email-code')
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
            security_edit_mode = True
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
                ok_rate, rate_error = check_verify_email_code_rate_limits(
                    request,
                    email,
                    endpoint='profile-email-code',
                )
                if ok_rate:
                    ok, error = confirm_email_verification(request.user, email, code)
                else:
                    ok, error = False, rate_error
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
                    security_edit_mode = False
                else:
                    target_field = 'email' if 'email' in error.lower() else 'code'
                    email_confirm_form.add_error(target_field, error)
                    alerts.append({'level': 'error', 'text': 'Не удалось подтвердить email.'})
            else:
                alerts.append({'level': 'error', 'text': 'Проверьте код подтверждения email.'})

        elif action == 'save_notification_preferences':
            notifications_edit_mode = True
            notification_preferences = get_or_create_notification_preferences(request.user)
            notification_form = NotificationPreferencesForm(request.POST)
            if notification_form.is_valid():
                notification_preferences.sms_order_updates_enabled = False
                notification_preferences.marketing_email_enabled = bool(
                    notification_form.cleaned_data.get('marketing_email_enabled')
                )
                notification_preferences.back_in_stock_enabled = bool(
                    notification_form.cleaned_data.get('back_in_stock_enabled')
                )
                notification_preferences.save(update_fields=[
                    'sms_order_updates_enabled',
                    'marketing_email_enabled',
                    'back_in_stock_enabled',
                    'updated_at',
                ])
                alerts.append({'level': 'success', 'text': 'Настройки уведомлений сохранены.'})
                notifications_edit_mode = False
            else:
                alerts.append({'level': 'error', 'text': 'Не удалось сохранить настройки уведомлений.'})

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

        else:
            alerts.append({'level': 'error', 'text': 'Неизвестное действие формы.'})

    if request.method == 'GET':
        edit_address_id = (request.GET.get('edit_address') or '').strip()
        if edit_address_id:
            editing_address = SavedAddress.objects.filter(
                pk=edit_address_id,
                user=request.user,
            ).first()
            if editing_address:
                address_edit_mode = True
                address_form = SavedAddressForm(initial=_saved_address_initial(editing_address))

    if get_pending_email_verification(request.user):
        security_edit_mode = True

    context = _build_profile_context(
        request=request,
        profile=profile,
        alerts=alerts,
        profile_form=profile_form,
        email_request_form=email_request_form,
        email_confirm_form=email_confirm_form,
        address_form=address_form,
        notification_form=notification_form,
        editing_address=editing_address,
        profile_edit_mode=profile_edit_mode,
        address_edit_mode=address_edit_mode,
        security_edit_mode=security_edit_mode,
        notifications_edit_mode=notifications_edit_mode,
    )
    context.update(build_account_sidebar_context(request, active_tab='settings'))
    return render(request, 'accounts/profile_settings.html', context)


@require_http_methods(['GET', 'POST'])
def profile_view(request):
    """Обзорная точка входа в кабинет. POST оставлен для обратной совместимости и ведёт в настройки."""
    if request.method == 'POST':
        return _render_profile_settings(request)

    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    ensure_profile(request.user)
    context = _build_profile_context(
        request=request,
        profile=request.user.profile,
        alerts=_consume_pending_alerts(request),
    )
    context.update(build_account_sidebar_context(request, active_tab='overview'))
    return render(request, 'accounts/profile.html', context)


@require_http_methods(['GET', 'POST'])
def profile_settings_view(request):
    """Страница редактирования профиля, адресов и настроек доступа."""
    return _render_profile_settings(request)


@require_GET
def balance_history_view(request):
    """История операций по балансу."""
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    ensure_profile(request.user)
    transactions = BalanceTransaction.objects.filter(user=request.user)[:100]
    context = {
        'profile': request.user.profile,
        'user': request.user,
        'transactions': transactions,
    }
    context.update(build_account_sidebar_context(request, active_tab='balance'))
    return render(request, 'accounts/balance_history.html', context)
