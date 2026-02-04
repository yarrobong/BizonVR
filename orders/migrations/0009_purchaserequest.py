# Generated manually for purchase request feature

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0008_orderitem_is_on_request'),
    ]

    operations = [
        migrations.CreateModel(
            name='PurchaseRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(max_length=20, verbose_name='Телефон')),
                ('telegram', models.CharField(help_text='@username или ссылка', max_length=100, verbose_name='Telegram')),
                ('items', models.JSONField(default=list, verbose_name='Товары')),
                ('total', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Сумма')),
                ('status', models.CharField(choices=[('new', 'Новая'), ('contacted', 'Связались'), ('processed', 'Обработана'), ('cancelled', 'Отменена')], db_index=True, default='new', max_length=20, verbose_name='Статус')),
                ('comment', models.TextField(blank=True, verbose_name='Комментарий (админ)')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='Создана')),
            ],
            options={
                'verbose_name': 'Заявка на покупку',
                'verbose_name_plural': 'Заявки на покупку',
                'ordering': ['-created_at'],
            },
        ),
    ]
