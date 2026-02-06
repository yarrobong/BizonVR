from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0010_contactrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='option_label',
            field=models.CharField(
                blank=True,
                help_text='Например: Цвет, Размер, Модель. Показывается над выбором варианта.',
                max_length=100,
                verbose_name='Подпись к вариантам',
            ),
        ),
        migrations.CreateModel(
            name='ProductVariant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='Название')),
                ('image', models.ImageField(blank=True, null=True, upload_to='products/', verbose_name='Изображение')),
                ('price_override', models.DecimalField(
                    blank=True,
                    decimal_places=2,
                    help_text='Пусто — использовать цену товара',
                    max_digits=12,
                    null=True,
                    verbose_name='Цена (переопределение)',
                )),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='variants',
                    to='catalog.product',
                    verbose_name='Товар',
                )),
            ],
            options={
                'verbose_name': 'Вариант товара',
                'verbose_name_plural': 'Варианты товара',
                'ordering': ('order', 'name'),
            },
        ),
    ]
