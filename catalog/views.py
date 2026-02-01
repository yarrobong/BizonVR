import json
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, ListView
from django_ratelimit.decorators import ratelimit

from .models import Category, City, Favorite, Product, ProductStock


def _get_cart_count(request):
    """Сумма quantity по всем позициям корзины в сессии."""
    items = request.session.get('cart_items', []) or []
    return sum(item.get('quantity', 0) for item in items)


def _get_stock_in_city(city_id, product_id):
    """Суммарный остаток товара по городу (все точки выдачи)."""
    if not city_id:
        return None
    total = (
        ProductStock.objects
        .filter(product_id=product_id, pickup_point__city_id=city_id)
        .aggregate(s=Sum('quantity'))
    )
    return (total['s'] or 0)


@require_POST
def set_city_view(request):
    """Установить выбранный город в сессии. Редирект на next или на каталог."""
    city_id = request.POST.get('city_id')
    next_url = request.POST.get('next') or request.GET.get('next') or reverse('catalog:product_list')
    if city_id:
        try:
            city_id = int(city_id)
            if City.objects.filter(pk=city_id).exists():
                request.session['selected_city_id'] = city_id
                request.session.modified = True
        except (TypeError, ValueError):
            pass
    return redirect(next_url)


def cart_page_view(request):
    """Отдельная страница корзины: список товаров, изменение количества, переход к оформлению."""
    cart_items = request.session.get('cart_items', []) or []
    total = sum(item.get('subtotal', 0) for item in cart_items)
    selected_city_id = request.session.get('selected_city_id')
    stock_by_product = {}
    if cart_items and selected_city_id:
        product_ids = [i['product_id'] for i in cart_items]
        for pid in product_ids:
            stock_by_product[pid] = _get_stock_in_city(selected_city_id, pid)
    if cart_items:
        product_ids = [i['product_id'] for i in cart_items]
        slugs = dict(
            Product.objects.filter(pk__in=product_ids).values_list('pk', 'slug')
        )
        for item in cart_items:
            item['product_slug'] = slugs.get(item['product_id'], '')
            item['stock_in_city'] = stock_by_product.get(item['product_id'])
    return render(request, 'catalog/cart.html', {
        'cart_items': cart_items,
        'total': total,
        'selected_city': City.objects.filter(pk=selected_city_id).first() if selected_city_id else None,
    })


def cart_partial(request):
    """Фрагмент корзины для модального окна (HTMX)."""
    cart_items = request.session.get('cart_items', []) or []
    total = sum(item.get('subtotal', 0) for item in cart_items)
    return render(request, 'catalog/partials/cart_content.html', {'cart_items': cart_items, 'total': total})


@ratelimit(key='ip', rate='60/m', method='POST')
@require_POST
def add_to_cart_view(request, product_id):
    """
    Добавить товар в корзину (сессия). quantity из POST или 1.
    Если выбран город — ограничиваем количество доступным остатком по городу.
    """
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    try:
        quantity = max(1, int(request.POST.get('quantity', 1)))
    except (TypeError, ValueError):
        quantity = 1

    cart_items = request.session.get('cart_items', []) or []
    current_in_cart = sum(i.get('quantity', 0) for i in cart_items if i.get('product_id') == product_id)
    selected_city_id = request.session.get('selected_city_id')
    if selected_city_id:
        stock = _get_stock_in_city(selected_city_id, product_id)
        available = max(0, stock - current_in_cart)
        if quantity > available:
            quantity = available
        if quantity <= 0:
            if request.headers.get('HX-Request'):
                total = sum(i.get('subtotal', 0) for i in cart_items)
                resp = render(request, 'catalog/partials/cart_content.html', {
                    'cart_items': cart_items,
                    'total': total,
                    'cart_error': 'Недостаточно товара в выбранном городе.',
                })
                resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': _get_cart_count(request)}})
                return resp
            next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
            return redirect(next_url + '?cart_error=1')

    image_url = product.image.url if product.image else ''
    for item in cart_items:
        if item.get('product_id') == product_id:
            item['quantity'] = item.get('quantity', 0) + quantity
            item['subtotal'] = item['price'] * item['quantity']
            break
    else:
        cart_items.append({
            'product_id': product.pk,
            'name': product.name,
            'price': float(product.price),
            'quantity': quantity,
            'image_url': image_url,
            'subtotal': float(product.price) * quantity,
        })

    request.session['cart_items'] = cart_items
    request.session.modified = True

    cart_count = _get_cart_count(request)

    if request.headers.get('HX-Request'):
        total = sum(i.get('subtotal', 0) for i in cart_items)
        resp = render(request, 'catalog/partials/cart_content.html', {
            'cart_items': cart_items,
            'total': total,
        })
        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': cart_count}})
        return resp

    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
    return redirect(next_url)


@require_POST
def cart_update_view(request):
    """
    Обновить количество или удалить позицию (quantity=0). Для HTMX возвращает фрагмент корзины.
    POST: product_id, quantity (0 = удалить). Если выбран город — ограничиваем количество остатком.
    """
    product_id = request.POST.get('product_id')
    try:
        product_id = int(product_id)
        quantity = int(request.POST.get('quantity', 0))
    except (TypeError, ValueError):
        if request.headers.get('HX-Request'):
            return cart_partial(request)
        return redirect('catalog:product_list')

    cart_items = request.session.get('cart_items', []) or []
    cart_items = [i for i in cart_items if i.get('product_id') != product_id]
    if quantity > 0:
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if product:
            selected_city_id = request.session.get('selected_city_id')
            if selected_city_id:
                stock = _get_stock_in_city(selected_city_id, product_id)
                quantity = min(quantity, max(0, stock))
            image_url = product.image.url if product.image else ''
            if quantity > 0:
                cart_items.append({
                    'product_id': product.pk,
                    'name': product.name,
                    'price': float(product.price),
                    'quantity': quantity,
                    'image_url': image_url,
                    'subtotal': float(product.price) * quantity,
                })
    request.session['cart_items'] = cart_items
    request.session.modified = True

    if request.headers.get('HX-Request'):
        total = sum(i.get('subtotal', 0) for i in cart_items)
        resp = render(request, 'catalog/partials/cart_content.html', {
            'cart_items': cart_items,
            'total': total,
        })
        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': _get_cart_count(request)}})
        return resp
    next_url = request.POST.get('next') or request.GET.get('next')
    return redirect(next_url or reverse('catalog:cart'))


class ProductListView(ListView):
    """Список товаров с фильтрацией по категории, пагинацией и сортировкой."""
    model = Product
    context_object_name = 'products'
    paginate_by = 12
    template_name = 'catalog/product_list.html'

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).select_related('category').order_by('-created_at')
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            qs = qs.filter(
                Q(name__icontains=search_query) | Q(description__icontains=search_query)
            )
        category_slug = self.request.GET.get('category')
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        section_slug = self.request.GET.get('section')
        if section_slug:
            qs = qs.filter(category__section__slug=section_slug)
        sort = self.request.GET.get('sort', 'newest')
        if sort == 'price_asc':
            qs = qs.order_by('price')
        elif sort == 'price_desc':
            qs = qs.order_by('-price')
        elif sort == 'name':
            qs = qs.order_by('name')
        # default: newest (уже -created_at)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        context['current_category'] = self.request.GET.get('category', '')
        context['current_section'] = self.request.GET.get('section', '')
        context['current_sort'] = self.request.GET.get('sort', 'newest')
        context['search_query'] = (self.request.GET.get('q') or '').strip()
        if self.request.user.is_authenticated:
            context['favorite_product_ids'] = set(
                Favorite.objects.filter(user=self.request.user).values_list('product_id', flat=True)
            )
        else:
            context['favorite_product_ids'] = set()
        selected_city_id = self.request.session.get('selected_city_id')
        if selected_city_id:
            stock_qs = (
                ProductStock.objects
                .filter(pickup_point__city_id=selected_city_id)
                .values('product_id')
                .annotate(total=Sum('quantity'))
            )
            context['product_stock_in_city'] = {row['product_id']: row['total'] for row in stock_qs}
        else:
            context['product_stock_in_city'] = {}
        return context


class ProductDetailView(DetailView):
    """Детальная страница товара."""
    model = Product
    context_object_name = 'product'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/product_detail.html'

    def get_queryset(self):
        return Product.objects.filter(is_active=True).prefetch_related('characteristics').select_related('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context['is_favorite'] = Favorite.objects.filter(
                user=self.request.user, product=self.object
            ).exists()
        else:
            context['is_favorite'] = False
        selected_city_id = self.request.session.get('selected_city_id')
        if selected_city_id:
            total = (
                ProductStock.objects
                .filter(product=self.object, pickup_point__city_id=selected_city_id)
                .aggregate(s=Sum('quantity'))
            )
            context['stock_in_city'] = (total['s'] or 0)
        else:
            context['stock_in_city'] = None
        return context


@login_required
def favorite_list_view(request):
    """Страница «Моё избранное»: список товаров, добавленных в избранное."""
    favorites = Favorite.objects.filter(user=request.user).select_related('product', 'product__category')
    products = [f.product for f in favorites if f.product.is_active]
    return render(request, 'catalog/favorite_list.html', {
        'products': products,
        'favorite_product_ids': set(p.pk for p in products),
    })


@require_POST
@login_required
def toggle_favorite_view(request, product_id):
    """Добавить или убрать товар из избранного. Редирект или JSON для HTMX."""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    fav, created = Favorite.objects.get_or_create(user=request.user, product=product)
    if not created:
        fav.delete()
        is_favorite = False
    else:
        is_favorite = True
    if request.headers.get('HX-Request'):
        return JsonResponse({'ok': True, 'is_favorite': is_favorite})
    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
    return redirect(next_url)
