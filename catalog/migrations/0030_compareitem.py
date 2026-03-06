# Generated manually for compare items

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0029_unify_product_images'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompareItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Добавлено')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='compared_by', to='catalog.product', verbose_name='Товар')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='compare_items', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={
                'verbose_name': 'Сравнение',
                'verbose_name_plural': 'Сравнение',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='compareitem',
            constraint=models.UniqueConstraint(fields=('user', 'product'), name='catalog_compareitem_user_product_unique'),
        ),
    ]
