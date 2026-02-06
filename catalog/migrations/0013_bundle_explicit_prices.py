from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0012_add_product_bundle'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductBundleItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.PositiveIntegerField(default=1, verbose_name='Количество')),
                ('price', models.DecimalField(
                    decimal_places=2,
                    help_text='Цена за единицу при покупке в составе набора',
                    max_digits=12,
                    verbose_name='Цена в наборе (₽)',
                )),
                ('bundle', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='catalog.productbundle',
                    verbose_name='Набор',
                )),
                ('product', models.ForeignKey(
                    limit_choices_to={'is_active': True},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='bundle_items',
                    to='catalog.product',
                    verbose_name='Товар',
                )),
            ],
            options={
                'verbose_name': 'Позиция набора',
                'verbose_name_plural': 'Позиции набора',
                'ordering': ('bundle', 'id'),
            },
        ),
        migrations.AddConstraint(
            model_name='productbundleitem',
            constraint=models.UniqueConstraint(
                fields=('bundle', 'product'),
                name='catalog_bundleitem_bundle_product_unique',
            ),
        ),
        migrations.RemoveField(
            model_name='productbundle',
            name='discount_percent',
        ),
        migrations.RemoveField(
            model_name='productbundle',
            name='products',
        ),
    ]
