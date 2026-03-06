from django.utils.html import format_html


def _admin_image_preview(obj, width=60, height=60):
    """Превью изображения для админки."""
    if obj and getattr(obj, 'image', None) and obj.image:
        return format_html(
            '<img src="{}" width="{}" height="{}" style="object-fit: cover; border-radius: 4px;" />',
            obj.image.url, width, height
        )
    return '—'
