from django.utils.html import format_html


def _admin_image_preview(obj, width=60, height=60):
    """Превью изображения для админки."""
    if obj and getattr(obj, 'image', None) and obj.image:
        return format_html(
            (
                '<a href="{url}" target="_blank" rel="noreferrer" '
                'class="product-admin-image-preview-link" '
                'data-product-admin-image-preview-link '
                'title="Открыть изображение крупнее">'
                '<img src="{url}" width="{width}" height="{height}" '
                'style="object-fit: cover; border-radius: 10px;" />'
                '</a>'
            ),
            url=obj.image.url,
            width=width,
            height=height,
        )
    return '—'
