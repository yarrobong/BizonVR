from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0022_alter_inventorymovement_movement_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='managerdeal',
            name='bitrix_deal_id',
            field=models.CharField(blank=True, db_index=True, max_length=64, verbose_name='ID сделки Bitrix'),
        ),
        migrations.AddField(
            model_name='managerdeal',
            name='bitrix_deal_url',
            field=models.URLField(blank=True, max_length=500, verbose_name='Ссылка на сделку Bitrix'),
        ),
    ]
