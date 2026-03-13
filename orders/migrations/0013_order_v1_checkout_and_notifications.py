# Generated manually for guest checkout v1 and order notifications.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0012_order_legal_acceptance_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrderNotificationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.CharField(choices=[('order_created', 'Заказ создан'), ('order_confirmed', 'Заказ подтверждён'), ('payment_received', 'Оплата получена'), ('order_shipped', 'Заказ отправлен'), ('order_ready_for_pickup', 'Заказ готов к выдаче'), ('order_cancelled', 'Заказ отменён')], max_length=40, verbose_name='Событие')),
                ('channel', models.CharField(choices=[('email', 'Email'), ('sms', 'SMS')], max_length=16, verbose_name='Канал')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('order', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='notification_logs', to='orders.order', verbose_name='Заказ')),
            ],
            options={
                'verbose_name': 'Лог уведомления заказа',
                'verbose_name_plural': 'Логи уведомлений заказа',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='order',
            name='address_line',
            field=models.TextField(blank=True, verbose_name='Адрес доставки (структурированный)'),
        ),
        migrations.AddField(
            model_name='order',
            name='city_text',
            field=models.CharField(blank=True, max_length=120, verbose_name='Город'),
        ),
        migrations.AddField(
            model_name='order',
            name='country',
            field=models.CharField(blank=True, max_length=120, verbose_name='Страна'),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_comment',
            field=models.TextField(blank=True, verbose_name='Комментарий для доставки'),
        ),
        migrations.AddField(
            model_name='order',
            name='guest_access_expires_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Гостевой доступ действует до'),
        ),
        migrations.AddField(
            model_name='order',
            name='guest_access_token',
            field=models.CharField(blank=True, db_index=True, max_length=64, verbose_name='Токен гостевого доступа'),
        ),
        migrations.AddField(
            model_name='order',
            name='payment_method',
            field=models.CharField(choices=[('bank_transfer', 'Перевод по реквизитам'), ('invoice', 'Через менеджера для юрлиц'), ('manager_payment', 'Через менеджера')], default='bank_transfer', max_length=32, verbose_name='Способ оплаты'),
        ),
        migrations.AddField(
            model_name='order',
            name='payment_status',
            field=models.CharField(choices=[('unpaid', 'Не оплачено'), ('pending_confirmation', 'Ожидает подтверждения'), ('paid', 'Оплачено'), ('refunded', 'Возвращено')], db_index=True, default='unpaid', max_length=32, verbose_name='Статус оплаты'),
        ),
        migrations.AddField(
            model_name='order',
            name='postal_code',
            field=models.CharField(blank=True, max_length=20, verbose_name='Индекс'),
        ),
        migrations.AddField(
            model_name='order',
            name='recipient_is_customer',
            field=models.BooleanField(default=True, verbose_name='Получатель совпадает с покупателем'),
        ),
        migrations.AddField(
            model_name='order',
            name='recipient_name',
            field=models.CharField(blank=True, max_length=255, verbose_name='Получатель'),
        ),
        migrations.AddField(
            model_name='order',
            name='recipient_phone',
            field=models.CharField(blank=True, max_length=20, verbose_name='Телефон получателя'),
        ),
        migrations.AlterField(
            model_name='order',
            name='delivery_type',
            field=models.CharField(blank=True, choices=[('courier', 'Курьером'), ('pickup', 'Самовывоз'), ('post', 'Почтой'), ('negotiable', 'По договорённости')], default='courier', max_length=20, verbose_name='Способ доставки'),
        ),
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('new', 'Новый'), ('confirmed', 'Подтверждён'), ('shipping', 'В доставке'), ('ready_for_pickup', 'Готов к выдаче'), ('done', 'Выполнен'), ('cancelled', 'Отменён')], db_index=True, default='new', max_length=20, verbose_name='Статус'),
        ),
        migrations.AddConstraint(
            model_name='ordernotificationlog',
            constraint=models.UniqueConstraint(fields=('order', 'event', 'channel'), name='orders_notificationlog_unique_order_event_channel'),
        ),
    ]
