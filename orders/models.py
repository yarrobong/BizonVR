"""
Модели заказа (Фаза 3–4). Order, OrderItem. Промокоды (скидка + бонус партнёру).
"""
from decimal import Decimal
from django.db import models
from django.conf import settings

from catalog.models import Product


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
    STATUS_NEW = 'new'
    STATUS_PAID = 'paid'
    STATUS_SHIPPING = 'shipping'
    STATUS_DONE = 'done'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_NEW, 'Новый'),
        (STATUS_PAID, 'Оплачен'),
        (STATUS_SHIPPING, 'В доставке'),
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
    DELIVERY_COURIER = 'courier'
    DELIVERY_PICKUP = 'pickup'
    DELIVERY_POST = 'post'
    DELIVERY_CHOICES = [
        (DELIVERY_COURIER, 'Курьером'),
        (DELIVERY_PICKUP, 'Самовывоз'),
        (DELIVERY_POST, 'Почтой'),
    ]
    delivery_type = models.CharField(
        'Способ доставки',
        max_length=20,
        choices=DELIVERY_CHOICES,
        default=DELIVERY_COURIER,
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
    address = models.TextField('Адрес доставки', blank=True)
    comment = models.TextField('Комментарий', blank=True)
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
        """Сумма к оплате с учётом промо-скидки."""
        return self.total - self.promo_discount


class OrderItem(models.Model):
    """Позиция заказа: товар, количество, цена на момент заказа."""
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Заказ',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='order_items',
        verbose_name='Товар',
    )
    quantity = models.PositiveIntegerField('Количество', default=1)
    price = models.DecimalField(
        'Цена за единицу',
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        verbose_name = 'Позиция заказа'
        verbose_name_plural = 'Позиции заказа'

    def __str__(self):
        return f'{self.product.name} x {self.quantity}'

    @property
    def subtotal(self):
        return self.price * self.quantity
