import mimetypes
import os

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.urls import reverse

from catalog.models import Category, Product

# Фоны hero по умолчанию (Unsplash), если нет своих в static
_HERO_DEFAULT_BG = [
    'https://images.unsplash.com/photo-1622979135225-d2ba269fb1bd?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1617802690658-1173a812650d?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1531746795393-6c2495d120b0?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?q=80&w=2070&auto=format&fit=crop',
]


def serve_media(request, path):
    """Раздача медиа при SERVE_MEDIA=1 (встроенный serve при DEBUG=False отдаёт 404)."""
    path = os.path.normpath(path).lstrip('/')
    full_path = os.path.normpath(os.path.join(settings.MEDIA_ROOT, path))
    if not full_path.startswith(os.path.realpath(settings.MEDIA_ROOT)):
        raise Http404()
    if os.path.isdir(full_path):
        raise Http404()
    if not os.path.exists(full_path):
        raise Http404()
    content_type, _ = mimetypes.guess_type(full_path)
    return FileResponse(
        open(full_path, 'rb'),
        as_attachment=False,
        content_type=content_type or 'application/octet-stream',
    )


def home_view(request):
    """Главная страница: hero, лучшие предложения (товары из каталога), сетка категорий, баннер."""
    featured = Product.objects.filter(is_active=True).select_related('category').order_by('-created_at')[:8]
    categories = Category.objects.all()

    # Фоны: свои из static или дефолтные; слайд «Трейд-ин» — всегда media/hero/tradein.webp
    hero_dir = settings.BASE_DIR / 'static' / 'images' / 'hero'
    if (hero_dir / 'hero_1.jpg').exists():
        from django.templatetags.static import static
        base_bg = [request.build_absolute_uri(static(f'images/hero/hero_{i}.jpg')) for i in range(1, 5)]
    else:
        base_bg = _HERO_DEFAULT_BG.copy()
    media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'
    tradein_bg = request.build_absolute_uri(media_url + 'hero/tradein.webp')
    catalog_url = reverse('catalog:product_list')

    # Ровно 4 слайда: Цифровой магазин, Трейд-ин (фон tradein.webp), Решения для VR бизнеса, VR Аттракционы
    hero_slides = [
        {
            'title': 'Цифровой магазин',
            'description': 'Цифровые товары и контент для VR. Ключи, подписки и лицензии в одном месте.',
            'url': f'{catalog_url}?section=cifrovye-tovary',
            'btn': 'В каталог',
            'bg_url': base_bg[0],
        },
        {
            'title': 'Трейд-ин',
            'description': 'Сдайте старый шлем и получите скидку на новое оборудование. Выгодный обмен и быстрая оценка.',
            'url': catalog_url,
            'btn': 'Подробнее',
            'bg_url': tradein_bg,  # фон: media/hero/tradein.webp
        },
        {
            'title': 'Решения для VR бизнеса',
            'description': 'Готовые решения для парков развлечений, торговых центров и квестов. Симуляторы, аттракционы и контент.',
            'url': f'{catalog_url}?section=resheniya-dlya-vr-biznesa',
            'btn': 'Смотреть решения',
            'bg_url': base_bg[2],
        },
        {
            'title': 'VR Аттракционы',
            'description': 'Коммерческие VR-аттракционы: гонки 5D, хоррор-комнаты, сферические симуляторы для парков и ТЦ.',
            'url': f'{catalog_url}?section=vr-attrakciony',
            'btn': 'Аттракционы',
            'bg_url': base_bg[3],
        },
    ]
    hero_slide_width_pct = (100 // len(hero_slides)) if hero_slides else 25
    return render(request, 'home.html', {
        'featured_products': featured,
        'categories': categories,
        'hero_slides': hero_slides,
        'hero_slide_width_pct': hero_slide_width_pct,
    })
