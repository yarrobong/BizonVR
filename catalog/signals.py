"""Signals for catalog app."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Product, ProductImage


def _sync_product_main_image(product_id):
    """Set Product.image to the first ProductImage by order, or None."""
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return
    first = ProductImage.objects.filter(product_id=product_id).order_by('order', 'id').first()
    new_image = first.image if first and first.image else None
    if product.image != new_image:
        product.image = new_image
        product.save(update_fields=['image'])


@receiver(post_save, sender=ProductImage)
def productimage_post_save(sender, instance, **kwargs):
    _sync_product_main_image(instance.product_id)


@receiver(post_delete, sender=ProductImage)
def productimage_post_delete(sender, instance, **kwargs):
    _sync_product_main_image(instance.product_id)
