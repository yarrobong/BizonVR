from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0053_clear_bundle_cartitem_price_override'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='discount_percent',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Скидка применяется к цене из наличия товара и его вариантов.',
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name='Скидка, %',
            ),
        ),
        migrations.AlterField(
            model_name='productbundleitem',
            name='price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Рассчитывается автоматически по актуальной цене товара из наличия.',
                max_digits=12,
                null=True,
                verbose_name='Цена в наборе (₽)',
            ),
        ),
    ]
