# Generated manually for manager manual order entry

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0001_initial'),
        ('orders', '0015_orderitem_comment_orderitem_condition_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ManagerDeal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deal_type', models.CharField(choices=[('sale_on_request', 'Продажа под заказ'), ('sale_from_stock', 'Продажа из наличия'), ('trade_in', 'Трейд-ин'), ('avito_sale', 'Продажа Avito')], db_index=True, max_length=32, verbose_name='Тип сделки')),
                ('buyer_type', models.CharField(choices=[('individual', 'Физ. лицо'), ('business', 'Юр. лицо')], db_index=True, max_length=20, verbose_name='Тип покупателя')),
                ('customer_source', models.CharField(choices=[('website', 'Сайт'), ('avito', 'Avito'), ('telegram', 'Telegram'), ('whatsapp', 'WhatsApp'), ('call', 'Звонок'), ('repeat', 'Повторный клиент'), ('other', 'Другое')], default='website', max_length=20, verbose_name='Источник клиента')),
                ('deal_created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name='Дата создания сделки')),
                ('individual_full_name', models.CharField(blank=True, max_length=255, verbose_name='ФИО физ. лица')),
                ('individual_phone', models.CharField(blank=True, max_length=40, verbose_name='Телефон физ. лица')),
                ('individual_additional_phone', models.CharField(blank=True, max_length=40, verbose_name='Доп. телефон физ. лица')),
                ('individual_city', models.CharField(blank=True, max_length=120, verbose_name='Город физ. лица')),
                ('individual_pickup_address', models.TextField(blank=True, verbose_name='Адрес ПВЗ СДЭК физ. лица')),
                ('individual_delivery_address', models.TextField(blank=True, verbose_name='Адрес доставки физ. лица')),
                ('individual_messenger', models.CharField(blank=True, max_length=120, verbose_name='Telegram / WhatsApp')),
                ('individual_comment', models.TextField(blank=True, verbose_name='Комментарий по физ. лицу')),
                ('business_company_name', models.CharField(blank=True, max_length=255, verbose_name='Название компании')),
                ('business_inn', models.CharField(blank=True, max_length=32, verbose_name='ИНН')),
                ('business_kpp', models.CharField(blank=True, max_length=32, verbose_name='КПП')),
                ('business_ogrn', models.CharField(blank=True, max_length=32, verbose_name='ОГРН / ОГРНИП')),
                ('business_legal_address', models.TextField(blank=True, verbose_name='Юридический адрес')),
                ('business_contact_person', models.CharField(blank=True, max_length=255, verbose_name='Контактное лицо')),
                ('business_phone', models.CharField(blank=True, max_length=40, verbose_name='Телефон юр. лица')),
                ('business_email', models.EmailField(blank=True, max_length=254, verbose_name='Email юр. лица')),
                ('business_city', models.CharField(blank=True, max_length=120, verbose_name='Город юр. лица')),
                ('business_delivery_address', models.TextField(blank=True, verbose_name='Адрес доставки / ПВЗ юр. лица')),
                ('business_comment', models.TextField(blank=True, verbose_name='Комментарий по юр. лицу')),
                ('delivery_method', models.CharField(choices=[('cdek_pvz', 'СДЭК ПВЗ'), ('cdek_courier', 'СДЭК курьер'), ('pickup', 'Самовывоз'), ('city_delivery', 'Доставка по городу'), ('other_transport', 'Другая ТК')], default='cdek_pvz', max_length=20, verbose_name='Способ доставки')),
                ('delivery_from_city', models.CharField(blank=True, max_length=120, verbose_name='Город отправки')),
                ('delivery_to_city', models.CharField(blank=True, max_length=120, verbose_name='Город получения')),
                ('delivery_pickup_address', models.TextField(blank=True, verbose_name='Адрес ПВЗ СДЭК')),
                ('delivery_full_address', models.TextField(blank=True, verbose_name='Полный адрес доставки')),
                ('delivery_payer', models.CharField(choices=[('client', 'Клиент'), ('seller', 'Продавец'), ('included', 'Включена в цену')], default='client', max_length=20, verbose_name='Кто оплачивает доставку')),
                ('tracking_number', models.CharField(blank=True, max_length=120, verbose_name='Номер заказа / отправления')),
                ('shipment_status', models.CharField(choices=[('draft', 'Черновик'), ('pending', 'Готовится'), ('sent', 'Отправлено'), ('delivered', 'Получено')], default='draft', max_length=20, verbose_name='Статус отправки')),
                ('shipped_at', models.DateField(blank=True, null=True, verbose_name='Дата отправки')),
                ('planned_receipt_at', models.DateField(blank=True, null=True, verbose_name='Плановая дата получения')),
                ('prepayment_amount', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Предоплата')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлен')),
                ('order', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='manager_deal', to='orders.order', verbose_name='Заказ')),
                ('responsible_manager', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manager_deals', to=settings.AUTH_USER_MODEL, verbose_name='Ответственный менеджер')),
            ],
            options={
                'verbose_name': 'Сделка менеджера',
                'verbose_name_plural': 'Сделки менеджеров',
                'ordering': ['-deal_created_at', '-id'],
            },
        ),
    ]
