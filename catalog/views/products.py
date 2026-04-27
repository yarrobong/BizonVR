import re
from difflib import SequenceMatcher

from django.core.paginator import Paginator
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.utils import ProgrammingError
from django.views.generic import DetailView, ListView

from config.formatting import format_amount

from ..cache_utils import get_active_category_ids, get_catalog_sections
from ..cart_services import get_cart_items
from ..filtering import CatalogFilterService
from ..models import (
    Category,
    ProductDescriptionBlock,
    Product,
    ProductBundle,
    ProductContentBlock,
    ProductStock,
)
from ..product_descriptions import resolve_product_description
from ..pricing import (
    PURCHASE_MODE_REQUEST_ONLY,
    PURCHASE_MODE_ON_REQUEST,
    PURCHASE_MODE_STOCK,
    has_explicit_in_stock_price,
    has_explicit_on_request_price,
    resolve_catalog_effective_price,
    resolve_in_stock_price,
    resolve_on_request_price,
    resolve_public_purchase_mode,
)
from ..recommendations import build_pdp_recommendations
from ..stock import public_stock_status
from .common import _get_stock_total, _product_stock_totals, _variant_stock_totals


class BundleDetailView(DetailView):
    """Страница набора: описание, состав, кнопка «Купить комплект»."""
    model = ProductBundle
    context_object_name = 'bundle'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/bundle_detail.html'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        ProductBundle.objects.filter(pk=self.object.pk).update(views_count=F('views_count') + 1)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_queryset(self):
        return ProductBundle.objects.select_related('category').prefetch_related(
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
        context['bundles_category'] = bundle.category
        return context


class ProductListView(ListView):
    """Список товаров с фильтрацией по категории, пагинацией и сортировкой."""
    model = Product
    context_object_name = 'products'
    paginate_by = 20
    template_name = 'catalog/product_list.html'

    @property
    def filter_service(self):
        if not hasattr(self, '_filter_service'):
            self._filter_service = CatalogFilterService(self.request)
        return self._filter_service

    def _build_query_string(self, **updates):
        return self.filter_service.build_query_string(**updates)

    def _build_active_filter_chips(self, context):
        chips = []

        if context['current_section_effective'] or context['current_category']:
            label = (
                context['current_category_obj'].name
                if context['current_category_obj']
                else context['section_name_map'].get(context['current_section_effective'])
            )
            if label:
                chips.append({
                    'label': label,
                    'remove_url': self._build_query_string(section='', category=''),
                })

        if context['price_min_filter'] or context['price_max_filter']:
            if context['price_min_filter'] and context['price_max_filter']:
                price_label = (
                    f'Цена: {format_amount(context["price_min_filter"])}-'
                    f'{format_amount(context["price_max_filter"])}'
                )
            elif context['price_min_filter']:
                price_label = f'Цена: от {format_amount(context["price_min_filter"])}'
            else:
                price_label = f'Цена: до {format_amount(context["price_max_filter"])}'
            chips.append({
                'label': price_label,
                'remove_url': self._build_query_string(price_min='', price_max=''),
            })

        if context['current_tag']:
            tag_name = next(
                (tag.name for tag in context['product_tags'] if tag.slug == context['current_tag']),
                context['current_tag'],
            )
            chips.append({
                'label': tag_name,
                'remove_url': self._build_query_string(tag=''),
            })

        for item in context['active_characteristic_filters']:
            chips.append({
                'label': f'{item["label"]}: {item["value"]}',
                'remove_url': item['remove_url'],
            })

        return chips

    def _build_filter_queryset(
        self,
        *,
        ignore_category=False,
        ignore_section=False,
        ignore_tag=False,
        ignore_price=False,
        include_char_filters=False,
        exclude_char_key=None,
        ):
        return self.filter_service.build_filter_queryset(
            ignore_category=ignore_category,
            ignore_section=ignore_section,
            ignore_tag=ignore_tag,
            ignore_price=ignore_price,
            include_char_filters=include_char_filters,
            exclude_char_key=exclude_char_key,
        )

    def _get_resolved_sort(self):
        sort = self.request.GET.get('sort', 'newest')
        search_query = (self.request.GET.get('q') or '').strip()
        if search_query and sort == 'newest':
            sort = 'relevance'
        return sort, search_query

    def _sort_product_queryset(self, qs):
        sort, search_query = self._get_resolved_sort()
        if sort == 'relevance' and search_query:
            return qs.annotate(
                relevance=Case(
                    When(name__istartswith=search_query, then=Value(3)),
                    When(name__icontains=search_query, then=Value(2)),
                    When(description__icontains=search_query, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ).order_by('-relevance', '-created_at')
        if sort == 'price_asc':
            return qs.order_by(F('catalog_effective_price').asc(nulls_last=True), '-created_at')
        if sort == 'price_desc':
            return qs.order_by(F('catalog_effective_price').desc(nulls_last=True), '-created_at')
        if sort == 'name':
            return qs.order_by('name')
        if sort == 'popularity':
            return qs.annotate(
                favorited_count=Count('favorited_by', distinct=True),
                cart_count=Count('cart_items', distinct=True),
            ).annotate(
                popularity=F('views_count') + F('favorited_count') * 5 + F('cart_count') * 3
            ).order_by('-popularity', '-created_at')
        return qs.order_by('-created_at')

    def _sort_bundle_queryset(self, qs):
        sort, search_query = self._get_resolved_sort()
        if sort == 'relevance' and search_query:
            return self.filter_service.annotate_bundle_relevance(qs, search_query).order_by('-relevance', '-created_at')
        if sort == 'price_asc':
            return qs.order_by(F('bundle_total_price').asc(), '-created_at')
        if sort == 'price_desc':
            return qs.order_by(F('bundle_total_price').desc(), '-created_at')
        if sort == 'name':
            return qs.order_by('name', '-created_at')
        if sort == 'popularity':
            return qs.order_by('-views_count', '-created_at')
        return qs.order_by('-created_at')

    def get_queryset(self):
        if self.filter_service.is_bundle_mode:
            return Product.objects.none()

        qs = (
            self._build_filter_queryset(include_char_filters=True)
            .select_related('category')
            .prefetch_related('tags', 'variants')
        )
        return self._sort_product_queryset(qs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_catalog_root'] = not self.request.GET
        context['current_category'] = self.filter_service.current_category_slug
        context['current_section'] = self.filter_service.current_section_slug
        context['categories'] = list(Category.objects.select_related('section').order_by('name'))
        if context['current_section']:
            context['categories'] = [c for c in context['categories'] if c.section and c.section.slug == context['current_section']]
        context['catalog_sections'] = get_catalog_sections()
        category_ids_with_products = set(get_active_category_ids())
        bundle_category_ids = set(
            ProductBundle.objects.filter(category__isnull=False).values_list('category_id', flat=True).distinct()
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
        sort, search_query = self._get_resolved_sort()
        context['current_sort'] = sort
        context['search_query'] = (self.request.GET.get('q') or '').strip()
        context['price_min_filter'] = self.request.GET.get('price_min', '')
        context['price_max_filter'] = self.request.GET.get('price_max', '')
        context['filter_clear'] = ''

        selected_category = self.filter_service.selected_category
        effective_section_slug = self.filter_service.effective_section_slug
        context['current_section_effective'] = effective_section_slug
        context['current_category_obj'] = selected_category
        context['is_bundles_category'] = self.filter_service.is_bundle_mode

        if context['is_bundles_category']:
            bundles_qs = (
                self._sort_bundle_queryset(
                    self._build_filter_queryset(include_char_filters=True)
                )
                .prefetch_related(
                    'items__product', 'items__product__images'
                )
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

        applied_qs = self._build_filter_queryset(include_char_filters=True)
        context.update(self.filter_service.get_price_bounds())
        context['product_tags'] = self.filter_service.get_product_tags()
        characteristics_context = self.filter_service.get_characteristics_context()
        context.update(characteristics_context)
        context.update(self.filter_service.get_category_and_section_counts())

        section_name_map = {s.slug: s.name for s in context['catalog_sections']}
        category_name_map = {}
        for section in context['catalog_sections']:
            for cat in section.categories.all():
                category_name_map[cat.slug] = cat.name
        context['section_name_map'] = section_name_map
        context['category_name_map'] = category_name_map
        if search_query:
            context['catalog_heading'] = f'Результаты поиска по запросу «{search_query}»'
        elif current_category := context['current_category_obj']:
            context['catalog_heading'] = current_category.name
        elif effective_section_slug:
            context['catalog_heading'] = section_name_map.get(effective_section_slug, 'Каталог')
        else:
            context['catalog_heading'] = 'Каталог VR-оборудования'

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
        context['active_filters_count'] = (
            int(bool(context['current_section_effective'] or context['current_category']))
            + int(bool(context['current_tag']))
            + int(bool(context['price_min_filter'] or context['price_max_filter']))
            + len(context['active_characteristic_filters'])
        )
        if context['is_bundles_category'] and context['bundle_page_obj'] is not None:
            context['results_count'] = context['bundle_page_obj'].paginator.count
        else:
            context['results_count'] = applied_qs.count()
        context['active_filter_chips'] = self._build_active_filter_chips(context)

        from ..cart_services import get_favorite_product_ids

        context['favorite_product_ids'] = get_favorite_product_ids(self.request)
        product_ids = [product.pk for product in context['products']]
        context['product_stock_total'] = _product_stock_totals(product_ids)
        context['variant_stock_total'] = _variant_stock_totals(product_ids)
        return context


def _float_or_none(value):
    return float(value) if value is not None else None


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
            'characteristics',
            'tags',
            'variants',
            'variants__characteristics',
            'images',
            'videos',
            Prefetch(
                'content_blocks',
                queryset=ProductContentBlock.objects.filter(is_active=True).order_by('sort_order', 'id'),
                to_attr='active_content_blocks',
            ),
            Prefetch(
                'product_description__blocks',
                queryset=(
                    ProductDescriptionBlock.objects
                    .select_related('block_type')
                    .prefetch_related('assets')
                    .order_by('sort_order', 'id')
                ),
            ),
        ).select_related('category', 'product_description', 'product_description__template')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from ..cart_services import (
            get_favorite_product_ids,
            is_favorite,
        )
        from orders.forms import PurchaseRequestForm

        context['is_favorite'] = is_favorite(self.request, self.object.pk)
        context['favorite_product_ids'] = get_favorite_product_ids(self.request)

        variants = list(self.object.variants.all())
        if variants:
            context['stock_by_variant'] = _variant_stock_totals([self.object.pk])
            context['stock_total'] = None
        else:
            context['stock_total'] = _get_stock_total(self.object.pk)
            context['stock_by_variant'] = {}
        context['stock_status_by_variant'] = {
            variant.pk: public_stock_status(context['stock_by_variant'].get(variant.pk, 0))['code']
            for variant in variants
        }
        context['stock_status'] = public_stock_status(context['stock_total'])['code']

        rec_data = build_pdp_recommendations(self.request, self.object)
        context['recommendation_sections'] = rec_data['sections']
        context['product_stock_total'] = rec_data['product_stock_total']
        context['recommended_variant_ids'] = rec_data['recommended_variant_ids']
        recommended_product_ids = []
        recommended_variants = {}

        for section in context['recommendation_sections']:
            for recommended_product in section['products']:
                if recommended_product.pk not in recommended_product_ids:
                    recommended_product_ids.append(recommended_product.pk)
                variant_id = context['recommended_variant_ids'].get(recommended_product.pk)
                if not variant_id:
                    continue
                recommended_variant = next(
                    (variant for variant in recommended_product.variants.all() if variant.pk == variant_id),
                    None,
                )
                if recommended_variant is not None:
                    recommended_variants[recommended_product.pk] = recommended_variant

        context['recommended_variants'] = recommended_variants
        context['variant_stock_total'] = _variant_stock_totals(recommended_product_ids)

        context['variant_characteristics'] = {
            v.pk: [(c.name, c.value) for c in v.characteristics.all()]
            for v in variants
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
        except ProgrammingError:
            context['bundles'] = []

        def _safe_image_url(img_field):
            try:
                return self.request.build_absolute_uri(img_field.url) if img_field else ''
            except (ValueError, OSError):
                return ''

        gallery = []
        product_media = []
        seen_images = set()
        seen_video_embeds = set()

        def _append_image(url, title=''):
            if not url or url in seen_images:
                return
            seen_images.add(url)
            gallery.append(url)
            product_media.append({
                'type': 'image',
                'imageUrl': url,
                'thumbnailUrl': url,
                'title': title or self.object.name,
            })

        _append_image(_safe_image_url(self.object.image), self.object.name)
        for img in self.object.images.all():
            _append_image(_safe_image_url(img.image), self.object.name)

        for video in self.object.videos.all():
            embed_url = (video.embed_url or '').strip()
            if not embed_url or embed_url in seen_video_embeds:
                continue
            seen_video_embeds.add(embed_url)
            product_media.append({
                'type': 'video',
                'embedUrl': embed_url,
                'thumbnailUrl': (video.thumbnail_url or '').strip(),
                'title': (video.title or self.object.name).strip(),
            })

        context['product_gallery'] = gallery
        context['product_media'] = product_media
        description_resolution = resolve_product_description(self.object)
        context['active_content_blocks'] = list(getattr(self.object, 'active_content_blocks', []))
        context['description_view'] = description_resolution['new']
        context['legacy_description_blocks'] = description_resolution['legacy_blocks']
        context['description_source'] = description_resolution['source']

        variants_data = []
        for variant in variants:
            variant_stock_total = context['stock_by_variant'].get(variant.pk, 0)
            variant_in_stock_price = resolve_in_stock_price(self.object, variant)
            variant_on_request_price = resolve_on_request_price(self.object, variant)
            variant_public_mode = resolve_public_purchase_mode(
                self.object,
                variant,
                stock_total=variant_stock_total,
            )
            variants_data.append({
                'id': variant.pk,
                'name': variant.name,
                'price': _float_or_none(variant.price),
                'inStockPrice': _float_or_none(variant_in_stock_price),
                'onRequestPrice': _float_or_none(variant_on_request_price),
                'hasInStockPrice': has_explicit_in_stock_price(self.object, variant),
                'hasOnRequestPrice': has_explicit_on_request_price(self.object, variant),
                'publicPurchaseMode': variant_public_mode,
                'effectivePrice': _float_or_none(
                    resolve_catalog_effective_price(
                        self.object,
                        variant,
                        stock_total=variant_stock_total,
                    )
                ),
                'imageUrl': _safe_image_url(variant.image),
            })
        initial_variant_id = None
        raw_variant_id = (self.request.GET.get('variant') or '').strip()
        if raw_variant_id:
            try:
                requested_variant_id = int(raw_variant_id)
            except (TypeError, ValueError):
                requested_variant_id = None
            if requested_variant_id and any(variant.pk == requested_variant_id for variant in variants):
                initial_variant_id = requested_variant_id
        purchase_request_source_path = self.object.get_absolute_url()
        if initial_variant_id:
            purchase_request_source_path = f'{purchase_request_source_path}?variant={initial_variant_id}'
        product_in_stock_price = resolve_in_stock_price(self.object)
        product_on_request_price = resolve_on_request_price(self.object)
        has_product_on_request_price = has_explicit_on_request_price(self.object)
        product_stock_total = context['stock_total'] if context['stock_total'] is not None else 0
        product_public_purchase_mode = resolve_public_purchase_mode(
            self.object,
            stock_total=product_stock_total,
        )
        default_purchase_mode = PURCHASE_MODE_STOCK
        if product_public_purchase_mode == PURCHASE_MODE_ON_REQUEST:
            default_purchase_mode = PURCHASE_MODE_ON_REQUEST

        context['product_detail_data'] = {
            'variants': variants_data,
            'productImage': _safe_image_url(self.object.image),
            'productPrice': _float_or_none(self.object.price),
            'productInStockPrice': _float_or_none(product_in_stock_price),
            'productOnRequestPrice': _float_or_none(product_on_request_price),
            'productHasInStockPrice': has_explicit_in_stock_price(self.object),
            'productHasOnRequestPrice': has_product_on_request_price,
            'productPublicPurchaseMode': product_public_purchase_mode,
            'productEffectivePrice': _float_or_none(
                resolve_catalog_effective_price(
                    self.object,
                    stock_total=product_stock_total,
                )
            ),
            'productGallery': gallery,
            'productMedia': product_media,
            'productCharacteristics': [[c.name, c.value] for c in self.object.characteristics.all()],
            'variantCharacteristics': context['variant_characteristics'],
            'stockByVariant': context['stock_by_variant'],
            'stockStatusByVariant': context['stock_status_by_variant'],
            'stockTotalProduct': context['stock_total'] if context['stock_total'] is not None else 0,
            'stockStatusProduct': context['stock_status'],
            'initialVariantId': initial_variant_id,
            'defaultPurchaseMode': default_purchase_mode,
            'purchaseModes': {
                'stock': PURCHASE_MODE_STOCK,
                'on_request': PURCHASE_MODE_ON_REQUEST,
                'request_only': PURCHASE_MODE_REQUEST_ONLY,
            },
            'allowOrderOnRequest': self.object.allow_order_on_request,
        }
        context['purchase_request_source_path'] = purchase_request_source_path
        if 'purchase_request_form' not in context:
            context['purchase_request_form'] = PurchaseRequestForm(initial={
                'product_id': self.object.pk,
                'variant_id': initial_variant_id,
                'source_path': purchase_request_source_path,
            })
        context['purchase_request_variant_id'] = context['purchase_request_form']['variant_id'].value()

        cart_qty_product = {
            PURCHASE_MODE_STOCK: 0,
            PURCHASE_MODE_ON_REQUEST: 0,
        }
        cart_qty_by_variant = {}
        for item in get_cart_items(self.request):
            if item.get('product_id') != self.object.pk:
                continue
            quantity = max(0, int(item.get('quantity') or 0))
            variant_id = item.get('variant_id')
            purchase_mode = item.get('purchase_mode') or PURCHASE_MODE_STOCK
            if variant_id is None:
                cart_qty_product[purchase_mode] = cart_qty_product.get(purchase_mode, 0) + quantity
            else:
                key = f'{variant_id}:{purchase_mode}'
                cart_qty_by_variant[key] = cart_qty_by_variant.get(key, 0) + quantity
        context['product_detail_data']['cartQtyProduct'] = cart_qty_product
        context['product_detail_data']['cartQtyByVariant'] = cart_qty_by_variant

        return context
