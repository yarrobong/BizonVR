import re
from collections import OrderedDict
from difflib import SequenceMatcher

from django.core.paginator import Paginator
from django.db.models import Case, Count, F, IntegerField, Q, Sum, Value, When
from django.db.utils import ProgrammingError
from django.views.generic import DetailView, ListView

from ..cart_services import get_cart_items
from ..models import (
    CatalogSection,
    Category,
    City,
    PickupPoint,
    Product,
    ProductBundle,
    ProductCharacteristic,
    ProductStock,
    ProductTag,
)
from ..recommendations import build_pdp_recommendations
from .common import _get_stock_in_city, _get_stock_total


class BundleDetailView(DetailView):
    """Страница набора: описание, состав, кнопка «Купить комплект»."""
    model = ProductBundle
    context_object_name = 'bundle'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/bundle_detail.html'

    def get_queryset(self):
        return ProductBundle.objects.prefetch_related(
            'items__product', 'items__product__images'
        ).annotate(items_count=Count('items')).filter(items_count__gte=2)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bundle = self.object
        items = list(bundle.items.select_related('product').all())
        for item in items:
            item.line_total = float(item.effective_price) * item.quantity
        context['bundle_items'] = items
        context['total_without_discount'] = float(bundle.total_price_without_discount)
        context['total_with_discount'] = float(bundle.total_price)
        context['discount_total'] = context['total_without_discount'] - context['total_with_discount']
        selected_city_id = self.request.session.get('selected_city_id')
        context['selected_city'] = City.objects.filter(pk=selected_city_id).first() if selected_city_id else None
        if context['selected_city']:
            context['pickup_points_count'] = PickupPoint.objects.filter(city=context['selected_city']).count()
        else:
            context['pickup_points_count'] = 0
        context['bundles_category'] = Category.objects.filter(is_bundles_category=True).first()
        return context


class ProductListView(ListView):
    """Список товаров с фильтрацией по категории, пагинацией и сортировкой."""
    model = Product
    context_object_name = 'products'
    paginate_by = 20
    template_name = 'catalog/product_list.html'

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('tags', 'characteristics', 'variants', 'images').order_by('-created_at')
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            qs = qs.filter(
                Q(name__icontains=search_query) | Q(description__icontains=search_query)
            )
        category_slug = self.request.GET.get('category')
        if category_slug:
            cat = Category.objects.filter(slug=category_slug).first()
            if cat and getattr(cat, 'is_bundles_category', False):
                return Product.objects.none()
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
        for key, value in self.request.GET.items():
            if key.startswith('char_') and value:
                ch_name = key[5:]
                qs = qs.filter(characteristics__name=ch_name, characteristics__value=value).distinct()
        sort = self.request.GET.get('sort', 'newest')
        if search_query and sort == 'newest':
            sort = 'relevance'

        if sort == 'relevance' and search_query:
            qs = qs.annotate(
                relevance=Case(
                    When(name__istartswith=search_query, then=Value(3)),
                    When(name__icontains=search_query, then=Value(2)),
                    When(description__icontains=search_query, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ).order_by('-relevance', '-created_at')
        elif sort == 'price_asc':
            qs = qs.order_by('price')
        elif sort == 'price_desc':
            qs = qs.order_by('-price')
        elif sort == 'name':
            qs = qs.order_by('name')
        elif sort == 'popularity':
            qs = qs.annotate(
                favorited_count=Count('favorited_by', distinct=True),
                cart_count=Count('cart_items', distinct=True),
            ).annotate(
                popularity=F('views_count') + F('favorited_count') * 5 + F('cart_count') * 3
            ).order_by('-popularity', '-created_at')
        elif sort == 'relevance' and not search_query:
            qs = qs.order_by('-created_at')
        else:
            qs = qs.order_by('-created_at')
        return qs

    def _get_filter_base_queryset(self):
        """Базовый queryset для сбора опций фильтров (без пагинации, без char-фильтров)."""
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants', 'images')
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
        context['is_catalog_root'] = not self.request.GET
        context['current_category'] = self.request.GET.get('category', '')
        context['current_section'] = self.request.GET.get('section', '')
        context['categories'] = list(Category.objects.select_related('section').order_by('name'))
        if context['current_section']:
            context['categories'] = [c for c in context['categories'] if c.section and c.section.slug == context['current_section']]
        context['catalog_sections'] = list(CatalogSection.objects.prefetch_related('categories').order_by('order', 'name'))
        category_ids_with_products = set(
            Product.objects.filter(is_active=True).values_list('category_id', flat=True).distinct()
        )
        bundle_category_ids = set(
            Category.objects.filter(is_bundles_category=True).values_list('pk', flat=True)
        )
        context['category_ids_to_show'] = list(category_ids_with_products | bundle_category_ids)
        section_slugs_to_show = set()
        for section in context['catalog_sections']:
            for cat in section.categories.all():
                if cat.pk in category_ids_with_products or cat.pk in bundle_category_ids:
                    section_slugs_to_show.add(section.slug)
                    break
        context['section_slugs_to_show'] = list(section_slugs_to_show)
        context['current_tag'] = (self.request.GET.get('tag') or '').strip()
        sort = self.request.GET.get('sort', 'newest')
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query and sort == 'newest':
            sort = 'relevance'
        context['current_sort'] = sort
        context['search_query'] = (self.request.GET.get('q') or '').strip()
        context['price_min_filter'] = self.request.GET.get('price_min', '')
        context['price_max_filter'] = self.request.GET.get('price_max', '')
        context['char_filters'] = {k[5:]: v for k, v in self.request.GET.items() if k.startswith('char_') and v}
        context['filter_clear'] = ''

        selected_category = None
        if context['current_category']:
            selected_category = Category.objects.select_related('section').filter(slug=context['current_category']).first()
        effective_section_slug = context['current_section'] or (
            selected_category.section.slug if selected_category and selected_category.section else ''
        )
        context['current_section_effective'] = effective_section_slug
        context['current_category_obj'] = selected_category
        context['is_bundles_category'] = bool(
            selected_category and getattr(selected_category, 'is_bundles_category', False)
        )

        if context['is_bundles_category']:
            bundles_qs = (
                ProductBundle.objects
                .prefetch_related('items__product', 'items__product__images')
                .annotate(items_count=Count('items'))
                .filter(items_count__gte=2)
                .order_by('name')
            )
            paginator = Paginator(bundles_qs, self.paginate_by)
            page_number = self.request.GET.get('page', 1)
            try:
                page_number = max(1, int(page_number))
            except (TypeError, ValueError):
                page_number = 1
            bundle_page = paginator.get_page(page_number)
            context['bundles'] = bundle_page.object_list
            context['bundle_page_obj'] = bundle_page
        else:
            context['bundles'] = []
            context['bundle_page_obj'] = None

        base_qs = self._get_filter_base_queryset()
        from django.db.models import Min, Max

        price_agg = base_qs.aggregate(min_p=Min('price'), max_p=Max('price'))
        context['filter_price_min'] = int(price_agg['min_p']) if price_agg['min_p'] is not None else 0
        context['filter_price_max'] = int(price_agg['max_p']) if price_agg['max_p'] is not None else 0

        tags_qs = ProductTag.objects.filter(products__in=base_qs).order_by('order', 'name').distinct()
        context['product_tags'] = list(tags_qs)

        base_qs_with_char = base_qs
        for ch_name, ch_value in context['char_filters'].items():
            base_qs_with_char = base_qs_with_char.filter(
                characteristics__name=ch_name, characteristics__value=ch_value
            ).distinct()
        char_qs = ProductCharacteristic.objects.filter(product__in=base_qs_with_char).values('name', 'value').distinct().order_by('name', 'value')
        char_options = OrderedDict()
        for row in char_qs:
            name = row['name']
            if name not in char_options:
                char_options[name] = []
            if row['value'] not in char_options[name]:
                char_options[name].append(row['value'])
        context['filter_characteristics'] = char_options

        section_name_map = {s.slug: s.name for s in context['catalog_sections']}
        category_name_map = {}
        for section in context['catalog_sections']:
            for cat in section.categories.all():
                category_name_map[cat.slug] = cat.name
        context['section_name_map'] = section_name_map
        context['category_name_map'] = category_name_map

        similar_categories = []
        if selected_category and selected_category.section:
            candidates = [c for c in selected_category.section.categories.all() if c.pk != selected_category.pk]

            def _normalize_tokens(value):
                return [t for t in re.split(r'[^a-zA-Zа-яА-Я0-9]+', value.lower()) if t]

            base_tokens = set(_normalize_tokens(selected_category.name))
            scored = []
            for cat in candidates:
                cat_tokens = set(_normalize_tokens(cat.name))
                token_score = len(base_tokens & cat_tokens) * 2
                ratio_score = SequenceMatcher(None, selected_category.name.lower(), cat.name.lower()).ratio()
                score = token_score + ratio_score
                scored.append((score, cat))
            scored.sort(key=lambda x: x[0], reverse=True)
            similar_categories = [cat for _, cat in scored[:3]]
        context['similar_categories'] = similar_categories

        from ..cart_services import get_favorite_product_ids

        context['favorite_product_ids'] = get_favorite_product_ids(self.request)
        selected_city_id = self.request.session.get('selected_city_id')
        stock_total_qs = (
            ProductStock.objects
            .values('product_id')
            .annotate(total=Sum('quantity'))
        )
        context['product_stock_total'] = {row['product_id']: row['total'] for row in stock_total_qs}
        variant_stock_total_qs = (
            ProductStock.objects
            .filter(variant_id__isnull=False)
            .values('variant_id')
            .annotate(total=Sum('quantity'))
        )
        context['variant_stock_total'] = {row['variant_id']: row['total'] for row in variant_stock_total_qs}
        if selected_city_id:
            stock_qs = (
                ProductStock.objects
                .filter(pickup_point__city_id=selected_city_id)
                .values('product_id')
                .annotate(total=Sum('quantity'))
            )
            context['product_stock_in_city'] = {row['product_id']: row['total'] for row in stock_qs}
            variant_stock_qs = (
                ProductStock.objects
                .filter(pickup_point__city_id=selected_city_id, variant_id__isnull=False)
                .values('variant_id')
                .annotate(total=Sum('quantity'))
            )
            context['variant_stock_in_city'] = {row['variant_id']: row['total'] for row in variant_stock_qs}
        else:
            context['product_stock_in_city'] = {}
            context['variant_stock_in_city'] = {}
        return context


class ProductDetailView(DetailView):
    """Детальная страница товара."""
    model = Product
    context_object_name = 'product'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/product_detail.html'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        Product.objects.filter(pk=self.object.pk).update(views_count=F('views_count') + 1)
        viewed = request.session.get('viewed_product_ids', [])
        viewed = [self.object.pk] + [x for x in viewed if x != self.object.pk][:9]
        request.session['viewed_product_ids'] = viewed
        request.session.modified = True
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_queryset(self):
        return Product.objects.filter(is_active=True).prefetch_related(
            'characteristics', 'tags', 'variants', 'variants__characteristics', 'images'
        ).select_related('category')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from ..cart_services import get_favorite_product_ids, is_favorite

        context['is_favorite'] = is_favorite(self.request, self.object.pk)
        context['favorite_product_ids'] = get_favorite_product_ids(self.request)
        selected_city_id = self.request.session.get('selected_city_id')

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
        selected_city = context['selected_city']

        if selected_city:
            pp_qs = PickupPoint.objects.filter(city=selected_city).order_by('order', 'name')
            context['pickup_points_count'] = pp_qs.count()
            context['pickup_points_preview'] = list(pp_qs[:3])
        else:
            context['pickup_points_count'] = 0
            context['pickup_points_preview'] = []

        rec_data = build_pdp_recommendations(self.request, self.object)
        context['recommendation_sections'] = rec_data['sections']
        context['product_stock_total'] = rec_data['product_stock_total']
        context['product_stock_in_city'] = rec_data['product_stock_in_city']
        context['recommended_variant_ids'] = rec_data['recommended_variant_ids']

        context['variant_characteristics'] = {
            v.pk: [(c.name, c.value) for c in v.characteristics.all()]
            for v in self.object.variants.all()
        }

        try:
            bundles = list(
                ProductBundle.objects
                .filter(items__product=self.object)
                .prefetch_related('items__product', 'items__product__variants', 'items__product__images')
                .distinct()
            )
            context['bundles'] = [b for b in bundles if b.items.count() >= 2]
            for b in context['bundles']:
                for item in b.items.all():
                    if item.product_id != self.object.pk:
                        pid = item.product_id
                        if pid not in context['product_stock_total']:
                            qs = ProductStock.objects.filter(product_id=pid).aggregate(s=Sum('quantity'))
                            context['product_stock_total'][pid] = int(qs['s'] or 0)
                        if selected_city_id and pid not in context['product_stock_in_city']:
                            qs = ProductStock.objects.filter(
                                product_id=pid, pickup_point__city_id=selected_city_id
                            ).aggregate(s=Sum('quantity'))
                            context['product_stock_in_city'][pid] = int(qs['s'] or 0)
        except ProgrammingError:
            context['bundles'] = []

        gallery = []
        seen = set()
        try:
            if self.object.image:
                url = self.request.build_absolute_uri(self.object.image.url)
                gallery.append(url)
                seen.add(url)
            for img in self.object.images.all():
                if img.image:
                    url = self.request.build_absolute_uri(img.image.url)
                    if url not in seen:
                        gallery.append(url)
                        seen.add(url)
        except (ValueError, OSError):
            pass
        context['product_gallery'] = gallery

        def _safe_image_url(img_field):
            try:
                return self.request.build_absolute_uri(img_field.url) if img_field else ''
            except (ValueError, OSError):
                return ''

        variants_data = [
            {
                'id': v.pk,
                'name': v.name,
                'price': float(v.price),
                'imageUrl': _safe_image_url(v.image),
            }
            for v in self.object.variants.all()
        ]
        initial_variant_id = None
        raw_variant_id = (self.request.GET.get('variant') or '').strip()
        if raw_variant_id:
            try:
                requested_variant_id = int(raw_variant_id)
            except (TypeError, ValueError):
                requested_variant_id = None
            if requested_variant_id and self.object.variants.filter(pk=requested_variant_id).exists():
                initial_variant_id = requested_variant_id
        context['product_detail_data'] = {
            'variants': variants_data,
            'productImage': _safe_image_url(self.object.image),
            'productPrice': float(self.object.price),
            'productGallery': gallery,
            'productCharacteristics': [[c.name, c.value] for c in self.object.characteristics.all()],
            'variantCharacteristics': context['variant_characteristics'],
            'stockByVariant': context['stock_by_variant'],
            'stockInCityByVariant': context['stock_in_city_by_variant'],
            'stockTotalProduct': context['stock_total'] if context['stock_total'] is not None else 0,
            'stockInCityProduct': context['stock_in_city'],
            'selectedCityName': context['selected_city'].name if context['selected_city'] else '',
            'initialVariantId': initial_variant_id,
        }

        cart_qty_product = 0
        cart_qty_by_variant = {}
        for item in get_cart_items(self.request):
            if item.get('product_id') != self.object.pk:
                continue
            quantity = max(0, int(item.get('quantity') or 0))
            variant_id = item.get('variant_id')
            if variant_id is None:
                cart_qty_product += quantity
            else:
                key = str(variant_id)
                cart_qty_by_variant[key] = cart_qty_by_variant.get(key, 0) + quantity
        context['product_detail_data']['cartQtyProduct'] = cart_qty_product
        context['product_detail_data']['cartQtyByVariant'] = cart_qty_by_variant

        return context
