# Generated manually for order-on-request feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0006_add_city_pickuppoint_productstock'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='allow_order_on_request',
            field=models.BooleanField(
                default=True,
                help_text='Если товара нет в наличии, покупатель может оформить заказ под заказ',
                verbose_name='Доступен под заказ',
            ),
        ),
    ]
