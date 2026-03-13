# Generated for Phase 5 (payment provider)

from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('orders', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.CharField(blank=True, db_index=True, max_length=64, verbose_name='ID у платёжного провайдера')),
                ('price_amount', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='Сумма (фиат)')),
                ('price_currency', models.CharField(default='usd', max_length=10, verbose_name='Валюта суммы')),
                ('pay_amount', models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True, verbose_name='Сумма у платёжного провайдера')),
                ('pay_currency', models.CharField(blank=True, max_length=20, verbose_name='Валюта провайдера')),
                ('pay_address', models.CharField(blank=True, max_length=256, verbose_name='Платёжный адрес / реквизит')),
                ('pay_url', models.URLField(blank=True, max_length=512, verbose_name='Ссылка на оплату')),
                ('status', models.CharField(choices=[('pending', 'Ожидает'), ('waiting', 'Ожидание оплаты'), ('confirming', 'Подтверждение'), ('sent', 'Отправлено'), ('finished', 'Оплачено'), ('failed', 'Ошибка'), ('refunded', 'Возврат'), ('expired', 'Истекло')], db_index=True, default='pending', max_length=20, verbose_name='Статус')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('ipn_data', models.JSONField(blank=True, null=True, verbose_name='Данные последнего IPN')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='orders.order', verbose_name='Заказ')),
            ],
            options={
                'verbose_name': 'Платёж',
                'verbose_name_plural': 'Платежи',
                'ordering': ['-created_at'],
            },
        ),
    ]
