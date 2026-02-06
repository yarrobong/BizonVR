from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0015_alter_productbundle_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='products/', verbose_name='Изображение')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='images',
                    to='catalog.product',
                    verbose_name='Товар',
                )),
            ],
            options={
                'verbose_name': 'Фото товара',
                'verbose_name_plural': 'Фото товара',
                'ordering': ('order', 'id'),
            },
        ),
    ]
