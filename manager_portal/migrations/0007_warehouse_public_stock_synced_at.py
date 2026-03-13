from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0006_legacyimportbatch_remove_managerdeal_reservation_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='warehouse',
            name='public_stock_synced_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Публичный остаток синхронизирован'),
        ),
    ]
