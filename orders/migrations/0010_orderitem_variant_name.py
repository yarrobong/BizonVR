from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0009_purchaserequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='variant_name',
            field=models.CharField(
                blank=True,
                help_text='Цвет, размер и т.п. — для отображения в заказе',
                max_length=100,
                verbose_name='Вариант',
            ),
        ),
    ]
