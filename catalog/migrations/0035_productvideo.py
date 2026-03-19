from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0034_product_sku_productvariant_sku'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductVideo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rutube_url', models.URLField(help_text='Вставьте обычную публичную ссылку на видео RUTUBE.', max_length=500, verbose_name='Ссылка RUTUBE')),
                ('rutube_video_id', models.CharField(blank=True, db_index=True, max_length=100, verbose_name='ID видео RUTUBE')),
                ('embed_url', models.URLField(blank=True, max_length=500, verbose_name='Embed URL')),
                ('thumbnail_url', models.URLField(blank=True, max_length=500, verbose_name='Постер')),
                ('title', models.CharField(blank=True, max_length=500, verbose_name='Заголовок видео')),
                ('order', models.PositiveIntegerField(db_index=True, default=0, verbose_name='Порядок')),
                ('product', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='videos', to='catalog.product', verbose_name='Товар')),
            ],
            options={
                'verbose_name': 'Видео товара',
                'verbose_name_plural': 'Видео товара',
                'ordering': ('order', 'id'),
            },
        ),
    ]
