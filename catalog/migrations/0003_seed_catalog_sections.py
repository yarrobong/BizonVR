# Data migration: создать разделы каталога из upgrade.md

from django.db import migrations


def create_sections(apps, schema_editor):
    CatalogSection = apps.get_model('catalog', 'CatalogSection')
    sections = [
        (1, 'Решения для VR бизнеса', 'resheniya-dlya-vr-biznesa'),
        (2, 'VR-аттракционы', 'vr-attrakciony'),
        (3, 'VR-оборудование', 'vr-oborudovanie'),
        (4, 'Цифровые товары', 'cifrovye-tovary'),
    ]
    for order, name, slug in sections:
        CatalogSection.objects.get_or_create(slug=slug, defaults={'name': name, 'order': order})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0002_catalogsection_and_category_section'),
    ]

    operations = [
        migrations.RunPython(create_sections, noop),
    ]
