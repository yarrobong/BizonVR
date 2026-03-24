from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0020_remove_order_cdek_fallback_to_nearest_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='contact_channel',
            field=models.CharField(
                choices=[
                    ('call', 'Звонок'),
                    ('telegram', 'Telegram'),
                    ('whatsapp', 'WhatsApp'),
                    ('email', 'Email'),
                ],
                default='call',
                max_length=20,
                verbose_name='Предпочтительный канал связи',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='contact_handle',
            field=models.CharField(blank=True, max_length=150, verbose_name='Контакт в выбранном канале'),
        ),
        migrations.AlterField(
            model_name='order',
            name='payment_method',
            field=models.CharField(
                choices=[
                    ('sbp', 'СБП после подтверждения менеджером'),
                    ('bank_transfer', 'Перевод по реквизитам после подтверждения'),
                    ('cash_on_delivery', 'Наличные при самовывозе'),
                    ('invoice', 'Счёт для юрлица'),
                    ('bank_card', 'Перевод на карту (архивный способ)'),
                    ('manager_payment', 'Через менеджера для юрлиц (архивный способ)'),
                    ('online_payment', 'Банковская карта (архивный способ)'),
                ],
                default='sbp',
                max_length=32,
                verbose_name='Способ оплаты',
            ),
        ),
    ]
