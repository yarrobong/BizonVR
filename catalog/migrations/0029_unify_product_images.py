# Generated manually: unify product images — db_index on order + data migration

from django.db import migrations, models


def unify_product_images(apps, schema_editor):
    """Migrate Product.image to ProductImage and sync product.image from first ProductImage."""
    Product = apps.get_model('catalog', 'Product')
    ProductImage = apps.get_model('catalog', 'ProductImage')

    for product in Product.objects.all():
        images = list(ProductImage.objects.filter(product=product).order_by('order', 'id'))

        if product.image and not images:
            # Product has main image but no ProductImage — create one
            ProductImage.objects.create(
                product=product,
                image=product.image,
                order=0,
            )
        elif images and not product.image:
            # Product has ProductImages but no main image — sync from first
            first = images[0]
            if first.image:
                product.image = first.image
                product.save(update_fields=['image'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0028_callbackrequest_legal_acceptance_ip_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productimage',
            name='order',
            field=models.PositiveIntegerField(db_index=True, default=0, verbose_name='Порядок'),
        ),
        migrations.RunPython(unify_product_images, noop),
    ]
