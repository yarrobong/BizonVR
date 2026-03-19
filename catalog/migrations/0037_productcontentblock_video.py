from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0036_productcontentblock'),
    ]

    operations = [
        migrations.AddField(
            model_name='productcontentblock',
            name='video',
            field=models.FileField(
                blank=True,
                help_text='Видео для отдельного видео-блока. Подойдут mp4, webm и mov.',
                null=True,
                upload_to='products/content_blocks/videos/',
                verbose_name='Видео',
            ),
        ),
        migrations.AlterField(
            model_name='productcontentblock',
            name='block_type',
            field=models.CharField(
                choices=[
                    ('text', 'Текстовый блок'),
                    ('image_text', 'Картинка и текст'),
                    ('full_image', 'Большое изображение'),
                    ('video', 'Видео'),
                ],
                default='text',
                max_length=20,
                verbose_name='Тип блока',
            ),
        ),
    ]
