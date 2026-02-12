# Generated manually — размер плитки категории в выпадающем меню каталога

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0020_seed_cities'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='tile_size',
            field=models.CharField(
                choices=[
                    ('small', 'Маленький квадрат (1×1)'),
                    ('medium', 'Широкий (2×1)'),
                    ('large', 'Большой квадрат (2×2)'),
                    ('tall', 'Высокий (1×2)'),
                ],
                default='small',
                max_length=10,
                verbose_name='Размер плитки в меню',
            ),
        ),
    ]
