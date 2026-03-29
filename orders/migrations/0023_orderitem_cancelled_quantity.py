from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0022_orderitem_actual_unit_cost_orderitem_cost_status_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='cancelled_quantity',
            field=models.PositiveIntegerField(default=0, verbose_name='Операционно отменено'),
        ),
        migrations.AddConstraint(
            model_name='orderitem',
            constraint=models.CheckConstraint(condition=models.Q(('cancelled_quantity__gte', 0)), name='order_item_cancelled_quantity_gte_zero'),
        ),
        migrations.AddConstraint(
            model_name='orderitem',
            constraint=models.CheckConstraint(condition=models.Q(('cancelled_quantity__lte', models.F('quantity'))), name='order_item_cancelled_quantity_lte_quantity'),
        ),
    ]
