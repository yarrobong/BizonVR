"""
Модели заказа (Фаза 3–4). Order, OrderItem. Промокоды (скидка + бонус партнёру).
Временно: PurchaseRequest — заявка на покупку (телефон + Telegram).
"""
import secrets
from decimal import Decimal
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from catalog.models import Product, ProductVariant


def resolve_order_item_image_url(*, product=None, variant=None):
    image = None
    if variant is not None and getattr(variant, 'image', None):
        image = variant.image
    elif product is not None:
        image = product.get_display_image()
    if not image:
        return ''
    try:
        return image.url
    except (AttributeError, ValueError):
        return ''


class PurchaseRequest(models.Model):
    """Временная заявка на покупку: клиент оставляет контакты, мы связываемся."""
    STATUS_NEW = 'new'
    STATUS_CONTACTED = 'contacted'
    STATUS_PROCESSED = 'processed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_NEW, 'Новая'),
        (STATUS_CONTACTED, 'Связались'),
        (STATUS_PROCESSED, 'Обработана'),
        (STATUS_CANCELLED, 'Отменена'),
    ]
    phone = models.CharField('Телефон', max_length=20)
    telegram = models.CharField('Telegram', max_length=100, help_text='@username или ссылка')
    items = models.JSONField('Товары', default=list)  # [{"product_id", "name", "price", "quantity", "subtotal"}]
    total = models.DecimalField('Сумма', max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True)
    comment = models.TextField('Комментарий (админ)', blank=True)
    legal_accepted_at = models.DateTimeField('Согласие с юр. документами', null=True, blank=True)
    legal_docs_version = models.CharField('Версия юр. документов', max_length=32, blank=True)
    legal_acceptance_ip = models.GenericIPAddressField('IP при согласии', null=True, blank=True)
    legal_acceptance_user_agent = models.CharField('User-Agent при согласии', max_length=512, blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Заявка на покупку'
        verbose_name_plural = 'Заявки на покупку'
        ordering = ['-created_at']

    def __str__(self):
        return f'Заявка #{self.pk} от {self.created_at.strftime("%d.%m.%Y %H:%M")} — {self.phone}'


class PromoCode(models.Model):
    """Промокод: скидка покупателю и бонус партнёру при оплате заказа."""
    code = models.CharField(
        'Код',
        max_length=64,
        unique=True,
        db_index=True,
    )
    label = models.CharField(
        'Название / партнёр',
        max_length=255,
        blank=True,
        help_text='Для отображения в админке',
    )
    discount_amount = models.DecimalField(
        'Скидка покупателю (₽)',
        max_digits=12,
        decimal_places=2,
        default=Decimal('500'),
    )
    partner_bonus = models.DecimalField(
        'Бонус партнёру за заказ (₽)',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    partner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promo_codes_as_partner',
        verbose_name='Партнёр (получатель бонуса)',
    )
    is_active = models.BooleanField('Активен', default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Промокод'
        verbose_name_plural = 'Промокоды'
        ordering = ['-created_at']

    def __str__(self):
        return self.code


class Order(models.Model):
    """Заказ: пользователь (или гость), статус, сумма, контакты, доставка."""

    PAYMENT_METHOD_BANK_CARD = 'bank_card'
    PAYMENT_METHOD_SBP = 'sbp'
    PAYMENT_METHOD_MANAGER_PAYMENT = 'manager_payment'
    PAYMENT_METHOD_ONLINE = 'online_payment'
    PAYMENT_METHOD_CASH_ON_DELIVERY = 'cash_on_delivery'
    CONTACT_CHANNEL_CALL = 'call'
    CONTACT_CHANNEL_TELEGRAM = 'telegram'
    CONTACT_CHANNEL_WHATSAPP = 'whatsapp'
    CONTACT_CHANNEL_EMAIL = 'email'
    CONTACT_CHANNEL_CHOICES = [
        (CONTACT_CHANNEL_CALL, 'Звонок'),
        (CONTACT_CHANNEL_TELEGRAM, 'Telegram'),
        (CONTACT_CHANNEL_WHATSAPP, 'WhatsApp'),
        (CONTACT_CHANNEL_EMAIL, 'Email'),
    ]
    STATUS_NEW = 'new'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_PAID = STATUS_CONFIRMED
    STATUS_SHIPPING = 'shipping'
    STATUS_READY_FOR_PICKUP = 'ready_for_pickup'
    STATUS_DONE = 'done'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_NEW, 'Новый'),
        (STATUS_CONFIRMED, 'Подтверждён'),
        (STATUS_SHIPPING, 'В доставке'),
        (STATUS_READY_FOR_PICKUP, 'Готов к выдаче'),
        (STATUS_DONE, 'Выполнен'),
        (STATUS_CANCELLED, 'Отменён'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Пользователь',
    )
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
        db_index=True,
    )
    total = models.DecimalField(
        'Сумма заказа (до скидки)',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    promo_code = models.ForeignKey(
        PromoCode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Промокод',
    )
    promo_discount = models.DecimalField(
        'Скидка по промокоду (₽)',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    partner_bonus_applied = models.BooleanField(
        'Бонус партнёру начислен',
        default=False,
    )
    stock_decreased = models.BooleanField(
        'Остаток списан',
        default=False,
    )
    PAYMENT_METHOD_BANK_TRANSFER = 'bank_transfer'
    PAYMENT_METHOD_INVOICE = 'invoice'
    PUBLIC_PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_SBP, 'СБП после подтверждения менеджером'),
        (PAYMENT_METHOD_BANK_TRANSFER, 'Перевод по реквизитам после подтверждения'),
        (PAYMENT_METHOD_CASH_ON_DELIVERY, 'Наличные при самовывозе'),
        (PAYMENT_METHOD_INVOICE, 'Счёт для юрлица'),
    ]
    LEGACY_PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_BANK_CARD, 'Перевод на карту (архивный способ)'),
        (PAYMENT_METHOD_MANAGER_PAYMENT, 'Через менеджера для юрлиц (архивный способ)'),
        (PAYMENT_METHOD_ONLINE, 'Банковская карта (архивный способ)'),
    ]
    PAYMENT_METHOD_CHOICES = PUBLIC_PAYMENT_METHOD_CHOICES + LEGACY_PAYMENT_METHOD_CHOICES
    PAYMENT_STATUS_UNPAID = 'unpaid'
    PAYMENT_STATUS_PENDING_CONFIRMATION = 'pending_confirmation'
    PAYMENT_STATUS_PAID = 'paid'
    PAYMENT_STATUS_REFUNDED = 'refunded'
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_UNPAID, 'Не оплачено'),
        (PAYMENT_STATUS_PENDING_CONFIRMATION, 'Ожидает подтверждения'),
        (PAYMENT_STATUS_PAID, 'Оплачено'),
        (PAYMENT_STATUS_REFUNDED, 'Возвращено'),
    ]
    DELIVERY_COURIER = 'courier'
    DELIVERY_PICKUP = 'pickup'
    DELIVERY_POST = 'post'
    DELIVERY_NEGOTIABLE = 'negotiable'
    DELIVERY_CDEK_COURIER = 'cdek_courier'
    DELIVERY_CITY = 'city_delivery'
    DELIVERY_OTHER_TRANSPORT = 'other_transport'
    DELIVERY_CDEK_PVZ = 'cdek_pvz'
    DELIVERY_CHOICES = [
        (DELIVERY_CDEK_PVZ, 'CDEK до ПВЗ'),
        (DELIVERY_CDEK_COURIER, 'CDEK курьер'),
        (DELIVERY_COURIER, 'Курьером'),
        (DELIVERY_PICKUP, 'Самовывоз'),
        (DELIVERY_CITY, 'Доставка по городу'),
        (DELIVERY_OTHER_TRANSPORT, 'Другая ТК'),
        (DELIVERY_POST, 'Почтой'),
        (DELIVERY_NEGOTIABLE, 'По договорённости'),
    ]
    payment_method = models.CharField(
        'Способ оплаты',
        max_length=32,
        choices=PAYMENT_METHOD_CHOICES,
        default=PAYMENT_METHOD_SBP,
    )
    contact_channel = models.CharField(
        'Предпочтительный канал связи',
        max_length=20,
        choices=CONTACT_CHANNEL_CHOICES,
        default=CONTACT_CHANNEL_CALL,
    )
    contact_handle = models.CharField(
        'Контакт в выбранном канале',
        max_length=150,
        blank=True,
    )
    payment_status = models.CharField(
        'Статус оплаты',
        max_length=32,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_STATUS_UNPAID,
        db_index=True,
    )
    delivery_type = models.CharField(
        'Способ доставки',
        max_length=20,
        choices=DELIVERY_CHOICES,
        default=DELIVERY_CDEK_PVZ,
        blank=True,
    )
    city = models.ForeignKey(
        'catalog.City',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Город',
    )
    pickup_point = models.ForeignKey(
        'catalog.PickupPoint',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Точка выдачи',
    )
    phone = models.CharField('Телефон', max_length=20, blank=True)
    email = models.EmailField('Email', blank=True)
    first_name = models.CharField('Имя', max_length=150, blank=True)
    last_name = models.CharField('Фамилия', max_length=150, blank=True)
    recipient_name = models.CharField('Получатель', max_length=255, blank=True)
    recipient_phone = models.CharField('Телефон получателя', max_length=20, blank=True)
    recipient_is_customer = models.BooleanField('Получатель совпадает с покупателем', default=True)
    country = models.CharField('Страна', max_length=120, blank=True)
    city_text = models.CharField('Город', max_length=120, blank=True)
    postal_code = models.CharField('Индекс', max_length=20, blank=True)
    address_line = models.TextField('Адрес доставки (структурированный)', blank=True)
    delivery_comment = models.TextField('Комментарий для доставки', blank=True)
    address = models.TextField('Адрес доставки', blank=True)
    cdek_office_snapshot = models.JSONField('Снимок ПВЗ CDEK', default=dict, blank=True)
    cdek_tariff_snapshot = models.JSONField('Снимок тарифа CDEK', default=dict, blank=True)
    business_company_name = models.CharField('Организация', max_length=255, blank=True)
    business_inn = models.CharField('ИНН организации', max_length=32, blank=True)
    business_kpp = models.CharField('КПП организации', max_length=32, blank=True)
    business_checking_account = models.CharField('Номер счёта', max_length=64, blank=True)
    business_bank_name = models.CharField('Банк', max_length=255, blank=True)
    business_bik = models.CharField('БИК', max_length=20, blank=True)
    business_correspondent_account = models.CharField('Корр. счёт банка', max_length=64, blank=True)
    business_phone = models.CharField('Телефон юр. лица', max_length=40, blank=True)
    business_telegram = models.CharField('Telegram юр. лица', max_length=120, blank=True)
    business_whatsapp = models.CharField('WhatsApp юр. лица', max_length=120, blank=True)
    delivery_cost = models.DecimalField(
        'Стоимость доставки',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    comment = models.TextField('Комментарий', blank=True)
    guest_access_token = models.CharField('Токен гостевого доступа', max_length=64, blank=True, db_index=True)
    guest_access_expires_at = models.DateTimeField('Гостевой доступ действует до', null=True, blank=True)
    legal_accepted_at = models.DateTimeField('Согласие с юр. документами', null=True, blank=True)
    legal_docs_version = models.CharField('Версия юр. документов', max_length=32, blank=True)
    legal_acceptance_ip = models.GenericIPAddressField('IP при согласии', null=True, blank=True)
    legal_acceptance_user_agent = models.CharField('User-Agent при согласии', max_length=512, blank=True)
    created_at = models.DateTimeField('Дата создания', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        ordering = ['-created_at']

    def __str__(self):
        return f'Заказ #{self.pk} от {self.created_at.strftime("%d.%m.%Y")}'

    @property
    def total_to_pay(self):
        """Сумма к оплате за товар с учётом промо-скидки."""
        return self.total - self.promo_discount

    @property
    def total_with_delivery(self):
        return self.total_to_pay + self.delivery_cost

    @property
    def is_guest_order(self):
        return self.user_id is None

    @property
    def shipping_contact_name(self):
        if self.recipient_name:
            return self.recipient_name
        return ' '.join(part for part in [self.first_name, self.last_name] if part).strip()

    @property
    def shipping_phone(self):
        return self.recipient_phone or self.phone

    @property
    def display_address(self):
        return self.address_line or self.address

    @property
    def cdek_office_code(self):
        return (self.cdek_office_snapshot or {}).get('code', '')

    @property
    def cdek_office_name(self):
        return (self.cdek_office_snapshot or {}).get('name', '')

    @property
    def cdek_office_address(self):
        return (self.cdek_office_snapshot or {}).get('address', '')

    @property
    def cdek_office_work_time(self):
        return (self.cdek_office_snapshot or {}).get('work_time', '')

    @property
    def public_delivery_label(self):
        if self.delivery_type == self.DELIVERY_PICKUP:
            return 'Самовывоз'
        if self.delivery_type == self.DELIVERY_CDEK_PVZ:
            return 'CDEK до ПВЗ'
        if self.delivery_type == self.DELIVERY_CDEK_COURIER:
            return 'CDEK курьер'
        if self.delivery_type in {self.DELIVERY_COURIER, self.DELIVERY_CITY}:
            return 'Доставка по адресу'
        if self.delivery_type == self.DELIVERY_POST:
            return 'Почтовая доставка'
        if self.delivery_type == self.DELIVERY_OTHER_TRANSPORT:
            return 'Другая транспортная компания'
        if self.delivery_type:
            return 'Доставка'
        return 'Способ доставки уточняется'

    def refresh_guest_access(self, *, ttl_days=30):
        self.guest_access_token = secrets.token_urlsafe(24)
        self.guest_access_expires_at = timezone.now() + timezone.timedelta(days=ttl_days)
        return self.guest_access_token

    def is_guest_access_valid(self, token):
        if not self.is_guest_order:
            return False
        if not token or token != self.guest_access_token:
            return False
        if not self.guest_access_expires_at:
            return False
        return self.guest_access_expires_at >= timezone.now()


class OrderNotificationLog(models.Model):
    EVENT_ORDER_CREATED = 'order_created'
    EVENT_ORDER_CONFIRMED = 'order_confirmed'
    EVENT_PAYMENT_RECEIVED = 'payment_received'
    EVENT_ORDER_SHIPPED = 'order_shipped'
    EVENT_ORDER_READY = 'order_ready_for_pickup'
    EVENT_ORDER_CANCELLED = 'order_cancelled'
    EVENT_CHOICES = [
        (EVENT_ORDER_CREATED, 'Заказ создан'),
        (EVENT_ORDER_CONFIRMED, 'Заказ подтверждён'),
        (EVENT_PAYMENT_RECEIVED, 'Оплата получена'),
        (EVENT_ORDER_SHIPPED, 'Заказ отправлен'),
        (EVENT_ORDER_READY, 'Заказ готов к выдаче'),
        (EVENT_ORDER_CANCELLED, 'Заказ отменён'),
    ]
    CHANNEL_EMAIL = 'email'
    CHANNEL_SMS = 'sms'
    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, 'Email'),
        (CHANNEL_SMS, 'SMS'),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='notification_logs',
        verbose_name='Заказ',
    )
    event = models.CharField('Событие', max_length=40, choices=EVENT_CHOICES)
    channel = models.CharField('Канал', max_length=16, choices=CHANNEL_CHOICES)
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Лог уведомления заказа'
        verbose_name_plural = 'Логи уведомлений заказа'
        constraints = [
            models.UniqueConstraint(
                fields=['order', 'event', 'channel'],
                name='orders_notificationlog_unique_order_event_channel',
            ),
        ]
        ordering = ['-created_at']


class OrderItem(models.Model):
    """Позиция заказа: товар, количество, цена на момент заказа."""
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

    CONDITION_NEW = 'new'
    CONDITION_USED = 'used'
    CONDITION_REFURBISHED = 'refurbished'
    CONDITION_CHOICES = [
        (CONDITION_NEW, 'Новый'),
        (CONDITION_USED, 'Б/у'),
        (CONDITION_REFURBISHED, 'Refurbished'),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Заказ',
    )
    line_type = models.CharField(
        'Тип строки',
        max_length=16,
        choices=LINE_TYPE_CHOICES,
        default=LINE_TYPE_CATALOG,
        db_index=True,
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='order_items',
        verbose_name='Товар',
    )
    product_name = models.CharField(
        'Название товара',
        max_length=300,
        blank=True,
        help_text='Снапшот названия на момент заказа или ручное название, если позиции нет в каталоге.',
    )
    custom_sku = models.CharField(
        'Произвольный SKU',
        max_length=64,
        blank=True,
        help_text='Используется только для произвольных строк сделки.',
    )
    product_image_url = models.CharField(
        'Изображение товара',
        max_length=500,
        blank=True,
        help_text='Снапшот изображения для ручных и архивных позиций.',
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='order_items',
        verbose_name='Вариант',
    )
    quantity = models.PositiveIntegerField('Количество', default=1)
    cancelled_quantity = models.PositiveIntegerField('Операционно отменено', default=0)
    price = models.DecimalField(
        'Цена за единицу',
        max_digits=12,
        decimal_places=2,
    )
    is_on_request = models.BooleanField(
        'Под заказ',
        default=False,
        help_text='Товар был заказан при отсутствии на складе',
    )
    variant_name = models.CharField(
        'Вариант',
        max_length=100,
        blank=True,
        help_text='Цвет, размер и т.п. — для отображения в заказе',
    )
    condition = models.CharField(
        'Состояние',
        max_length=20,
        choices=CONDITION_CHOICES,
        default=CONDITION_NEW,
    )
    purchase_price = models.DecimalField(
        'Эффективная себестоимость за единицу',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    planned_unit_cost = models.DecimalField(
        'Плановая себестоимость за единицу',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    actual_unit_cost = models.DecimalField(
        'Фактическая себестоимость за единицу',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    cost_status = models.CharField(
        'Статус себестоимости',
        max_length=16,
        choices=COST_STATUS_CHOICES,
        default=COST_STATUS_NONE,
        db_index=True,
    )
    discount_amount = models.DecimalField(
        'Скидка за единицу',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    comment = models.TextField('Комментарий', blank=True)

    class Meta:
        verbose_name = 'Позиция заказа'
        verbose_name_plural = 'Позиции заказа'
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
                name='order_item_line_type_integrity',
            ),
            models.CheckConstraint(
                condition=Q(planned_unit_cost__gte=0),
                name='order_item_planned_unit_cost_gte_zero',
            ),
            models.CheckConstraint(
                condition=Q(actual_unit_cost__gte=0),
                name='order_item_actual_unit_cost_gte_zero',
            ),
            models.CheckConstraint(
                condition=Q(cancelled_quantity__gte=0),
                name='order_item_cancelled_quantity_gte_zero',
            ),
            models.CheckConstraint(
                condition=Q(cancelled_quantity__lte=models.F('quantity')),
                name='order_item_cancelled_quantity_lte_quantity',
            ),
        ]

    def __str__(self):
        return f'{self.display_name} x {self.quantity}'

    def save(self, *args, **kwargs):
        if self.line_type == self.LINE_TYPE_CUSTOM:
            self.product = None
            self.variant = None
        elif self.product_id:
            self.line_type = self.LINE_TYPE_CATALOG
        if self.planned_unit_cost in (None, Decimal('0')) and self.purchase_price:
            self.planned_unit_cost = self.purchase_price
        if self.actual_unit_cost and self.actual_unit_cost > 0:
            self.cost_status = self.COST_STATUS_ACTUAL
        elif self.planned_unit_cost and self.planned_unit_cost > 0 and self.cost_status == self.COST_STATUS_NONE:
            self.cost_status = self.COST_STATUS_PLANNED
        self.purchase_price = self.effective_unit_cost
        if self.product_id:
            if not (self.product_name or '').strip():
                self.product_name = self.product.name
            if not (self.product_image_url or '').strip():
                self.product_image_url = resolve_order_item_image_url(product=self.product, variant=self.variant)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            normalized_fields = set(update_fields)
            normalized_fields.update(
                {
                    'line_type',
                    'product',
                    'variant',
                    'product_name',
                    'product_image_url',
                    'planned_unit_cost',
                    'actual_unit_cost',
                    'cost_status',
                    'purchase_price',
                }
            )
            kwargs['update_fields'] = list(normalized_fields)
        super().save(*args, **kwargs)

    def clean(self):
        if self.line_type == self.LINE_TYPE_CATALOG and not self.product_id:
            raise ValidationError({'product': 'Для каталоговой строки выберите товар.'})
        if self.line_type == self.LINE_TYPE_CUSTOM and self.product_id:
            raise ValidationError({'product': 'Произвольная строка не должна ссылаться на товар каталога.'})
        if not self.product_id and not (self.product_name or '').strip():
            raise ValidationError({'product_name': 'Укажите название позиции.'})
        if self.variant_id and not self.product_id:
            raise ValidationError({'variant': 'Вариант можно указать только для товара из каталога.'})
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({'variant': 'Вариант должен относиться к выбранному товару.'})
        if self.product_id and self.product.variants.exists() and not self.variant_id:
            raise ValidationError({'variant': 'Для товара с вариантами выберите конкретный вариант.'})
        if self.product_id and not (self.product_name or '').strip():
            self.product_name = self.product.name
        if self.product_id and not (self.product_image_url or '').strip():
            self.product_image_url = resolve_order_item_image_url(product=self.product, variant=self.variant)
        if self.line_type == self.LINE_TYPE_CATALOG and (self.custom_sku or '').strip():
            raise ValidationError({'custom_sku': 'Для каталоговой строки произвольный SKU не используется.'})
        if self.planned_unit_cost and self.actual_unit_cost and self.actual_unit_cost < 0:
            raise ValidationError({'actual_unit_cost': 'Фактическая себестоимость не может быть отрицательной.'})
        if self.cancelled_quantity > self.quantity:
            raise ValidationError({'cancelled_quantity': 'Операционно отмененное количество не может превышать количество строки.'})

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    @property
    def unit_price(self):
        return max(self.price - self.discount_amount, Decimal('0'))

    @property
    def discount_total(self):
        return self.discount_amount * self.quantity

    @property
    def sale_total(self):
        return self.subtotal

    @property
    def is_catalog_item(self):
        return bool(self.product_id)

    @property
    def active_quantity(self):
        return max(int(self.quantity or 0) - int(self.cancelled_quantity or 0), 0)

    @property
    def shipped_quantity(self):
        return min(
            sum(int(allocation.shipped_qty or 0) for allocation in self.allocations.filter(status='shipped')),
            self.active_quantity,
        )

    @property
    def covered_quantity(self):
        return min(
            sum(
                int(link.active_reserved_quantity or 0)
                for link in self.reservation_links.filter(
                    reservation__status__in={'draft', 'active', 'partial'}
                ).select_related('reservation')
            ),
            self.active_quantity,
        )

    @property
    def planned_sale_total(self):
        return self.unit_price * Decimal(self.active_quantity)

    @property
    def actual_sale_total(self):
        return self.unit_price * Decimal(self.shipped_quantity)

    @property
    def coverage_status(self):
        if self.active_quantity <= 0:
            return 'cancelled'
        if self.covered_quantity <= 0:
            return 'uncovered'
        if self.covered_quantity >= self.active_quantity:
            return 'covered'
        return 'partially_covered'

    @property
    def shipment_status(self):
        if self.active_quantity <= 0:
            return 'cancelled'
        if self.shipped_quantity <= 0:
            return 'unshipped'
        if self.shipped_quantity >= self.active_quantity:
            return 'shipped'
        return 'partially_shipped'

    @property
    def fulfillment_status(self):
        if self.shipped_quantity >= self.active_quantity and self.active_quantity > 0:
            return 'fulfilled'
        if self.covered_quantity > 0:
            return 'covered'
        return 'uncovered'

    @property
    def effective_unit_cost(self):
        if self.cost_status == self.COST_STATUS_ACTUAL and Decimal(self.actual_unit_cost or 0) > 0:
            return Decimal(self.actual_unit_cost or 0)
        if self.cost_status in {self.COST_STATUS_PLANNED, self.COST_STATUS_ACTUAL} and Decimal(self.planned_unit_cost or 0) > 0:
            return Decimal(self.planned_unit_cost or 0)
        return Decimal(self.purchase_price or 0)

    @property
    def planned_cost_total(self):
        return Decimal(self.planned_unit_cost or 0) * Decimal(self.active_quantity)

    @property
    def actual_cost_total(self):
        return Decimal(self.actual_unit_cost or 0) * Decimal(self.shipped_quantity)

    @property
    def effective_cost_total(self):
        return self.effective_unit_cost * Decimal(self.active_quantity)

    @property
    def planned_margin_total(self):
        return self.planned_sale_total - self.planned_cost_total

    @property
    def actual_margin_total(self):
        return self.actual_sale_total - self.actual_cost_total

    @property
    def resolved_product_name(self):
        if (self.product_name or '').strip():
            return self.product_name.strip()
        if self.product_id:
            return self.product.name
        return 'Товар'

    @property
    def resolved_variant_name(self):
        if (self.variant_name or '').strip():
            return self.variant_name.strip()
        if self.variant_id:
            return self.variant.name
        return ''

    @property
    def display_name(self):
        variant_label = self.resolved_variant_name
        if variant_label:
            return f'{self.resolved_product_name} ({variant_label})'
        return self.resolved_product_name

    @property
    def display_image_url(self):
        if (self.product_image_url or '').strip():
            return self.product_image_url.strip()
        if self.product_id:
            return resolve_order_item_image_url(product=self.product, variant=self.variant)
        return ''

    @property
    def sku(self):
        if (self.custom_sku or '').strip():
            return self.custom_sku.strip()
        if self.variant_id and getattr(self.variant, 'sku', ''):
            return self.variant.sku.strip()
        if self.product_id:
            return (self.product.sku or '').strip()
        return ''
