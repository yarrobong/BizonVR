# Generated manually for Phase 4

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='delivery_type',
            field=models.CharField(
                blank=True,
                choices=[('courier', 'Курьером'), ('pickup', 'Самовывоз'), ('post', 'Почтой')],
                default='courier',
                max_length=20,
                verbose_name='Способ доставки',
            ),
        ),
    ]
