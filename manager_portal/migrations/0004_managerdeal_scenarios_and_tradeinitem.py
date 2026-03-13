# Generated manually for manager deal scenarios

import django.db.models.deletion
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0003_financedealtype_financedeal_financeexpensecategory_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='managerdeal',
            name='avito_commission',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Комиссия Avito'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='avito_contact_channel',
            field=models.CharField(blank=True, max_length=120, verbose_name='Канал обращения'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='avito_final_price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Финальная цена продажи'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='avito_list_price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Цена в объявлении'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='avito_listing_id',
            field=models.CharField(blank=True, max_length=120, verbose_name='ID объявления Avito'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='avito_listing_title',
            field=models.CharField(blank=True, max_length=255, verbose_name='Название объявления'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='avito_listing_url',
            field=models.URLField(blank=True, verbose_name='Ссылка на объявление Avito'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='customer_deadline',
            field=models.DateField(blank=True, null=True, verbose_name='Дедлайн клиента'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='customer_request',
            field=models.TextField(blank=True, verbose_name='Что хочет клиент'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='customer_request_comment',
            field=models.TextField(blank=True, verbose_name='Комментарий клиента'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='deal_status',
            field=models.CharField(choices=[('new_request', 'Новая заявка'), ('awaiting_prepayment', 'Ожидает предоплату'), ('prepayment_received', 'Предоплата получена'), ('supplier_ordered', 'Заказ размещен у поставщика'), ('in_transit', 'Товар в пути'), ('received', 'Товар поступил'), ('ready_to_ship', 'Готов к отправке'), ('shipped', 'Отправлен'), ('completed', 'Завершена'), ('cancelled', 'Отменена'), ('new', 'Новая'), ('reserved', 'Резерв создан'), ('awaiting_payment', 'Ожидает оплату'), ('paid', 'Оплачена'), ('assembling', 'Собирается'), ('awaiting_evaluation', 'Ожидает оценку'), ('evaluated', 'Оценено'), ('terms_agreed', 'Условия согласованы'), ('awaiting_device_shipment', 'Ожидает отправку устройства клиентом'), ('device_received', 'Устройство получено'), ('inspected', 'Проверено'), ('ready_for_exchange', 'Готово к обмену'), ('topup_received', 'Доплата получена'), ('new_item_shipped', 'Новый товар отправлен'), ('correspondence', 'Переписка'), ('booked', 'Бронь'), ('confirmed', 'Подтверждена'), ('received_by_customer', 'Получена')], db_index=True, default='new', max_length=40, verbose_name='Статус сделки'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='expected_arrival_date',
            field=models.DateField(blank=True, null=True, verbose_name='Ожидаемая дата поступления'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='expected_customer_ship_date',
            field=models.DateField(blank=True, null=True, verbose_name='Ожидаемая дата отправки клиенту'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='planned_purchase_date',
            field=models.DateField(blank=True, null=True, verbose_name='Плановая дата закупки'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='prepayment_required_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Требуемая предоплата'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='procurement_origin',
            field=models.CharField(blank=True, max_length=255, verbose_name='Откуда заказываем'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='reserve_created_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Резерв создан'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='reservation',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deal', to='manager_portal.reservation', verbose_name='Резерв'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='shipping_comment',
            field=models.TextField(blank=True, verbose_name='Комментарий по отправке'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='stock_warehouse',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manager_deals_from_stock', to='manager_portal.warehouse', verbose_name='Склад'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='supplier_agent',
            field=models.CharField(blank=True, max_length=255, verbose_name='Агент'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='supplier_name',
            field=models.CharField(blank=True, max_length=255, verbose_name='Поставщик'),
        ),
        migrations.CreateModel(
            name='TradeInItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_type', models.CharField(max_length=120, verbose_name='Тип устройства')),
                ('model_name', models.CharField(max_length=255, verbose_name='Модель')),
                ('version', models.CharField(blank=True, max_length=120, verbose_name='Версия')),
                ('kit_description', models.TextField(blank=True, verbose_name='Комплектация')),
                ('condition', models.CharField(max_length=120, verbose_name='Состояние')),
                ('is_working', models.BooleanField(default=True, verbose_name='Работает')),
                ('has_box', models.BooleanField(default=False, verbose_name='Есть коробка')),
                ('has_controllers', models.BooleanField(default=False, verbose_name='Есть контроллеры')),
                ('has_accessories', models.BooleanField(default=False, verbose_name='Есть ремешок / маска / доп. аксессуары')),
                ('defects', models.TextField(blank=True, verbose_name='Дефекты')),
                ('photo', models.ImageField(blank=True, upload_to='manager/tradein/', verbose_name='Фото устройства')),
                ('preliminary_estimate', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Предварительная оценка')),
                ('final_estimate', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Финальная оценка')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('deal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trade_in_items', to='manager_portal.managerdeal', verbose_name='Сделка')),
            ],
            options={
                'verbose_name': 'Позиция трейд-ин',
                'verbose_name_plural': 'Позиции трейд-ин',
                'ordering': ['id'],
            },
        ),
    ]
