from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0055_category_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='product_kind',
            field=models.CharField(
                choices=[('physical', 'Обычный товар'), ('game_pack', 'Пак игр')],
                db_index=True,
                default='physical',
                help_text='Пак игр не использует складские остатки и продаётся как одна позиция.',
                max_length=20,
                verbose_name='Тип товара',
            ),
        ),
        migrations.CreateModel(
            name='GamePackItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='Название игры')),
                ('platform', models.CharField(blank=True, max_length=120, verbose_name='Платформа')),
                ('note', models.CharField(blank=True, max_length=255, verbose_name='Примечание')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                (
                    'product',
                    models.ForeignKey(
                        limit_choices_to={'product_kind': 'game_pack'},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='game_pack_items',
                        to='catalog.product',
                        verbose_name='Пак игр',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Игра в паке',
                'verbose_name_plural': 'Игры в паке',
                'ordering': ('sort_order', 'id'),
            },
        ),
    ]
