from django.db import migrations, models


def backfill_dispatch_centric_fields(apps, schema_editor):
    Reservation = apps.get_model('manager_portal', 'Reservation')
    ReservationItem = apps.get_model('manager_portal', 'ReservationItem')
    Shipment = apps.get_model('manager_portal', 'Shipment')
    reservation_status_fulfilled = 'fulfilled'
    reservation_status_cancelled = 'cancelled'
    reservation_status_expired = 'expired'
    shipment_statuses_consumed = ['shipped', 'delivered']

    for item in ReservationItem.objects.select_related('reservation').all().iterator():
        update_fields = []
        status = item.reservation.status
        if status == reservation_status_fulfilled and item.fulfilled_quantity != item.quantity:
            item.fulfilled_quantity = item.quantity
            item.released_quantity = 0
            update_fields.extend(['fulfilled_quantity', 'released_quantity'])
        elif status in {reservation_status_cancelled, reservation_status_expired, 'released'} and item.released_quantity != item.quantity:
            item.fulfilled_quantity = 0
            item.released_quantity = item.quantity
            update_fields.extend(['fulfilled_quantity', 'released_quantity'])
        if update_fields:
            item.save(update_fields=update_fields)

    shipments = Shipment.objects.select_related('order', 'reservation').filter(
        status__in=shipment_statuses_consumed,
        inventory_consumed_at__isnull=True,
    )
    for shipment in shipments.iterator():
        order_proves_consumption = bool(shipment.order_id and shipment.order and shipment.order.stock_decreased)
        reservation_proves_consumption = bool(
            shipment.reservation_id and shipment.reservation and shipment.reservation.status == reservation_status_fulfilled
        )
        if not (order_proves_consumption or reservation_proves_consumption):
            continue
        shipment.inventory_consumed_at = (
            shipment.delivered_at
            or shipment.shipped_at
            or shipment.updated_at
            or shipment.created_at
        )
        shipment.save(update_fields=['inventory_consumed_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0018_inventorylot_salelineallocation_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseitem',
            name='cancelled_quantity',
            field=models.PositiveIntegerField(default=0, verbose_name='Операционно отменено'),
        ),
        migrations.AddField(
            model_name='reservationitem',
            name='fulfilled_quantity',
            field=models.PositiveIntegerField(default=0, verbose_name='Исполнено отгрузками'),
        ),
        migrations.AddField(
            model_name='reservationitem',
            name='released_quantity',
            field=models.PositiveIntegerField(default=0, verbose_name='Освобождено'),
        ),
        migrations.AddField(
            model_name='shipment',
            name='inventory_consumed_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Складской эффект проведен'),
        ),
        migrations.AlterField(
            model_name='reservation',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Черновик'),
                    ('active', 'Активно'),
                    ('partial', 'Частично выдано'),
                    ('released', 'Освобождено'),
                    ('fulfilled', 'Выполнено'),
                    ('cancelled', 'Отменено'),
                    ('expired', 'Истекло'),
                ],
                db_index=True,
                default='active',
                max_length=20,
                verbose_name='Статус',
            ),
        ),
        migrations.RunPython(backfill_dispatch_centric_fields, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='purchaseitem',
            constraint=models.CheckConstraint(condition=models.Q(('cancelled_quantity__gte', 0)), name='purchase_item_cancelled_quantity_gte_zero'),
        ),
        migrations.AddConstraint(
            model_name='purchaseitem',
            constraint=models.CheckConstraint(condition=models.Q(('cancelled_quantity__lte', models.F('quantity'))), name='purchase_item_cancelled_quantity_lte_quantity'),
        ),
        migrations.AddConstraint(
            model_name='reservationitem',
            constraint=models.CheckConstraint(condition=models.Q(('fulfilled_quantity__gte', 0)), name='reservation_item_fulfilled_quantity_gte_zero'),
        ),
        migrations.AddConstraint(
            model_name='reservationitem',
            constraint=models.CheckConstraint(condition=models.Q(('released_quantity__gte', 0)), name='reservation_item_released_quantity_gte_zero'),
        ),
        migrations.AddConstraint(
            model_name='reservationitem',
            constraint=models.CheckConstraint(condition=models.Q(('fulfilled_quantity__lte', models.F('quantity'))), name='reservation_item_fulfilled_quantity_lte_quantity'),
        ),
        migrations.AddConstraint(
            model_name='reservationitem',
            constraint=models.CheckConstraint(condition=models.Q(('released_quantity__lte', models.F('quantity'))), name='reservation_item_released_quantity_lte_quantity'),
        ),
        migrations.AddConstraint(
            model_name='reservationitem',
            constraint=models.CheckConstraint(
                condition=models.Q(('fulfilled_quantity__lte', models.F('quantity') - models.F('released_quantity'))),
                name='reservation_item_combined_quantity_lte_quantity',
            ),
        ),
    ]
