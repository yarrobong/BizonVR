"""Context processors для каталога."""

from .models import CatalogSection, City, Favorite


def catalog_menu(request):
    """Разделы каталога с категориями для выпадающего меню в шапке; счётчик корзины; города."""
    sections = CatalogSection.objects.prefetch_related('categories').order_by('order', 'name')
    result = {'catalog_sections': list(sections)}

    if request.user.is_authenticated:
        result['favorites_count'] = Favorite.objects.filter(user=request.user).count()
    else:
        result['favorites_count'] = 0

    cart_items = request.session.get('cart_items', []) or []
    result['cart_count'] = sum(item.get('quantity', 0) for item in cart_items)
    result['cart_total'] = sum(item.get('subtotal', 0) for item in cart_items)

    result['cities'] = list(City.objects.order_by('order', 'name'))
    selected_city_id = request.session.get('selected_city_id')
    result['selected_city'] = next((c for c in result['cities'] if c.pk == selected_city_id), None)
    return result
