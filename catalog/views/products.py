import json
import re
import time
from hashlib import sha1
from difflib import SequenceMatcher

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, Count, F, IntegerField, Max, Prefetch, Q, Sum, Value, When
from django.db.utils import ProgrammingError
from django.http import JsonResponse
from django.views.generic import DetailView, ListView

from config.formatting import format_amount

from ..cache_utils import get_active_category_ids, get_catalog_sections
from ..cart_services import get_cart_items
from ..filtering import CatalogFilterService
from ..image_utils import (
    RESPONSIVE_GALLERY_WIDTHS,
    RESPONSIVE_HERO_WIDTHS,
    RESPONSIVE_VARIANT_WIDTHS,
    build_responsive_image_data,
)
from ..models import (
    Category,
    GamePack,
    GamePackEntry,
    ProductDescriptionBlock,
    Product,
    ProductBundle,
    ProductContentBlock,
    ProductStock,
    ProductVariant,
)
from ..product_descriptions import resolve_product_description
from ..pricing import (
    PURCHASE_MODE_REQUEST_ONLY,
    PURCHASE_MODE_ON_REQUEST,
    PURCHASE_MODE_STOCK,
    has_explicit_in_stock_price,
    has_explicit_on_request_price,
    resolve_catalog_effective_price,
    resolve_in_stock_base_price,
    resolve_in_stock_price,
    resolve_on_request_price,
    resolve_public_purchase_mode,
)
from ..recommendations import build_pdp_recommendations
from ..stock import public_product_stock_status, public_stock_status
from .common import (
    ALWAYS_AVAILABLE_STOCK_TOTAL,
    _get_stock_total,
    _product_stock_totals,
    _variant_stock_totals,
    _with_game_pack_availability,
)

LIVE_SEARCH_MIN_QUERY_LENGTH = 2
LIVE_SEARCH_MAX_QUERY_LENGTH = 80
LIVE_SEARCH_GROUP_LIMIT = 3
LIVE_SEARCH_CACHE_TTL_SECONDS = 120


class HtmxPartialResponseMixin:
    def is_htmx_request(self):
        return self.request.headers.get('HX-Request') == 'true'

    def get_htmx_page_title(self):
        return ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['render_htmx_partial'] = self.is_htmx_request()
        context['htmx_page_title'] = self.get_htmx_page_title() if context['render_htmx_partial'] else ''
        return context


def _normalize_live_search_query(raw_query):
    return (raw_query or '').strip()[:LIVE_SEARCH_MAX_QUERY_LENGTH]


def _build_live_search_cache_key(request, query):
    host = request.get_host() if request is not None else ''
    scheme = 'https' if request is not None and request.is_secure() else 'http'
    digest = sha1(f'{scheme}:{host}:{query.casefold()}'.encode('utf-8')).hexdigest()
    return f'bizonvr:catalog:search_suggest:{digest}'


def _build_media_url(request, image_field):
    if not image_field:
        return ''
    try:
        image_url = image_field.url
    except (ValueError, AttributeError):
        return ''
    return request.build_absolute_uri(image_url)


def _format_price_label(value):
    if value is None:
        return ''
    return f'{format_amount(value)} ₽'


def _resolve_product_display_image(product):
    if product.image:
        return product.image
    for variant in product.variants.all():
        if variant.image:
            return variant.image
    extra_images = list(product.images.all())
    first_extra = extra_images[0] if extra_images else None
    if first_extra and first_extra.image:
        return first_extra.image
    return None


def _resolve_short_status(stock_total, *, allow_order_on_request=True):
    if int(stock_total or 0) > 0:
        return 'В наличии'
    if allow_order_on_request:
        return 'Под заказ'
    return 'Нет в наличии'


def _serialize_product_suggestion(request, product, stock_total):
    image = _resolve_product_display_image(product)
    price = resolve_catalog_effective_price(product, stock_total=stock_total)
    status = public_product_stock_status(product, stock_total)
    return {
        'type': 'product',
        'title': product.name,
        'subtitle': product.category.name if product.category_id else '',
        'url': product.get_absolute_url(),
        'image_url': _build_media_url(request, image),
        'price_label': _format_price_label(price),
        'status_label': status['label'] if not product.tracks_stock else _resolve_short_status(
            stock_total,
            allow_order_on_request=product.allow_order_on_request,
        ),
        'badge': 'Товар',
    }


def _resolve_bundle_status(bundle, product_stock_totals):
    has_on_request_items = False
    has_items = False
    for item in bundle.items.all():
        has_items = True
        stock_total = product_stock_totals.get(item.product_id, 0)
        if stock_total > 0:
            continue
        if item.product.allow_order_on_request:
            has_on_request_items = True
            continue
        return 'Нет в наличии'
    if not has_items:
        return 'Нет в наличии'
    if has_on_request_items:
        return 'Под заказ'
    return 'В наличии'


def _serialize_bundle_suggestion(request, bundle, product_stock_totals):
    image = bundle.get_display_image()
    bundle_items = list(bundle.items.all())
    item_names = [item.product.name for item in bundle_items[:2]]
    subtitle = ', '.join(item_names)
    if len(bundle_items) > 2:
        subtitle = f'{subtitle} и еще {len(bundle_items) - 2}'
    return {
        'type': 'bundle',
        'title': bundle.name or f'Комплект #{bundle.pk}',
        'subtitle': subtitle,
        'url': bundle.get_absolute_url(),
        'image_url': _build_media_url(request, image),
        'price_label': _format_price_label(bundle.total_price),
        'status_label': _resolve_bundle_status(bundle, product_stock_totals),
        'badge': 'Комплект',
    }


def _serialize_variant_suggestion(request, variant, stock_total):
    image = variant.image or _resolve_product_display_image(variant.product)
    price = resolve_catalog_effective_price(variant.product, variant, stock_total=stock_total)
    subtitle_bits = []
    if variant.sku:
        subtitle_bits.append(f'SKU: {variant.sku}')
    if variant.product.category_id:
        subtitle_bits.append(variant.product.category.name)
    return {
        'type': 'variant',
        'title': f'{variant.product.name} · {variant.name}',
        'subtitle': ' • '.join(subtitle_bits) if subtitle_bits else 'Вариант товара',
        'url': f'{variant.product.get_absolute_url()}?variant={variant.pk}',
        'image_url': _build_media_url(request, image),
        'price_label': _format_price_label(price),
        'status_label': _resolve_short_status(
            stock_total,
            allow_order_on_request=variant.product.allow_order_on_request,
        ),
        'badge': 'Вариант',
    }


def product_search_suggest_view(request):
    query = _normalize_live_search_query(request.GET.get('q'))
    empty_payload = {
        'query': query,
        'groups': {
            'products': [],
            'bundles': [],
            'variants': [],
        },
        'has_results': False,
    }
    if len(query) < LIVE_SEARCH_MIN_QUERY_LENGTH:
        return JsonResponse(empty_payload)

    cache_key = _build_live_search_cache_key(request, query)
    cached_payload = cache.get(cache_key)
    if cached_payload is not None:
        return JsonResponse(cached_payload)

    products = list(
        Product.objects.filter(is_active=True)
        .filter(Q(name__icontains=query) | Q(description__icontains=query))
        .select_related('category')
        .prefetch_related('variants', 'images')
        .annotate(
            relevance=Case(
                When(name__istartswith=query, then=Value(4)),
                When(name__icontains=query, then=Value(3)),
                When(description__icontains=query, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .filter(relevance__gt=0)
        .order_by('-relevance', '-created_at')[:LIVE_SEARCH_GROUP_LIMIT]
    )
    product_stock_totals = _product_stock_totals([product.pk for product in products])

    bundles = list(
        ProductBundle.objects.select_related('category')
        .prefetch_related('items__product')
        .annotate(items_count=Count('items', distinct=True))
        .filter(items_count__gte=2)
        .filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(items__product__name__icontains=query)
            | Q(items__product__description__icontains=query)
        )
        .annotate(
            relevance=Max(
                Case(
                    When(name__istartswith=query, then=Value(4)),
                    When(name__icontains=query, then=Value(3)),
                    When(description__icontains=query, then=Value(2)),
                    When(items__product__name__istartswith=query, then=Value(2)),
                    When(items__product__name__icontains=query, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
        )
        .filter(relevance__gt=0)
        .order_by('-relevance', '-created_at')[:LIVE_SEARCH_GROUP_LIMIT]
    )
    bundle_product_ids = []
    for bundle in bundles:
        bundle_product_ids.extend(item.product_id for item in bundle.items.all())
    bundle_product_stock_totals = _product_stock_totals(bundle_product_ids)

    variants = list(
        ProductVariant.objects.select_related('product', 'product__category')
        .prefetch_related('product__images', 'product__variants')
        .filter(product__is_active=True)
        .filter(Q(name__icontains=query) | Q(sku__icontains=query))
        .annotate(
            relevance=Case(
                When(sku__iexact=query, then=Value(5)),
                When(name__iexact=query, then=Value(4)),
                When(sku__istartswith=query, then=Value(3)),
                When(name__istartswith=query, then=Value(3)),
                When(sku__icontains=query, then=Value(2)),
                When(name__icontains=query, then=Value(2)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .filter(relevance__gt=0)
        .order_by('-relevance', '-product__created_at', 'order', 'name')[:LIVE_SEARCH_GROUP_LIMIT]
    )
    variant_stock_totals = _variant_stock_totals([variant.product_id for variant in variants])

    groups = {
        'products': [
            _serialize_product_suggestion(request, product, product_stock_totals.get(product.pk, 0))
            for product in products
        ],
        'bundles': [
            _serialize_bundle_suggestion(request, bundle, bundle_product_stock_totals)
            for bundle in bundles
        ],
        'variants': [
            _serialize_variant_suggestion(request, variant, variant_stock_totals.get(variant.pk, 0))
            for variant in variants
        ],
    }
    payload = {
        'query': query,
        'groups': groups,
        'has_results': any(groups.values()),
    }
    cache.set(cache_key, payload, LIVE_SEARCH_CACHE_TTL_SECONDS)
    return JsonResponse(payload)


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

    def _sort_game_pack_queryset(self, qs):
        sort, search_query = self._get_resolved_sort()
        if sort == 'relevance' and search_query:
            return qs.order_by('-created_at')
        if sort == 'price_asc':
            return qs.order_by(F('catalog_effective_price').asc(), '-created_at')
        if sort == 'price_desc':
            return qs.order_by(F('catalog_effective_price').desc(), '-created_at')
        if sort == 'name':
            return qs.order_by('name', '-created_at')
        if sort == 'popularity':
            return qs.order_by('-views_count', '-created_at')
        return qs.order_by('sort_order', '-created_at')

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
            item.regular_line_total = float(item.regular_price) * item.quantity
        context['bundle_items'] = items
        context['total_price'] = float(bundle.total_price)
        context['total_without_discount'] = float(bundle.total_price_without_discount)
        context['bundles_category'] = bundle.category
        return context


class GamePackDetailView(DetailView):
    model = GamePack
    context_object_name = 'game_pack'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/game_pack_detail.html'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        GamePack.objects.filter(pk=self.object.pk).update(views_count=F('views_count') + 1)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_queryset(self):
        return GamePack.objects.select_related('category').prefetch_related(
            'tags',
            Prefetch('entries', queryset=GamePackEntry.objects.select_related('product', 'product__category').order_by('sort_order', 'id')),
            'entries__product__images',
            'entries__product__characteristics',
            'service_entries__service',
        ).filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        game_pack = self.object
        game_pack_entries = list(game_pack.entries.all())
        game_pack_service_entries = list(game_pack.service_entries.all())

        context['bundle_items'] = []
        context['game_pack_entries'] = game_pack_entries
        context['game_pack_service_entries'] = game_pack_service_entries
        context['stock_total'] = ALWAYS_AVAILABLE_STOCK_TOTAL
        context['stock_status'] = 'digital_pack'

        def _safe_image_url(img_field):
            try:
                return self.request.build_absolute_uri(img_field.url) if img_field else ''
            except (ValueError, OSError):
                return ''

        def _safe_image_dimensions(img_field):
            try:
                if not img_field:
                    return None, None
                width = int(getattr(img_field, 'width', 0) or 0)
                height = int(getattr(img_field, 'height', 0) or 0)
            except (ValueError, OSError, FileNotFoundError):
                return None, None
            if width <= 0 or height <= 0:
                return None, None
            return width, height

        def _serialize_responsive_image(img_field, *, widths, default_width, sizes=''):
            return build_responsive_image_data(
                img_field,
                widths=widths,
                default_width=default_width,
                request=self.request,
                sizes=sizes,
            )

        display_image = game_pack.get_display_image()
        display_image_width, display_image_height = _safe_image_dimensions(display_image)
        hero_image = _serialize_responsive_image(
            display_image,
            widths=RESPONSIVE_HERO_WIDTHS,
            default_width=960,
            sizes='(min-width: 1280px) 42vw, (min-width: 768px) 50vw, 100vw',
        )
        thumbnail_image = _serialize_responsive_image(
            display_image,
            widths=RESPONSIVE_GALLERY_WIDTHS,
            default_width=240,
            sizes='96px',
        )

        game_pack_media = []
        game_pack_gallery = []
        if display_image:
            hero_image_url = hero_image.get('src') or _safe_image_url(display_image)
            thumbnail_image_url = thumbnail_image.get('src') or hero_image_url
            if hero_image_url:
                game_pack_gallery.append(hero_image_url)
                game_pack_media.append({
                    'type': 'image',
                    'imageUrl': hero_image_url,
                    'imageSrcset': hero_image.get('srcset', ''),
                    'imageSizes': hero_image.get('sizes', ''),
                    'thumbnailUrl': thumbnail_image_url,
                    'thumbnailSrcset': thumbnail_image.get('srcset', ''),
                    'thumbnailSizes': thumbnail_image.get('sizes', ''),
                    'title': game_pack.name,
                    'width': display_image_width,
                    'height': display_image_height,
                })

        product_in_stock_price = resolve_in_stock_price(game_pack)
        product_on_request_price = resolve_on_request_price(game_pack)
        product_public_purchase_mode = resolve_public_purchase_mode(
            game_pack,
            stock_total=context['stock_total'],
        )
        default_purchase_mode = PURCHASE_MODE_STOCK
        if product_public_purchase_mode == PURCHASE_MODE_ON_REQUEST:
            default_purchase_mode = PURCHASE_MODE_ON_REQUEST

        cart_qty_product = {
            PURCHASE_MODE_STOCK: 0,
            PURCHASE_MODE_ON_REQUEST: 0,
        }
        for item in get_cart_items(self.request):
            if item.get('game_pack_id') != game_pack.pk:
                continue
            quantity = max(0, int(item.get('quantity') or 0))
            purchase_mode = item.get('purchase_mode') or PURCHASE_MODE_STOCK
            cart_qty_product[purchase_mode] = cart_qty_product.get(purchase_mode, 0) + quantity

        context['game_pack_media'] = game_pack_media
        context['game_pack_gallery'] = game_pack_gallery
        context['game_pack_detail_data'] = {
            'productImage': hero_image.get('src') or _safe_image_url(display_image),
            'productPrice': _float_or_none(game_pack.price),
            'productDiscountPercent': _float_or_none(game_pack.discount_percent),
            'productRegularInStockPrice': _float_or_none(resolve_in_stock_base_price(game_pack)),
            'productInStockPrice': _float_or_none(product_in_stock_price),
            'productOnRequestPrice': _float_or_none(product_on_request_price),
            'productHasInStockPrice': has_explicit_in_stock_price(game_pack),
            'productHasOnRequestPrice': has_explicit_on_request_price(game_pack),
            'productPublicPurchaseMode': product_public_purchase_mode,
            'productEffectivePrice': _float_or_none(
                resolve_catalog_effective_price(
                    game_pack,
                    stock_total=context['stock_total'],
                )
            ),
            'productGallery': game_pack_gallery,
            'productMedia': game_pack_media,
            'stockTotalProduct': context['stock_total'],
            'stockStatusProduct': context['stock_status'],
            'defaultPurchaseMode': default_purchase_mode,
            'allowOrderOnRequest': game_pack.allow_order_on_request,
            'isGamePack': True,
            'cartQtyProduct': cart_qty_product,
        }
        context['game_pack_detail_data_json'] = json.dumps(
            context['game_pack_detail_data'],
            ensure_ascii=False,
        )
        return context


class ProductListView(HtmxPartialResponseMixin, ListView):
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

    def get_htmx_page_title(self):
        return 'Каталог — BizonVR'

    def _sort_game_pack_queryset(self, qs):
        sort, search_query = self._get_resolved_sort()
        if sort == 'relevance' and search_query:
            return qs.order_by('-created_at')
        if sort == 'price_asc':
            return qs.order_by(F('catalog_effective_price').asc(), '-created_at')
        if sort == 'price_desc':
            return qs.order_by(F('catalog_effective_price').desc(), '-created_at')
        if sort == 'name':
            return qs.order_by('name', '-created_at')
        if sort == 'popularity':
            return qs.order_by('-views_count', '-created_at')
        return qs.order_by('sort_order', '-created_at')

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
        if self.filter_service.is_bundle_mode or self.filter_service.is_game_pack_mode:
            return Product.objects.none()

        qs = (
            self._build_filter_queryset(include_char_filters=True)
            .select_related('category')
            .prefetch_related('tags', 'variants', 'images')
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
        game_pack_category_ids = set(
            GamePack.objects.filter(category__isnull=False, is_active=True).values_list('category_id', flat=True).distinct()
        )
        context['category_ids_to_show'] = list(category_ids_with_products | bundle_category_ids | game_pack_category_ids)
        section_slugs_to_show = set()
        for section in context['catalog_sections']:
            for cat in section.categories.all():
                if cat.pk in category_ids_with_products or cat.pk in bundle_category_ids or cat.pk in game_pack_category_ids:
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
        context['is_game_packs_category'] = self.filter_service.is_game_pack_mode

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

        if context['is_game_packs_category']:
            game_packs_qs = self._sort_game_pack_queryset(self._build_filter_queryset(include_char_filters=True)).prefetch_related('tags', 'entries__product', 'service_entries__service')
            paginator = Paginator(game_packs_qs, self.paginate_by)
            page_number = self.request.GET.get('page', 1)
            try:
                page_number = max(1, int(page_number))
            except (TypeError, ValueError):
                page_number = 1
            game_pack_page = paginator.get_page(page_number)
            context['game_packs'] = game_pack_page.object_list
            context['game_pack_page_obj'] = game_pack_page
        else:
            context['game_packs'] = []
            context['game_pack_page_obj'] = None

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
        elif context['is_game_packs_category'] and context['game_pack_page_obj'] is not None:
            context['results_count'] = context['game_pack_page_obj'].paginator.count
        else:
            context['results_count'] = applied_qs.count()
        context['active_filter_chips'] = self._build_active_filter_chips(context)

        from ..cart_services import get_favorite_product_ids

        context['favorite_product_ids'] = get_favorite_product_ids(self.request)
        product_ids = [product.pk for product in context['products']]
        context['product_stock_total'] = _with_game_pack_availability(
            _product_stock_totals(product_ids),
            context['products'],
        )
        context['variant_stock_total'] = _variant_stock_totals(product_ids)
        return context


def _float_or_none(value):
    return float(value) if value is not None else None


class ProductDetailView(HtmxPartialResponseMixin, DetailView):
    """Детальная страница товара."""
    model = Product
    context_object_name = 'product'
    slug_url_kwarg = 'slug'
    template_name = 'catalog/product_detail.html'

    def get_htmx_page_title(self):
        if getattr(self, 'object', None) is not None:
            return f'{self.object.name} — BizonVR'
        return 'BizonVR'

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
            'game_pack_items',
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
        if not self.object.tracks_stock:
            context['stock_total'] = ALWAYS_AVAILABLE_STOCK_TOTAL
            context['stock_by_variant'] = {}
        elif variants:
            context['stock_by_variant'] = _variant_stock_totals([self.object.pk])
            context['stock_total'] = None
        else:
            context['stock_total'] = _get_stock_total(self.object.pk)
            context['stock_by_variant'] = {}
        context['stock_status_by_variant'] = {
            variant.pk: public_product_stock_status(self.object, context['stock_by_variant'].get(variant.pk, 0))['code']
            for variant in variants
        }
        context['stock_status'] = public_product_stock_status(self.object, context['stock_total'])['code']
        context['game_pack_items'] = list(self.object.game_pack_items.all()) if self.object.is_game_pack else []
        category_name = (self.object.category.name or '').lower() if self.object.category_id else ''
        product_name = (self.object.name or '').lower()
        context['show_vr_club_games_upsell'] = (
            not self.object.is_game_pack
            and any(token in f'{category_name} {product_name}' for token in ('шлем', 'quest', 'pico', 'vr headset', 'очки vr'))
        )
        context['vr_club_recommended_packs'] = list(
            GamePack.objects
            .filter(is_active=True, show_on_vr_club_page=True)
            .order_by('vr_club_tariff', '-created_at')[:3]
        )

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

        def _safe_image_dimensions(img_field):
            try:
                if not img_field:
                    return None, None
                width = int(getattr(img_field, 'width', 0) or 0)
                height = int(getattr(img_field, 'height', 0) or 0)
            except (ValueError, OSError, FileNotFoundError):
                return None, None
            if width <= 0 or height <= 0:
                return None, None
            return width, height

        def _serialize_responsive_image(img_field, *, widths, default_width, sizes=''):
            return build_responsive_image_data(
                img_field,
                widths=widths,
                default_width=default_width,
                request=self.request,
                sizes=sizes,
            )

        def _characteristic_value(product, name):
            for characteristic in product.characteristics.all():
                if characteristic.name == name:
                    return characteristic.value
            return ''

        if self.object.is_game_pack and context['game_pack_items']:
            linked_game_titles = [item.title for item in context['game_pack_items'] if item.title]
            linked_games = (
                Product.objects.filter(is_active=True, name__in=linked_game_titles)
                .prefetch_related('characteristics', 'images')
            )
            linked_games_by_title = {product.name: product for product in linked_games}
            enriched_game_pack_items = []
            for item in context['game_pack_items']:
                linked_product = linked_games_by_title.get(item.title)
                image_url = ''
                detail_url = ''
                genre = ''
                modes = ''
                devices = ''
                if linked_product is not None:
                    linked_image = _serialize_responsive_image(
                        linked_product.image or linked_product.get_display_image(),
                        widths=RESPONSIVE_GALLERY_WIDTHS,
                        default_width=480,
                        sizes='(min-width: 1024px) 240px, (min-width: 768px) 33vw, 100vw',
                    )
                    image_url = linked_image.get('src') or _safe_image_url(linked_product.get_display_image())
                    detail_url = linked_product.get_absolute_url()
                    genre = _characteristic_value(linked_product, 'Жанр')
                    modes = _characteristic_value(linked_product, 'Игровые режимы')
                    devices = _characteristic_value(linked_product, 'Совместимые устройства')
                enriched_game_pack_items.append({
                    'title': item.title,
                    'platform': item.platform,
                    'note': item.note,
                    'image_url': image_url,
                    'detail_url': detail_url,
                    'genre': genre,
                    'modes': modes,
                    'devices': devices,
                })
            context['game_pack_items'] = enriched_game_pack_items

        gallery = []
        product_media = []
        seen_images = set()
        seen_video_embeds = set()

        def _append_image(img_field, title=''):
            url = _safe_image_url(img_field)
            if not url or url in seen_images:
                return
            seen_images.add(url)
            width, height = _safe_image_dimensions(img_field)
            hero_image = _serialize_responsive_image(
                img_field,
                widths=RESPONSIVE_HERO_WIDTHS,
                default_width=960,
                sizes='(min-width: 1280px) 42vw, (min-width: 768px) 50vw, 100vw',
            )
            thumbnail_image = _serialize_responsive_image(
                img_field,
                widths=RESPONSIVE_GALLERY_WIDTHS,
                default_width=240,
                sizes='96px',
            )
            gallery.append(url)
            product_media.append({
                'type': 'image',
                'imageUrl': hero_image.get('src') or url,
                'imageSrcset': hero_image.get('srcset', ''),
                'imageSizes': hero_image.get('sizes', ''),
                'thumbnailUrl': thumbnail_image.get('src') or url,
                'thumbnailSrcset': thumbnail_image.get('srcset', ''),
                'thumbnailSizes': thumbnail_image.get('sizes', ''),
                'title': title or self.object.name,
                'width': width,
                'height': height,
            })

        _append_image(self.object.image, self.object.name)
        for img in self.object.images.all():
            _append_image(img.image, self.object.name)

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
            variant_image_width, variant_image_height = _safe_image_dimensions(variant.image)
            variant_hero_image = _serialize_responsive_image(
                variant.image,
                widths=RESPONSIVE_HERO_WIDTHS,
                default_width=960,
                sizes='(min-width: 1280px) 42vw, (min-width: 768px) 50vw, 100vw',
            )
            variant_thumbnail_image = _serialize_responsive_image(
                variant.image,
                widths=RESPONSIVE_VARIANT_WIDTHS,
                default_width=120,
                sizes='56px',
            )
            variant_public_mode = resolve_public_purchase_mode(
                self.object,
                variant,
                stock_total=variant_stock_total,
            )
            variants_data.append({
                'id': variant.pk,
                'name': variant.name,
                'price': _float_or_none(variant.price),
                'regularInStockPrice': _float_or_none(resolve_in_stock_base_price(self.object, variant)),
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
                'imageUrl': variant_hero_image.get('src') or _safe_image_url(variant.image),
                'imageSrcset': variant_hero_image.get('srcset', ''),
                'imageSizes': variant_hero_image.get('sizes', ''),
                'thumbnailUrl': variant_thumbnail_image.get('src') or _safe_image_url(variant.image),
                'thumbnailSrcset': variant_thumbnail_image.get('srcset', ''),
                'thumbnailSizes': variant_thumbnail_image.get('sizes', ''),
                'imageWidth': variant_image_width,
                'imageHeight': variant_image_height,
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
            'productImage': (
                _serialize_responsive_image(
                    self.object.image,
                    widths=RESPONSIVE_HERO_WIDTHS,
                    default_width=960,
                    sizes='(min-width: 1280px) 42vw, (min-width: 768px) 50vw, 100vw',
                ).get('src')
                or _safe_image_url(self.object.image)
            ),
            'productPrice': _float_or_none(self.object.price),
            'productDiscountPercent': _float_or_none(self.object.discount_percent),
            'productRegularInStockPrice': _float_or_none(resolve_in_stock_base_price(self.object)),
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
            'isGamePack': self.object.is_game_pack,
            'gamePackItems': [
                {
                    'title': item.get('title', '') if hasattr(item, 'get') else getattr(item, 'title', ''),
                    'platform': item.get('platform', '') if hasattr(item, 'get') else getattr(item, 'platform', ''),
                    'note': item.get('note', '') if hasattr(item, 'get') else getattr(item, 'note', ''),
                }
                for item in context['game_pack_items']
            ],
        }
        context['form_started_at'] = int(time.time())
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
        context['product_detail_data_json'] = json.dumps(context['product_detail_data'], ensure_ascii=False)

        return context
