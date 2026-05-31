from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify


ROOT_IDENTITY_WIDTH = 6
CONTRACT_ROOT_IDENTITY_WIDTH = 4
CHILD_IDENTITY_WIDTH = 2
RUSSIAN_MONTH_LABELS = {
    1: 'январь',
    2: 'февраль',
    3: 'март',
    4: 'апрель',
    5: 'май',
    6: 'июнь',
    7: 'июль',
    8: 'август',
    9: 'сентябрь',
    10: 'октябрь',
    11: 'ноябрь',
    12: 'декабрь',
}


def _year_from_value(value):
    if value is None:
        return timezone.localdate().year
    return getattr(value, 'year', timezone.localdate().year)


def _split_identity_code(value):
    parts = (value or '').split('-')
    if len(parts) < 3:
        return None, None
    year = parts[1]
    seq = parts[2]
    if not (year.isdigit() and seq.isdigit()):
        return None, None
    return year, seq


def _next_identity_sequence(model, field_name, prefix, *, exclude_pk=None):
    queryset = model.objects.filter(**{f'{field_name}__startswith': prefix})
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    max_value = 0
    for code in queryset.values_list(field_name, flat=True):
        tail = (code or '').split('-')[-1]
        if tail.isdigit():
            max_value = max(max_value, int(tail))
    return max_value + 1


def _formatted_identity(prefix, year, sequence, *, width=ROOT_IDENTITY_WIDTH):
    return f'{prefix}-{year}-{sequence:0{width}d}'


def _deal_child_identity(prefix, deal_code, model, field_name, *, exclude_pk=None):
    deal_year, deal_seq = _split_identity_code(deal_code)
    if not deal_year or not deal_seq:
        year = timezone.localdate().year
        sequence = _next_identity_sequence(model, field_name, f'{prefix}-{year}-', exclude_pk=exclude_pk)
        return _formatted_identity(prefix, year, sequence)
    code_prefix = f'{prefix}-{deal_year}-{deal_seq}-'
    child_sequence = _next_identity_sequence(model, field_name, code_prefix, exclude_pk=exclude_pk)
    return f'{code_prefix}{child_sequence:0{CHILD_IDENTITY_WIDTH}d}'


def _join_identity_title(*parts):
    return ' · '.join(str(part).strip() for part in parts if str(part).strip())


def _month_year_label(value):
    if not value:
        return ''
    return f'{RUSSIAN_MONTH_LABELS.get(value.month, value.month)} {value.year}'


def _extend_update_fields(kwargs, *field_names):
    update_fields = kwargs.get('update_fields')
    if update_fields is None:
        return
    normalized_fields = set(update_fields)
    normalized_fields.update(field_names)
    kwargs['update_fields'] = list(normalized_fields)


class ManagerClient(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Активный'),
        (STATUS_ARCHIVED, 'Архив'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_clients',
        verbose_name='Пользователь сайта',
    )
    name = models.CharField('Имя / компания', max_length=255)
    email = models.EmailField('Email', blank=True)
    phone = models.CharField('Телефон', max_length=40, blank=True)
    telegram = models.CharField('Telegram', max_length=120, blank=True)
    address = models.TextField('Адрес', blank=True)
    comments = models.TextField('Комментарий', blank=True)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    orders = models.ManyToManyField(
        'orders.Order',
        related_name='manager_client_links',
        blank=True,
        verbose_name='Связанные заказы сайта',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Внутренний клиент'
        verbose_name_plural = 'Внутренние клиенты'
        ordering = ['name', 'id']

    def __str__(self):
        return self.name


class ManagerPersonAlias(models.Model):
    display_name = models.CharField('Отображаемое имя', max_length=255, unique=True)
    slug = models.SlugField('Slug', max_length=255, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_person_aliases',
        verbose_name='Связанный пользователь',
    )
    is_active = models.BooleanField('Активен', default=True, db_index=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Алиас участника сделки'
        verbose_name_plural = 'Алиасы участников сделки'
        ordering = ['display_name', 'id']

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.display_name, allow_unicode=True)
        super().save(*args, **kwargs)


class ManagerDeal(models.Model):
    DEAL_SALE_ON_REQUEST = 'sale_on_request'
    DEAL_SALE_FROM_STOCK = 'sale_from_stock'
    DEAL_TRADE_IN = 'trade_in'
    DEAL_AVITO = 'avito_sale'
    DEAL_TYPE_CHOICES = [
        (DEAL_SALE_ON_REQUEST, 'Продажа под заказ'),
        (DEAL_SALE_FROM_STOCK, 'Продажа из наличия'),
        (DEAL_TRADE_IN, 'Трейд-ин'),
        (DEAL_AVITO, 'Продажа Avito'),
    ]

    DEAL_STATUS_NEW_REQUEST = 'new_request'
    DEAL_STATUS_AWAITING_PREPAYMENT = 'awaiting_prepayment'
    DEAL_STATUS_PREPAYMENT_RECEIVED = 'prepayment_received'
    DEAL_STATUS_SUPPLIER_ORDERED = 'supplier_ordered'
    DEAL_STATUS_IN_TRANSIT = 'in_transit'
    DEAL_STATUS_RECEIVED = 'received'
    DEAL_STATUS_READY_TO_SHIP = 'ready_to_ship'
    DEAL_STATUS_SHIPPED = 'shipped'
    DEAL_STATUS_COMPLETED = 'completed'
    DEAL_STATUS_CANCELLED = 'cancelled'
    DEAL_STATUS_NEW = 'new'
    DEAL_STATUS_RESERVED = 'reserved'
    DEAL_STATUS_AWAITING_PAYMENT = 'awaiting_payment'
    DEAL_STATUS_PAID = 'paid'
    DEAL_STATUS_ASSEMBLING = 'assembling'
    DEAL_STATUS_AWAITING_EVALUATION = 'awaiting_evaluation'
    DEAL_STATUS_EVALUATED = 'evaluated'
    DEAL_STATUS_TERMS_AGREED = 'terms_agreed'
    DEAL_STATUS_AWAITING_DEVICE_SHIPMENT = 'awaiting_device_shipment'
    DEAL_STATUS_DEVICE_RECEIVED = 'device_received'
    DEAL_STATUS_INSPECTED = 'inspected'
    DEAL_STATUS_READY_FOR_EXCHANGE = 'ready_for_exchange'
    DEAL_STATUS_TOPUP_RECEIVED = 'topup_received'
    DEAL_STATUS_NEW_ITEM_SHIPPED = 'new_item_shipped'
    DEAL_STATUS_CORRESPONDENCE = 'correspondence'
    DEAL_STATUS_BOOKED = 'booked'
    DEAL_STATUS_CONFIRMED = 'confirmed'
    DEAL_STATUS_RECEIVED_BY_CUSTOMER = 'received_by_customer'
    DEAL_STATUS_RETURNED = 'returned'
    DEAL_STATUS_CHOICES = [
        (DEAL_STATUS_NEW_REQUEST, 'Новая заявка'),
        (DEAL_STATUS_AWAITING_PREPAYMENT, 'Ожидает предоплату'),
        (DEAL_STATUS_PREPAYMENT_RECEIVED, 'Предоплата получена'),
        (DEAL_STATUS_SUPPLIER_ORDERED, 'Заказ размещен у поставщика'),
        (DEAL_STATUS_IN_TRANSIT, 'Товар в пути'),
        (DEAL_STATUS_RECEIVED, 'Товар поступил'),
        (DEAL_STATUS_READY_TO_SHIP, 'Готов к отправке'),
        (DEAL_STATUS_SHIPPED, 'Отправлен'),
        (DEAL_STATUS_COMPLETED, 'Завершена'),
        (DEAL_STATUS_CANCELLED, 'Отменена'),
        (DEAL_STATUS_NEW, 'Новая'),
        (DEAL_STATUS_RESERVED, 'Резерв создан'),
        (DEAL_STATUS_AWAITING_PAYMENT, 'Ожидает оплату'),
        (DEAL_STATUS_PAID, 'Оплачена'),
        (DEAL_STATUS_ASSEMBLING, 'Собирается'),
        (DEAL_STATUS_AWAITING_EVALUATION, 'Ожидает оценку'),
        (DEAL_STATUS_EVALUATED, 'Оценено'),
        (DEAL_STATUS_TERMS_AGREED, 'Условия согласованы'),
        (DEAL_STATUS_AWAITING_DEVICE_SHIPMENT, 'Ожидает отправку устройства клиентом'),
        (DEAL_STATUS_DEVICE_RECEIVED, 'Устройство получено'),
        (DEAL_STATUS_INSPECTED, 'Проверено'),
        (DEAL_STATUS_READY_FOR_EXCHANGE, 'Готово к обмену'),
        (DEAL_STATUS_TOPUP_RECEIVED, 'Доплата получена'),
        (DEAL_STATUS_NEW_ITEM_SHIPPED, 'Новый товар отправлен'),
        (DEAL_STATUS_CORRESPONDENCE, 'Переписка'),
        (DEAL_STATUS_BOOKED, 'Бронь'),
        (DEAL_STATUS_CONFIRMED, 'Подтверждена'),
        (DEAL_STATUS_RECEIVED_BY_CUSTOMER, 'Выдано'),
        (DEAL_STATUS_RETURNED, 'Возврат'),
    ]
    DEAL_STATUS_CHOICES_BY_TYPE = {
        DEAL_SALE_ON_REQUEST: [
            DEAL_STATUS_NEW_REQUEST,
            DEAL_STATUS_AWAITING_PREPAYMENT,
            DEAL_STATUS_PREPAYMENT_RECEIVED,
            DEAL_STATUS_SUPPLIER_ORDERED,
            DEAL_STATUS_IN_TRANSIT,
            DEAL_STATUS_RECEIVED,
            DEAL_STATUS_READY_TO_SHIP,
            DEAL_STATUS_SHIPPED,
            DEAL_STATUS_COMPLETED,
            DEAL_STATUS_CANCELLED,
        ],
        DEAL_SALE_FROM_STOCK: [
            DEAL_STATUS_NEW,
            DEAL_STATUS_RESERVED,
            DEAL_STATUS_AWAITING_PAYMENT,
            DEAL_STATUS_PAID,
            DEAL_STATUS_ASSEMBLING,
            DEAL_STATUS_SHIPPED,
            DEAL_STATUS_COMPLETED,
            DEAL_STATUS_CANCELLED,
        ],
        DEAL_TRADE_IN: [
            DEAL_STATUS_NEW_REQUEST,
            DEAL_STATUS_AWAITING_EVALUATION,
            DEAL_STATUS_EVALUATED,
            DEAL_STATUS_TERMS_AGREED,
            DEAL_STATUS_AWAITING_DEVICE_SHIPMENT,
            DEAL_STATUS_DEVICE_RECEIVED,
            DEAL_STATUS_INSPECTED,
            DEAL_STATUS_READY_FOR_EXCHANGE,
            DEAL_STATUS_TOPUP_RECEIVED,
            DEAL_STATUS_NEW_ITEM_SHIPPED,
            DEAL_STATUS_COMPLETED,
            DEAL_STATUS_CANCELLED,
        ],
        DEAL_AVITO: [
            DEAL_STATUS_NEW,
            DEAL_STATUS_SHIPPED,
            DEAL_STATUS_RECEIVED_BY_CUSTOMER,
            DEAL_STATUS_RETURNED,
        ],
    }

    CASE_STATUS_NEW = 'new'
    CASE_STATUS_CONFIRMED = 'confirmed'
    CASE_STATUS_IN_PROGRESS = 'in_progress'
    CASE_STATUS_WAITING_CLIENT = 'waiting_client'
    CASE_STATUS_READY_TO_SHIP = 'ready_to_ship'
    CASE_STATUS_COMPLETED = 'completed'
    CASE_STATUS_CANCELLED = 'cancelled'
    CASE_STATUS_CHOICES = [
        (CASE_STATUS_NEW, 'Новая'),
        (CASE_STATUS_CONFIRMED, 'Подтверждена'),
        (CASE_STATUS_IN_PROGRESS, 'В работе'),
        (CASE_STATUS_WAITING_CLIENT, 'Ждет клиента'),
        (CASE_STATUS_READY_TO_SHIP, 'Готова к отправке'),
        (CASE_STATUS_COMPLETED, 'Завершена'),
        (CASE_STATUS_CANCELLED, 'Отменена'),
    ]

    PAYMENT_STATE_UNPAID = 'unpaid'
    PAYMENT_STATE_PARTIAL = 'partial'
    PAYMENT_STATE_PAID = 'paid'
    PAYMENT_STATE_REFUNDED = 'refunded'
    PAYMENT_STATE_CHOICES = [
        (PAYMENT_STATE_UNPAID, 'Не оплачено'),
        (PAYMENT_STATE_PARTIAL, 'Частичная оплата'),
        (PAYMENT_STATE_PAID, 'Оплачено'),
        (PAYMENT_STATE_REFUNDED, 'Возврат'),
    ]

    FULFILLMENT_STATUS_NOT_RESERVED = 'not_reserved'
    FULFILLMENT_STATUS_RESERVED_STOCK = 'reserved_stock'
    FULFILLMENT_STATUS_RESERVED_INCOMING = 'reserved_incoming'
    FULFILLMENT_STATUS_PROCUREMENT_REQUIRED = 'procurement_required'
    FULFILLMENT_STATUS_FULFILLED = 'fulfilled'
    FULFILLMENT_STATUS_CHOICES = [
        (FULFILLMENT_STATUS_NOT_RESERVED, 'Без резерва'),
        (FULFILLMENT_STATUS_RESERVED_STOCK, 'Резерв со склада'),
        (FULFILLMENT_STATUS_RESERVED_INCOMING, 'Резерв из incoming'),
        (FULFILLMENT_STATUS_PROCUREMENT_REQUIRED, 'Нужна закупка'),
        (FULFILLMENT_STATUS_FULFILLED, 'Исполнено'),
    ]

    DELIVERY_STATUS_NOT_REQUIRED = 'not_required'
    DELIVERY_STATUS_PREPARING = 'preparing'
    DELIVERY_STATUS_READY = 'ready'
    DELIVERY_STATUS_SHIPPED = 'shipped'
    DELIVERY_STATUS_DELIVERED = 'delivered'
    DELIVERY_STATUS_CHOICES = [
        (DELIVERY_STATUS_NOT_REQUIRED, 'Не требуется'),
        (DELIVERY_STATUS_PREPARING, 'Подготовка'),
        (DELIVERY_STATUS_READY, 'Готово'),
        (DELIVERY_STATUS_SHIPPED, 'Отправлено'),
        (DELIVERY_STATUS_DELIVERED, 'Доставлено'),
    ]

    DOCUMENTS_STATUS_NOT_REQUIRED = 'not_required'
    DOCUMENTS_STATUS_DRAFT = 'draft'
    DOCUMENTS_STATUS_SENT = 'sent'
    DOCUMENTS_STATUS_SIGNED = 'signed'
    DOCUMENTS_STATUS_CHOICES = [
        (DOCUMENTS_STATUS_NOT_REQUIRED, 'Не требуются'),
        (DOCUMENTS_STATUS_DRAFT, 'Черновик'),
        (DOCUMENTS_STATUS_SENT, 'Отправлены'),
        (DOCUMENTS_STATUS_SIGNED, 'Подписаны'),
    ]

    NEXT_STEP_SOURCE_SYSTEM = 'system'
    NEXT_STEP_SOURCE_MANUAL = 'manual'
    NEXT_STEP_SOURCE_CHOICES = [
        (NEXT_STEP_SOURCE_SYSTEM, 'Система'),
        (NEXT_STEP_SOURCE_MANUAL, 'Ручное управление'),
    ]

    NEXT_STEP_NEEDS_CONFIRMATION = 'needs_confirmation'
    NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION = 'needs_availability_confirmation'
    NEXT_STEP_NEEDS_PAYMENT = 'needs_payment'
    NEXT_STEP_NEEDS_RESERVATION = 'needs_reservation'
    NEXT_STEP_NEEDS_PROCUREMENT = 'needs_procurement'
    NEXT_STEP_NEEDS_DOCUMENTS = 'needs_documents'
    NEXT_STEP_NEEDS_DOCUMENT_DISPATCH = 'needs_document_dispatch'
    NEXT_STEP_READY_TO_SHIP = 'ready_to_ship'
    NEXT_STEP_SHIPPED = 'shipped'
    NEXT_STEP_RETURN_TO_STOCK = 'return_to_stock'
    NEXT_STEP_COMPLETED = 'completed'
    NEXT_STEP_CHOICES = [
        (NEXT_STEP_NEEDS_CONFIRMATION, 'Подтвердить заказ'),
        (NEXT_STEP_NEEDS_AVAILABILITY_CONFIRMATION, 'Подтвердить наличие'),
        (NEXT_STEP_NEEDS_PAYMENT, 'Получить оплату'),
        (NEXT_STEP_NEEDS_RESERVATION, 'Создать бронь'),
        (NEXT_STEP_NEEDS_PROCUREMENT, 'Запустить закупку'),
        (NEXT_STEP_NEEDS_DOCUMENTS, 'Подготовить документы'),
        (NEXT_STEP_NEEDS_DOCUMENT_DISPATCH, 'Отправить клиенту документы'),
        (NEXT_STEP_READY_TO_SHIP, 'Подготовить отправление'),
        (NEXT_STEP_SHIPPED, 'Контролировать доставку'),
        (NEXT_STEP_RETURN_TO_STOCK, 'Забрать возврат'),
        (NEXT_STEP_COMPLETED, 'Сделка завершена'),
    ]
    NEXT_STEP_LABELS = dict(NEXT_STEP_CHOICES)

    PROBLEM_FLAG_NO_ASSIGNEE = 'no_assignee'
    PROBLEM_FLAG_SLA_OVERDUE = 'sla_overdue'
    PROBLEM_FLAG_STOCK_CONFLICT = 'stock_conflict'
    PROBLEM_FLAG_MISSING_CONTACTS = 'missing_contacts'
    PROBLEM_FLAG_MISSING_PAYMENT = 'missing_payment'
    PROBLEM_FLAG_PAYMENT_BLOCKED = 'payment_blocked'
    PROBLEM_FLAG_MISSING_DOCUMENTS = 'missing_documents'
    PROBLEM_FLAG_SHIPMENT_BLOCKED = 'shipment_blocked'
    PROBLEM_FLAG_STALE_UPDATES = 'stale_updates'
    PROBLEM_FLAG_LABELS = {
        PROBLEM_FLAG_NO_ASSIGNEE: 'Без ответственного',
        PROBLEM_FLAG_SLA_OVERDUE: 'SLA просрочен',
        PROBLEM_FLAG_STOCK_CONFLICT: 'Конфликт по остатку',
        PROBLEM_FLAG_MISSING_CONTACTS: 'Нет контактов',
        PROBLEM_FLAG_MISSING_PAYMENT: 'Нет оплаты',
        PROBLEM_FLAG_PAYMENT_BLOCKED: 'Блокировка оплаты',
        PROBLEM_FLAG_MISSING_DOCUMENTS: 'Не хватает документов',
        PROBLEM_FLAG_SHIPMENT_BLOCKED: 'Блокировка отгрузки',
        PROBLEM_FLAG_STALE_UPDATES: 'Нет обновлений 48 ч',
    }

    BUYER_INDIVIDUAL = 'individual'
    BUYER_BUSINESS = 'business'
    BUYER_TYPE_CHOICES = [
        (BUYER_INDIVIDUAL, 'Физ. лицо'),
        (BUYER_BUSINESS, 'Юр. лицо'),
    ]

    SOURCE_WEBSITE = 'website'
    SOURCE_AVITO = 'avito'
    SOURCE_TELEGRAM = 'telegram'
    SOURCE_WHATSAPP = 'whatsapp'
    SOURCE_CALL = 'call'
    SOURCE_REPEAT = 'repeat'
    SOURCE_OTHER = 'other'
    CUSTOMER_SOURCE_CHOICES = [
        (SOURCE_WEBSITE, 'Сайт'),
        (SOURCE_AVITO, 'Avito'),
        (SOURCE_TELEGRAM, 'Telegram'),
        (SOURCE_WHATSAPP, 'WhatsApp'),
        (SOURCE_CALL, 'Звонок'),
        (SOURCE_REPEAT, 'Повторный клиент'),
        (SOURCE_OTHER, 'Другое'),
    ]

    DELIVERY_CDEK_PVZ = 'cdek_pvz'
    DELIVERY_CDEK_COURIER = 'cdek_courier'
    DELIVERY_PICKUP = 'pickup'
    DELIVERY_CITY = 'city_delivery'
    DELIVERY_OTHER_TRANSPORT = 'other_transport'
    DELIVERY_METHOD_CHOICES = [
        (DELIVERY_CDEK_PVZ, 'СДЭК ПВЗ'),
        (DELIVERY_CDEK_COURIER, 'СДЭК курьер'),
        (DELIVERY_PICKUP, 'Самовывоз'),
        (DELIVERY_CITY, 'Доставка по городу'),
        (DELIVERY_OTHER_TRANSPORT, 'Другая ТК'),
    ]

    DELIVERY_PAYER_CLIENT = 'client'
    DELIVERY_PAYER_SELLER = 'seller'
    DELIVERY_PAYER_INCLUDED = 'included'
    DELIVERY_PAYER_CHOICES = [
        (DELIVERY_PAYER_CLIENT, 'Клиент'),
        (DELIVERY_PAYER_SELLER, 'Продавец'),
        (DELIVERY_PAYER_INCLUDED, 'Включена в цену'),
    ]

    SHIPMENT_DRAFT = 'draft'
    SHIPMENT_PENDING = 'pending'
    SHIPMENT_SENT = 'sent'
    SHIPMENT_DELIVERED = 'delivered'
    SHIPMENT_STATUS_CHOICES = [
        (SHIPMENT_DRAFT, 'Черновик'),
        (SHIPMENT_PENDING, 'Готовится'),
        (SHIPMENT_SENT, 'Отправлено'),
        (SHIPMENT_DELIVERED, 'Получено'),
    ]

    order = models.OneToOneField(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='manager_deal',
        verbose_name='Заказ',
    )
    code = models.CharField('Код сделки', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    responsible_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_deals',
        verbose_name='Ответственный менеджер',
    )
    assigned_at = models.DateTimeField('Назначен', null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_manager_deals',
        verbose_name='Назначил',
    )
    deal_type = models.CharField('Тип сделки', max_length=32, choices=DEAL_TYPE_CHOICES, db_index=True)
    deal_status = models.CharField(
        'Legacy статус сделки',
        max_length=40,
        choices=DEAL_STATUS_CHOICES,
        default=DEAL_STATUS_NEW,
        db_index=True,
    )
    case_status = models.CharField(
        'Главный этап сделки',
        max_length=32,
        choices=CASE_STATUS_CHOICES,
        default=CASE_STATUS_NEW,
        db_index=True,
    )
    payment_state = models.CharField(
        'Состояние оплаты',
        max_length=20,
        choices=PAYMENT_STATE_CHOICES,
        default=PAYMENT_STATE_UNPAID,
        db_index=True,
    )
    fulfillment_status = models.CharField(
        'Состояние обеспечения',
        max_length=32,
        choices=FULFILLMENT_STATUS_CHOICES,
        default=FULFILLMENT_STATUS_NOT_RESERVED,
        db_index=True,
    )
    delivery_status = models.CharField(
        'Состояние доставки',
        max_length=20,
        choices=DELIVERY_STATUS_CHOICES,
        default=DELIVERY_STATUS_NOT_REQUIRED,
        db_index=True,
    )
    documents_status = models.CharField(
        'Состояние документов',
        max_length=20,
        choices=DOCUMENTS_STATUS_CHOICES,
        default=DOCUMENTS_STATUS_NOT_REQUIRED,
        db_index=True,
    )
    next_step_code = models.CharField('Следующий шаг', max_length=32, blank=True, db_index=True)
    next_step_reason_snapshot = models.TextField('Причина следующего шага', blank=True)
    next_step_source = models.CharField(
        'Источник следующего шага',
        max_length=20,
        choices=NEXT_STEP_SOURCE_CHOICES,
        default=NEXT_STEP_SOURCE_SYSTEM,
        db_index=True,
    )
    next_step_overridden_at = models.DateTimeField('Переопределен следующий шаг', null=True, blank=True)
    next_step_overridden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='overridden_manager_deals',
        verbose_name='Переопределил следующий шаг',
    )
    sla_due_at = models.DateTimeField('SLA до', null=True, blank=True, db_index=True)
    sla_breached_at = models.DateTimeField('SLA нарушен', null=True, blank=True, db_index=True)
    problem_flags = models.JSONField('Проблемные флаги', default=list, blank=True)
    last_activity_at = models.DateTimeField('Последняя активность', null=True, blank=True, db_index=True)
    buyer_type = models.CharField('Тип покупателя', max_length=20, choices=BUYER_TYPE_CHOICES, db_index=True)
    customer_source = models.CharField(
        'Источник клиента',
        max_length=20,
        choices=CUSTOMER_SOURCE_CHOICES,
        default=SOURCE_WEBSITE,
    )
    bitrix_deal_id = models.CharField('ID сделки Bitrix', max_length=64, blank=True, db_index=True)
    bitrix_deal_url = models.URLField('Ссылка на сделку Bitrix', blank=True, max_length=500)
    deal_created_at = models.DateTimeField('Дата создания сделки', default=timezone.now, db_index=True)
    individual_full_name = models.CharField('ФИО физ. лица', max_length=255, blank=True)
    individual_phone = models.CharField('Телефон физ. лица', max_length=40, blank=True)
    individual_additional_phone = models.CharField('Доп. телефон физ. лица', max_length=40, blank=True)
    individual_city = models.CharField('Город физ. лица', max_length=120, blank=True)
    individual_pickup_address = models.TextField('Адрес ПВЗ СДЭК физ. лица', blank=True)
    individual_delivery_address = models.TextField('Адрес доставки физ. лица', blank=True)
    individual_messenger = models.CharField('Telegram / WhatsApp', max_length=120, blank=True)
    individual_comment = models.TextField('Комментарий по физ. лицу', blank=True)
    business_company_name = models.CharField('Название компании', max_length=255, blank=True)
    business_inn = models.CharField('ИНН', max_length=32, blank=True)
    business_kpp = models.CharField('КПП', max_length=32, blank=True)
    business_ogrn = models.CharField('ОГРН / ОГРНИП', max_length=32, blank=True)
    business_legal_address = models.TextField('Юридический адрес', blank=True)
    business_contact_person = models.CharField('Контактное лицо', max_length=255, blank=True)
    business_phone = models.CharField('Телефон юр. лица', max_length=40, blank=True)
    business_telegram = models.CharField('Telegram юр. лица', max_length=120, blank=True)
    business_whatsapp = models.CharField('WhatsApp юр. лица', max_length=120, blank=True)
    business_email = models.EmailField('Email юр. лица', blank=True)
    business_city = models.CharField('Город юр. лица', max_length=120, blank=True)
    business_delivery_address = models.TextField('Адрес доставки / ПВЗ юр. лица', blank=True)
    business_checking_account = models.CharField('Номер счёта', max_length=64, blank=True)
    business_bank_name = models.CharField('Банк', max_length=255, blank=True)
    business_bik = models.CharField('БИК', max_length=20, blank=True)
    business_correspondent_account = models.CharField('Корр. счёт банка', max_length=64, blank=True)
    business_comment = models.TextField('Комментарий по юр. лицу', blank=True)
    customer_request = models.TextField('Что хочет клиент', blank=True)
    customer_deadline = models.DateField('Дедлайн клиента', null=True, blank=True)
    customer_request_comment = models.TextField('Комментарий клиента', blank=True)
    delivery_method = models.CharField(
        'Способ доставки',
        max_length=20,
        choices=DELIVERY_METHOD_CHOICES,
        default=DELIVERY_CDEK_PVZ,
    )
    delivery_provider_name = models.CharField('Перевозчик / провайдер доставки', max_length=255, blank=True)
    delivery_from_city = models.CharField('Город отправки', max_length=120, blank=True)
    delivery_to_city = models.CharField('Город получения', max_length=120, blank=True)
    delivery_pickup_address = models.TextField('Адрес ПВЗ СДЭК', blank=True)
    delivery_full_address = models.TextField('Полный адрес доставки', blank=True)
    delivery_payer = models.CharField(
        'Кто оплачивает доставку',
        max_length=20,
        choices=DELIVERY_PAYER_CHOICES,
        default=DELIVERY_PAYER_CLIENT,
    )
    tracking_number = models.CharField('Номер заказа / отправления', max_length=120, blank=True)
    shipping_comment = models.TextField('Комментарий по отправке', blank=True)
    shipment_status = models.CharField(
        'Статус отправки',
        max_length=20,
        choices=SHIPMENT_STATUS_CHOICES,
        default=SHIPMENT_DRAFT,
    )
    shipped_at = models.DateField('Дата отправки', null=True, blank=True)
    planned_receipt_at = models.DateField('Плановая дата получения', null=True, blank=True)
    prepayment_required_amount = models.DecimalField('Требуемая предоплата', max_digits=12, decimal_places=2, default=Decimal('0'))
    prepayment_amount = models.DecimalField('Оплачено клиентом', max_digits=12, decimal_places=2, default=Decimal('0'))
    last_payment_at = models.DateTimeField('Дата последнего платежа', null=True, blank=True)
    stock_warehouse = models.ForeignKey(
        'manager_portal.Warehouse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_deals_from_stock',
        verbose_name='Склад',
    )
    primary_reservation = models.OneToOneField(
        'manager_portal.Reservation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='primary_for_deal',
        verbose_name='Основной резерв',
    )
    reserve_created_at = models.DateTimeField('Резерв создан', null=True, blank=True)
    procurement_origin = models.CharField('Откуда заказываем', max_length=255, blank=True)
    supplier_name = models.CharField('Поставщик', max_length=255, blank=True)
    supplier_agent = models.CharField('Агент', max_length=255, blank=True)
    planned_purchase_date = models.DateField('Плановая дата закупки', null=True, blank=True)
    expected_arrival_date = models.DateField('Ожидаемая дата поступления', null=True, blank=True)
    expected_customer_ship_date = models.DateField('Ожидаемая дата отправки клиенту', null=True, blank=True)
    avito_listing_url = models.URLField('Ссылка на объявление Avito', blank=True)
    avito_listing_id = models.CharField('ID объявления Avito', max_length=120, blank=True)
    avito_listing_title = models.CharField('Название объявления', max_length=255, blank=True)
    avito_contact_channel = models.CharField('Канал обращения', max_length=120, blank=True)
    avito_list_price = models.DecimalField('Цена в объявлении', max_digits=12, decimal_places=2, default=Decimal('0'))
    avito_final_price = models.DecimalField('Финальная цена продажи', max_digits=12, decimal_places=2, default=Decimal('0'))
    avito_commission = models.DecimalField('Комиссия Avito', max_digits=12, decimal_places=2, default=Decimal('0'))
    returned_to_stock_at = models.DateTimeField('Возврат на склад подтвержден', null=True, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Сделка менеджера'
        verbose_name_plural = 'Сделки менеджеров'
        ordering = ['-deal_created_at', '-id']

    def __str__(self):
        return self.code or f'Сделка #{self.order_id}'

    @property
    def identity_code(self):
        return self.code or f'DEAL-{_year_from_value(self.deal_created_at)}-{self.pk or 0:0{ROOT_IDENTITY_WIDTH}d}'

    def main_product_label(self):
        order_item = self.order.items.select_related('product', 'variant').first()
        if not order_item:
            return ''
        return _join_identity_title(order_item.resolved_product_name, order_item.resolved_variant_name)

    def generated_title(self):
        return _join_identity_title(
            self.get_deal_type_display(),
            self.customer_name,
            self.main_product_label(),
            self.customer_city or self.delivery_to_city or getattr(self.order, 'city_text', ''),
        )

    def generated_short_label(self):
        return ' / '.join(part for part in [self.customer_name, self.main_product_label()] if part)

    def populate_identity_fields(self):
        if not self.code:
            year = _year_from_value(self.deal_created_at or self.created_at)
            sequence = _next_identity_sequence(self.__class__, 'code', f'DEAL-{year}-', exclude_pk=self.pk)
            self.code = _formatted_identity('DEAL', year, sequence)
        if not self.title:
            self.title = self.generated_title()
        if not self.short_label:
            self.short_label = self.generated_short_label()

    @classmethod
    def uses_avito_workflow(cls, deal_type, customer_source=''):
        return deal_type == cls.DEAL_AVITO or customer_source == cls.SOURCE_AVITO

    @classmethod
    def allowed_status_choices(cls, deal_type, customer_source=''):
        workflow_type = cls.DEAL_AVITO if cls.uses_avito_workflow(deal_type, customer_source) else deal_type
        allowed_codes = cls.DEAL_STATUS_CHOICES_BY_TYPE.get(workflow_type, [])
        labels = dict(cls.DEAL_STATUS_CHOICES)
        return [(code, labels[code]) for code in allowed_codes if code in labels]

    @classmethod
    def order_status_for_deal_status(cls, deal_status):
        if deal_status in {cls.DEAL_STATUS_CANCELLED, cls.DEAL_STATUS_RETURNED}:
            return 'cancelled'
        if deal_status in {cls.DEAL_STATUS_SHIPPED, cls.DEAL_STATUS_NEW_ITEM_SHIPPED}:
            return 'shipping'
        if deal_status in {cls.DEAL_STATUS_COMPLETED, cls.DEAL_STATUS_RECEIVED_BY_CUSTOMER}:
            return 'done'
        return 'new'

    @classmethod
    def next_step_label_for(cls, next_step_code):
        return cls.NEXT_STEP_LABELS.get(next_step_code, next_step_code or '—')

    @property
    def next_step_label(self):
        return self.next_step_label_for(self.next_step_code)

    @property
    def problem_flag_labels(self):
        return [self.PROBLEM_FLAG_LABELS.get(flag, flag) for flag in (self.problem_flags or [])]

    @property
    def has_problems(self):
        return bool(self.problem_flags)

    @property
    def reservation(self):
        return self.primary_reservation

    @reservation.setter
    def reservation(self, value):
        self.primary_reservation = value

    @property
    def customer_name(self):
        if self.buyer_type == self.BUYER_BUSINESS:
            return self.business_company_name or self.business_contact_person
        return self.individual_full_name

    @property
    def customer_phone(self):
        if self.buyer_type == self.BUYER_BUSINESS:
            return self.business_phone
        return self.individual_phone

    @property
    def customer_city(self):
        if self.buyer_type == self.BUYER_BUSINESS:
            return self.business_city
        return self.individual_city

    @property
    def is_avito(self):
        return self.uses_avito_workflow(self.deal_type, self.customer_source)

    @property
    def requires_documents(self):
        return not self.is_avito and bool(
            self.buyer_type == self.BUYER_BUSINESS
            or self.order.payment_method in {
                self.order.PAYMENT_METHOD_MANAGER_PAYMENT,
                self.order.PAYMENT_METHOD_INVOICE,
            }
        )

    @property
    def requires_delivery_workflow(self):
        return not self.is_avito and self.delivery_method != self.DELIVERY_PICKUP

    @property
    def avito_return_pending(self):
        return self.is_avito and self.deal_status == self.DEAL_STATUS_RETURNED and self.returned_to_stock_at is None

    @property
    def items_gross_total(self):
        return sum((item.price * item.quantity for item in self.order.items.all()), Decimal('0'))

    @property
    def items_discount_total(self):
        return sum((item.discount_total for item in self.order.items.all()), Decimal('0'))

    @property
    def goods_total(self):
        return sum((item.subtotal for item in self.order.items.all()), Decimal('0'))

    @property
    def planned_outgoing_cost_total(self):
        return sum((item.planned_cost_total for item in self.order.items.all()), Decimal('0'))

    @property
    def actual_outgoing_cost_total(self):
        return sum((item.actual_cost_total for item in self.order.items.all()), Decimal('0'))

    @property
    def outgoing_cost_total(self):
        return sum((item.effective_cost_total for item in self.order.items.all()), Decimal('0'))

    @property
    def trade_in_value(self):
        return sum((item.effective_estimate for item in self.trade_in_items.all()), Decimal('0'))

    @property
    def grand_total(self):
        return self.goods_total - self.trade_in_value + self.order.delivery_cost

    @property
    def balance_due(self):
        return self.grand_total - self.prepayment_amount

    @property
    def amount_paid(self):
        return self.prepayment_amount

    @property
    def expected_margin(self):
        return self.goods_total - self.planned_outgoing_cost_total - self.avito_commission - self.trade_in_value

    @property
    def actual_margin(self):
        return self.goods_total - self.actual_outgoing_cost_total - self.avito_commission - self.trade_in_value

    @property
    def overpayment_to_client(self):
        balance = self.balance_due
        if balance < 0:
            return abs(balance)
        return Decimal('0')

    def clean(self):
        allowed_statuses = {
            code for code, _label in self.allowed_status_choices(self.deal_type, self.customer_source)
        }
        if self.deal_status and self.deal_status not in allowed_statuses:
            raise ValidationError({'deal_status': 'Статус не подходит для выбранного типа сделки.'})
        if (
            self.deal_type == self.DEAL_SALE_FROM_STOCK
            and not self.stock_warehouse_id
            and self.deal_status
            not in {
                self.DEAL_STATUS_NEW,
                self.DEAL_STATUS_CANCELLED,
            }
        ):
            raise ValidationError({'stock_warehouse': 'Для продажи из наличия выберите склад.'})
        if self.deal_type == self.DEAL_SALE_ON_REQUEST and self.deal_status == self.DEAL_STATUS_SUPPLIER_ORDERED:
            if self.prepayment_required_amount > 0 and self.prepayment_amount < self.prepayment_required_amount:
                raise ValidationError({'prepayment_amount': 'Нельзя размещать заказ у поставщика без требуемой предоплаты.'})
        if self.deal_type == self.DEAL_SALE_ON_REQUEST and self.deal_status == self.DEAL_STATUS_READY_TO_SHIP:
            if self.shipment_status not in {self.SHIPMENT_PENDING, self.SHIPMENT_DRAFT} and not self.expected_arrival_date:
                raise ValidationError({'deal_status': 'Товар должен быть получен до подготовки к отправке.'})
        if self.deal_type == self.DEAL_AVITO and self.customer_source == self.SOURCE_AVITO and not self.avito_listing_url:
            raise ValidationError({'avito_listing_url': 'Для сделки Avito укажите ссылку на объявление.'})

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        _extend_update_fields(kwargs, 'code', 'title', 'short_label')
        super().save(*args, **kwargs)


class DealActivity(models.Model):
    SOURCE_SYSTEM = 'system'
    SOURCE_USER = 'user'
    SOURCE_CHOICES = [
        (SOURCE_SYSTEM, 'Система'),
        (SOURCE_USER, 'Пользователь'),
    ]

    manager_deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.CASCADE,
        related_name='activities',
        verbose_name='Сделка',
    )
    event_type = models.CharField('Тип события', max_length=80, db_index=True)
    source = models.CharField('Источник', max_length=20, choices=SOURCE_CHOICES, default=SOURCE_SYSTEM, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_deal_activities',
        verbose_name='Автор',
    )
    payload = models.JSONField('Payload', default=dict, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Активность сделки'
        verbose_name_plural = 'Активности сделки'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.manager_deal_id}: {self.event_type}'


class ManagerDealParticipant(models.Model):
    ROLE_ANSWERED = 'answered'
    ROLE_SHIPPED = 'shipped'
    ROLE_ITEM_OWNER = 'item_owner'
    ROLE_PLANNED_PROFIT_SHARE = 'planned_profit_share'
    ROLE_CHOICES = [
        (ROLE_ANSWERED, 'Ответил'),
        (ROLE_SHIPPED, 'Отправил'),
        (ROLE_ITEM_OWNER, 'Владелец позиции'),
        (ROLE_PLANNED_PROFIT_SHARE, 'Плановое распределение маржи'),
    ]

    manager_deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.CASCADE,
        related_name='participants',
        verbose_name='Сделка',
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_deal_participants',
        verbose_name='Строка заказа',
    )
    person_alias = models.ForeignKey(
        ManagerPersonAlias,
        on_delete=models.PROTECT,
        related_name='deal_participations',
        verbose_name='Участник',
    )
    role = models.CharField('Роль', max_length=32, choices=ROLE_CHOICES, db_index=True)
    amount = models.DecimalField('Сумма', max_digits=14, decimal_places=2, null=True, blank=True)
    quantity_basis = models.PositiveIntegerField('База по количеству', null=True, blank=True)
    note = models.TextField('Примечание', blank=True)
    source_payload = models.JSONField('Payload источника', default=dict, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Участник / начисление сделки'
        verbose_name_plural = 'Участники / начисления сделки'
        ordering = ['manager_deal_id', 'role', 'id']

    def __str__(self):
        return f'{self.manager_deal_id}: {self.person_alias.display_name} ({self.role})'


class DealSavedView(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='manager_deal_saved_views',
        verbose_name='Владелец',
    )
    name = models.CharField('Название', max_length=120)
    query_string = models.TextField('Query string', blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Сохраненный вид сделок'
        verbose_name_plural = 'Сохраненные виды сделок'
        ordering = ['name', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name'],
                name='manager_deal_saved_view_owner_name_unique',
            ),
        ]

    def __str__(self):
        return self.name


class TradeInItem(models.Model):
    deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.CASCADE,
        related_name='trade_in_items',
        verbose_name='Сделка',
    )
    device_type = models.CharField('Тип устройства', max_length=120)
    model_name = models.CharField('Модель', max_length=255)
    version = models.CharField('Версия', max_length=120, blank=True)
    kit_description = models.TextField('Комплектация', blank=True)
    condition = models.CharField('Состояние', max_length=120)
    is_working = models.BooleanField('Работает', default=True)
    has_box = models.BooleanField('Есть коробка', default=False)
    has_controllers = models.BooleanField('Есть контроллеры', default=False)
    has_accessories = models.BooleanField('Есть ремешок / маска / доп. аксессуары', default=False)
    defects = models.TextField('Дефекты', blank=True)
    photo = models.ImageField('Фото устройства', upload_to='manager/tradein/', blank=True)
    preliminary_estimate = models.DecimalField('Предварительная оценка', max_digits=12, decimal_places=2, default=Decimal('0'))
    final_estimate = models.DecimalField('Финальная оценка', max_digits=12, decimal_places=2, default=Decimal('0'))
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Позиция трейд-ин'
        verbose_name_plural = 'Позиции трейд-ин'
        ordering = ['id']

    def __str__(self):
        return f'{self.model_name} ({self.deal_id})'

    @property
    def effective_estimate(self):
        return self.final_estimate if self.final_estimate > 0 else self.preliminary_estimate


class FinanceDealType(models.Model):
    name = models.CharField('Тип сделки', max_length=255, unique=True)
    partner_share = models.DecimalField('Доля партнера', max_digits=5, decimal_places=4, default=Decimal('0'))
    is_active = models.BooleanField('Активен', default=True, db_index=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: тип сделки'
        verbose_name_plural = 'Финансы: типы сделок'
        ordering = ['name', 'id']

    def __str__(self):
        return self.name


class FinanceDistributionScheme(models.Model):
    name = models.CharField('Название схемы', max_length=255)
    version = models.PositiveIntegerField('Версия', default=1)
    is_active = models.BooleanField('Активна', default=False, db_index=True)
    description = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлена', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: схема распределения'
        verbose_name_plural = 'Финансы: схемы распределения'
        ordering = ['name', '-version', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'version'],
                name='manager_finance_distribution_scheme_name_version_unique',
            ),
        ]

    def __str__(self):
        return f'{self.name} v{self.version}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_active:
            self.__class__.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)


class FinanceDistributionRule(models.Model):
    RULE_PERCENT_OWNER_MARGIN = 'percent_owner_margin'
    RULE_PERCENT_TOTAL_MARGIN = 'percent_total_margin'
    RULE_PERCENT_REMAINDER_AFTER_RULE = 'percent_remainder_after_rule'
    RULE_EQUAL_SPLIT_REMAINDER = 'equal_split_remainder'
    RULE_TYPE_CHOICES = [
        (RULE_PERCENT_OWNER_MARGIN, 'Процент от маржи владельца строк'),
        (RULE_PERCENT_TOTAL_MARGIN, 'Процент от общей маржи'),
        (RULE_PERCENT_REMAINDER_AFTER_RULE, 'Процент от остатка после правила'),
        (RULE_EQUAL_SPLIT_REMAINDER, 'Равная доля остатка'),
    ]

    scheme = models.ForeignKey(
        FinanceDistributionScheme,
        on_delete=models.CASCADE,
        related_name='rules',
        verbose_name='Схема',
    )
    participant_alias = models.ForeignKey(
        ManagerPersonAlias,
        on_delete=models.PROTECT,
        related_name='finance_distribution_rules',
        verbose_name='Участник',
    )
    position = models.PositiveIntegerField('Порядок', default=100)
    rule_type = models.CharField('Тип правила', max_length=40, choices=RULE_TYPE_CHOICES, db_index=True)
    percent = models.DecimalField('Процент / коэффициент', max_digits=7, decimal_places=4, default=Decimal('0'))
    owner_alias = models.ForeignKey(
        ManagerPersonAlias,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='finance_distribution_owner_rules',
        verbose_name='Владелец строк',
    )
    reference_rule = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dependent_rules',
        verbose_name='Опорное правило',
    )
    note = models.CharField('Комментарий', max_length=255, blank=True)
    is_active = models.BooleanField('Активно', default=True, db_index=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: правило распределения'
        verbose_name_plural = 'Финансы: правила распределения'
        ordering = ['scheme_id', 'position', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['scheme', 'participant_alias'],
                name='manager_finance_distribution_rule_scheme_participant_unique',
            ),
        ]

    def __str__(self):
        return f'{self.scheme} · {self.participant_alias}'

    def clean(self):
        super().clean()
        if self.rule_type == self.RULE_PERCENT_OWNER_MARGIN and not self.owner_alias_id:
            raise ValidationError({'owner_alias': 'Укажите владельца строк для этого правила.'})
        if self.rule_type == self.RULE_PERCENT_REMAINDER_AFTER_RULE and not self.reference_rule_id:
            raise ValidationError({'reference_rule': 'Укажите правило, после которого считается остаток.'})
        if self.reference_rule_id and self.pk and self.reference_rule_id == self.pk:
            raise ValidationError({'reference_rule': 'Правило не может ссылаться само на себя.'})
        if self.reference_rule_id and self.reference_rule and self.reference_rule.scheme_id != self.scheme_id:
            raise ValidationError({'reference_rule': 'Опорное правило должно принадлежать той же схеме.'})
        if self.rule_type == self.RULE_EQUAL_SPLIT_REMAINDER and self.percent not in {None, Decimal('0'), Decimal('0.0000')}:
            raise ValidationError({'percent': 'Для равного деления остатка процент не используется.'})


class FinanceExpenseCategory(models.Model):
    SIDE_OURS = 'ours'
    SIDE_PARTNER = 'partner'
    SIDE_CHOICES = [
        (SIDE_OURS, 'Наши'),
        (SIDE_PARTNER, 'Партнера'),
    ]

    expense_side = models.CharField('Сторона расхода', max_length=20, choices=SIDE_CHOICES, db_index=True)
    name = models.CharField('Категория', max_length=255)
    is_active = models.BooleanField('Активна', default=True, db_index=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлена', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: категория расхода'
        verbose_name_plural = 'Финансы: категории расходов'
        ordering = ['expense_side', 'name', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['expense_side', 'name'],
                name='manager_finance_expense_category_side_name_unique',
            ),
        ]

    def __str__(self):
        return f'{self.get_expense_side_display()}: {self.name}'


class FinanceDeal(models.Model):
    code = models.CharField('Код финкейса', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    manager_deal = models.OneToOneField(
        ManagerDeal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_deal',
        verbose_name='Связанная сделка',
    )
    responsible_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_finance_deals',
        verbose_name='Ответственный менеджер',
    )
    linked_document = models.ForeignKey(
        'manager_portal.ContractDocument',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_deals',
        verbose_name='Связанный документ',
    )
    distribution_scheme = models.ForeignKey(
        FinanceDistributionScheme,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_deals',
        verbose_name='Схема распределения',
    )
    date = models.DateField('Дата сделки', default=timezone.localdate, db_index=True)
    contract_number = models.CharField('Договор / клиент', max_length=255, blank=True)
    deal_type = models.ForeignKey(
        FinanceDealType,
        on_delete=models.PROTECT,
        related_name='deals',
        verbose_name='Тип сделки',
    )
    payment_method = models.CharField('Способ оплаты', max_length=32, blank=True)
    payment_state = models.CharField('Платежный статус заказа', max_length=32, blank=True)
    revenue = models.DecimalField('Выручка', max_digits=14, decimal_places=2, default=Decimal('0'))
    cost_of_goods = models.DecimalField(
        'Закуп / себестоимость',
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        db_column='cost_price',
    )
    direct_expenses = models.DecimalField('Прямые расходы', max_digits=14, decimal_places=2, default=Decimal('0'))
    manager_bonus = models.DecimalField('Бонус менеджера', max_digits=14, decimal_places=2, default=Decimal('0'))
    distributable_profit = models.DecimalField(
        'Распределяемая прибыль',
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        db_column='margin',
    )
    partner_share_amount = models.DecimalField('Доля партнера', max_digits=14, decimal_places=2, default=Decimal('0'))
    distribution_scheme_name_snapshot = models.CharField('Название схемы распределения', max_length=255, blank=True)
    distribution_scheme_version_snapshot = models.PositiveIntegerField('Версия схемы распределения', null=True, blank=True)
    expected_distributable_profit_snapshot = models.DecimalField(
        'Ожидаемая распределяемая прибыль сделки',
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        db_column='expected_margin_snapshot',
    )
    snapshot_data = models.JSONField('Снимок финкейса', default=dict, blank=True)
    comment = models.TextField('Комментарий', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_finance_deals',
        verbose_name='Создал',
    )
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлена', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: сделка'
        verbose_name_plural = 'Финансы: сделки'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.code or self.contract_number or f'Сделка #{self.pk}'

    def populate_identity_fields(self):
        if self.manager_deal_id and not self.manager_deal.code:
            self.manager_deal.save()
        if not self.code:
            if self.manager_deal_id and self.manager_deal.code:
                year, sequence = _split_identity_code(self.manager_deal.code)
                if year and sequence:
                    self.code = f'FIN-{year}-{sequence}'
            if not self.code:
                year = _year_from_value(self.date)
                sequence = _next_identity_sequence(self.__class__, 'code', f'FIN-{year}-', exclude_pk=self.pk)
                self.code = _formatted_identity('FIN', year, sequence)
        if not self.title:
            self.title = _join_identity_title('Финансы', self.manager_deal.customer_name if self.manager_deal_id else '', self.manager_deal.code if self.manager_deal_id else '')
        if not self.short_label:
            self.short_label = ' / '.join(part for part in [self.manager_deal.customer_name if self.manager_deal_id else '', 'Финансы'] if part)

    def recalculate(self):
        revenue = Decimal(self.revenue or 0)
        cost_of_goods = Decimal(self.cost_of_goods or 0)
        direct_expenses = Decimal(self.direct_expenses or 0)
        manager_bonus = Decimal(self.manager_bonus or 0)
        self.distributable_profit = revenue - cost_of_goods - direct_expenses - manager_bonus
        if not self.distribution_scheme_id:
            share = Decimal(self.deal_type.partner_share if self.deal_type_id else 0)
            self.partner_share_amount = self.distributable_profit * share

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        self.recalculate()
        self.populate_identity_fields()
        if self.linked_document_id and not self.contract_number:
            self.contract_number = self.linked_document.number or self.linked_document.title or ''
        if self.manager_deal_id and not self.contract_number:
            self.contract_number = f'Сделка #{self.manager_deal.order_id}'
        if self.distribution_scheme_id:
            self.distribution_scheme_name_snapshot = self.distribution_scheme.name
            self.distribution_scheme_version_snapshot = self.distribution_scheme.version
        if update_fields is not None:
            normalized_fields = set(update_fields)
            normalized_fields.update(
                {
                    'distributable_profit',
                    'partner_share_amount',
                    'code',
                    'title',
                    'short_label',
                    'contract_number',
                    'distribution_scheme_name_snapshot',
                    'distribution_scheme_version_snapshot',
                }
            )
            kwargs['update_fields'] = list(normalized_fields)
        super().save(*args, **kwargs)

    @property
    def expense_total(self):
        return sum((expense.amount for expense in self.expenses.all()), Decimal('0'))

    def _base_lines(self):
        return self.lines.filter(replacement_of__isnull=True)

    @property
    def planned_cost_total(self):
        return sum((line.planned_cost_total for line in self._base_lines()), Decimal('0'))

    @property
    def actual_cost_total(self):
        return sum((line.actual_cost_total for line in self._base_lines()), Decimal('0'))

    @property
    def gross_profit(self):
        return Decimal(self.revenue or 0) - Decimal(self.cost_of_goods or 0)

    @property
    def planned_distributable_profit_total(self):
        revenue = sum((line.sale_total for line in self._base_lines()), Decimal('0')) or Decimal(self.revenue or 0)
        return revenue - self.planned_cost_total - Decimal(self.direct_expenses or 0) - Decimal(self.manager_bonus or 0)

    @property
    def actual_distributable_profit_total(self):
        revenue = sum((line.sale_total for line in self._base_lines()), Decimal('0')) or Decimal(self.revenue or 0)
        return revenue - self.actual_cost_total - Decimal(self.direct_expenses or 0) - Decimal(self.manager_bonus or 0)

    @property
    def cost_price(self):
        return self.cost_of_goods

    @cost_price.setter
    def cost_price(self, value):
        self.cost_of_goods = value

    @property
    def margin(self):
        return self.distributable_profit

    @margin.setter
    def margin(self, value):
        self.distributable_profit = value

    @property
    def expected_margin_snapshot(self):
        return self.expected_distributable_profit_snapshot

    @expected_margin_snapshot.setter
    def expected_margin_snapshot(self, value):
        self.expected_distributable_profit_snapshot = value

    @property
    def planned_margin_total(self):
        return self.planned_distributable_profit_total

    @property
    def actual_margin_total(self):
        return self.actual_distributable_profit_total


class FinanceDealLine(models.Model):
    LINE_TYPE_CATALOG = 'catalog'
    LINE_TYPE_CUSTOM = 'custom'
    LINE_TYPE_CHOICES = [
        (LINE_TYPE_CATALOG, 'Каталог'),
        (LINE_TYPE_CUSTOM, 'Произвольный товар'),
    ]

    COST_STATUS_NONE = 'none'
    COST_STATUS_PLANNED = 'planned'
    COST_STATUS_ACTUAL = 'actual'
    COST_STATUS_CHOICES = [
        (COST_STATUS_NONE, 'Нет'),
        (COST_STATUS_PLANNED, 'План'),
        (COST_STATUS_ACTUAL, 'Факт'),
    ]

    finance_deal = models.ForeignKey(
        FinanceDeal,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name='Финансовая сделка',
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_deal_lines',
        verbose_name='Строка заказа',
    )
    replacement_of = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replacement_lines',
        verbose_name='Замена для строки',
    )
    line_type = models.CharField(
        'Тип строки',
        max_length=16,
        choices=LINE_TYPE_CHOICES,
        default=LINE_TYPE_CATALOG,
        db_index=True,
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_finance_lines',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_finance_lines',
        verbose_name='Вариант',
    )
    sort_order = models.PositiveIntegerField('Порядок', default=0)
    product_name = models.CharField('Товар', max_length=255)
    custom_sku = models.CharField('Произвольный SKU', max_length=64, blank=True)
    quantity = models.PositiveIntegerField('Количество', default=1)
    unit_cost_price = models.DecimalField('Себестоимость за единицу', max_digits=14, decimal_places=2, default=Decimal('0'))
    unit_sale_price = models.DecimalField('Продажа за единицу', max_digits=14, decimal_places=2, default=Decimal('0'))
    planned_unit_cost = models.DecimalField('Плановая себестоимость за единицу', max_digits=14, decimal_places=2, default=Decimal('0'))
    actual_unit_cost = models.DecimalField('Фактическая себестоимость за единицу', max_digits=14, decimal_places=2, default=Decimal('0'))
    cost_status = models.CharField(
        'Статус себестоимости',
        max_length=16,
        choices=COST_STATUS_CHOICES,
        default=COST_STATUS_NONE,
        db_index=True,
    )
    owner_alias = models.ForeignKey(
        ManagerPersonAlias,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_deal_lines',
        verbose_name='Владелец строки',
    )
    line_status = models.CharField('Статус', max_length=120, blank=True)
    delivery_status = models.CharField('Доставка', max_length=120, blank=True)
    source_payload = models.JSONField('Payload источника', default=dict, blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлена', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: строка сделки'
        verbose_name_plural = 'Финансы: строки сделки'
        ordering = ['sort_order', 'id']
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(line_type='catalog')
                        & Q(product__isnull=False)
                        & ~Q(product_name='')
                        & Q(custom_sku='')
                    )
                    | (
                        Q(line_type='custom')
                        & Q(product__isnull=True)
                        & Q(variant__isnull=True)
                        & ~Q(product_name='')
                    )
                ),
                name='finance_line_line_type_integrity',
            ),
            models.CheckConstraint(
                condition=Q(planned_unit_cost__gte=0),
                name='finance_line_planned_unit_cost_gte_zero',
            ),
            models.CheckConstraint(
                condition=Q(actual_unit_cost__gte=0),
                name='finance_line_actual_unit_cost_gte_zero',
            ),
        ]

    def __str__(self):
        return f'{self.finance_deal_id}: {self.product_name}'

    def save(self, *args, **kwargs):
        if self.order_item_id and not self.product_name:
            self.product_name = self.order_item.resolved_product_name
        if self.order_item_id and not self.product_id:
            self.product = self.order_item.product
            self.variant = self.order_item.variant
            self.line_type = self.order_item.line_type
            self.custom_sku = self.order_item.custom_sku
        if self.product_id:
            self.line_type = self.LINE_TYPE_CATALOG
            if not (self.product_name or '').strip():
                self.product_name = self.product.name
        else:
            self.line_type = self.LINE_TYPE_CUSTOM
            self.variant = None
        if self.planned_unit_cost in (None, Decimal('0')) and self.unit_cost_price:
            self.planned_unit_cost = self.unit_cost_price
        if self.actual_unit_cost and self.actual_unit_cost > 0:
            self.cost_status = self.COST_STATUS_ACTUAL
        elif self.planned_unit_cost and self.planned_unit_cost > 0 and self.cost_status == self.COST_STATUS_NONE:
            self.cost_status = self.COST_STATUS_PLANNED
        self.unit_cost_price = self.effective_unit_cost
        super().save(*args, **kwargs)

    @property
    def gross_profit_per_unit(self):
        return Decimal(self.unit_sale_price or 0) - self.effective_unit_cost

    @property
    def gross_profit_total(self):
        return self.sale_total - self.cost_total

    @property
    def sale_total(self):
        if self.order_item_id:
            return Decimal(self.unit_sale_price or 0) * Decimal(self.order_item.active_quantity)
        return Decimal(self.unit_sale_price or 0) * Decimal(self.quantity or 0)

    @property
    def actual_sale_total(self):
        if self.order_item_id:
            return Decimal(self.unit_sale_price or 0) * Decimal(self.order_item.shipped_quantity)
        return Decimal('0')

    @property
    def cost_total(self):
        if self.order_item_id:
            return self.effective_unit_cost * Decimal(self.order_item.active_quantity)
        return self.effective_unit_cost * Decimal(self.quantity or 0)

    @property
    def effective_unit_cost(self):
        if self.cost_status == self.COST_STATUS_ACTUAL and Decimal(self.actual_unit_cost or 0) > 0:
            return Decimal(self.actual_unit_cost or 0)
        if self.cost_status in {self.COST_STATUS_PLANNED, self.COST_STATUS_ACTUAL} and Decimal(self.planned_unit_cost or 0) > 0:
            return Decimal(self.planned_unit_cost or 0)
        return Decimal(self.unit_cost_price or 0)

    @property
    def planned_cost_total(self):
        if self.order_item_id:
            return Decimal(self.planned_unit_cost or 0) * Decimal(self.order_item.active_quantity)
        return Decimal(self.planned_unit_cost or 0) * Decimal(self.quantity or 0)

    @property
    def actual_cost_total(self):
        if self.order_item_id:
            return Decimal(self.actual_unit_cost or 0) * Decimal(self.order_item.shipped_quantity)
        return Decimal(self.actual_unit_cost or 0) * Decimal(self.quantity or 0)

    @property
    def planned_gross_profit_total(self):
        return self.sale_total - self.planned_cost_total

    @property
    def actual_gross_profit_total(self):
        return self.actual_sale_total - self.actual_cost_total

    @property
    def margin_per_unit(self):
        return self.gross_profit_per_unit

    @property
    def margin_total(self):
        return self.gross_profit_total

    @property
    def planned_margin_total(self):
        return self.planned_gross_profit_total

    @property
    def actual_margin_total(self):
        return self.actual_gross_profit_total


class FinanceDealShare(models.Model):
    finance_deal = models.ForeignKey(
        FinanceDeal,
        on_delete=models.CASCADE,
        related_name='shares',
        verbose_name='Финансовая сделка',
    )
    rule = models.ForeignKey(
        FinanceDistributionRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deal_shares',
        verbose_name='Правило',
    )
    participant_alias = models.ForeignKey(
        ManagerPersonAlias,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_deal_shares',
        verbose_name='Участник',
    )
    participant_name_snapshot = models.CharField('Имя участника', max_length=255)
    calculation_type = models.CharField('Тип расчета', max_length=40, blank=True)
    formula_label = models.CharField('Пояснение формулы', max_length=255, blank=True)
    base_amount = models.DecimalField('База расчета', max_digits=14, decimal_places=2, default=Decimal('0'))
    calculated_amount = models.DecimalField('Рассчитанная сумма', max_digits=14, decimal_places=2, default=Decimal('0'))
    final_amount = models.DecimalField('Итоговая сумма', max_digits=14, decimal_places=2, default=Decimal('0'))
    quantity_basis = models.PositiveIntegerField('База по количеству', null=True, blank=True)
    breakdown = models.JSONField('Расшифровка', default=dict, blank=True)
    is_manual_override = models.BooleanField('Ручная корректировка', default=False)
    manual_amount_override = models.DecimalField('Ручная сумма', max_digits=14, decimal_places=2, null=True, blank=True)
    rule_params_override = models.JSONField('Переопределение параметров правила', default=dict, blank=True)
    scheme_name_snapshot = models.CharField('Название схемы', max_length=255, blank=True)
    scheme_version_snapshot = models.PositiveIntegerField('Версия схемы', null=True, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: доля участника'
        verbose_name_plural = 'Финансы: доли участников'
        ordering = ['finance_deal_id', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['finance_deal', 'participant_alias'],
                condition=Q(participant_alias__isnull=False),
                name='manager_finance_deal_share_finance_deal_participant_unique',
            ),
        ]

    def __str__(self):
        return f'{self.finance_deal_id}: {self.participant_name_snapshot}'

    @property
    def effective_amount(self):
        if self.manual_amount_override is not None:
            return self.manual_amount_override
        return self.final_amount


class FinanceExpense(models.Model):
    code = models.CharField('Код расхода', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    SIDE_OURS = 'ours'
    SIDE_PARTNER = 'partner'
    SIDE_CHOICES = [
        (SIDE_OURS, 'Наши'),
        (SIDE_PARTNER, 'Партнера'),
    ]
    REFUND_POLICY_NON_REFUNDABLE = 'non_refundable'
    REFUND_POLICY_PROPORTIONAL = 'proportional_to_reversal'
    REFUND_POLICY_ON_FULL_REVERSAL = 'on_full_reversal'
    REFUND_POLICY_CHOICES = [
        (REFUND_POLICY_NON_REFUNDABLE, 'Не возвращается'),
        (REFUND_POLICY_PROPORTIONAL, 'Пропорционально развороту'),
        (REFUND_POLICY_ON_FULL_REVERSAL, 'Только при полном развороте'),
    ]

    WHO_PAID_OURS = 'Я (Из кассы бизнеса/свои)'
    WHO_PAID_PARTNER = 'Партнер (Свои деньги)'

    manager_deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_expenses',
        verbose_name='Связанная сделка',
    )
    expense_side = models.CharField('Сторона расхода', max_length=20, choices=SIDE_CHOICES, db_index=True)
    date = models.DateField('Дата', default=timezone.localdate, db_index=True)
    category = models.ForeignKey(
        FinanceExpenseCategory,
        on_delete=models.PROTECT,
        related_name='expenses',
        verbose_name='Категория',
    )
    amount = models.DecimalField('Сумма', max_digits=14, decimal_places=2)
    who_paid = models.CharField('Кто оплатил', max_length=255, blank=True)
    partner_expense_share = models.DecimalField('Доля партнера в расходе', max_digits=14, decimal_places=2, default=Decimal('0'))
    comment = models.TextField('Комментарий', blank=True)
    deal = models.ForeignKey(
        FinanceDeal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name='Сделка',
    )
    finance_line = models.ForeignKey(
        FinanceDealLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name='Строка сделки',
    )
    affects_direct_expenses = models.BooleanField(
        'Учитывать в прямых расходах',
        null=True,
        blank=True,
        default=None,
    )
    refund_policy = models.CharField(
        'Политика возврата',
        max_length=40,
        choices=REFUND_POLICY_CHOICES,
        default=REFUND_POLICY_NON_REFUNDABLE,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_finance_expenses',
        verbose_name='Создал',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Финансы: расход'
        verbose_name_plural = 'Финансы: расходы'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.code or f'{self.category.name}: {self.amount}'

    def populate_identity_fields(self):
        if not self.code:
            year = _year_from_value(self.date)
            sequence = _next_identity_sequence(self.__class__, 'code', f'EXP-{year}-', exclude_pk=self.pk)
            self.code = _formatted_identity('EXP', year, sequence)
        if not self.title:
            self.title = _join_identity_title('Расход', self.category.name if self.category_id else '', f'{self.amount}')
        if not self.short_label:
            self.short_label = ' / '.join(part for part in [self.category.name if self.category_id else 'Расход', f'{self.amount}'] if part)

    def clean(self):
        if self.category_id and self.expense_side and self.category.expense_side != self.expense_side:
            raise ValidationError({'category': 'Категория должна совпадать со стороной расхода.'})
        if self.finance_line_id and self.deal_id and self.finance_line.finance_deal_id != self.deal_id:
            raise ValidationError({'finance_line': 'Строка расхода должна принадлежать той же финансовой сделке.'})

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        if self.finance_line_id and not self.deal_id:
            self.deal = self.finance_line.finance_deal
        if self.deal_id and not self.manager_deal_id:
            self.manager_deal = self.deal.manager_deal
        if not self.who_paid:
            self.who_paid = self.WHO_PAID_PARTNER if self.expense_side == self.SIDE_PARTNER else self.WHO_PAID_OURS
        if self.affects_direct_expenses is None:
            self.affects_direct_expenses = self.expense_side == self.SIDE_OURS
        _extend_update_fields(
            kwargs,
            'code',
            'title',
            'short_label',
            'deal',
            'manager_deal',
            'who_paid',
            'affects_direct_expenses',
        )
        super().save(*args, **kwargs)


class FinanceDealAdjustment(models.Model):
    KIND_SHIPMENT_RETURN = 'shipment_return'
    KIND_SHIPMENT_CANCELLATION = 'shipment_cancellation'
    KIND_REPLACEMENT_REVERSAL = 'replacement_reversal'
    KIND_REPLACEMENT_ADDITION = 'replacement_addition'
    KIND_DIRECT_EXPENSE_REFUND = 'direct_expense_refund'
    KIND_MANUAL_CORRECTION = 'manual_correction'
    KIND_CHOICES = [
        (KIND_SHIPMENT_RETURN, 'Возврат после отгрузки'),
        (KIND_SHIPMENT_CANCELLATION, 'Отмена до отгрузки'),
        (KIND_REPLACEMENT_REVERSAL, 'Разворот заменяемой строки'),
        (KIND_REPLACEMENT_ADDITION, 'Добавление строки замены'),
        (KIND_DIRECT_EXPENSE_REFUND, 'Возврат прямого расхода'),
        (KIND_MANUAL_CORRECTION, 'Ручная корректировка'),
    ]

    finance_deal = models.ForeignKey(
        FinanceDeal,
        on_delete=models.CASCADE,
        related_name='adjustments',
        verbose_name='Финансовая сделка',
    )
    finance_line = models.ForeignKey(
        FinanceDealLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='adjustments',
        verbose_name='Строка сделки',
    )
    related_expense = models.ForeignKey(
        FinanceExpense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='adjustments',
        verbose_name='Связанный расход',
    )
    related_shipment = models.ForeignKey(
        'manager_portal.Shipment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_adjustments',
        verbose_name='Связанная отгрузка',
    )
    related_activity = models.ForeignKey(
        DealActivity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_adjustments',
        verbose_name='Связанное событие',
    )
    related_document = models.ForeignKey(
        'manager_portal.ContractDocument',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_adjustments',
        verbose_name='Связанный документ',
    )
    adjustment_kind = models.CharField('Тип корректировки', max_length=40, choices=KIND_CHOICES, db_index=True)
    reason_code = models.CharField('Причина', max_length=80, blank=True)
    quantity_delta = models.DecimalField('Изменение количества', max_digits=14, decimal_places=2, default=Decimal('0'))
    revenue_delta = models.DecimalField('Изменение выручки', max_digits=14, decimal_places=2, default=Decimal('0'))
    cost_of_goods_delta = models.DecimalField('Изменение себестоимости', max_digits=14, decimal_places=2, default=Decimal('0'))
    direct_expenses_delta = models.DecimalField('Изменение прямых расходов', max_digits=14, decimal_places=2, default=Decimal('0'))
    manager_bonus_delta = models.DecimalField('Изменение бонуса менеджера', max_digits=14, decimal_places=2, default=Decimal('0'))
    payload = models.JSONField('Payload', default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_finance_adjustments',
        verbose_name='Создал',
    )
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'Финансы: корректировка'
        verbose_name_plural = 'Финансы: корректировки'
        ordering = ['finance_deal_id', '-created_at', '-id']

    def __str__(self):
        return f'{self.finance_deal_id}: {self.adjustment_kind}'


class FinancePayout(models.Model):
    code = models.CharField('Код выплаты', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    manager_deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_payouts',
        verbose_name='Связанная сделка',
    )
    date = models.DateField('Дата', default=timezone.localdate, db_index=True)
    amount = models.DecimalField('Сумма', max_digits=14, decimal_places=2)
    comment = models.TextField('Комментарий', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_finance_payouts',
        verbose_name='Создал',
    )
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'Финансы: выплата'
        verbose_name_plural = 'Финансы: выплаты'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.code or f'Выплата #{self.pk}'

    def populate_identity_fields(self):
        if not self.code:
            year = _year_from_value(self.date)
            sequence = _next_identity_sequence(self.__class__, 'code', f'PYO-{year}-', exclude_pk=self.pk)
            self.code = _formatted_identity('PYO', year, sequence)
        if not self.title:
            self.title = _join_identity_title('Выплата', self.manager_deal.customer_name if self.manager_deal_id else '', f'{self.amount}')
        if not self.short_label:
            self.short_label = ' / '.join(part for part in [self.manager_deal.customer_name if self.manager_deal_id else 'Выплата', f'{self.amount}'] if part)

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        _extend_update_fields(kwargs, 'code', 'title', 'short_label')
        super().save(*args, **kwargs)


class Warehouse(models.Model):
    name = models.CharField('Название', max_length=255)
    address = models.TextField('Адрес', blank=True)
    pickup_point = models.ForeignKey(
        'catalog.PickupPoint',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_warehouses',
        verbose_name='Публичная точка выдачи',
    )
    is_active = models.BooleanField('Активен', default=True, db_index=True)
    public_stock_synced_at = models.DateTimeField('Публичный остаток синхронизирован', null=True, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Склад'
        verbose_name_plural = 'Склады'
        ordering = ['name', 'id']

    def __str__(self):
        return self.name


class InventoryBalance(models.Model):
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='inventory_balances',
        verbose_name='Склад',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='manager_inventory_balances',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_inventory_balances',
        verbose_name='Вариант',
    )
    quantity = models.IntegerField('Количество на складе', default=0)
    min_stock = models.PositiveIntegerField('Минимальный остаток', default=0)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Остаток склада'
        verbose_name_plural = 'Остатки складов'
        ordering = ['warehouse', 'product', 'variant']
        constraints = [
            models.UniqueConstraint(
                fields=['warehouse', 'product'],
                condition=Q(variant__isnull=True),
                name='manager_balance_unique_without_variant',
            ),
            models.UniqueConstraint(
                fields=['warehouse', 'product', 'variant'],
                condition=Q(variant__isnull=False),
                name='manager_balance_unique_with_variant',
            ),
        ]

    def __str__(self):
        label = self.product.name
        if self.variant_id:
            label = f'{label} ({self.variant.name})'
        return f'{self.warehouse}: {label} = {self.quantity}'


class InventoryMovement(models.Model):
    TYPE_RECEIPT = 'receipt'
    TYPE_ADJUSTMENT = 'adjustment'
    TYPE_RESERVE = 'reserve'
    TYPE_RELEASE = 'release'
    TYPE_TRANSFER_OUT = 'transfer_out'
    TYPE_TRANSFER_IN = 'transfer_in'
    TYPE_CHOICES = [
        (TYPE_RECEIPT, 'Приемка'),
        (TYPE_ADJUSTMENT, 'Корректировка'),
        (TYPE_RESERVE, 'Резерв'),
        (TYPE_RELEASE, 'Снятие резерва'),
        (TYPE_TRANSFER_OUT, 'Перемещение со склада'),
        (TYPE_TRANSFER_IN, 'Перемещение на склад'),
    ]

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='inventory_movements',
        verbose_name='Склад',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='manager_inventory_movements',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_inventory_movements',
        verbose_name='Вариант',
    )
    movement_type = models.CharField('Тип движения', max_length=20, choices=TYPE_CHOICES)
    quantity = models.PositiveIntegerField('Количество')
    reference_type = models.CharField('Тип документа', max_length=40, blank=True)
    reference_id = models.PositiveIntegerField('ID документа', null=True, blank=True)
    comment = models.CharField('Комментарий', max_length=255, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_inventory_movements',
        verbose_name='Автор',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Движение по складу'
        verbose_name_plural = 'Движения по складу'
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['warehouse', 'product', 'variant', '-created_at'], name='mgr_inv_move_lookup_idx'),
        ]


class InventoryLot(models.Model):
    purchase_item = models.ForeignKey(
        'manager_portal.PurchaseItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_lots',
        verbose_name='Позиция закупки',
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='inventory_lots',
        verbose_name='Склад',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='inventory_lots',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='inventory_lots',
        verbose_name='Вариант',
    )
    received_qty = models.PositiveIntegerField('Получено')
    remaining_qty = models.PositiveIntegerField('Остаток в лоте')
    unit_cost = models.DecimalField('Себестоимость за единицу', max_digits=12, decimal_places=2, default=Decimal('0'))
    unit_cost_base = models.DecimalField('Базовая себестоимость за единицу', max_digits=12, decimal_places=2, default=Decimal('0'))
    unit_cost_final = models.DecimalField('Итоговая себестоимость за единицу', max_digits=12, decimal_places=2, default=Decimal('0'))
    received_at = models.DateTimeField('Дата приемки', default=timezone.now, db_index=True)
    reference_type = models.CharField('Тип документа', max_length=40, blank=True)
    reference_id = models.PositiveIntegerField('ID документа', null=True, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Лот склада'
        verbose_name_plural = 'Лоты склада'
        ordering = ['received_at', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(received_qty__gt=0), name='inventory_lot_received_qty_gt_zero'),
            models.CheckConstraint(condition=Q(remaining_qty__gte=0), name='inventory_lot_remaining_qty_gte_zero'),
            models.CheckConstraint(condition=Q(remaining_qty__lte=models.F('received_qty')), name='inventory_lot_remaining_qty_lte_received_qty'),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name='inventory_lot_unit_cost_gte_zero'),
            models.CheckConstraint(condition=Q(unit_cost_base__gte=0), name='inventory_lot_unit_cost_base_gte_zero'),
            models.CheckConstraint(condition=Q(unit_cost_final__gte=0), name='inventory_lot_unit_cost_final_gte_zero'),
        ]

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({'variant': 'Вариант должен относиться к выбранному товару.'})

    def save(self, *args, **kwargs):
        if self.unit_cost_base in (None, Decimal('0')) and self.unit_cost:
            self.unit_cost_base = self.unit_cost
        if self.unit_cost_final in (None, Decimal('0')) and self.unit_cost:
            self.unit_cost_final = self.unit_cost
        if self.unit_cost in (None, Decimal('0')):
            self.unit_cost = self.unit_cost_final or self.unit_cost_base or Decimal('0')
        super().save(*args, **kwargs)


class SaleLineAllocation(models.Model):
    STATUS_RESERVED = 'reserved'
    STATUS_SHIPPED = 'shipped'
    STATUS_RELEASED = 'released'
    STATUS_CHOICES = [
        (STATUS_RESERVED, 'Зарезервировано'),
        (STATUS_SHIPPED, 'Отгружено'),
        (STATUS_RELEASED, 'Освобождено'),
    ]

    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.CASCADE,
        related_name='allocations',
        verbose_name='Строка заказа',
    )
    inventory_lot = models.ForeignKey(
        InventoryLot,
        on_delete=models.CASCADE,
        related_name='allocations',
        verbose_name='Лот',
    )
    reserved_qty = models.PositiveIntegerField('Зарезервировано', default=0)
    shipped_qty = models.PositiveIntegerField('Отгружено', default=0)
    unit_cost_snapshot = models.DecimalField('Снимок себестоимости', max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField('Статус', max_length=16, choices=STATUS_CHOICES, default=STATUS_RESERVED, db_index=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Аллокация строки сделки'
        verbose_name_plural = 'Аллокации строк сделки'
        ordering = ['order_item_id', 'inventory_lot_id', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(reserved_qty__gte=0), name='sale_line_alloc_reserved_qty_gte_zero'),
            models.CheckConstraint(condition=Q(shipped_qty__gte=0), name='sale_line_alloc_shipped_qty_gte_zero'),
            models.CheckConstraint(condition=Q(reserved_qty__gte=models.F('shipped_qty')), name='sale_line_alloc_reserved_qty_gte_shipped_qty'),
            models.UniqueConstraint(fields=['order_item', 'inventory_lot', 'status'], name='sale_line_alloc_order_item_lot_status_unique'),
        ]


class Purchase(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ORDERED = 'ordered'
    STATUS_PARTIAL = 'partial'
    STATUS_RECEIVED = 'received'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Черновик'),
        (STATUS_ORDERED, 'Заказано'),
        (STATUS_PARTIAL, 'Частично получено'),
        (STATUS_RECEIVED, 'Получено'),
        (STATUS_CANCELLED, 'Отменено'),
    ]

    code = models.CharField('Код закупки', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    date = models.DateField('Дата')
    supplier_name = models.CharField('Поставщик', max_length=255, blank=True)
    agent = models.CharField('Агент', max_length=255, blank=True)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    currency = models.CharField('Валюта', max_length=12, default='CNY')
    total_amount = models.DecimalField('Сумма', max_digits=12, decimal_places=2, default=Decimal('0'))
    comments = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Закупка'
        verbose_name_plural = 'Закупки'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.code or f'Закупка #{self.pk}'

    def populate_identity_fields(self):
        if not self.code:
            year = _year_from_value(self.date)
            sequence = _next_identity_sequence(self.__class__, 'code', f'PO-{year}-', exclude_pk=self.pk)
            self.code = _formatted_identity('PO', year, sequence)
        if not self.title:
            self.title = _join_identity_title('Закупка', self.supplier_name or 'Поставщик не указан', _month_year_label(self.date))
        if not self.short_label:
            self.short_label = ' / '.join(part for part in [self.supplier_name or 'Закупка', _month_year_label(self.date)] if part)

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        _extend_update_fields(kwargs, 'code', 'title', 'short_label')
        super().save(*args, **kwargs)


class PurchaseItem(models.Model):
    def __init__(self, *args, **kwargs):
        if 'price' in kwargs and 'unit_cost' not in kwargs:
            kwargs['unit_cost'] = kwargs.pop('price')
        super().__init__(*args, **kwargs)

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Закупка',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='manager_purchase_items',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_purchase_items',
        verbose_name='Вариант',
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_links',
        verbose_name='Строка заказа',
    )
    quantity = models.PositiveIntegerField('Количество')
    cancelled_quantity = models.PositiveIntegerField('Операционно отменено', default=0)
    unit_cost = models.DecimalField('Себестоимость за единицу', max_digits=12, decimal_places=2, default=Decimal('0'))
    received_quantity = models.PositiveIntegerField('Получено', default=0)
    received_at = models.DateTimeField('Дата приемки', null=True, blank=True)
    arrival_photo = models.ImageField('Фото приемки', upload_to='manager/purchases/', blank=True)

    class Meta:
        verbose_name = 'Позиция закупки'
        verbose_name_plural = 'Позиции закупки'
        ordering = ['id']
        constraints = [
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name='purchase_item_unit_cost_gte_zero'),
            models.CheckConstraint(condition=Q(cancelled_quantity__gte=0), name='purchase_item_cancelled_quantity_gte_zero'),
            models.CheckConstraint(
                condition=Q(cancelled_quantity__lte=models.F('quantity')),
                name='purchase_item_cancelled_quantity_lte_quantity',
            ),
        ]

    def __str__(self):
        return f'{self.product} x {self.quantity}'

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({'variant': 'Вариант должен относиться к выбранному товару.'})
        if self.product_id and self.product.variants.exists() and not self.variant_id:
            raise ValidationError({'variant': 'Для товара с вариантами выберите конкретный вариант.'})
        if self.order_item_id:
            if self.order_item.product_id != self.product_id:
                raise ValidationError({'order_item': 'Строка заказа должна ссылаться на тот же товар.'})
            if self.variant_id != self.order_item.variant_id:
                raise ValidationError({'order_item': 'Строка заказа должна ссылаться на тот же вариант.'})
            if self.order_item.line_type != self.order_item.LINE_TYPE_CATALOG:
                raise ValidationError({'order_item': 'С закупкой можно связать только каталоговую строку сделки.'})

    @property
    def linked_order(self):
        return self.order_item.order if self.order_item_id else None

    @property
    def active_quantity(self):
        return max(self.quantity - self.cancelled_quantity, 0)

    @property
    def remaining_quantity(self):
        return max(self.active_quantity - self.received_quantity, 0)

    @property
    def receipt_status(self):
        if self.active_quantity <= 0:
            return 'cancelled'
        if self.received_quantity <= 0:
            return 'ordered'
        if self.received_quantity >= self.active_quantity:
            return 'fully_received'
        return 'partially_received'

    @property
    def price(self):
        return self.unit_cost

    @price.setter
    def price(self, value):
        self.unit_cost = value


class Cargo(models.Model):
    STATUS_CREATED = 'created'
    STATUS_IN_TRANSIT = 'in_transit'
    STATUS_ARRIVED_RF = 'arrived_rf'
    STATUS_DELIVERY_RF = 'delivery_rf'
    STATUS_AWAITING_RECEIPT = 'awaiting_receipt'
    STATUS_RECEIVED = 'received'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Создан'),
        (STATUS_IN_TRANSIT, 'В пути в РФ'),
        (STATUS_ARRIVED_RF, 'Прибыл в РФ'),
        (STATUS_DELIVERY_RF, 'Доставка по РФ'),
        (STATUS_AWAITING_RECEIPT, 'Ожидает приемки'),
        (STATUS_RECEIVED, 'Принят'),
        (STATUS_CANCELLED, 'Отменен'),
    ]

    cargo_number = models.CharField('Номер груза', max_length=120, unique=True, blank=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cargos',
        verbose_name='Закупка',
    )
    status = models.CharField('Статус', max_length=32, choices=STATUS_CHOICES, default=STATUS_CREATED, db_index=True)
    eta = models.DateField('ETA', null=True, blank=True)
    destination_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incoming_cargos',
        verbose_name='Склад назначения',
    )
    comments = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Груз'
        verbose_name_plural = 'Грузы'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.cargo_number

    def populate_identity_fields(self):
        if not self.cargo_number:
            year = _year_from_value(self.created_at or timezone.localdate())
            sequence = _next_identity_sequence(self.__class__, 'cargo_number', f'CG-{year}-', exclude_pk=self.pk)
            self.cargo_number = _formatted_identity('CG', year, sequence)
        if not self.title:
            route = ' → '.join(part for part in [self.purchase.supplier_name if self.purchase_id and self.purchase.supplier_name else '', self.destination_warehouse.name if self.destination_warehouse_id else 'Склад'] if part)
            self.title = _join_identity_title('Груз', route, _month_year_label(self.eta or timezone.localdate()))
        if not self.short_label:
            self.short_label = ' / '.join(part for part in [self.destination_warehouse.name if self.destination_warehouse_id else 'Груз', _month_year_label(self.eta or timezone.localdate())] if part)

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        _extend_update_fields(kwargs, 'cargo_number', 'title', 'short_label')
        super().save(*args, **kwargs)


class CargoItem(models.Model):
    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Груз',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='manager_cargo_items',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_cargo_items',
        verbose_name='Вариант',
    )
    purchase_item = models.ForeignKey(
        PurchaseItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cargo_items',
        verbose_name='Позиция закупки',
    )
    quantity = models.PositiveIntegerField('Количество')
    received_quantity = models.PositiveIntegerField('Принято', default=0)
    arrival_photo = models.ImageField('Фото приемки', upload_to='manager/cargo-items/', blank=True)

    class Meta:
        verbose_name = 'Позиция груза'
        verbose_name_plural = 'Позиции груза'
        ordering = ['id']

    @property
    def remaining_quantity(self):
        return max(self.quantity - self.received_quantity, 0)

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({'variant': 'Вариант должен относиться к выбранному товару.'})
        if self.purchase_item_id:
            if self.purchase_item.product_id != self.product_id:
                raise ValidationError({'purchase_item': 'Позиция закупки должна ссылаться на тот же товар.'})
            if self.variant_id != self.purchase_item.variant_id:
                raise ValidationError({'purchase_item': 'Позиция закупки должна ссылаться на тот же вариант.'})

    @property
    def linked_order(self):
        if self.purchase_item_id and self.purchase_item.order_item_id:
            return self.purchase_item.order_item.order
        return None


class CargoPhoto(models.Model):
    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        related_name='photos',
        verbose_name='Груз',
    )
    image = models.ImageField('Фото', upload_to='manager/cargos/')
    caption = models.CharField('Подпись', max_length=255, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Фото груза'
        verbose_name_plural = 'Фото грузов'
        ordering = ['-created_at', '-id']


class TransportLeg(models.Model):
    STATUS_CREATED = 'created'
    STATUS_IN_TRANSIT = 'in_transit'
    STATUS_ARRIVED = 'arrived'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Создан'),
        (STATUS_IN_TRANSIT, 'В пути'),
        (STATUS_ARRIVED, 'Прибыл'),
        (STATUS_CANCELLED, 'Отменен'),
    ]

    code = models.CharField('Код этапа', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        related_name='legs',
        verbose_name='Груз',
    )
    from_location = models.CharField('Откуда', max_length=255)
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name='transport_legs',
        verbose_name='Куда',
    )
    method = models.CharField('Метод', max_length=120, blank=True)
    track_number = models.CharField('Трек', max_length=120, blank=True)
    cost = models.DecimalField('Стоимость', max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)
    departed_at = models.DateTimeField('Отправлен', null=True, blank=True)
    arrived_at = models.DateTimeField('Прибыл', null=True, blank=True)
    comments = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Этап перевозки'
        verbose_name_plural = 'Этапы перевозки'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.code or f'Этап #{self.pk}'

    def populate_identity_fields(self):
        if not self.code:
            year = _year_from_value(self.created_at or timezone.localdate())
            sequence = _next_identity_sequence(self.__class__, 'code', f'LEG-{year}-', exclude_pk=self.pk)
            self.code = _formatted_identity('LEG', year, sequence)
        route = ' → '.join(part for part in [self.from_location, self.to_warehouse.name if self.to_warehouse_id else ''] if part)
        if not self.title:
            self.title = _join_identity_title('Этап перевозки', route, self.method)
        if not self.short_label:
            self.short_label = route or self.method or self.code or 'Этап'

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        _extend_update_fields(kwargs, 'code', 'title', 'short_label')
        super().save(*args, **kwargs)


class Expense(models.Model):
    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name='Груз',
    )
    leg = models.ForeignKey(
        TransportLeg,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='expenses',
        verbose_name='Этап',
    )
    category = models.CharField('Категория', max_length=120)
    name = models.CharField('Название', max_length=255)
    amount = models.DecimalField('Сумма', max_digits=12, decimal_places=2)
    date = models.DateField('Дата')

    class Meta:
        verbose_name = 'Расход'
        verbose_name_plural = 'Расходы'
        ordering = ['-date', '-id']

    def clean(self):
        if not self.cargo_id and not self.leg_id:
            raise ValidationError('Укажите груз или этап перевозки.')


class Shipment(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_PENDING = 'pending'
    STATUS_SHIPPED = 'shipped'
    STATUS_DELIVERED = 'delivered'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Черновик'),
        (STATUS_PENDING, 'Готовится'),
        (STATUS_SHIPPED, 'Отправлено'),
        (STATUS_DELIVERED, 'Доставлено'),
        (STATUS_CANCELLED, 'Отменено'),
    ]

    code = models.CharField('Код отгрузки', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    manager_deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments',
        verbose_name='Связанная сделка',
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_shipments',
        verbose_name='Заказ',
    )
    client = models.ForeignKey(
        ManagerClient,
        on_delete=models.CASCADE,
        related_name='shipments',
        verbose_name='Клиент',
    )
    reservation = models.ForeignKey(
        'manager_portal.Reservation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments',
        verbose_name='Резерв',
    )
    source_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='outgoing_shipments',
        verbose_name='Склад-источник',
    )
    target_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incoming_shipments',
        verbose_name='Склад назначения',
    )
    delivery_method = models.CharField('Способ доставки', max_length=32, blank=True)
    delivery_provider_name = models.CharField('Перевозчик / провайдер доставки', max_length=255, blank=True)
    recipient_name = models.CharField('Получатель', max_length=255, blank=True)
    recipient_phone = models.CharField('Телефон получателя', max_length=40, blank=True)
    delivery_address = models.TextField('Адрес доставки', blank=True)
    planned_receipt_at = models.DateField('Плановая дата получения', null=True, blank=True)
    delivery_payer = models.CharField(
        'Кто оплачивает доставку',
        max_length=20,
        choices=ManagerDeal.DELIVERY_PAYER_CHOICES,
        blank=True,
    )
    tracking_number = models.CharField('Трек', max_length=120, blank=True)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    inventory_consumed_at = models.DateTimeField('Складской эффект проведен', null=True, blank=True, db_index=True)
    shipped_at = models.DateTimeField('Отправлено', null=True, blank=True)
    delivered_at = models.DateTimeField('Доставлено', null=True, blank=True)
    comments = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Отгрузка'
        verbose_name_plural = 'Отгрузки'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.code or f'Отгрузка #{self.pk}'

    def populate_identity_fields(self):
        if self.manager_deal_id and not self.manager_deal.code:
            self.manager_deal.save()
        if not self.code:
            if self.manager_deal_id and self.manager_deal.code:
                self.code = _deal_child_identity('SHP', self.manager_deal.code, self.__class__, 'code', exclude_pk=self.pk)
            else:
                year = _year_from_value(self.created_at or timezone.localdate())
                sequence = _next_identity_sequence(self.__class__, 'code', f'SHP-{year}-', exclude_pk=self.pk)
                self.code = _formatted_identity('SHP', year, sequence)
        if not self.title:
            deal_code = self.manager_deal.code if self.manager_deal_id else ''
            delivery_label = (
                self.delivery_provider_name
                or self.delivery_method
                or (self.manager_deal.delivery_provider_name if self.manager_deal_id else '')
                or (self.manager_deal.get_delivery_method_display() if self.manager_deal_id else '')
            )
            self.title = _join_identity_title('Отгрузка', self.client.name if self.client_id else '', delivery_label, deal_code)
        if not self.short_label:
            self.short_label = ' / '.join(
                part
                for part in [
                    self.client.name if self.client_id else '',
                    self.delivery_provider_name or self.delivery_method or 'Отгрузка',
                ]
                if part
            )

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        _extend_update_fields(kwargs, 'code', 'title', 'short_label')
        super().save(*args, **kwargs)


class ShipmentItem(models.Model):
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Отгрузка',
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipment_items',
        verbose_name='Строка заказа',
    )
    reservation_item = models.ForeignKey(
        'manager_portal.ReservationItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipment_items',
        verbose_name='Строка резерва',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='manager_shipment_items',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_shipment_items',
        verbose_name='Вариант',
    )
    quantity = models.PositiveIntegerField('Количество')

    class Meta:
        verbose_name = 'Позиция отгрузки'
        verbose_name_plural = 'Позиции отгрузки'
        ordering = ['id']

    def __str__(self):
        return f'{self.product} x {self.quantity}'

    @property
    def shipment_status(self):
        return self.shipment.status

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({'variant': 'Вариант должен относиться к выбранному товару.'})
        if self.order_item_id:
            if self.order_item.line_type != self.order_item.LINE_TYPE_CATALOG:
                raise ValidationError({'order_item': 'С бронью можно связать только каталоговую строку сделки.'})
            if self.order_item.product_id != self.product_id:
                raise ValidationError({'order_item': 'Строка заказа должна ссылаться на тот же товар.'})
            if self.variant_id != self.order_item.variant_id:
                raise ValidationError({'order_item': 'Строка заказа должна ссылаться на тот же вариант.'})
        if self.reservation_item_id:
            if self.reservation_item.product_id != self.product_id:
                raise ValidationError({'reservation_item': 'Строка резерва должна ссылаться на тот же товар.'})
            if self.variant_id != self.reservation_item.variant_id:
                raise ValidationError({'reservation_item': 'Строка резерва должна ссылаться на тот же вариант.'})


class Reservation(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ACTIVE = 'active'
    STATUS_PARTIAL = 'partial'
    STATUS_RELEASED = 'released'
    STATUS_FULFILLED = 'fulfilled'
    STATUS_CANCELLED = 'cancelled'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Черновик'),
        (STATUS_ACTIVE, 'Активно'),
        (STATUS_PARTIAL, 'Частично выдано'),
        (STATUS_RELEASED, 'Освобождено'),
        (STATUS_FULFILLED, 'Выполнено'),
        (STATUS_CANCELLED, 'Отменено'),
        (STATUS_EXPIRED, 'Истекло'),
    ]

    SOURCE_WAREHOUSE = 'warehouse'
    SOURCE_CARGO = 'cargo'
    SOURCE_CHOICES = [
        (SOURCE_WAREHOUSE, 'Со склада'),
        (SOURCE_CARGO, 'Из груза'),
    ]

    code = models.CharField('Код брони', max_length=32, unique=True, null=True, blank=True, db_index=True)
    title = models.CharField('Рабочее название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    manager_deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        verbose_name='Связанная сделка',
    )
    client = models.ForeignKey(
        ManagerClient,
        on_delete=models.CASCADE,
        related_name='reservations',
        verbose_name='Клиент',
    )
    linked_order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_reservations',
        verbose_name='Заказ сайта',
    )
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    source_type = models.CharField('Источник', max_length=20, choices=SOURCE_CHOICES)
    source_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='warehouse_reservations',
        verbose_name='Склад-источник',
    )
    source_cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cargo_reservations',
        verbose_name='Груз-источник',
    )
    target_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='target_reservations',
        verbose_name='Склад назначения',
    )
    comments = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Бронирование'
        verbose_name_plural = 'Бронирования'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.code or f'Бронь #{self.pk}'

    def populate_identity_fields(self):
        if self.manager_deal_id and not self.manager_deal.code:
            self.manager_deal.save()
        if not self.code:
            if self.manager_deal_id and self.manager_deal.code:
                self.code = _deal_child_identity('RSV', self.manager_deal.code, self.__class__, 'code', exclude_pk=self.pk)
            else:
                year = _year_from_value(self.created_at or timezone.localdate())
                sequence = _next_identity_sequence(self.__class__, 'code', f'RSV-{year}-', exclude_pk=self.pk)
                self.code = _formatted_identity('RSV', year, sequence)
        if not self.title:
            deal_code = self.manager_deal.code if self.manager_deal_id else ''
            source_label = self.source_warehouse.name if self.source_warehouse_id else self.source_cargo.cargo_number if self.source_cargo_id else ''
            self.title = _join_identity_title('Бронь', self.client.name if self.client_id else '', deal_code or source_label)
        if not self.short_label:
            self.short_label = ' / '.join(part for part in [self.client.name if self.client_id else '', self.get_status_display()] if part)

    def save(self, *args, **kwargs):
        self.populate_identity_fields()
        _extend_update_fields(kwargs, 'code', 'title', 'short_label')
        super().save(*args, **kwargs)

    def clean(self):
        if self.source_type == self.SOURCE_WAREHOUSE:
            if not self.source_warehouse_id:
                raise ValidationError({'source_warehouse': 'Выберите склад-источник.'})
            if self.source_cargo_id:
                raise ValidationError({'source_cargo': 'Для склада груз указывать нельзя.'})
        if self.source_type == self.SOURCE_CARGO:
            if not self.source_cargo_id:
                raise ValidationError({'source_cargo': 'Выберите груз-источник.'})
            if self.source_warehouse_id:
                raise ValidationError({'source_warehouse': 'Для груза склад указывать нельзя.'})


class ReservationItem(models.Model):
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Бронь',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.CASCADE,
        related_name='manager_reservation_items',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='manager_reservation_items',
        verbose_name='Вариант',
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservation_links',
        verbose_name='Строка заказа',
    )
    quantity = models.PositiveIntegerField('Количество')
    fulfilled_quantity = models.PositiveIntegerField('Исполнено отгрузками', default=0)
    released_quantity = models.PositiveIntegerField('Освобождено', default=0)

    class Meta:
        verbose_name = 'Позиция брони'
        verbose_name_plural = 'Позиции брони'
        ordering = ['id']
        constraints = [
            models.CheckConstraint(condition=Q(fulfilled_quantity__gte=0), name='reservation_item_fulfilled_quantity_gte_zero'),
            models.CheckConstraint(condition=Q(released_quantity__gte=0), name='reservation_item_released_quantity_gte_zero'),
            models.CheckConstraint(
                condition=Q(fulfilled_quantity__lte=models.F('quantity')),
                name='reservation_item_fulfilled_quantity_lte_quantity',
            ),
            models.CheckConstraint(
                condition=Q(released_quantity__lte=models.F('quantity')),
                name='reservation_item_released_quantity_lte_quantity',
            ),
            models.CheckConstraint(
                condition=Q(fulfilled_quantity__lte=models.F('quantity') - models.F('released_quantity')),
                name='reservation_item_combined_quantity_lte_quantity',
            ),
        ]

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({'variant': 'Вариант должен относиться к выбранному товару.'})
        if self.order_item_id:
            if self.order_item.product_id != self.product_id:
                raise ValidationError({'order_item': 'Строка заказа должна ссылаться на тот же товар.'})
            if self.variant_id != self.order_item.variant_id:
                raise ValidationError({'order_item': 'Строка заказа должна ссылаться на тот же вариант.'})
        if self.fulfilled_quantity + self.released_quantity > self.quantity:
            raise ValidationError('Сумма исполненного и освобожденного количества не может превышать количество брони.')

    @property
    def active_reserved_quantity(self):
        return max(self.quantity - self.fulfilled_quantity - self.released_quantity, 0)

    @property
    def reservation_status(self):
        if self.quantity <= 0:
            return 'pending'
        if self.fulfilled_quantity >= self.quantity:
            return 'fulfilled'
        if self.released_quantity >= self.quantity:
            return 'released'
        if self.fulfilled_quantity > 0 or self.released_quantity > 0:
            return 'partially_fulfilled'
        if self.active_reserved_quantity > 0:
            return 'reserved'
        return 'pending'


class ContractCompanyProfile(models.Model):
    LEGAL_TYPE_OOO = 'ooo'
    LEGAL_TYPE_IP = 'ip'
    LEGAL_TYPE_PERSON = 'person'
    LEGAL_TYPE_OTHER = 'other'
    LEGAL_TYPE_CHOICES = [
        (LEGAL_TYPE_OOO, 'ООО'),
        (LEGAL_TYPE_IP, 'ИП'),
        (LEGAL_TYPE_PERSON, 'Физ. лицо'),
        (LEGAL_TYPE_OTHER, 'Другое'),
    ]

    external_id = models.CharField('Legacy ID', max_length=80, blank=True, null=True, unique=True)
    name = models.CharField('Название профиля', max_length=255)
    legal_type = models.CharField('Тип лица', max_length=20, choices=LEGAL_TYPE_CHOICES, default=LEGAL_TYPE_IP)
    company_name = models.CharField('Полное наименование', max_length=255)
    inn = models.CharField('ИНН', max_length=20, blank=True)
    kpp = models.CharField('КПП', max_length=20, blank=True)
    ogrn = models.CharField('ОГРН', max_length=20, blank=True)
    ogrnip = models.CharField('ОГРНИП', max_length=20, blank=True)
    director_genitive = models.CharField('Подписант (род. падеж)', max_length=255, blank=True)
    legal_address = models.TextField('Юридический адрес', blank=True)
    email = models.EmailField('Email', blank=True)
    phone = models.CharField('Телефон', max_length=40, blank=True)
    bank_name = models.CharField('Банк', max_length=255, blank=True)
    checking_account = models.CharField('Расчетный счет', max_length=64, blank=True)
    correspondent_account = models.CharField('Корр. счет', max_length=64, blank=True)
    bik = models.CharField('БИК', max_length=20, blank=True)
    card_number = models.CharField('Номер карты', max_length=40, blank=True)
    sbp_phone = models.CharField('Телефон СБП', max_length=40, blank=True)
    passport_series = models.CharField('Серия паспорта', max_length=20, blank=True)
    passport_number = models.CharField('Номер паспорта', max_length=20, blank=True)
    passport_issued_by = models.CharField('Кем выдан', max_length=255, blank=True)
    passport_issued_date = models.DateField('Дата выдачи паспорта', null=True, blank=True)
    passport_department_code = models.CharField('Код подразделения', max_length=20, blank=True)
    registration_address = models.TextField('Адрес регистрации', blank=True)
    residence_address = models.TextField('Адрес проживания', blank=True)
    bank_accounts = models.JSONField('Банковские счета', default=list, blank=True)
    legacy_payload = models.JSONField('Legacy payload', default=dict, blank=True)
    is_active = models.BooleanField('Активный профиль', default=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Профиль договоров'
        verbose_name_plural = 'Профили договоров'
        ordering = ['-is_active', 'name', 'id']

    def __str__(self):
        return self.name


class ContractTemplate(models.Model):
    DOC_TYPE_CONTRACT = 'contract'
    DOC_TYPE_INVOICE = 'invoice'
    DOC_TYPE_ACT = 'act'
    DOC_TYPE_APPENDIX = 'appendix'
    DOC_TYPE_OFFER = 'offer'
    DOC_TYPE_OTHER = 'other'
    DOCUMENT_TYPE_CHOICES = [
        (DOC_TYPE_CONTRACT, 'Договор'),
        (DOC_TYPE_INVOICE, 'Счет'),
        (DOC_TYPE_ACT, 'Акт'),
        (DOC_TYPE_APPENDIX, 'Приложение'),
        (DOC_TYPE_OFFER, 'Оферта / КП'),
        (DOC_TYPE_OTHER, 'Другое'),
    ]

    external_id = models.CharField('Legacy ID', max_length=80, blank=True, null=True, unique=True)
    sort_order = models.IntegerField('Порядок', default=0)
    name = models.CharField('Название', max_length=255)
    slug = models.SlugField('Slug', max_length=255, blank=True)
    document_type = models.CharField('Тип документа', max_length=20, choices=DOCUMENT_TYPE_CHOICES, default=DOC_TYPE_CONTRACT)
    version = models.CharField('Версия', max_length=50, default='1.0')
    description = models.TextField('Описание', blank=True)
    is_active = models.BooleanField('Активен', default=True)
    content_html = models.TextField('HTML шаблона', blank=True)
    css_text = models.TextField('CSS шаблона', blank=True)
    variables_schema = models.JSONField('Переменные', default=list, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Шаблон договора'
        verbose_name_plural = 'Шаблоны договоров'
        ordering = ['-is_active', 'sort_order', 'name', 'id']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:255] or f'template-{self.pk or "new"}'
        super().save(*args, **kwargs)


class ContractDocument(models.Model):
    SOURCE_INTERNAL = 'internal'
    SOURCE_IMPORTED = 'imported_docuflow'
    SOURCE_CHOICES = [
        (SOURCE_INTERNAL, 'Внутренний кабинет'),
        (SOURCE_IMPORTED, 'Импортировано из DocuFlow'),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_REVIEW = 'review'
    STATUS_SENT = 'sent'
    STATUS_SIGNED = 'signed'
    STATUS_PAID = 'paid'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Черновик'),
        (STATUS_REVIEW, 'На согласовании'),
        (STATUS_SENT, 'Отправлен'),
        (STATUS_SIGNED, 'Подписан'),
        (STATUS_PAID, 'Оплачен'),
        (STATUS_ARCHIVED, 'Архив'),
    ]

    CURRENCY_RUB = 'RUB'
    CURRENCY_USDT = 'USDT'
    CURRENCY_CHOICES = [
        (CURRENCY_RUB, 'RUB'),
        (CURRENCY_USDT, 'USDT'),
    ]

    manager_deal = models.ForeignKey(
        ManagerDeal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contract_documents',
        verbose_name='Связанная сделка',
    )
    external_id = models.CharField('Legacy ID', max_length=80, blank=True, null=True, unique=True)
    source = models.CharField('Источник', max_length=30, choices=SOURCE_CHOICES, default=SOURCE_INTERNAL)
    sort_order = models.IntegerField('Порядок', default=0)
    number = models.CharField('Номер документа', max_length=100, db_index=True, blank=True)
    title = models.CharField('Название', max_length=255, blank=True)
    short_label = models.CharField('Короткий ярлык', max_length=255, blank=True)
    document_type = models.CharField(
        'Тип документа',
        max_length=20,
        choices=ContractTemplate.DOCUMENT_TYPE_CHOICES,
        default=ContractTemplate.DOC_TYPE_CONTRACT,
        db_index=True,
    )
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    template = models.ForeignKey(
        ContractTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documents',
        verbose_name='Шаблон',
    )
    company_profile = models.ForeignKey(
        ContractCompanyProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documents',
        verbose_name='Профиль компании',
    )
    manager_client = models.ForeignKey(
        ManagerClient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contract_documents',
        verbose_name='Клиент кабинета',
    )
    linked_order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contract_documents',
        verbose_name='Заказ сайта',
    )
    responsible_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='responsible_contract_documents',
        verbose_name='Ответственный менеджер',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_contract_documents',
        verbose_name='Создал',
    )
    issue_date = models.DateField('Дата документа', default=timezone.localdate, db_index=True)
    effective_until = models.DateField('Действует до', null=True, blank=True)
    amount = models.DecimalField('Сумма', max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField('Валюта', max_length=10, choices=CURRENCY_CHOICES, default=CURRENCY_RUB)
    payment_terms = models.PositiveIntegerField('Срок оплаты, дней', null=True, blank=True)
    include_delivery = models.BooleanField('Включать доставку', default=False)
    delivery_date = models.DateField('Дата доставки', null=True, blank=True)
    vat_rate = models.CharField('НДС', max_length=20, default='none')
    vat_mode = models.CharField('Режим НДС', max_length=20, default='included')
    markup_percent = models.DecimalField('Наценка, %', max_digits=6, decimal_places=2, default=Decimal('6.00'))
    markup_mode = models.CharField('Режим наценки', max_length=30, default='per_item')
    markup_calc_mode = models.CharField('Формула наценки', max_length=30, default='simple')
    subject = models.TextField('Предмет документа', blank=True)
    counterparty_name = models.CharField('Контрагент', max_length=255, blank=True)
    counterparty_email = models.EmailField('Email контрагента', blank=True)
    counterparty_phone = models.CharField('Телефон контрагента', max_length=40, blank=True)
    counterparty_inn = models.CharField('ИНН контрагента', max_length=20, blank=True)
    counterparty_kpp = models.CharField('КПП контрагента', max_length=20, blank=True)
    counterparty_ogrn = models.CharField('ОГРН контрагента', max_length=20, blank=True)
    counterparty_ogrnip = models.CharField('ОГРНИП контрагента', max_length=20, blank=True)
    counterparty_address = models.TextField('Адрес контрагента', blank=True)
    counterparty_data = models.JSONField('Снимок контрагента', default=dict, blank=True)
    document_data = models.JSONField('Данные документа', default=dict, blank=True)
    invoice_data = models.JSONField('Данные счета', default=dict, blank=True)
    html_snapshot = models.TextField('HTML снапшот', blank=True)
    snapshot_css = models.TextField('CSS снапшота', blank=True)
    notes = models.TextField('Комментарии', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)

    class Meta:
        verbose_name = 'Документ договора'
        verbose_name_plural = 'Документы договоров'
        ordering = ['-issue_date', '-created_at', '-id']

    def __str__(self):
        return self.number or self.title or f'Документ #{self.pk}'

    @property
    def code(self):
        return self.number

    @property
    def counterparty_display(self):
        if self.counterparty_name:
            return self.counterparty_name
        if self.manager_client_id:
            return self.manager_client.name
        return self.counterparty_data.get('name') or 'Без контрагента'

    def populate_runtime_defaults(self):
        if self.manager_deal_id:
            if not self.linked_order_id:
                self.linked_order = self.manager_deal.order
            if not self.manager_client_id:
                order_phone = self.manager_deal.customer_phone
                self.manager_client = ManagerClient.objects.filter(phone=order_phone).first()
        if self.manager_client_id:
            if not self.counterparty_name:
                self.counterparty_name = self.manager_client.name
            if not self.counterparty_email:
                self.counterparty_email = self.manager_client.email
            if not self.counterparty_phone:
                self.counterparty_phone = self.manager_client.phone
            if not self.counterparty_address:
                self.counterparty_address = self.manager_client.address
        if not self.number:
            prefix_map = {
                ContractTemplate.DOC_TYPE_CONTRACT: 'DOG',
                ContractTemplate.DOC_TYPE_INVOICE: 'SCH',
                ContractTemplate.DOC_TYPE_ACT: 'ACT',
                ContractTemplate.DOC_TYPE_APPENDIX: 'UPD',
                ContractTemplate.DOC_TYPE_OFFER: 'KP',
                ContractTemplate.DOC_TYPE_OTHER: 'DOC',
            }
            prefix = prefix_map.get(self.document_type, 'DOC')
            if self.manager_deal_id and not self.manager_deal.code:
                self.manager_deal.save()
            if self.manager_deal_id and self.manager_deal.code:
                self.number = _deal_child_identity(prefix, self.manager_deal.code, self.__class__, 'number', exclude_pk=self.pk)
            else:
                year = _year_from_value(self.issue_date)
                sequence = _next_identity_sequence(self.__class__, 'number', f'{prefix}-{year}-', exclude_pk=self.pk)
                self.number = _formatted_identity(
                    prefix,
                    year,
                    sequence,
                    width=CONTRACT_ROOT_IDENTITY_WIDTH,
                )
        if not self.title:
            deal_code = self.manager_deal.code if self.manager_deal_id else ''
            self.title = _join_identity_title(self.get_document_type_display(), self.counterparty_display, deal_code)
        if not self.short_label:
            self.short_label = ' / '.join(part for part in [self.get_document_type_display(), self.counterparty_display] if part)

    def save(self, *args, **kwargs):
        self.populate_runtime_defaults()
        _extend_update_fields(
            kwargs,
            'number',
            'title',
            'short_label',
            'linked_order',
            'manager_client',
            'counterparty_name',
            'counterparty_email',
            'counterparty_phone',
            'counterparty_address',
        )
        super().save(*args, **kwargs)


class LegacyImportBatch(models.Model):
    SOURCE_DOCUFLOW = 'docuflow'
    SOURCE_BUSINESS_FINANCE = 'business_finance'
    SOURCE_SITE_SQLITE = 'site_sqlite'
    SOURCE_TABULAR_SALES = 'tabular_sales'
    SOURCE_CHOICES = [
        (SOURCE_DOCUFLOW, 'legacy DocuFlow'),
        (SOURCE_BUSINESS_FINANCE, 'legacy BusinessFinance'),
        (SOURCE_SITE_SQLITE, 'legacy site SQLite'),
        (SOURCE_TABULAR_SALES, 'tabular manager sales'),
    ]

    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Выполняется'),
        (STATUS_COMPLETED, 'Завершен'),
        (STATUS_FAILED, 'Ошибка'),
    ]

    source_system = models.CharField('Источник', max_length=40, choices=SOURCE_CHOICES, db_index=True)
    source_ref = models.CharField('Источник данных', max_length=500)
    dry_run = models.BooleanField('Только проверка', default=True, db_index=True)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_RUNNING, db_index=True)
    summary = models.JSONField('Сводка', default=dict, blank=True)
    error_text = models.TextField('Ошибка', blank=True)
    started_at = models.DateTimeField('Старт', auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField('Завершен', null=True, blank=True)

    class Meta:
        verbose_name = 'Пакет legacy-импорта'
        verbose_name_plural = 'Пакеты legacy-импорта'
        ordering = ['-started_at', '-id']

    def __str__(self):
        return f'{self.get_source_system_display()} #{self.pk}'


class LegacyImportRecord(models.Model):
    STATUS_CREATED = 'created'
    STATUS_MATCHED = 'matched'
    STATUS_ENRICHED = 'enriched'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Создано'),
        (STATUS_MATCHED, 'Совпало'),
        (STATUS_ENRICHED, 'Дополнено'),
        (STATUS_SKIPPED, 'Пропущено'),
    ]

    batch = models.ForeignKey(
        LegacyImportBatch,
        on_delete=models.CASCADE,
        related_name='records',
        verbose_name='Пакет',
    )
    source_system = models.CharField('Источник', max_length=40, choices=LegacyImportBatch.SOURCE_CHOICES, db_index=True)
    source_model = models.CharField('Таблица источника', max_length=120, db_index=True)
    source_pk = models.CharField('PK источника', max_length=120, db_index=True)
    status = models.CharField('Результат', max_length=20, choices=STATUS_CHOICES, db_index=True)
    target_model = models.CharField('Целевая модель', max_length=120, blank=True)
    target_pk = models.PositiveBigIntegerField('PK цели', null=True, blank=True)
    source_payload = models.JSONField('Снимок источника', default=dict, blank=True)
    details = models.JSONField('Детали', default=dict, blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлена', auto_now=True)

    class Meta:
        verbose_name = 'Запись legacy-импорта'
        verbose_name_plural = 'Записи legacy-импорта'
        ordering = ['source_system', 'source_model', 'source_pk']
        constraints = [
            models.UniqueConstraint(
                fields=['source_system', 'source_model', 'source_pk'],
                name='manager_legacyimportrecord_source_unique',
            ),
        ]

    def __str__(self):
        return f'{self.source_system}:{self.source_model}:{self.source_pk}'


class LegacyImportConflict(models.Model):
    batch = models.ForeignKey(
        LegacyImportBatch,
        on_delete=models.CASCADE,
        related_name='conflicts',
        verbose_name='Пакет',
    )
    source_system = models.CharField('Источник', max_length=40, choices=LegacyImportBatch.SOURCE_CHOICES, db_index=True)
    source_model = models.CharField('Таблица источника', max_length=120, db_index=True)
    source_pk = models.CharField('PK источника', max_length=120, db_index=True)
    target_model = models.CharField('Целевая модель', max_length=120, blank=True)
    target_pk = models.PositiveBigIntegerField('PK цели', null=True, blank=True)
    conflict_type = models.CharField('Тип конфликта', max_length=80, db_index=True)
    message = models.TextField('Описание')
    source_payload = models.JSONField('Снимок источника', default=dict, blank=True)
    target_payload = models.JSONField('Снимок цели', default=dict, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Конфликт legacy-импорта'
        verbose_name_plural = 'Конфликты legacy-импорта'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.source_system}:{self.source_model}:{self.source_pk}:{self.conflict_type}'
