# Generated manually — добавляет города по умолчанию, если их ещё нет

from django.db import migrations


def seed_cities(apps, schema_editor):
    City = apps.get_model('catalog', 'City')
    if City.objects.exists():
        return
    City.objects.bulk_create([
        City(name='Москва', slug='moscow', order=0),
        City(name='Санкт-Петербург', slug='spb', order=1),
    ])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0019_add_icon_fields'),
    ]

    operations = [
        migrations.RunPython(seed_cities, noop),
    ]
