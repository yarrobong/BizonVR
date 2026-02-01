"""
Модель платежа (Фаза 5). Интеграция NowPayments.
"""
from decimal import Decimal
from django.db import models
from django.conf import settings


class Payment(models.Model):
    """Платёж: заказ, внешний id NowPayments, сумма, статус, адрес/ссылка оплаты."""
    STATUS_PENDING = 'pending'
    STATUS_WAITING = 'waiting'
    STATUS_CONFIRMING = 'confirming'
    STATUS_SENT = 'sent'
    STATUS_FINISHED = 'finished'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ожидает'),
        (STATUS_WAITING, 'Ожидание оплаты'),
        (STATUS_CONFIRMING, 'Подтверждение'),
        (STATUS_SENT, 'Отправлено'),
        (STATUS_FINISHED, 'Оплачено'),
        (STATUS_FAILED, 'Ошибка'),
        (STATUS_REFUNDED, 'Возврат'),
        (STATUS_EXPIRED, 'Истекло'),
    ]

    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name='Заказ',
    )
    external_id = models.CharField(
        'ID в NowPayments',
        max_length=64,
        blank=True,
        db_index=True,
    )
    price_amount = models.DecimalField(
        'Сумма (фиат)',
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
    )
    price_currency = models.CharField(
        'Валюта суммы',
        max_length=10,
        default='usd',
    )
    pay_amount = models.DecimalField(
        'Сумма к оплате (крипто)',
        max_digits=24,
        decimal_places=8,
        null=True,
        blank=True,
    )
    pay_currency = models.CharField(
        'Криптовалюта',
        max_length=20,
        blank=True,
    )
    pay_address = models.CharField(
        'Адрес для оплаты',
        max_length=256,
        blank=True,
    )
    pay_url = models.URLField(
        'Ссылка на оплату',
        max_length=512,
        blank=True,
    )
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Ответ IPN (сырой) для отладки — опционально
    ipn_data = models.JSONField(
        'Данные последнего IPN',
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'
        ordering = ['-created_at']

    def __str__(self):
        return f'Платёж #{self.pk} (заказ {self.order_id}, {self.status})'

    @property
    def is_pending(self):
        return self.status in (
            self.STATUS_PENDING,
            self.STATUS_WAITING,
            self.STATUS_CONFIRMING,
            self.STATUS_SENT,
        )

    @property
    def is_finished(self):
        return self.status == self.STATUS_FINISHED
