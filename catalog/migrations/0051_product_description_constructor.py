from django.db import migrations, models
import django.db.models.deletion


BLOCK_TYPES = [
    ('hero_summary', 'Hero-блок', 'Крупный заголовок, лид, буллеты и изображение.', 'structure', 'sparkles', {'title': '', 'lead': '', 'bullets': []}),
    ('text', 'Текст', 'Заголовок и текстовый абзац.', 'content', 'text', {'title': '', 'text': ''}),
    ('image_text', 'Картинка и текст', 'Двухколоночный блок с изображением и текстом.', 'media', 'image-text', {'title': '', 'text': '', 'image_position': 'left'}),
    ('full_image', 'Большое изображение', 'Широкое изображение с подписью.', 'media', 'image', {'title': '', 'caption': ''}),
    ('feature_grid', 'Сетка преимуществ', 'Карточки преимуществ товара.', 'content', 'grid', {'title': '', 'items': []}),
    ('spec_highlights', 'Ключевые характеристики', 'Выжимка важных характеристик в карточках.', 'content', 'list-checks', {'title': 'Ключевые характеристики', 'items': []}),
    ('use_cases', 'Сценарии применения', 'Карточки сценариев использования.', 'content', 'target', {'title': 'Сценарии использования', 'items': []}),
    ('whats_in_box', 'Комплектация', 'Список того, что входит в комплект.', 'content', 'package', {'title': 'Комплектация', 'items': []}),
    ('comparison', 'Сравнение', 'Таблица сравнения комплектаций или версий.', 'content', 'table', {'title': '', 'columns': [], 'rows': []}),
    ('video', 'Видео', 'Видео-блок с публичной ссылкой RUTUBE.', 'media', 'play', {'title': '', 'rutube_url': '', 'caption': ''}),
    ('cta_note', 'Сервисная заметка', 'Акцентный блок про консультацию, демо, доставку или монтаж.', 'content', 'message-circle', {'title': '', 'text': '', 'tone': 'neutral'}),
]


TEMPLATES = [
    {
        'slug': 'vr_headset_standard',
        'name': 'VR-шлем: стандарт',
        'category': 'VR оборудование',
        'description': 'Универсальный шаблон для шлемов и комплектов VR.',
        'slots': [
            ('hero', 'hero_summary', 'Короткая выжимка', 10, True, {'title': 'Готовое VR-решение', 'lead': '', 'bullets': ['', '', '']}),
            ('benefits', 'feature_grid', 'Преимущества', 20, True, {'title': 'Почему выбирают эту модель', 'items': [{'icon': 'monitor', 'title': '', 'text': ''}, {'icon': 'zap', 'title': '', 'text': ''}, {'icon': 'shield', 'title': '', 'text': ''}]}),
            ('details', 'image_text', 'Подробнее о товаре', 30, False, {'title': '', 'text': '', 'image_position': 'right'}),
            ('box', 'whats_in_box', 'Комплектация', 40, False, {'title': 'Комплектация', 'items': []}),
            ('specs', 'spec_highlights', 'Ключевые характеристики', 50, False, {'title': 'Ключевые характеристики', 'items': []}),
            ('video', 'video', 'Видеообзор', 60, False, {'title': 'Видеообзор', 'rutube_url': '', 'caption': ''}),
        ],
    },
    {
        'slug': 'vr_attraction_business',
        'name': 'VR-аттракцион для бизнеса',
        'category': 'VR аттракционы',
        'description': 'Шаблон для аттракционов, парков и коммерческих VR-зон.',
        'slots': [
            ('hero', 'hero_summary', 'Бизнес-выжимка', 10, True, {'title': 'VR-аттракцион для коммерческой площадки', 'lead': '', 'bullets': ['', '', '']}),
            ('use_cases', 'use_cases', 'Где использовать', 20, True, {'title': 'Подходит для площадок', 'items': [{'icon': 'building', 'title': '', 'text': ''}, {'icon': 'users', 'title': '', 'text': ''}]}),
            ('image', 'full_image', 'Внешний вид', 30, False, {'title': '', 'caption': ''}),
            ('features', 'feature_grid', 'Преимущества для бизнеса', 40, True, {'title': 'Что получает владелец', 'items': [{'icon': 'chart', 'title': '', 'text': ''}, {'icon': 'tool', 'title': '', 'text': ''}, {'icon': 'clock', 'title': '', 'text': ''}]}),
            ('comparison', 'comparison', 'Сравнение комплектаций', 50, False, {'title': 'Комплектации', 'columns': [], 'rows': []}),
            ('manager', 'cta_note', 'Заметка менеджера', 60, False, {'title': 'Поможем с запуском', 'text': 'Менеджер подскажет комплектацию под площадь, поток гостей и бюджет.', 'tone': 'accent'}),
        ],
    },
    {
        'slug': 'simulator_complex',
        'name': 'Симулятор или комплекс',
        'category': 'VR аттракционы',
        'description': 'Шаблон для симуляторов, кабин и сложных комплектов.',
        'slots': [
            ('hero', 'hero_summary', 'Главное', 10, True, {'title': 'VR-комплекс для яркого опыта', 'lead': '', 'bullets': ['', '', '']}),
            ('mechanics', 'image_text', 'Как работает', 20, True, {'title': 'Как устроен комплекс', 'text': '', 'image_position': 'left'}),
            ('features', 'feature_grid', 'Преимущества', 30, True, {'title': 'Сильные стороны', 'items': [{'icon': 'activity', 'title': '', 'text': ''}, {'icon': 'settings', 'title': '', 'text': ''}, {'icon': 'star', 'title': '', 'text': ''}]}),
            ('box', 'whats_in_box', 'Что входит', 40, False, {'title': 'Что входит', 'items': []}),
            ('specs', 'spec_highlights', 'Характеристики', 50, False, {'title': 'Ключевые характеристики', 'items': []}),
            ('video', 'video', 'Видео', 60, False, {'title': 'Видео', 'rutube_url': '', 'caption': ''}),
        ],
    },
    {
        'slug': 'accessory_short',
        'name': 'Аксессуар: короткий',
        'category': 'VR оборудование',
        'description': 'Быстрый шаблон для аксессуаров и небольших товаров.',
        'slots': [
            ('summary', 'text', 'Описание', 10, True, {'title': 'Описание', 'text': ''}),
            ('details', 'image_text', 'Детали', 20, False, {'title': '', 'text': '', 'image_position': 'right'}),
            ('box', 'whats_in_box', 'Комплектация', 30, False, {'title': 'Комплектация', 'items': []}),
            ('specs', 'spec_highlights', 'Характеристики', 40, False, {'title': 'Ключевые характеристики', 'items': []}),
        ],
    },
    {
        'slug': 'service_or_bundle',
        'name': 'Услуга или комплект',
        'category': 'Комплекты и услуги',
        'description': 'Шаблон для наборов, услуг, монтажа и сервисных предложений.',
        'slots': [
            ('hero', 'hero_summary', 'Главное', 10, True, {'title': 'Готовое решение', 'lead': '', 'bullets': ['', '', '']}),
            ('use_cases', 'use_cases', 'Сценарии', 20, True, {'title': 'Когда подходит', 'items': [{'icon': 'check', 'title': '', 'text': ''}, {'icon': 'check', 'title': '', 'text': ''}]}),
            ('features', 'feature_grid', 'Что входит в подход', 30, True, {'title': 'Что важно', 'items': [{'icon': 'tool', 'title': '', 'text': ''}, {'icon': 'truck', 'title': '', 'text': ''}, {'icon': 'headphones', 'title': '', 'text': ''}]}),
            ('note', 'cta_note', 'Сервисная заметка', 40, False, {'title': 'Уточним детали перед заказом', 'text': 'Менеджер поможет подобрать состав решения под задачу.', 'tone': 'accent'}),
        ],
    },
]


def seed_description_constructor(apps, schema_editor):
    DescriptionBlockType = apps.get_model('catalog', 'DescriptionBlockType')
    DescriptionTemplate = apps.get_model('catalog', 'DescriptionTemplate')
    DescriptionTemplateSlot = apps.get_model('catalog', 'DescriptionTemplateSlot')

    block_types = {}
    for order, (slug, name, description, category, icon, default_data) in enumerate(BLOCK_TYPES, start=1):
        block_type, _ = DescriptionBlockType.objects.update_or_create(
            slug=slug,
            defaults={
                'name': name,
                'description': description,
                'category': category,
                'icon': icon,
                'schema': {},
                'default_data': default_data,
                'preview_data': default_data,
                'is_active': True,
                'sort_order': order * 10,
            },
        )
        block_types[slug] = block_type

    for template_data in TEMPLATES:
        template, _ = DescriptionTemplate.objects.update_or_create(
            slug=template_data['slug'],
            defaults={
                'name': template_data['name'],
                'description': template_data['description'],
                'category': template_data['category'],
                'preview_data': {'blocks': [slot[5] | {'block_type': slot[1]} for slot in template_data['slots']]},
                'is_active': True,
                'version': 1,
            },
        )
        for slot_key, block_type_slug, label, sort_order, is_required, default_data in template_data['slots']:
            DescriptionTemplateSlot.objects.update_or_create(
                template=template,
                slot_key=slot_key,
                defaults={
                    'block_type': block_types[block_type_slug],
                    'label': label,
                    'help_text': '',
                    'sort_order': sort_order,
                    'is_required': is_required,
                    'default_data': default_data,
                    'settings': {},
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0050_catalogimportbatch_catalogimportconflict'),
    ]

    operations = [
        migrations.CreateModel(
            name='DescriptionBlockType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=80, unique=True, verbose_name='Slug')),
                ('name', models.CharField(max_length=160, verbose_name='Название')),
                ('description', models.TextField(blank=True, verbose_name='Описание')),
                ('category', models.CharField(blank=True, max_length=80, verbose_name='Категория')),
                ('icon', models.CharField(blank=True, max_length=80, verbose_name='Иконка')),
                ('schema', models.JSONField(blank=True, default=dict, verbose_name='Схема данных')),
                ('default_data', models.JSONField(blank=True, default=dict, verbose_name='Данные по умолчанию')),
                ('preview_data', models.JSONField(blank=True, default=dict, verbose_name='Данные для предпросмотра')),
                ('is_active', models.BooleanField(default=True, verbose_name='Активен')),
                ('sort_order', models.IntegerField(db_index=True, default=0, verbose_name='Порядок')),
            ],
            options={
                'verbose_name': 'Тип блока описания',
                'verbose_name_plural': 'Типы блоков описания',
                'ordering': ('sort_order', 'name'),
            },
        ),
        migrations.CreateModel(
            name='DescriptionTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=180, verbose_name='Название')),
                ('slug', models.SlugField(max_length=120, unique=True, verbose_name='Slug')),
                ('description', models.TextField(blank=True, verbose_name='Описание')),
                ('preview_image', models.ImageField(blank=True, null=True, upload_to='products/description_templates/', verbose_name='Изображение предпросмотра')),
                ('preview_data', models.JSONField(blank=True, default=dict, verbose_name='Данные предпросмотра')),
                ('category', models.CharField(blank=True, max_length=120, verbose_name='Категория')),
                ('is_active', models.BooleanField(default=True, verbose_name='Активен')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Версия')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
            ],
            options={
                'verbose_name': 'Шаблон подробного описания',
                'verbose_name_plural': 'Шаблоны подробного описания',
                'ordering': ('category', 'name'),
            },
        ),
        migrations.CreateModel(
            name='ProductDescription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=255, verbose_name='Заголовок описания')),
                ('intro', models.TextField(blank=True, verbose_name='Вступление')),
                ('status', models.CharField(choices=[('draft', 'Черновик'), ('published', 'Опубликовано')], db_index=True, default='draft', max_length=20, verbose_name='Статус')),
                ('is_active', models.BooleanField(default=False, verbose_name='Показывать на витрине')),
                ('source', models.CharField(choices=[('legacy', 'Legacy-блоки'), ('template', 'Шаблон'), ('custom', 'Произвольное')], db_index=True, default='custom', max_length=20, verbose_name='Источник')),
                ('published_at', models.DateTimeField(blank=True, null=True, verbose_name='Опубликовано')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлено')),
                ('product', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='product_description', to='catalog.product', verbose_name='Товар')),
                ('template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='product_descriptions', to='catalog.descriptiontemplate', verbose_name='Шаблон')),
            ],
            options={
                'verbose_name': 'Подробное описание товара',
                'verbose_name_plural': 'Подробные описания товаров',
                'ordering': ('product__name',),
            },
        ),
        migrations.CreateModel(
            name='DescriptionTemplateSlot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slot_key', models.SlugField(max_length=80, verbose_name='Ключ слота')),
                ('label', models.CharField(max_length=160, verbose_name='Название блока')),
                ('help_text', models.TextField(blank=True, verbose_name='Подсказка')),
                ('sort_order', models.IntegerField(db_index=True, default=0, verbose_name='Порядок')),
                ('is_required', models.BooleanField(default=False, verbose_name='Обязательный')),
                ('default_data', models.JSONField(blank=True, default=dict, verbose_name='Данные по умолчанию')),
                ('settings', models.JSONField(blank=True, default=dict, verbose_name='Настройки редактора')),
                ('block_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='template_slots', to='catalog.descriptionblocktype', verbose_name='Тип блока')),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slots', to='catalog.descriptiontemplate', verbose_name='Шаблон')),
            ],
            options={
                'verbose_name': 'Блок шаблона описания',
                'verbose_name_plural': 'Блоки шаблонов описания',
                'ordering': ('sort_order', 'id'),
            },
        ),
        migrations.CreateModel(
            name='ProductDescriptionBlock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slot_key', models.SlugField(max_length=80, verbose_name='Ключ слота')),
                ('sort_order', models.IntegerField(db_index=True, default=0, verbose_name='Порядок')),
                ('is_active', models.BooleanField(default=True, verbose_name='Активен')),
                ('data', models.JSONField(blank=True, default=dict, verbose_name='Данные блока')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
                ('block_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='product_blocks', to='catalog.descriptionblocktype', verbose_name='Тип блока')),
                ('description', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='blocks', to='catalog.productdescription', verbose_name='Описание')),
            ],
            options={
                'verbose_name': 'Блок подробного описания товара',
                'verbose_name_plural': 'Блоки подробных описаний товаров',
                'ordering': ('sort_order', 'id'),
            },
        ),
        migrations.CreateModel(
            name='ProductDescriptionAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='products/description_assets/', verbose_name='Изображение')),
                ('alt', models.CharField(blank=True, max_length=255, verbose_name='Alt-текст')),
                ('caption', models.CharField(blank=True, max_length=255, verbose_name='Подпись')),
                ('role', models.CharField(blank=True, max_length=80, verbose_name='Роль')),
                ('sort_order', models.IntegerField(db_index=True, default=0, verbose_name='Порядок')),
                ('block', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='assets', to='catalog.productdescriptionblock', verbose_name='Блок')),
                ('description', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assets', to='catalog.productdescription', verbose_name='Описание')),
            ],
            options={
                'verbose_name': 'Медиа подробного описания',
                'verbose_name_plural': 'Медиа подробных описаний',
                'ordering': ('sort_order', 'id'),
            },
        ),
        migrations.AddIndex(
            model_name='productdescription',
            index=models.Index(fields=['status', 'is_active'], name='product_desc_status_active_idx'),
        ),
        migrations.AddIndex(
            model_name='descriptiontemplateslot',
            index=models.Index(fields=['template', 'sort_order'], name='desc_tpl_slot_order_idx'),
        ),
        migrations.AddConstraint(
            model_name='descriptiontemplateslot',
            constraint=models.UniqueConstraint(fields=('template', 'slot_key'), name='description_template_slot_key_unique'),
        ),
        migrations.AddIndex(
            model_name='productdescriptionblock',
            index=models.Index(fields=['description', 'sort_order'], name='prod_desc_block_order_idx'),
        ),
        migrations.AddConstraint(
            model_name='productdescriptionblock',
            constraint=models.UniqueConstraint(fields=('description', 'slot_key'), name='product_description_slot_key_unique'),
        ),
        migrations.RunPython(seed_description_constructor, migrations.RunPython.noop),
    ]
