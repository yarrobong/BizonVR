# Generated manually: страница набора (slug, description, image) и скидка в корзине (bundle, price_override)

from django.db import migrations, models
import django.db.models.deletion


def fill_bundle_slugs(apps, schema_editor):
    ProductBundle = apps.get_model('catalog', 'ProductBundle')
    for b in ProductBundle.objects.all():
        if not b.slug:
            name = (b.name or '').strip() or f'Набор {b.pk}'
            from django.utils.text import slugify
            base = slugify(name, allow_unicode=True) or f'bundle-{b.pk}'
            slug = base
            n = 1
            while ProductBundle.objects.filter(slug=slug).exclude(pk=b.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            b.slug = slug
            b.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0026_category_is_bundles_category'),
    ]

    operations = [
        # ProductBundle: slug, description, image; name no longer blank
        migrations.AddField(
            model_name='productbundle',
            name='slug',
            field=models.SlugField(blank=True, help_text='URL страницы набора, например nabor-quest-3', max_length=200, null=True, unique=True, verbose_name='Slug'),
        ),
        migrations.AddField(
            model_name='productbundle',
            name='description',
            field=models.TextField(blank=True, help_text='Как у обычного товара: текст о наборе', verbose_name='Описание'),
        ),
        migrations.AddField(
            model_name='productbundle',
            name='image',
            field=models.ImageField(blank=True, help_text='Главное фото набора (если пусто — используется фото первого товара)', null=True, upload_to='bundles/', verbose_name='Изображение'),
        ),
        migrations.RunPython(fill_bundle_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='productbundle',
            name='slug',
            field=models.SlugField(blank=True, help_text='URL страницы набора, например nabor-quest-3', max_length=200, unique=True, verbose_name='Slug'),
        ),
        # CartItem: bundle, price_override
        migrations.AddField(
            model_name='cartitem',
            name='bundle',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cart_items', to='catalog.productbundle', verbose_name='Входит в комплект'),
        ),
        migrations.AddField(
            model_name='cartitem',
            name='price_override',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Если задана — в корзине используется эта цена вместо цены товара', max_digits=12, null=True, verbose_name='Цена (в комплекте со скидкой)'),
        ),
        # Replace unique constraints
        migrations.RemoveConstraint(
            model_name='cartitem',
            name='cart_user_product_no_variant_unique',
        ),
        migrations.RemoveConstraint(
            model_name='cartitem',
            name='cart_user_product_variant_unique',
        ),
        migrations.AddConstraint(
            model_name='cartitem',
            constraint=models.UniqueConstraint(condition=models.Q(('bundle__isnull', True)), fields=('user', 'product', 'variant'), name='catalog_cartitem_standalone_unique'),
        ),
        migrations.AddConstraint(
            model_name='cartitem',
            constraint=models.UniqueConstraint(condition=models.Q(('bundle__isnull', False)), fields=('user', 'product', 'variant', 'bundle'), name='catalog_cartitem_bundle_unique'),
        ),
    ]
