from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0023_orderitem_cancelled_quantity'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='cdek_office_snapshot',
            field=models.JSONField(blank=True, default=dict, verbose_name='Снимок ПВЗ CDEK'),
        ),
        migrations.AddField(
            model_name='order',
            name='cdek_tariff_snapshot',
            field=models.JSONField(blank=True, default=dict, verbose_name='Снимок тарифа CDEK'),
        ),
    ]
