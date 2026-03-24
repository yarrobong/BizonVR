from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0039_remove_compareitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='avito_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Прямая ссылка на этот же товар в Avito.',
                max_length=500,
                verbose_name='Ссылка на Avito',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='ozon_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Прямая ссылка на этот же товар в Ozon.',
                max_length=500,
                verbose_name='Ссылка на Ozon',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='wildberries_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Прямая ссылка на этот же товар в Wildberries.',
                max_length=500,
                verbose_name='Ссылка на Wildberries',
            ),
        ),
    ]
