from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0035_productvideo'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductContentBlock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('block_type', models.CharField(choices=[('text', 'Текстовый блок'), ('image_text', 'Картинка и текст'), ('full_image', 'Большое изображение')], default='text', max_length=20, verbose_name='Тип блока')),
                ('title', models.CharField(blank=True, help_text='Крупный заголовок секции. Для full_image можно оставить пустым.', max_length=255, verbose_name='Заголовок')),
                ('text', models.TextField(blank=True, help_text='Основной текст блока. Для full_image не используется.', verbose_name='Текст')),
                ('image', models.ImageField(blank=True, help_text='Изображение для блока. Обязательно для типов "Картинка и текст" и "Большое изображение".', null=True, upload_to='products/content_blocks/', verbose_name='Изображение')),
                ('image_position', models.CharField(blank=True, choices=[('left', 'Слева'), ('right', 'Справа')], default='left', help_text='Используется только для блока "Картинка и текст".', max_length=10, verbose_name='Положение изображения')),
                ('caption', models.CharField(blank=True, help_text='Необязательная подпись под большим изображением.', max_length=255, verbose_name='Подпись к изображению')),
                ('sort_order', models.IntegerField(db_index=True, default=0, help_text='Чем меньше число, тем выше блок на странице.', verbose_name='Порядок')),
                ('is_active', models.BooleanField(default=True, help_text='Позволяет временно скрыть блок без удаления.', verbose_name='Активен')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлён')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_blocks', to='catalog.product', verbose_name='Товар')),
            ],
            options={
                'verbose_name': 'Блок подробного описания',
                'verbose_name_plural': 'Блоки подробного описания',
                'ordering': ('sort_order', 'id'),
            },
        ),
    ]
