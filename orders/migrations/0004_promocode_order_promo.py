# Промокоды: модель PromoCode, связь с Order, флаг начисления бонуса партнёру

from decimal import Decimal
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_order_promo_discount'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PromoCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, max_length=64, unique=True, verbose_name='Код')),
                ('label', models.CharField(blank=True, help_text='Для отображения в админке', max_length=255, verbose_name='Название / партнёр')),
                ('discount_amount', models.DecimalField(decimal_places=2, default=Decimal('500'), max_digits=12, verbose_name='Скидка покупателю (₽)')),
                ('partner_bonus', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name='Бонус партнёру за заказ (₽)')),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='Активен')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('partner_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='promo_codes_as_partner', to=settings.AUTH_USER_MODEL, verbose_name='Партнёр (получатель бонуса)')),
            ],
            options={
                'verbose_name': 'Промокод',
                'verbose_name_plural': 'Промокоды',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='order',
            name='partner_bonus_applied',
            field=models.BooleanField(default=False, verbose_name='Бонус партнёру начислен'),
        ),
        migrations.AddField(
            model_name='order',
            name='promo_code',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='orders', to='orders.promocode', verbose_name='Промокод'),
        ),
    ]
