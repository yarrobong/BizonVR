from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0044_alter_characteristicdefinition_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='CatalogFilterSourceSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_source_name', models.CharField(max_length=200, unique=True, verbose_name='Сырое имя характеристики')),
                ('first_seen_at', models.DateTimeField(auto_now_add=True, verbose_name='Впервые обнаружено')),
                ('last_seen_at', models.DateTimeField(auto_now=True, verbose_name='Последний раз обнаружено')),
            ],
            options={
                'verbose_name': 'Snapshot source name фильтра',
                'verbose_name_plural': 'Snapshots source name фильтров',
                'ordering': ('raw_source_name',),
            },
        ),
        migrations.CreateModel(
            name='CatalogFilterValueSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_source_name', models.CharField(max_length=200, verbose_name='Сырое имя характеристики')),
                ('raw_value', models.CharField(max_length=500, verbose_name='Сырое значение')),
                ('first_seen_at', models.DateTimeField(auto_now_add=True, verbose_name='Впервые обнаружено')),
                ('last_seen_at', models.DateTimeField(auto_now=True, verbose_name='Последний раз обнаружено')),
            ],
            options={
                'verbose_name': 'Snapshot значения фильтра',
                'verbose_name_plural': 'Snapshots значений фильтров',
                'ordering': ('raw_source_name', 'raw_value'),
            },
        ),
        migrations.CreateModel(
            name='CharacteristicSourceAlias',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_source_name', models.CharField(max_length=200, verbose_name='Сырое имя характеристики')),
                ('sort_order', models.IntegerField(default=0, verbose_name='Порядок')),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='Активен')),
                ('characteristic_definition', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='source_aliases', to='catalog.characteristicdefinition', verbose_name='Характеристика')),
            ],
            options={
                'verbose_name': 'Алиас source name',
                'verbose_name_plural': 'Алиасы source name',
                'ordering': ('characteristic_definition', 'sort_order', 'raw_source_name'),
            },
        ),
        migrations.AddConstraint(
            model_name='catalogfiltervaluesnapshot',
            constraint=models.UniqueConstraint(fields=('raw_source_name', 'raw_value'), name='catalog_filter_value_snapshot_unique'),
        ),
        migrations.AddConstraint(
            model_name='characteristicsourcealias',
            constraint=models.UniqueConstraint(fields=('characteristic_definition', 'raw_source_name'), name='catalog_char_source_alias_unique'),
        ),
        migrations.AddIndex(
            model_name='characteristicsourcealias',
            index=models.Index(fields=['characteristic_definition', 'is_active'], name='catalog_char_src_active_idx'),
        ),
    ]
