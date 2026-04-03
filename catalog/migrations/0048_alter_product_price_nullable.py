from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0047_simplify_filters'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=12,
                null=True,
                verbose_name='Цена из наличия',
            ),
        ),
    ]
