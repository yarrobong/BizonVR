from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0045_characteristicsourcealias_catalogfiltersourcesnapshot_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CharacteristicPreset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=100, unique=True, verbose_name='Код')),
                ('name', models.CharField(max_length=200, verbose_name='Название')),
                ('value_type', models.CharField(choices=[('text', 'Текст'), ('memory', 'Память / накопитель'), ('screen_size', 'Диагональ'), ('boolean', 'Булево'), ('resolution', 'Разрешение'), ('color', 'Цвет')], default='text', max_length=50, verbose_name='Тип значений')),
                ('sorting_mode', models.CharField(choices=[('alpha', 'Алфавит'), ('numeric_unit', 'Число + единица'), ('screen_size', 'Диагональ'), ('boolean', 'Булево'), ('resolution', 'Разрешение')], default='alpha', max_length=50, verbose_name='Режим сортировки')),
                ('normalization_mode', models.CharField(choices=[('default', 'Обычная'), ('memory', 'Память'), ('screen_size', 'Диагональ'), ('boolean', 'Булево'), ('resolution', 'Разрешение')], default='default', max_length=50, verbose_name='Режим нормализации')),
                ('default_display_unit', models.CharField(blank=True, max_length=30, verbose_name='Единица отображения по умолчанию')),
                ('suggested_sort_order', models.IntegerField(default=0, verbose_name='Рекомендуемый порядок')),
                ('is_quick_filter_candidate', models.BooleanField(default=False, verbose_name='Кандидат в quick filter')),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='Активен')),
            ],
            options={
                'verbose_name': 'Preset характеристики',
                'verbose_name_plural': 'Presets характеристик',
                'ordering': ('suggested_sort_order', 'name', 'code'),
            },
        ),
        migrations.AddField(
            model_name='characteristicdefinition',
            name='preset',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='definitions', to='catalog.characteristicpreset', verbose_name='Preset'),
        ),
    ]
