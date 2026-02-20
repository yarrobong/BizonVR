from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0024_service'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CartShare',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, max_length=7, unique=True, verbose_name='Код')),
                ('items', models.JSONField(blank=True, default=list, verbose_name='Позиции')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('expires_at', models.DateTimeField(db_index=True, verbose_name='Действует до')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='created_cart_shares', to=settings.AUTH_USER_MODEL, verbose_name='Создал')),
            ],
            options={
                'verbose_name': 'Шаринг корзины',
                'verbose_name_plural': 'Шаринг корзины',
                'ordering': ['-created_at'],
            },
        ),
    ]
