from django.conf import settings
from django.db.models import Q
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse

from catalog.cache_utils import get_catalog_product_tags, get_home_category_backgrounds
from catalog.models import Product
from catalog.views.common import _product_stock_totals

_HOME_FEATURED_PROMO_TAG_KEYWORDS = (
    'hit',
    'хит',
    'sale',
    'распродаж',
    'акци',
    'скидк',
    'bestseller',
    'expert-choice',
    'new',
    'новин',
)

_HERO_DEFAULT_BG = [
    'https://images.unsplash.com/photo-1617802690658-1173a812650d?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1531746795393-6c2495d120b0?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?q=80&w=2070&auto=format&fit=crop',
]

_MARKETING_TILE_FALLBACKS = {
    'unitree_robot': 'products/image-Photoroom_20_4RdGPzn.webp',
    'portable_consoles': 'products/image-Photoroom_3.webp',
    'vr_attractions': 'products/Two-person_360_flight_simulator.webp',
}


def _home_view_impl(request):
    """Внутренняя реализация главной страницы."""
    promo_tag_filter = Q()
    for keyword in _HOME_FEATURED_PROMO_TAG_KEYWORDS:
        promo_tag_filter |= Q(tags__slug__icontains=keyword) | Q(tags__name__icontains=keyword)

    featured_qs = (
        Product.objects.filter(is_active=True)
        .filter(promo_tag_filter)
        .select_related('category')
        .prefetch_related('tags', 'images')
        .distinct()
        .order_by('-created_at')
    )
    tag_slug = (request.GET.get('tag') or '').strip()
    if tag_slug:
        featured_qs = featured_qs.filter(tags__slug=tag_slug).distinct()
    featured = list(featured_qs[:8])
    product_tags = get_catalog_product_tags()

    hero_dir = settings.BASE_DIR / 'static' / 'images' / 'hero'
    if (hero_dir / 'hero_1.jpg').exists():
        base_bg = [request.build_absolute_uri(static(f'images/hero/hero_{i}.jpg')) for i in range(1, 5)]
    else:
        base_bg = _HERO_DEFAULT_BG.copy()
    media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'

    def build_media_url(relative_path):
        if not relative_path:
            return ''
        relative_path = str(relative_path).lstrip('/')
        return request.build_absolute_uri(media_url + relative_path)

    def product_image_url(*name_queries, fallback=''):
        image = (
            Product.objects.filter(is_active=True, image__isnull=False)
            .exclude(image='')
            .filter(*[Q(name__icontains=query) for query in name_queries])
            .values_list('image', flat=True)
            .first()
        )
        if image:
            return build_media_url(image)
        return build_media_url(fallback)

    compact_vr_bg = request.build_absolute_uri(media_url + 'hero/compact-vr.webp')
    mart_bg = request.build_absolute_uri(media_url + 'hero/mart.webp')
    tradein_bg = request.build_absolute_uri(media_url + 'hero/tradein.webp')
    attractions_bg = request.build_absolute_uri(media_url + 'hero/attractions.webp')
    catalog_url = reverse('catalog:product_list')

    marketing_tiles = [
        {
            'key': 'quest_accessories',
            'bg_url': product_image_url('Meta Quest 3S'),
            'image_url': product_image_url('Meta Quest 3', '512GB'),
            'alt': 'Meta Quest 3 accessories',
            'url': catalog_url,
        },
        {
            'key': 'unitree_robot',
            'bg_url': product_image_url('AgiBot', fallback=_MARKETING_TILE_FALLBACKS['unitree_robot']),
            'url': catalog_url,
        },
        {
            'key': 'gamepads',
            'bg_url': product_image_url('BOBOVR P4U'),
            'url': catalog_url,
        },
        {
            'key': 'portable_consoles',
            'bg_url': product_image_url('Pico 4 Ultra', fallback=_MARKETING_TILE_FALLBACKS['portable_consoles']),
            'url': catalog_url,
        },
        {
            'key': 'vr_attractions',
            'bg_url': product_image_url('Two-person 360', fallback=_MARKETING_TILE_FALLBACKS['vr_attractions']),
            'url': f'{catalog_url}?section=vr-attrakciony',
        },
        {
            'key': 'pico_accessories',
            'image_url': product_image_url('BOBOVR S3 PRO'),
            'bg_url': product_image_url('Pico 4 Ultra'),
            'alt': 'PICO 4 accessories',
            'url': catalog_url,
        },
    ]
    marketing_tiles_map = {tile['key']: tile for tile in marketing_tiles}

    category_bg_map = {
        slug: request.build_absolute_uri(image_url)
        for slug, image_url in get_home_category_backgrounds().items()
    }

    hero_slides = [
        {
            'title': 'Компактная VR-арена',
            'description': 'Компактный формат запуска VR-локации под ключ: от 62 м², лизинг или покупка, гарантия 36 месяцев.',
            'url': '/compact-vr/',
            'btn': 'Подробнее',
            'bg_url': compact_vr_bg,
            'bg_position': 'center center',
        },
        {
            'title': '\u0426\u0438\u0444\u0440\u043e\u0432\u044b\u0435 \u0442\u043e\u0432\u0430\u0440\u044b',
            'description': 'Цифровые товары и контент для VR. Ключи, подписки и лицензии в одном месте.',
            'url': f'{catalog_url}?section=cifrovye-tovary',
            'btn': 'В каталог',
            'bg_url': mart_bg,
            'bg_position': 'center center',
        },
        {
            'title': 'Трейд-ин',
            'description': 'Сдайте старый шлем и получите скидку на новое оборудование. Выгодный обмен и быстрая оценка.',
            'url': catalog_url,
            'btn': 'Подробнее',
            'bg_url': tradein_bg,
            'bg_position': 'center center',
        },
        {
            'title': 'VR Аттракционы',
            'description': 'Коммерческие VR-аттракционы: гонки 5D, хоррор-комнаты, сферические симуляторы для парков и ТЦ.',
            'url': f'{catalog_url}?section=vr-attrakciony',
            'btn': 'Аттракционы',
            'bg_url': attractions_bg,
            'bg_position': '60% center',
        },
    ]
    hero_slide_width_pct = (100 // len(hero_slides)) if hero_slides else 25
    from catalog.cart_services import get_favorite_product_ids

    favorite_product_ids = get_favorite_product_ids(request)
    return render(request, 'home.html', {
        'featured_products': featured,
        'product_tags': product_tags,
        'current_tag': tag_slug,
        'hero_slides': hero_slides,
        'hero_slide_width_pct': hero_slide_width_pct,
        'favorite_product_ids': favorite_product_ids,
        'product_stock_total': _product_stock_totals([product.pk for product in featured]),
        'marketing_tiles': marketing_tiles,
        'marketing_tiles_map': marketing_tiles_map,
        'category_bg_map': category_bg_map,
    })


def home_view(request):
    """Главная страница: hero, лучшие предложения, сетка категорий."""
    return _home_view_impl(request)
