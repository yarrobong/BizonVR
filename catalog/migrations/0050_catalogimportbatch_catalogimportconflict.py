from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0049_product_can_import_catalog_json_permission'),
    ]

    operations = [
        migrations.CreateModel(
            name='CatalogImportBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_filename', models.CharField(max_length=255, verbose_name='Имя исходного файла')),
                ('raw_payload', models.JSONField(blank=True, default=dict, verbose_name='Исходный payload')),
                ('editable_payload', models.JSONField(blank=True, default=dict, verbose_name='Редактируемый payload')),
                ('summary', models.JSONField(blank=True, default=dict, verbose_name='Сводка анализа')),
                ('status', models.CharField(choices=[('review', 'На проверке'), ('partial', 'Частично применён'), ('completed', 'Завершён'), ('failed', 'Ошибка')], db_index=True, default='review', max_length=20, verbose_name='Статус')),
                ('error_text', models.TextField(blank=True, verbose_name='Текст ошибки')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
            ],
            options={
                'verbose_name': 'Пакет импорта каталога',
                'verbose_name_plural': 'Пакеты импорта каталога',
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='CatalogImportConflict',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('collection_name', models.CharField(db_index=True, max_length=80, verbose_name='Коллекция')),
                ('source_index', models.PositiveIntegerField(verbose_name='Индекс в payload')),
                ('source_id', models.CharField(blank=True, max_length=80, verbose_name='Source ID')),
                ('item_label', models.CharField(blank=True, max_length=255, verbose_name='Подпись элемента')),
                ('target_model', models.CharField(blank=True, max_length=120, verbose_name='Модель цели')),
                ('target_pk', models.PositiveBigIntegerField(blank=True, null=True, verbose_name='ID цели')),
                ('conflict_kind', models.CharField(db_index=True, max_length=80, verbose_name='Тип конфликта')),
                ('source_snapshot', models.JSONField(blank=True, default=dict, verbose_name='Снимок источника')),
                ('target_snapshot', models.JSONField(blank=True, default=dict, verbose_name='Снимок цели')),
                ('field_conflicts', models.JSONField(blank=True, default=dict, verbose_name='Конфликтующие поля')),
                ('resolutions', models.JSONField(blank=True, default=dict, verbose_name='Решения пользователя')),
                ('status', models.CharField(choices=[('pending', 'Ожидает решения'), ('resolved', 'Разрешён'), ('applied', 'Применён'), ('cleared', 'Устарел')], db_index=True, default='pending', max_length=20, verbose_name='Статус')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
                ('batch', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='conflicts', to='catalog.catalogimportbatch', verbose_name='Пакет импорта')),
            ],
            options={
                'verbose_name': 'Конфликт импорта каталога',
                'verbose_name_plural': 'Конфликты импорта каталога',
                'ordering': ('collection_name', 'source_index', 'id'),
            },
        ),
        migrations.AddConstraint(
            model_name='catalogimportconflict',
            constraint=models.UniqueConstraint(fields=('batch', 'collection_name', 'source_index'), name='catalog_import_conflict_batch_collection_index_unique'),
        ),
    ]
