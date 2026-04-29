from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0024_order_cdek_snapshots'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='payment_method',
            field=models.CharField(
                choices=[
                    ('manager_contact', 'Оплату согласует менеджер'),
                    ('bank_transfer', 'Перевод по реквизитам после подтверждения (архивный способ)'),
                    ('cash_on_delivery', 'Наличные при самовывозе (архивный способ)'),
                    ('invoice', 'Счёт для юрлица (архивный способ)'),
                    ('bank_card', 'Перевод на карту (архивный способ)'),
                    ('manager_payment', 'Через менеджера для юрлиц (архивный способ)'),
                    ('online_payment', 'Банковская карта (архивный способ)'),
                ],
                default='manager_contact',
                max_length=32,
                verbose_name='Способ оплаты',
            ),
        ),
    ]
