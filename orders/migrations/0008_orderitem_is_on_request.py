# Generated manually for order-on-request feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0007_order_stock_decreased'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='is_on_request',
            field=models.BooleanField(
                default=False,
                help_text='Товар был заказан при отсутствии на складе',
                verbose_name='Под заказ',
            ),
        ),
    ]
