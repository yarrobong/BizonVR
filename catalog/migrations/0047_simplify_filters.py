"""
Упрощение системы фильтров:
- CharacteristicDefinition: убираем FK на preset, добавляем sorting_mode напрямую
- FilterConfig: единая модель вместо CategoryFilterConfig + SectionFilterConfig
- Удаляем: CharacteristicPreset, CategoryFilterConfig, SectionFilterConfig,
           CatalogFilterSourceSnapshot, CatalogFilterValueSnapshot
"""
from django.db import migrations, models
import django.db.models.deletion


def migrate_data_forward(apps, schema_editor):
    CharacteristicDefinition = apps.get_model('catalog', 'CharacteristicDefinition')
    CategoryFilterConfig = apps.get_model('catalog', 'CategoryFilterConfig')
    SectionFilterConfig = apps.get_model('catalog', 'SectionFilterConfig')
    FilterConfig = apps.get_model('catalog', 'FilterConfig')

    # Переносим sorting_mode из preset в definition
    for defn in CharacteristicDefinition.objects.select_related('preset').all():
        if defn.preset_id and defn.preset:
            defn.sorting_mode = defn.preset.sorting_mode
            defn.save(update_fields=['sorting_mode'])

    # Переносим CategoryFilterConfig → FilterConfig
    for cfg in CategoryFilterConfig.objects.all():
        FilterConfig.objects.get_or_create(
            category_id=cfg.category_id,
            section=None,
            characteristic_definition_id=cfg.characteristic_definition_id,
            defaults=dict(
                is_visible=cfg.is_visible,
                is_quick_filter=cfg.is_quick_filter,
                sort_order=cfg.sort_order,
                is_expanded_by_default=cfg.is_expanded_by_default,
                show_top_n=cfg.show_top_n,
                hide_single_value=cfg.hide_single_value,
            ),
        )

    # Переносим SectionFilterConfig → FilterConfig
    for cfg in SectionFilterConfig.objects.all():
        FilterConfig.objects.get_or_create(
            category=None,
            section_id=cfg.section_id,
            characteristic_definition_id=cfg.characteristic_definition_id,
            defaults=dict(
                is_visible=cfg.is_visible,
                is_quick_filter=cfg.is_quick_filter,
                sort_order=cfg.sort_order,
                is_expanded_by_default=cfg.is_expanded_by_default,
                show_top_n=cfg.show_top_n,
                hide_single_value=cfg.hide_single_value,
            ),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0046_characteristicpreset_characteristicdefinition_preset'),
    ]

    operations = [
        # 1. Добавляем sorting_mode в CharacteristicDefinition
        migrations.AddField(
            model_name='characteristicdefinition',
            name='sorting_mode',
            field=models.CharField(
                choices=[
                    ('alpha', 'Алфавит'),
                    ('numeric_unit', 'Число + единица (ГБ, Гц…)'),
                    ('screen_size', 'Диагональ (дюймы)'),
                    ('boolean', 'Да / Нет'),
                    ('resolution', 'Разрешение (WxH)'),
                ],
                default='alpha',
                max_length=50,
                verbose_name='Сортировка значений',
            ),
        ),

        # 2. Создаём FilterConfig
        migrations.CreateModel(
            name='FilterConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='filter_configs',
                    to='catalog.category',
                    verbose_name='Категория',
                )),
                ('section', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='filter_configs',
                    to='catalog.catalogsection',
                    verbose_name='Раздел',
                )),
                ('characteristic_definition', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='filter_configs',
                    to='catalog.characteristicdefinition',
                    verbose_name='Характеристика',
                )),
                ('is_visible', models.BooleanField(db_index=True, default=True, verbose_name='Показывать')),
                ('is_quick_filter', models.BooleanField(default=False, verbose_name='Быстрый фильтр')),
                ('sort_order', models.IntegerField(db_index=True, default=0, verbose_name='Порядок')),
                ('is_expanded_by_default', models.BooleanField(default=False, verbose_name='Раскрыт по умолчанию')),
                ('show_top_n', models.PositiveIntegerField(blank=True, null=True, verbose_name='Показывать первых N значений')),
                ('hide_single_value', models.BooleanField(default=True, verbose_name='Скрывать при одном значении')),
            ],
            options={
                'verbose_name': 'Конфиг фильтра',
                'verbose_name_plural': 'Конфиги фильтров',
                'ordering': ('sort_order', 'characteristic_definition__sort_order', 'id'),
            },
        ),
        migrations.AddConstraint(
            model_name='filterconfig',
            constraint=models.UniqueConstraint(
                condition=models.Q(category__isnull=False),
                fields=['category', 'characteristic_definition'],
                name='catalog_filter_config_category_def_unique',
            ),
        ),
        migrations.AddConstraint(
            model_name='filterconfig',
            constraint=models.UniqueConstraint(
                condition=models.Q(section__isnull=False),
                fields=['section', 'characteristic_definition'],
                name='catalog_filter_config_section_def_unique',
            ),
        ),

        # 3. Переносим данные
        migrations.RunPython(migrate_data_forward, migrations.RunPython.noop),

        # 4. Удаляем старые модели
        migrations.RemoveField(model_name='characteristicdefinition', name='preset'),
        migrations.DeleteModel(name='CharacteristicPreset'),
        migrations.DeleteModel(name='CategoryFilterConfig'),
        migrations.DeleteModel(name='SectionFilterConfig'),
        migrations.DeleteModel(name='CatalogFilterSourceSnapshot'),
        migrations.DeleteModel(name='CatalogFilterValueSnapshot'),
    ]
