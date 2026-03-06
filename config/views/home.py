from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse

from catalog.cache_utils import CACHE_KEY_PRODUCT_TAGS
from catalog.models import Product, ProductTag

_CACHE_TTL = 300
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


def _home_view_impl(request):
    """Внутренняя реализация главной страницы."""
    promo_tag_filter = Q()
    for keyword in _HOME_FEATURED_PROMO_TAG_KEYWORDS:
        promo_tag_filter |= Q(tags__slug__icontains=keyword) | Q(tags__name__icontains=keyword)

    featured_qs = (
        Product.objects.filter(is_active=True)
        .filter(promo_tag_filter)
        .select_related('category')
        .prefetch_related('tags')
        .distinct()
        .order_by('-created_at')
    )
    tag_slug = (request.GET.get('tag') or '').strip()
    if tag_slug:
        featured_qs = featured_qs.filter(tags__slug=tag_slug).distinct()
    featured = list(featured_qs[:8])
    product_tags = cache.get(CACHE_KEY_PRODUCT_TAGS)
    if product_tags is None:
        product_tags = list(ProductTag.objects.order_by('order', 'name'))
        cache.set(CACHE_KEY_PRODUCT_TAGS, product_tags, _CACHE_TTL)

    hero_dir = settings.BASE_DIR / 'static' / 'images' / 'hero'
    if (hero_dir / 'hero_1.jpg').exists():
        from django.templatetags.static import static

        base_bg = [request.build_absolute_uri(static(f'images/hero/hero_{i}.jpg')) for i in range(1, 5)]
    else:
        base_bg = _HERO_DEFAULT_BG.copy()
    media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'

    def build_media_url(relative_path):
        if not relative_path:
            return ''
        relative_path = str(relative_path).lstrip('/')
        return request.build_absolute_uri(media_url + relative_path)

    mart_bg = request.build_absolute_uri(media_url + 'hero/mart.webp')
    tradein_bg = request.build_absolute_uri(media_url + 'hero/tradein.webp')
    attractions_bg = request.build_absolute_uri(media_url + 'hero/attractions.webp')
    catalog_url = reverse('catalog:product_list')

    marketing_tiles = [
        {
            'key': 'quest_accessories',
            'bg_url': build_media_url('products/Quest_3s_Lite_Pack.webp'),
            'image_url': build_media_url('products/Meta_Quest_3_512GB.webp'),
            'alt': 'Meta Quest 3 accessories',
            'url': catalog_url,
        },
        {
            'key': 'unitree_robot',
            'bg_url': build_media_url('products/image-Photoroom_20_4RdGPzn.png'),
            'url': catalog_url,
        },
        {
            'key': 'gamepads',
            'bg_url': build_media_url('products/BoboVR_P4U.webp'),
            'url': catalog_url,
        },
        {
            'key': 'portable_consoles',
            'bg_url': build_media_url('products/image-Photoroom_3.png'),
            'url': catalog_url,
        },
        {
            'key': 'vr_attractions',
            'bg_url': build_media_url('products/Two-person_360_flight_simulator.png'),
            'url': f'{catalog_url}?section=vr-attrakciony',
        },
        {
            'key': 'pico_accessories',
            'image_url': build_media_url('products/bobovr_s3.webp'),
            'bg_url': build_media_url('products/Quest_3s_Lite_Pack_aRPKIUk.webp'),
            'alt': 'PICO 4 accessories',
            'url': catalog_url,
        },
    ]
    marketing_tiles_map = {tile['key']: tile for tile in marketing_tiles}

    category_bg_map = {}
    latest_category_images = (
        Product.objects.filter(is_active=True, image__isnull=False)
        .order_by('category_id', '-updated_at')
        .distinct('category_id')
        .values('category__slug', 'image')
    )
    for entry in latest_category_images:
        slug = entry['category__slug']
        if slug:
            category_bg_map[slug] = build_media_url(entry['image'])

    hero_slides = [
        {
            'title': 'Цифровой магазин',
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
        'marketing_tiles': marketing_tiles,
        'marketing_tiles_map': marketing_tiles_map,
        'category_bg_map': category_bg_map,
    })


def home_view(request):
    """Главная страница: hero, лучшие предложения, сетка категорий. Без полного кэша страницы, чтобы шапка (города из БД) всегда была актуальной."""
    return _home_view_impl(request)
