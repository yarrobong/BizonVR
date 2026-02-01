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
    """Профиль пользователя: телефон, баланс."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    phone = models.CharField('Телефон', max_length=20, unique=True, db_index=True)
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

    class Meta:
        verbose_name = 'Код подтверждения'
        verbose_name_plural = 'Коды подтверждения'
        ordering = ['-created_at']
