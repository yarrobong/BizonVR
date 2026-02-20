# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0025_cart_share'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='is_bundles_category',
            field=models.BooleanField(
                default=False,
                help_text='Вместо товаров в этой категории отображаются комплекты (наборы). Добавьте категорию в нужный раздел каталога.',
                verbose_name='Показывать наборы товаров',
            ),
        ),
    ]
