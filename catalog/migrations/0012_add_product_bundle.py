from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0011_add_product_variants'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductBundle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('discount_percent', models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='Скидка, %')),
                ('name', models.CharField(blank=True, help_text='Опционально, для отображения в админке', max_length=200, verbose_name='Название набора')),
                ('products', models.ManyToManyField(
                    limit_choices_to={'is_active': True},
                    related_name='bundles',
                    to='catalog.product',
                    verbose_name='Товары',
                )),
            ],
            options={
                'verbose_name': 'Набор товаров',
                'verbose_name_plural': 'Наборы товаров',
            },
        ),
    ]
