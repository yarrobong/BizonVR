from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0018_order_business_bank_name_order_business_bik_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='product_image_url',
            field=models.CharField(
                blank=True,
                help_text='Снапшот изображения для ручных и архивных позиций.',
                max_length=500,
                verbose_name='Изображение товара',
            ),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='product_name',
            field=models.CharField(
                blank=True,
                help_text='Снапшот названия на момент заказа или ручное название, если позиции нет в каталоге.',
                max_length=300,
                verbose_name='Название товара',
            ),
        ),
        migrations.AlterField(
            model_name='orderitem',
            name='product',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name='order_items',
                to='catalog.product',
                verbose_name='Товар',
            ),
        ),
    ]
