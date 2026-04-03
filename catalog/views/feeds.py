from decimal import Decimal
from urllib.parse import urljoin

from django.conf import settings
from django.db.models import Prefetch
from django.http import Http404
from django.template.response import TemplateResponse
from django.utils import timezone

from ..models import CatalogSection, Category, Product, ProductImage, ProductVariant
from ..pricing import (
    PURCHASE_MODE_REQUEST_ONLY,
    resolve_catalog_effective_price,
    resolve_public_purchase_mode,
)
from .common import _get_stock_total


VR_ATTRACTIONS_SECTION_SLUG = 'vr-attrakciony'


def _build_absolute_url(request, value):
    if not value:
        return ''
    if value.startswith('http://') or value.startswith('https://'):
        return value
    try:
        return request.build_absolute_uri(value)
    except Exception:
        return urljoin(f'{settings.SITE_URL}/', value.lstrip('/'))


def _serialize_price(value):
    return str(Decimal(str(value)).quantize(Decimal('0.01')))


def _get_offer_picture_url(request, product, variant=None):
    if variant is not None and getattr(variant, 'image', None):
        return _build_absolute_url(request, variant.image.url)

    display_image = product.get_display_image()
    if display_image:
        return _build_absolute_url(request, display_image.url)

    extra_image = next(iter(getattr(product, 'prefetched_feed_images', [])), None)
    if extra_image and extra_image.image:
        return _build_absolute_url(request, extra_image.image.url)
    return ''


def _build_offer_payload(request, product, variant=None):
    stock_total = _get_stock_total(product.pk, getattr(variant, 'pk', None))
    public_purchase_mode = resolve_public_purchase_mode(product, variant, stock_total=stock_total)
    if public_purchase_mode == PURCHASE_MODE_REQUEST_ONLY:
        return None

    price = resolve_catalog_effective_price(product, variant, stock_total=stock_total)
    if price is None:
        return None

    product_url = _build_absolute_url(request, product.get_absolute_url())
    variant_suffix = f' - {variant.name}' if variant is not None else ''

    return {
        'id': (
            f'product-{product.pk}-variant-{variant.pk}'
            if variant is not None else f'product-{product.pk}'
        ),
        'available': 'true',
        'url': product_url,
        'price': _serialize_price(price),
        'category_id': product.category_id,
        'picture': _get_offer_picture_url(request, product, variant),
        'name': f'{product.name}{variant_suffix}',
        'description': product.description or '',
    }


def vr_attractions_yml_feed_view(request):
    section = (
        CatalogSection.objects
        .filter(slug=VR_ATTRACTIONS_SECTION_SLUG)
        .first()
    )
    if section is None:
        raise Http404('VR attractions section is not configured.')

    section_categories = list(
        Category.objects.filter(section=section).order_by('name', 'pk')
    )
    category_ids = [category.pk for category in section_categories]

    products = list(
        Product.objects
        .filter(is_active=True, category_id__in=category_ids)
        .select_related('category')
        .prefetch_related(
            Prefetch('variants', queryset=ProductVariant.objects.order_by('order', 'name', 'pk')),
            Prefetch('images', queryset=ProductImage.objects.order_by('order', 'pk'), to_attr='prefetched_feed_images'),
        )
        .order_by('category__name', 'name', 'pk')
    )

    offers = []
    used_category_ids = set()
    for product in products:
        variants = list(product.variants.all())
        if variants:
            for variant in variants:
                offer = _build_offer_payload(request, product, variant)
                if offer is None:
                    continue
                offers.append(offer)
                used_category_ids.add(product.category_id)
        else:
            offer = _build_offer_payload(request, product)
            if offer is None:
                continue
            offers.append(offer)
            used_category_ids.add(product.category_id)

    categories = [category for category in section_categories if category.pk in used_category_ids]
    context = {
        'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M'),
        'shop_name': settings.SITE_BRAND,
        'shop_company': settings.SITE_BRAND,
        'shop_url': settings.SITE_URL,
        'categories': categories,
        'offers': offers,
    }
    return TemplateResponse(
        request,
        'catalog/feeds/vr_attractions.yml.xml',
        context,
        content_type='application/xml; charset=utf-8',
    )
