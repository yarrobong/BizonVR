# Generated manually for combined auth v1.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_merge_0012_email_and_email_verification'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='phone_verified_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Телефон подтверждён'),
        ),
        migrations.CreateModel(
            name='EmailLoginCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(db_index=True, max_length=254, verbose_name='Email')),
                ('code', models.CharField(max_length=10, verbose_name='Код')),
                ('purpose', models.CharField(choices=[('login', 'Вход'), ('order_claim', 'Привязка заказа')], default='login', max_length=20, verbose_name='Назначение')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('used_at', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Использован')),
            ],
            options={
                'verbose_name': 'Код входа по email',
                'verbose_name_plural': 'Коды входа по email',
                'ordering': ['-created_at'],
            },
        ),
    ]
