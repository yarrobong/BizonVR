from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_bundle_categories(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    ProductBundle = apps.get_model('catalog', 'ProductBundle')

    uncategorized_qs = ProductBundle.objects.filter(category__isnull=True)
    if not uncategorized_qs.exists():
        return

    bundle_category_ids = list(
        Category.objects.filter(is_bundles_category=True).values_list('id', flat=True)
    )
    if len(bundle_category_ids) != 1:
        raise RuntimeError(
            'Expected exactly one bundle category while backfilling ProductBundle.category.'
        )

    uncategorized_qs.update(category_id=bundle_category_ids[0])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0051_product_description_constructor'),
    ]

    operations = [
        migrations.AddField(
            model_name='productbundle',
            name='category',
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={'is_bundles_category': True},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='product_bundles',
                to='catalog.category',
                verbose_name='Категория набора',
            ),
        ),
        migrations.AddField(
            model_name='productbundle',
            name='created_at',
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                verbose_name='Создан',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='productbundle',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='Обновлён',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='productbundle',
            name='views_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Счётчик просмотров страницы набора для сортировки по популярности',
                verbose_name='Просмотры',
            ),
        ),
        migrations.RunPython(backfill_bundle_categories, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='productbundle',
            name='category',
            field=models.ForeignKey(
                limit_choices_to={'is_bundles_category': True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='product_bundles',
                to='catalog.category',
                verbose_name='Категория набора',
            ),
        ),
    ]
