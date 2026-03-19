from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0037_productcontentblock_video'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='productcontentblock',
            name='video',
        ),
        migrations.AddField(
            model_name='productcontentblock',
            name='embed_url',
            field=models.URLField(blank=True, max_length=500, verbose_name='Embed URL'),
        ),
        migrations.AddField(
            model_name='productcontentblock',
            name='rutube_url',
            field=models.URLField(
                blank=True,
                help_text='Для видео-блока вставьте обычную публичную ссылку RUTUBE.',
                max_length=500,
                verbose_name='Ссылка RUTUBE',
            ),
        ),
        migrations.AddField(
            model_name='productcontentblock',
            name='rutube_video_id',
            field=models.CharField(blank=True, db_index=True, max_length=100, verbose_name='ID видео RUTUBE'),
        ),
    ]
