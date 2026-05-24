from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class WarehouseTransfer(models.Model):
    source_warehouse = models.ForeignKey(
        'manager_portal.Warehouse',
        on_delete=models.PROTECT,
        related_name='warehouse_ui_outgoing_transfers',
        verbose_name='Склад-источник',
    )
    target_warehouse = models.ForeignKey(
        'manager_portal.Warehouse',
        on_delete=models.PROTECT,
        related_name='warehouse_ui_incoming_transfers',
        verbose_name='Склад-получатель',
    )
    comment = models.CharField('Комментарий', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='warehouse_ui_transfers',
        verbose_name='Создал',
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Складское перемещение'
        verbose_name_plural = 'Складские перемещения'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.source_warehouse} -> {self.target_warehouse} #{self.pk}'

    def clean(self):
        if self.source_warehouse_id and self.target_warehouse_id and self.source_warehouse_id == self.target_warehouse_id:
            raise ValidationError({'target_warehouse': 'Склад назначения должен отличаться от склада-источника.'})


class WarehouseTransferLine(models.Model):
    transfer = models.ForeignKey(
        WarehouseTransfer,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name='Перемещение',
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.PROTECT,
        related_name='warehouse_ui_transfer_lines',
        verbose_name='Товар',
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='warehouse_ui_transfer_lines',
        verbose_name='Вариант',
    )
    source_lot = models.ForeignKey(
        'manager_portal.InventoryLot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='warehouse_ui_source_transfer_lines',
        verbose_name='Исходный лот',
    )
    target_lot = models.ForeignKey(
        'manager_portal.InventoryLot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='warehouse_ui_target_transfer_lines',
        verbose_name='Созданный лот',
    )
    quantity = models.PositiveIntegerField('Количество')
    unit_cost = models.DecimalField('Себестоимость за единицу', max_digits=12, decimal_places=2, default=Decimal('0'))
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Строка складского перемещения'
        verbose_name_plural = 'Строки складского перемещения'
        ordering = ['id']
        indexes = [
            models.Index(fields=['transfer', 'product', 'variant']),
        ]

    def __str__(self):
        return f'{self.product} x {self.quantity}'

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({'variant': 'Вариант должен относиться к выбранному товару.'})
