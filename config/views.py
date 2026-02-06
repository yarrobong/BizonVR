import mimetypes
import os

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from catalog.models import Category, ContactRequest, Product, ProductTag

from .forms import ContactForm

# Фоны hero по умолчанию (Unsplash), если нет своих в static
_HERO_DEFAULT_BG = [
    'https://images.unsplash.com/photo-1622979135225-d2ba269fb1bd?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1617802690658-1173a812650d?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1531746795393-6c2495d120b0?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?q=80&w=2070&auto=format&fit=crop',
]


def serve_media(request, path):
    """Раздача медиа при DEBUG или SERVE_MEDIA=1."""
    path = os.path.normpath(path).lstrip('/').lstrip('\\')
    if '..' in path or path.startswith('/'):
        raise Http404()
    media_root = os.path.abspath(os.path.realpath(str(settings.MEDIA_ROOT)))
    full_path = os.path.abspath(os.path.join(media_root, path))
    if not full_path.startswith(media_root):
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


def privacy_view(request):
    """Страница политики конфиденциальности."""
    return render(request, 'privacy.html')


def contacts_view(request):
    """Страница контактов: форма обратной связи и контактная информация."""
    form = ContactForm()
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            ContactRequest.objects.create(
                name=form.cleaned_data['name'],
                email=form.cleaned_data['email'],
                phone=form.cleaned_data.get('phone', ''),
                message=form.cleaned_data['message'],
            )
            messages.success(request, 'Спасибо! Ваше сообщение отправлено. Мы свяжемся с вами в ближайшее время.')
            return redirect('contacts')
    return render(request, 'contacts.html', {'form': form})


def home_view(request):
    """Главная страница: hero, лучшие предложения (товары из каталога), сетка категорий, баннер."""
    featured_qs = (
        Product.objects.filter(is_active=True)
        .select_related('category')
        .prefetch_related('tags')
        .order_by('-created_at')
    )
    tag_slug = (request.GET.get('tag') or '').strip()
    if tag_slug:
        featured_qs = featured_qs.filter(tags__slug=tag_slug).distinct()
    featured = list(featured_qs[:8])
    product_tags = list(ProductTag.objects.order_by('order', 'name'))
    categories = Category.objects.all()

    # Фоны: свои из static или дефолтные; слайд «Трейд-ин» — всегда media/hero/tradein.webp
    hero_dir = settings.BASE_DIR / 'static' / 'images' / 'hero'
    if (hero_dir / 'hero_1.jpg').exists():
        from django.templatetags.static import static
        base_bg = [request.build_absolute_uri(static(f'images/hero/hero_{i}.jpg')) for i in range(1, 5)]
    else:
        base_bg = _HERO_DEFAULT_BG.copy()
    media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'
    # Относительные пути — корректно работают локально и за прокси
    mart_bg = media_url + 'hero/mart.webp'
    tradein_bg = media_url + 'hero/tradein.webp'
    attractions_bg = media_url + 'hero/attractions.webp'
    catalog_url = reverse('catalog:product_list')

    # Ровно 4 слайда: Цифровой магазин, Трейд-ин (фон tradein.webp), Решения для VR бизнеса, VR Аттракционы
    hero_slides = [
        {
            'title': 'Цифровой магазин',
            'description': 'Цифровые товары и контент для VR. Ключи, подписки и лицензии в одном месте.',
            'url': f'{catalog_url}?section=cifrovye-tovary',
            'btn': 'В каталог',
            'bg_url': mart_bg,  # фон: media/hero/mart.webp
            'bg_position': 'center center',
            'bg_size': 'auto 100%',
            'bg_repeat': 'repeat-x',
        },
        {
            'title': 'Трейд-ин',
            'description': 'Сдайте старый шлем и получите скидку на новое оборудование. Выгодный обмен и быстрая оценка.',
            'url': catalog_url,
            'btn': 'Подробнее',
            'bg_url': tradein_bg,  # фон: media/hero/tradein.webp
            'bg_position': 'center center',
            'bg_size': 'auto 100%',
            'bg_repeat': 'repeat-x',
        },
        {
            'title': 'Решения для VR бизнеса',
            'description': 'Готовые решения для парков развлечений, торговых центров и квестов. Симуляторы, аттракционы и контент.',
            'url': f'{catalog_url}?section=resheniya-dlya-vr-biznesa',
            'btn': 'Смотреть решения',
            'bg_url': base_bg[2],
            'bg_position': 'center center',
            'bg_size': 'auto 100%',
            'bg_repeat': 'repeat-x',
        },
        {
            'title': 'VR Аттракционы',
            'description': 'Коммерческие VR-аттракционы: гонки 5D, хоррор-комнаты, сферические симуляторы для парков и ТЦ.',
            'url': f'{catalog_url}?section=vr-attrakciony',
            'btn': 'Аттракционы',
            'bg_url': attractions_bg,  # фон: media/hero/attractions.webp 5760×1800
            'bg_position': '60% center',  # сдвиг вправо
            'bg_size': 'auto 100%',
            'bg_repeat': 'repeat-x',
        },
    ]
    hero_slide_width_pct = (100 // len(hero_slides)) if hero_slides else 25
    return render(request, 'home.html', {
        'featured_products': featured,
        'product_tags': product_tags,
        'current_tag': tag_slug,
        'categories': categories,
        'hero_slides': hero_slides,
        'hero_slide_width_pct': hero_slide_width_pct,
    })
