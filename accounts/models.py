"""
Модели для входа по телефону (Фаза 2) и ЛК — баланс (Фаза 3).
Реферальная система удалена; скидка по заказу — в orders (промо 500 ₽ за каждые 15 000 ₽).
"""
import re
from decimal import Decimal
from django.db import models
from django.conf import settings


def normalize_phone(raw: str) -> str:
    """Оставляем только цифры номера (для России: 10 цифр или 11 с 7/8)."""
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits[0] in ('7', '8'):
        return digits[1:]
    if len(digits) == 10:
        return digits
    return digits


class Profile(models.Model):
    """Профиль пользователя: телефон, баланс, контактное лицо."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    phone = models.CharField('Телефон', max_length=20, unique=True, db_index=True)
    contact_name = models.CharField('Контактное лицо (ФИО)', max_length=255, blank=True)
    privacy_agreed_at = models.DateTimeField('Согласие на обработку ПД', null=True, blank=True)
    privacy_policy_version = models.CharField('Версия политики ПД', max_length=32, blank=True)
    balance = models.DecimalField(
        'Баланс',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return self.phone


class CommercialProposalContact(models.Model):
    """Контакты для коммерческих предложений (не зависят от логина по телефону)."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cp_contact',
        verbose_name='Пользователь',
    )
    phone = models.CharField(
        'Телефон для связи в КП',
        max_length=40,
        blank=True,
        help_text='Номер, который будет указан в коммерческом предложении в блоке «Телефон для связи». Если не заполнен — подставляется телефон из профиля или общий номер сайта.',
    )
    email = models.EmailField(
        'Email для КП',
        blank=True,
        help_text='Email менеджера в КП (если нужен).',
    )
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Контакты для КП'
        verbose_name_plural = 'Контакты для КП'

    def __str__(self):
        return f'КП-контакты: {self.user}'


class SavedAddress(models.Model):
    """Сохранённый адрес/сценарий доставки пользователя для повторных заказов."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_addresses',
        verbose_name='Пользователь',
    )
    label = models.CharField('Название адреса', max_length=120)
    recipient_name = models.CharField('Получатель', max_length=255)
    phone = models.CharField('Телефон', max_length=40)
    email = models.EmailField('Email', blank=True)
    delivery_type = models.CharField(
        'Способ доставки',
        max_length=20,
        choices=[
            ('courier', 'Курьером'),
            ('pickup', 'Самовывоз'),
            ('post', 'Почтой'),
        ],
    )
    pickup_point = models.ForeignKey(
        'catalog.PickupPoint',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='saved_addresses',
        verbose_name='Точка выдачи',
    )
    address = models.TextField('Адрес', blank=True)
    comment = models.TextField('Комментарий', blank=True)
    is_default = models.BooleanField('Адрес по умолчанию', default=False)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Сохранённый адрес'
        verbose_name_plural = 'Сохранённые адреса'
        ordering = ['-is_default', '-updated_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_default=True),
                name='accounts_savedaddress_single_default_per_user',
            ),
        ]

    def __str__(self):
        return f'{self.user} — {self.label}'


class BalanceTransaction(models.Model):
    """Операция по балансу: пополнение, списание за заказ, бонус по промокоду."""
    TYPE_TOPUP = 'topup'
    TYPE_REFERRAL_BONUS = 'referral_bonus'  # для старых записей
    TYPE_ORDER_PAYMENT = 'order_payment'
    TYPE_PROMO_BONUS = 'promo_bonus'  # бонус партнёру за заказ по промокоду
    TYPE_CHOICES = [
        (TYPE_TOPUP, 'Пополнение'),
        (TYPE_REFERRAL_BONUS, 'Бонус за реферала'),
        (TYPE_ORDER_PAYMENT, 'Оплата заказа'),
        (TYPE_PROMO_BONUS, 'Бонус по промокоду'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='balance_transactions',
    )
    kind = models.CharField('Тип', max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField('Сумма', max_digits=12, decimal_places=2)
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='balance_operations',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Операция по балансу'
        verbose_name_plural = 'Операции по балансу'
        ordering = ['-created_at']


class PhoneVerificationCode(models.Model):
    """Код подтверждения по SMS: телефон, код, время создания (TTL 10 мин)."""
    phone = models.CharField(max_length=20, db_index=True)
    code = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = 'Код подтверждения'
        verbose_name_plural = 'Коды подтверждения'
        ordering = ['-created_at']
