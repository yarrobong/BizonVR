from django.db import migrations


def clear_bundle_cartitem_price_override(apps, schema_editor):
    CartItem = apps.get_model('catalog', 'CartItem')
    CartItem.objects.filter(bundle__isnull=False, price_override__isnull=False).update(price_override=None)


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0052_productbundle_category_and_more'),
    ]

    operations = [
        migrations.RunPython(clear_bundle_cartitem_price_override, migrations.RunPython.noop),
    ]
