# Generated manually for product tags (Бестселлер, Выбор экспертов, Новинка, Акция)

from django.db import migrations, models


def create_default_tags(apps, schema_editor):
    ProductTag = apps.get_model('catalog', 'ProductTag')
    tags = [
        ('bestseller', 'Бестселлер', 0),
        ('expert-choice', 'Выбор экспертов', 1),
        ('new', 'Новинка', 2),
        ('sale', 'Акция', 3),
    ]
    for slug, name, order in tags:
        ProductTag.objects.get_or_create(slug=slug, defaults={'name': name, 'order': order})


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0007_product_allow_order_on_request'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='Название')),
                ('slug', models.SlugField(max_length=100, unique=True)),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Порядок отображения')),
            ],
            options={
                'verbose_name': 'Тег товара',
                'verbose_name_plural': 'Теги товаров',
                'ordering': ('order', 'name'),
            },
        ),
        migrations.AddField(
            model_name='product',
            name='tags',
            field=models.ManyToManyField(
                blank=True,
                help_text='Бестселлер, Выбор экспертов, Новинка, Акция',
                related_name='products',
                to='catalog.producttag',
                verbose_name='Теги',
            ),
        ),
        migrations.RunPython(create_default_tags, migrations.RunPython.noop),
    ]
