from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0043_characteristicdefinition_categoryfilterconfig_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='characteristicdefinition',
            name='code',
            field=models.SlugField(blank=True, max_length=100, unique=True, verbose_name='Код'),
        ),
    ]
