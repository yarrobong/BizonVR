import json
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.db.utils import ProgrammingError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, ListView
from django_ratelimit.decorators import ratelimit

from .models import CatalogSection, Category, City, Favorite, Product, ProductBundle, ProductBundleItem, ProductCharacteristic, ProductStock, ProductTag, ProductVariant


def _get_cart_count(request):
    """Сумма quantity по всем позициям корзины в сессии."""
    items = request.session.get('cart_items', []) or []
    return sum(item.get('quantity', 0) for item in items)


def _get_stock_in_city(city_id, product_id, variant_id=None):
    """Суммарный остаток товара по городу. variant_id — для товаров с вариантами."""
    if not city_id:
        return None
    qs = ProductStock.objects.filter(
        product_id=product_id,
        pickup_point__city_id=city_id,
    )
    if variant_id is not None:
        qs = qs.filter(variant_id=variant_id)
    else:
        qs = qs.filter(variant__isnull=True)
    total = qs.aggregate(s=Sum('quantity'))
    return (total['s'] or 0)


def _get_stock_total(product_id, variant_id=None):
    """Суммарный остаток товара по всей России. variant_id — для товаров с вариантами."""
    qs = ProductStock.objects.filter(product_id=product_id)
    if variant_id is not None:
        qs = qs.filter(variant_id=variant_id)
    else:
        qs = qs.filter(variant__isnull=True)
    total = qs.aggregate(s=Sum('quantity'))
    return (total['s'] or 0)


def _safe_redirect_target(url, request):
    """Проверка, что URL безопасен для редиректа (внутренний или относительный путь)."""
    if not url:
        return False
    if url.startswith('/') and not url.startswith('//'):
        return True
    return url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()})


@require_POST
def set_city_view(request):
    """Установить выбранный город в сессии. Редирект на next, referer или каталог."""
    city_id = request.POST.get('city_id')
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if not _safe_redirect_target(next_url, request):
        next_url = reverse('catalog:product_list')
    # На главной при смене города — в каталог, чтобы сразу видеть наличие
    if next_url:
        path = urlparse(next_url).path if '//' in next_url else next_url
        if path.rstrip('/') == '':
            next_url = reverse('catalog:product_list')
    if city_id:
        try:
            city_id = int(city_id)
            if City.objects.filter(pk=city_id).exists():
                request.session['selected_city_id'] = city_id
                request.session.modified = True
        except (TypeError, ValueError):
            pass
    else:
        request.session.pop('selected_city_id', None)
        request.session.modified = True
    return redirect(next_url)


def cart_page_view(request):
    """Отдельная страница корзины: список товаров, изменение количества, переход к оформлению."""
    cart_items = request.session.get('cart_items', []) or []
    total = sum(item.get('subtotal', 0) for item in cart_items)
    selected_city_id = request.session.get('selected_city_id')
    stock_by_product = {}
    stock_total_by_product = {}
    if cart_items:
        slugs = dict(
            Product.objects.filter(pk__in=[i['product_id'] for i in cart_items]).values_list('pk', 'slug')
        )
        for item in cart_items:
            pid = item['product_id']
            vid = item.get('variant_id')
            key = (pid, vid)
            stock_total_by_product[key] = _get_stock_total(pid, vid)
            if selected_city_id:
                stock_by_product[key] = _get_stock_in_city(selected_city_id, pid, vid)
            item['product_slug'] = slugs.get(pid, '')
            item['stock_in_city'] = stock_by_product.get(key)
            item['stock_total'] = stock_total_by_product.get(key, 0)
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


def _cart_item_matches(item, product_id, variant_id=None):
    """Позиция корзины совпадает с product_id + variant_id."""
    if item.get('product_id') != product_id:
        return False
    item_vid = item.get('variant_id')
    if variant_id is None and item_vid is None:
        return True
    return item_vid == variant_id


@ratelimit(key='ip', rate='60/m', method='POST')
@require_POST
def add_to_cart_view(request, product_id):
    """
    Добавить товар в корзину (сессия). quantity из POST или 1.
    variant_id из POST — вариант товара (цвет, размер и т.п.).
    Если выбран город — ограничиваем количество доступным остатком по городу.
    """
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    variant_id = request.POST.get('variant_id')
    variant = None
    if variant_id:
        try:
            variant_id = int(variant_id)
            variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
            if not variant:
                variant_id = None
                variant = None
        except (TypeError, ValueError):
            variant_id = None
    if product.variants.exists() and not variant:
        if request.headers.get('HX-Request'):
            total = sum(i.get('subtotal', 0) for i in request.session.get('cart_items', []) or [])
            resp = render(request, 'catalog/partials/cart_content.html', {
                'cart_items': request.session.get('cart_items', []) or [],
                'total': total,
                'cart_error': 'Выберите вариант товара.',
            })
            resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': _get_cart_count(request)}})
            return resp
        next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
        return redirect(next_url + '?cart_error=1')
    try:
        quantity = max(1, int(request.POST.get('quantity', 1)))
    except (TypeError, ValueError):
        quantity = 1

    cart_items = request.session.get('cart_items', []) or []
    current_in_cart = sum(
        i.get('quantity', 0) for i in cart_items
        if _cart_item_matches(i, product_id, variant_id)
    )
    selected_city_id = request.session.get('selected_city_id')
    if selected_city_id:
        stock = _get_stock_in_city(selected_city_id, product_id, variant_id)
        available = max(0, stock - current_in_cart)
        if stock > 0:
            # Товар в наличии — ограничиваем остатком
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
        else:
            # Товара нет в городе — проверяем общий остаток по России
            stock_total = _get_stock_total(product_id, variant_id)
            if stock_total > 0:
                # В наличии в другом городе — ограничиваем общим остатком
                available = max(0, stock_total - current_in_cart)
                if quantity > available:
                    quantity = available
                if quantity <= 0:
                    if request.headers.get('HX-Request'):
                        total = sum(i.get('subtotal', 0) for i in cart_items)
                        resp = render(request, 'catalog/partials/cart_content.html', {
                            'cart_items': cart_items,
                            'total': total,
                            'cart_error': 'Недостаточно товара.',
                        })
                        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': _get_cart_count(request)}})
                        return resp
                    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
                    return redirect(next_url + '?cart_error=1')
            else:
                # Нет нигде — под заказ (если разрешено)
                if not getattr(product, 'allow_order_on_request', True):
                    if request.headers.get('HX-Request'):
                        total = sum(i.get('subtotal', 0) for i in cart_items)
                        resp = render(request, 'catalog/partials/cart_content.html', {
                            'cart_items': cart_items,
                            'total': total,
                            'cart_error': 'Товар недоступен для заказа.',
                        })
                        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': _get_cart_count(request)}})
                        return resp
                    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
                    return redirect(next_url + '?cart_error=1')

    if variant:
        display_name = f'{product.name} ({variant.name})'
        price = float(variant.price)
        image_url = variant.image.url if variant.image else (product.image.url if product.image else '')
    else:
        display_name = product.name
        price = float(product.price)
        image_url = product.image.url if product.image else ''

    for item in cart_items:
        if _cart_item_matches(item, product_id, variant_id):
            item['quantity'] = item.get('quantity', 0) + quantity
            item['subtotal'] = item['price'] * item['quantity']
            break
    else:
        cart_items.append({
            'product_id': product.pk,
            'variant_id': variant_id,
            'variant_name': variant.name if variant else None,
            'name': display_name,
            'price': price,
            'quantity': quantity,
            'image_url': image_url,
            'subtotal': price * quantity,
        })

    request.session['cart_items'] = cart_items
    request.session.modified = True

    cart_count = _get_cart_count(request)

    if request.headers.get('HX-Request'):
        total = sum(i.get('subtotal', 0) for i in cart_items)
        added_item = {
            'name': display_name,
            'quantity': quantity,
            'price': price,
            'subtotal': price * quantity,
            'image_url': request.build_absolute_uri(image_url) if image_url else '',
        }
        items_preview = [
            {'name': i['name'], 'quantity': i['quantity'], 'subtotal': i['subtotal'], 'image_url': request.build_absolute_uri(i['image_url']) if i.get('image_url') else ''}
            for i in reversed(cart_items[-5:])
        ]
        resp = render(request, 'catalog/partials/cart_content.html', {
            'cart_items': cart_items,
            'total': total,
        })
        resp['HX-Trigger'] = json.dumps({
            'cart-updated': {
                'count': cart_count,
                'total': total,
                'added_item': added_item,
                'items': items_preview,
            }
        })
        return resp

    next_url = request.POST.get('next') or request.GET.get('next') or product.get_absolute_url()
    return redirect(next_url)


@require_POST
def cart_update_view(request):
    """
    Обновить количество или удалить позицию (quantity=0). Для HTMX возвращает фрагмент корзины.
    POST: product_id, quantity (0 = удалить), variant_id (опционально).
    Если выбран город — ограничиваем количество остатком.
    """
    product_id = request.POST.get('product_id')
    variant_id = request.POST.get('variant_id')
    try:
        product_id = int(product_id)
        quantity = int(request.POST.get('quantity', 0))
        if variant_id:
            variant_id = int(variant_id)
        else:
            variant_id = None
    except (TypeError, ValueError):
        if request.headers.get('HX-Request'):
            return cart_partial(request)
        return redirect('catalog:product_list')

    cart_items = request.session.get('cart_items', []) or []
    cart_items = [i for i in cart_items if not _cart_item_matches(i, product_id, variant_id)]
    if quantity > 0:
        product = Product.objects.filter(pk=product_id, is_active=True).first()
        if product:
            variant = None
            if variant_id:
                variant = ProductVariant.objects.filter(product_id=product_id, pk=variant_id).first()
                if not variant:
                    variant_id = None
            selected_city_id = request.session.get('selected_city_id')
            if selected_city_id:
                stock = _get_stock_in_city(selected_city_id, product_id, variant_id)
                if stock > 0:
                    quantity = min(quantity, stock)
                else:
                    stock_total = _get_stock_total(product_id, variant_id)
                    if stock_total > 0:
                        quantity = min(quantity, stock_total)
                    # иначе stock_total == 0 — под заказ, quantity не ограничиваем
            if variant:
                display_name = f'{product.name} ({variant.name})'
                price = float(variant.price)
                image_url = variant.image.url if variant.image else (product.image.url if product.image else '')
            else:
                display_name = product.name
                price = float(product.price)
                image_url = product.image.url if product.image else ''
            if quantity > 0:
                cart_items.append({
                    'product_id': product.pk,
                    'variant_id': variant_id,
                    'variant_name': variant.name if variant else None,
                    'name': display_name,
                    'price': price,
                    'quantity': quantity,
                    'image_url': image_url,
                    'subtotal': price * quantity,
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


def _add_product_to_cart_items(cart_items, product, variant_id, variant, quantity, price_override=None):
    """Добавить или обновить позицию товара в cart_items. Возвращает (cart_items, added_item_dict)."""
    display_name = f'{product.name} ({variant.name})' if variant else product.name
    price = float(variant.price) if variant else float(product.price)
    if price_override is not None:
        price = float(price_override)
    image_url = (variant.image.url if variant and variant.image else product.image.url) if product.image else ''
    if not image_url and variant and variant.image:
        image_url = variant.image.url
    for item in cart_items:
        if _cart_item_matches(item, product.pk, variant_id):
            item['quantity'] = item.get('quantity', 0) + quantity
            item['price'] = price
            item['subtotal'] = price * item['quantity']
            return cart_items, {
                'product_id': product.pk,
                'variant_id': variant_id,
                'variant_name': variant.name if variant else None,
                'name': display_name,
                'price': price,
                'quantity': quantity,
                'image_url': image_url,
                'subtotal': price * quantity,
            }
    cart_items.append({
        'product_id': product.pk,
        'variant_id': variant_id,
        'variant_name': variant.name if variant else None,
        'name': display_name,
        'price': price,
        'quantity': quantity,
        'image_url': image_url,
        'subtotal': price * quantity,
    })
    return cart_items, {
        'product_id': product.pk,
        'variant_id': variant_id,
        'variant_name': variant.name if variant else None,
        'name': display_name,
        'price': price,
        'quantity': quantity,
        'image_url': image_url,
        'subtotal': price * quantity,
    }


@ratelimit(key='ip', rate='30/m', method='POST')
@require_POST
def add_bundle_to_cart_view(request):
    """
    Добавить набор товаров в корзину.
    POST: bundle_id — добавить все товары набора (наборы задаются в админке).
    """
    cart_items = request.session.get('cart_items', []) or []
    bundle_id = request.POST.get('bundle_id')

    if bundle_id:
        try:
            bundle_id = int(bundle_id)
        except (TypeError, ValueError):
            bundle_id = None
        bundle = ProductBundle.objects.filter(pk=bundle_id).prefetch_related('items__product', 'items__product__variants').first()
        items = list(bundle.items.select_related('product').all()) if bundle else []
        if not bundle or len(items) < 2:
            if request.headers.get('HX-Request'):
                total = sum(i.get('subtotal', 0) for i in cart_items)
                resp = render(request, 'catalog/partials/cart_content.html', {
                    'cart_items': cart_items,
                    'total': total,
                    'cart_error': 'Набор не найден или содержит менее 2 позиций.',
                })
                resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': _get_cart_count(request)}})
                return resp
            return redirect('catalog:product_list')

        for item in items:
            product = item.product
            if not product.is_active:
                continue
            variant = product.variants.first()
            variant_id = variant.pk if variant else None
            price_in_bundle = float(item.price)
            qty = item.quantity
            cart_items, _ = _add_product_to_cart_items(
                cart_items, product, variant_id, variant, qty, price_override=price_in_bundle
            )

        request.session['cart_items'] = cart_items
        request.session.modified = True

        if request.headers.get('HX-Request'):
            total = sum(i.get('subtotal', 0) for i in cart_items)
            resp = render(request, 'catalog/partials/cart_content.html', {
                'cart_items': cart_items,
                'total': total,
            })
            resp['HX-Trigger'] = json.dumps({
                'cart-updated': {
                    'count': _get_cart_count(request),
                    'total': total,
                }
            })
            return resp
        next_url = request.POST.get('next') or request.GET.get('next') or reverse('catalog:product_list')
        return redirect(next_url)

    if request.headers.get('HX-Request'):
        total = sum(i.get('subtotal', 0) for i in cart_items)
        resp = render(request, 'catalog/partials/cart_content.html', {
            'cart_items': cart_items,
            'total': total,
            'cart_error': 'Укажите набор (bundle_id).',
        })
        resp['HX-Trigger'] = json.dumps({'cart-updated': {'count': _get_cart_count(request)}})
        return resp
    return redirect('catalog:product_list')


class ProductListView(ListView):
    """Список товаров с фильтрацией по категории, пагинацией и сортировкой."""
    model = Product
    context_object_name = 'products'
    paginate_by = 12
    template_name = 'catalog/product_list.html'

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('tags', 'characteristics').order_by('-created_at')
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
        tag_slug = (self.request.GET.get('tag') or '').strip()
        if tag_slug:
            qs = qs.filter(tags__slug=tag_slug).distinct()
        # Фильтр по цене
        price_min = self.request.GET.get('price_min')
        if price_min:
            try:
                qs = qs.filter(price__gte=float(price_min))
            except (ValueError, TypeError):
                pass
        price_max = self.request.GET.get('price_max')
        if price_max:
            try:
                qs = qs.filter(price__lte=float(price_max))
            except (ValueError, TypeError):
                pass
        # Фильтр по характеристикам (char_<name>=<value>)
        for key, value in self.request.GET.items():
            if key.startswith('char_') and value:
                ch_name = key[5:]
                qs = qs.filter(characteristics__name=ch_name, characteristics__value=value).distinct()
        sort = self.request.GET.get('sort', 'newest')
        if sort == 'price_asc':
            qs = qs.order_by('price')
        elif sort == 'price_desc':
            qs = qs.order_by('-price')
        elif sort == 'name':
            qs = qs.order_by('name')
        return qs

    def _get_filter_base_queryset(self):
        """Базовый queryset для сбора опций фильтров (без пагинации, без char-фильтров)."""
        qs = Product.objects.filter(is_active=True).select_related('category')
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
        tag_slug = (self.request.GET.get('tag') or '').strip()
        if tag_slug:
            qs = qs.filter(tags__slug=tag_slug).distinct()
        price_min = self.request.GET.get('price_min')
        if price_min:
            try:
                qs = qs.filter(price__gte=float(price_min))
            except (ValueError, TypeError):
                pass
        price_max = self.request.GET.get('price_max')
        if price_max:
            try:
                qs = qs.filter(price__lte=float(price_max))
            except (ValueError, TypeError):
                pass
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_category'] = self.request.GET.get('category', '')
        context['current_section'] = self.request.GET.get('section', '')
        context['categories'] = list(Category.objects.select_related('section').order_by('name'))
        if context['current_section']:
            context['categories'] = [c for c in context['categories'] if c.section and c.section.slug == context['current_section']]
        context['catalog_sections'] = list(CatalogSection.objects.prefetch_related('categories').order_by('order', 'name'))
        context['current_tag'] = (self.request.GET.get('tag') or '').strip()
        context['product_tags'] = list(ProductTag.objects.order_by('order', 'name'))
        context['current_sort'] = self.request.GET.get('sort', 'newest')
        context['search_query'] = (self.request.GET.get('q') or '').strip()
        context['price_min_filter'] = self.request.GET.get('price_min', '')
        context['price_max_filter'] = self.request.GET.get('price_max', '')
        context['char_filters'] = {k[5:]: v for k, v in self.request.GET.items() if k.startswith('char_') and v}
        context['filter_clear'] = ''  # для filter_url: удалить параметр

        # Опции фильтров из товаров текущего раздела
        base_qs = self._get_filter_base_queryset()
        from django.db.models import Min, Max
        price_agg = base_qs.aggregate(min_p=Min('price'), max_p=Max('price'))
        context['filter_price_min'] = int(price_agg['min_p']) if price_agg['min_p'] is not None else 0
        context['filter_price_max'] = int(price_agg['max_p']) if price_agg['max_p'] is not None else 0

        char_qs = ProductCharacteristic.objects.filter(product__in=base_qs).values('name', 'value').distinct().order_by('name', 'value')
        from collections import OrderedDict
        char_options = OrderedDict()
        for row in char_qs:
            name = row['name']
            if name not in char_options:
                char_options[name] = []
            if row['value'] not in char_options[name]:
                char_options[name].append(row['value'])
        context['filter_characteristics'] = char_options
        if self.request.user.is_authenticated:
            context['favorite_product_ids'] = set(
                Favorite.objects.filter(user=self.request.user).values_list('product_id', flat=True)
            )
        else:
            context['favorite_product_ids'] = set()
        selected_city_id = self.request.session.get('selected_city_id')
        stock_total_qs = (
            ProductStock.objects
            .values('product_id')
            .annotate(total=Sum('quantity'))
        )
        context['product_stock_total'] = {row['product_id']: row['total'] for row in stock_total_qs}
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
        return Product.objects.filter(is_active=True).prefetch_related(
            'characteristics', 'tags', 'variants', 'variants__characteristics', 'images'
        ).select_related('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context['is_favorite'] = Favorite.objects.filter(
                user=self.request.user, product=self.object
            ).exists()
        else:
            context['is_favorite'] = False
        selected_city_id = self.request.session.get('selected_city_id')

        # Остатки: для товаров с вариантами — по варианту, иначе — по товару
        if self.object.variants.exists():
            context['stock_by_variant'] = {
                v.pk: _get_stock_total(self.object.pk, v.pk)
                for v in self.object.variants.all()
            }
            context['stock_in_city_by_variant'] = {}
            if selected_city_id:
                context['stock_in_city_by_variant'] = {
                    v.pk: _get_stock_in_city(selected_city_id, self.object.pk, v.pk)
                    for v in self.object.variants.all()
                }
            context['stock_total'] = None
            context['stock_in_city'] = None
        else:
            context['stock_total'] = _get_stock_total(self.object.pk)
            context['stock_in_city'] = _get_stock_in_city(selected_city_id, self.object.pk) if selected_city_id else None
            context['stock_by_variant'] = {}
            context['stock_in_city_by_variant'] = {}

        context['selected_city'] = City.objects.filter(pk=selected_city_id).first() if selected_city_id else None

        # Характеристики вариантов для шаблона
        context['variant_characteristics'] = {
            v.pk: [(c.name, c.value) for c in v.characteristics.all()]
            for v in self.object.variants.all()
        }

        # Наборы с текущим товаром (через ProductBundleItem)
        try:
            bundles = list(
                ProductBundle.objects
                .filter(items__product=self.object)
                .prefetch_related('items__product', 'items__product__variants')
                .distinct()
            )
            # Оставляем только наборы с 2+ позициями
            context['bundles'] = [b for b in bundles if b.items.count() >= 2]
        except ProgrammingError:
            # Защита от устаревшей схемы (catalog_productbundle_products)
            context['bundles'] = []

        # Галерея фото: только основное + общие доп. фото (без фото вариантов — они показываются при выборе варианта)
        gallery = []
        seen = set()
        if self.object.image:
            url = self.request.build_absolute_uri(self.object.image.url)
            gallery.append(url)
            seen.add(url)
        for img in self.object.images.all():
            url = self.request.build_absolute_uri(img.image.url)
            if url not in seen:
                gallery.append(url)
                seen.add(url)
        context['product_gallery'] = gallery

        # Данные для Alpine.js (json_script) — избегаем проблем с x-data в атрибуте
        variants_data = [
            {
                'id': v.pk,
                'name': v.name,
                'price': float(v.price),
                'imageUrl': self.request.build_absolute_uri(v.image.url) if v.image else '',
            }
            for v in self.object.variants.all()
        ]
        context['product_detail_data'] = {
            'variants': variants_data,
            'productImage': self.request.build_absolute_uri(self.object.image.url) if self.object.image else '',
            'productPrice': float(self.object.price),
            'productGallery': gallery,
            'productCharacteristics': [[c.name, c.value] for c in self.object.characteristics.all()],
            'variantCharacteristics': context['variant_characteristics'],
            'stockByVariant': context['stock_by_variant'],
            'stockInCityByVariant': context['stock_in_city_by_variant'],
            'stockTotalProduct': context['stock_total'] if context['stock_total'] is not None else 0,
            'stockInCityProduct': context['stock_in_city'],
            'selectedCityName': context['selected_city'].name if context['selected_city'] else '',
        }

        return context


@login_required
def favorite_list_view(request):
    """Страница «Моё избранное»: список товаров, добавленных в избранное."""
    favorites = Favorite.objects.filter(user=request.user).select_related('product', 'product__category').prefetch_related('product__tags')
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
