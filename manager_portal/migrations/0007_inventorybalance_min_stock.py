from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0006_legacyimportbatch_remove_managerdeal_reservation_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorybalance',
            name='min_stock',
            field=models.PositiveIntegerField(default=0, verbose_name='Минимальный остаток'),
        ),
    ]
