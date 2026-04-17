from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0048_alter_product_price_nullable'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='product',
            options={
                'ordering': ('-created_at',),
                'permissions': (
                    ('can_restore_backup', 'Can restore catalog backup'),
                    ('can_import_catalog_json', 'Can import catalog from JSON'),
                ),
                'verbose_name': 'Товар',
                'verbose_name_plural': 'Товары',
            },
        ),
    ]
