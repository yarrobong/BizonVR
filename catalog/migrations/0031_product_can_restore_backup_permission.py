from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0030_compareitem'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='product',
            options={
                'ordering': ('-created_at',),
                'permissions': (('can_restore_backup', 'Can restore catalog backup'),),
                'verbose_name': 'Товар',
                'verbose_name_plural': 'Товары',
            },
        ),
    ]
