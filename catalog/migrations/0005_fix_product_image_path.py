# Data migration: исправить путь изображения 1.jpg -> 1.png (файл на диске — 1.png)

from django.db import migrations


def fix_image_path(apps, schema_editor):
    Product = apps.get_model('catalog', 'Product')
    updated = Product.objects.filter(image='products/1.jpg').update(image='products/1.png')
    if updated:
        # Логируем только при миграции; в RunPython нет доступа к self.stdout
        pass


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0004_add_favorite'),
    ]

    operations = [
        migrations.RunPython(fix_image_path, noop),
    ]
