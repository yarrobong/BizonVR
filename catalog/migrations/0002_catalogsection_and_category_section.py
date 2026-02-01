# Generated for Phase 1: CatalogSection and Category.section

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CatalogSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Название')),
                ('slug', models.SlugField(blank=True, max_length=200, unique=True, verbose_name='Slug')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
            ],
            options={
                'verbose_name': 'Раздел каталога',
                'verbose_name_plural': 'Разделы каталога',
                'ordering': ('order', 'name'),
            },
        ),
        migrations.AddField(
            model_name='category',
            name='section',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='categories',
                to='catalog.catalogsection',
                verbose_name='Раздел каталога',
            ),
        ),
    ]
