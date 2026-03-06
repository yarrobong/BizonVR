# Generated manually for saved addresses

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0029_unify_product_images'),
        ('accounts', '0009_profile_privacy_policy_version_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedAddress',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(max_length=120, verbose_name='Название адреса')),
                ('recipient_name', models.CharField(max_length=255, verbose_name='Получатель')),
                ('phone', models.CharField(max_length=40, verbose_name='Телефон')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='Email')),
                ('delivery_type', models.CharField(choices=[('courier', 'Курьером'), ('pickup', 'Самовывоз'), ('post', 'Почтой')], max_length=20, verbose_name='Способ доставки')),
                ('address', models.TextField(blank=True, verbose_name='Адрес')),
                ('comment', models.TextField(blank=True, verbose_name='Комментарий')),
                ('is_default', models.BooleanField(default=False, verbose_name='Адрес по умолчанию')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
                ('pickup_point', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='saved_addresses', to='catalog.pickuppoint', verbose_name='Точка выдачи')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_addresses', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={
                'verbose_name': 'Сохранённый адрес',
                'verbose_name_plural': 'Сохранённые адреса',
                'ordering': ['-is_default', '-updated_at', '-id'],
            },
        ),
        migrations.AddConstraint(
            model_name='savedaddress',
            constraint=models.UniqueConstraint(condition=models.Q(('is_default', True)), fields=('user',), name='accounts_savedaddress_single_default_per_user'),
        ),
    ]
