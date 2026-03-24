from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0038_productcontentblock_rutube_only'),
    ]

    operations = [
        migrations.DeleteModel(
            name='CompareItem',
        ),
    ]
