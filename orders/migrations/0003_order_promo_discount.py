# Промо-скидка: 500 ₽ за каждые 15 000 ₽ заказа

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_add_delivery_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='promo_discount',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                max_digits=12,
                verbose_name='Промо-скидка (500 ₽ за каждые 15 000 ₽)',
            ),
        ),
    ]
