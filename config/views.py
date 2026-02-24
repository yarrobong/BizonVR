import mimetypes
import os
from dataclasses import dataclass

from django.conf import settings
from django.contrib import messages
from django.db import connection
from django.db.models import Q
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from catalog.models import CallbackRequest, City, ContactRequest, Product, ProductTag, Service

from .forms import CallbackForm, ContactForm
from catalog.cache_utils import CACHE_KEY_PRODUCT_TAGS
from .legal_consent import build_legal_acceptance_payload
from .legal_docs import get_legal_doc

_CACHE_TTL = 300  # 5 минут
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

# Фоны hero по умолчанию (Unsplash), если нет своих в static
_HERO_DEFAULT_BG = [
    'https://images.unsplash.com/photo-1617802690658-1173a812650d?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1531746795393-6c2495d120b0?q=80&w=2070&auto=format&fit=crop',
    'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?q=80&w=2070&auto=format&fit=crop',
]


def favicon_view(request):
    """Редирект /favicon.ico на SVG-иконку."""
    return HttpResponseRedirect(settings.STATIC_URL + 'images/favicon.svg')


def robots_txt_view(request):
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /accounts/',
        '',
        'Allow: /',
        '',
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
        '',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')


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


@dataclass(frozen=True)
class _LegalOperatorContacts:
    full_name: str
    short_name: str
    legal_form: str
    inn: str
    ogrn: str
    legal_address: str
    postal_address: str
    email: str
    pd_email: str
    phone: str
    authority_basis: str


def _get_legal_operator_contacts():
    return _LegalOperatorContacts(
        full_name=getattr(settings, 'LEGAL_OPERATOR_FULL_NAME', '[УКАЖИТЕ ПОЛНОЕ НАИМЕНОВАНИЕ ОПЕРАТОРА ПД]'),
        short_name=getattr(settings, 'LEGAL_OPERATOR_SHORT_NAME', getattr(settings, 'SITE_BRAND', 'BizonVR')),
        legal_form=getattr(settings, 'LEGAL_OPERATOR_FORM', '[ООО/ИП]'),
        inn=getattr(settings, 'LEGAL_OPERATOR_INN', '[ИНН]'),
        ogrn=getattr(settings, 'LEGAL_OPERATOR_OGRN', '[ОГРН / ОГРНИП]'),
        legal_address=getattr(settings, 'LEGAL_OPERATOR_LEGAL_ADDRESS', '[ЮРИДИЧЕСКИЙ АДРЕС]'),
        postal_address=getattr(settings, 'LEGAL_OPERATOR_POSTAL_ADDRESS', '[ПОЧТОВЫЙ АДРЕС]'),
        email=getattr(settings, 'SITE_CONTACT_EMAIL', 'info@example.com'),
        pd_email=getattr(settings, 'LEGAL_OPERATOR_PD_EMAIL', getattr(settings, 'SITE_CONTACT_EMAIL', 'info@example.com')),
        phone=getattr(settings, 'SITE_CONTACT_PHONE', ''),
        authority_basis=getattr(settings, 'LEGAL_SIGNATORY_BASIS', '[УСТАВ / ДОВЕРЕННОСТЬ №___ ОТ ___]'),
    )


def _render_legal_page(request, slug):
    legal_doc = get_legal_doc(slug)
    if not legal_doc:
        raise Http404()
    return render(request, legal_doc['template_name'], {
        'legal_doc': legal_doc,
        'operator_contacts': _get_legal_operator_contacts(),
    })


def privacy_view(request):
    """Страница политики конфиденциальности."""
    return _render_legal_page(request, 'privacy')


def oferta_view(request):
    """Страница публичной оферты."""
    return _render_legal_page(request, 'oferta')


def user_agreement_view(request):
    return _render_legal_page(request, 'user_agreement')


def pd_consent_view(request):
    return _render_legal_page(request, 'pd_consent')


def cookies_policy_view(request):
    return _render_legal_page(request, 'cookies_policy')


def sales_terms_view(request):
    return _render_legal_page(request, 'sales_terms')


def service_request_terms_view(request):
    return _render_legal_page(request, 'service_request_terms')


def arenda_view(request):
    """Страница аренды VR-шлемов Meta Quest."""
    from urllib.parse import quote
    media_url = (settings.MEDIA_URL or '/media/').rstrip('/') + '/'

    def build_media_url(relative_path):
        if not relative_path:
            return ''
        # Кодируем путь для URL (пробелы в именах файлов)
        encoded = '/'.join(quote(part, safe='') for part in relative_path.lstrip('/').split('/'))
        return request.build_absolute_uri(media_url + encoded)

    callback_form = CallbackForm()
    if request.method == 'POST' and request.POST.get('form_type') == 'callback':
        callback_form = CallbackForm(request.POST)
        if callback_form.is_valid():
            CallbackRequest.objects.create(
                name=callback_form.cleaned_data.get('name', '').strip(),
                phone=callback_form.cleaned_data['phone'],
                source='arenda',
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Заявка отправлена! Мы перезвоним в ближайшее время.')
            return redirect(reverse('arenda') + '#contacts')

    return render(request, 'arenda.html', {
        'quest3_image_url': build_media_url('rent/Quest 3.webp'),
        'quest2_image_url': build_media_url('rent/Quest 2.webp'),
        'callback_form': callback_form,
    })


def uslugi_view(request):
    """Страница услуг компании."""
    services = Service.objects.filter(is_active=True).order_by('order', 'name')
    callback_form = CallbackForm()

    if request.method == 'POST' and request.POST.get('form_type') == 'callback':
        callback_form = CallbackForm(request.POST)
        if callback_form.is_valid():
            CallbackRequest.objects.create(
                name=callback_form.cleaned_data.get('name', '').strip(),
                phone=callback_form.cleaned_data['phone'],
                source='uslugi',
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Заявка отправлена! Мы перезвоним в ближайшее время.')
            return redirect(reverse('uslugi') + '#contacts')

    return render(
        request,
        'uslugi.html',
        {
            'services': services,
            'callback_form': callback_form,
        },
    )


def debug_cities_view(request):
    """Только при DEBUG: сколько городов в БД и какие — для проверки, что сайт и админка видят одну БД."""
    if not settings.DEBUG:
        raise Http404()
    db_name = connection.settings_dict.get('NAME', '?')
    cities = list(City.objects.order_by('order', 'name').values_list('name', flat=True))
    count = len(cities)
    body = (
        f"Database: {db_name}\n"
        f"Engine: {connection.settings_dict.get('ENGINE', '?')}\n"
        f"Host: {connection.settings_dict.get('HOST', '?')}\n"
        f"Городов в БД: {count}\n"
        f"Список: {', '.join(cities) or '(пусто)'}\n"
    )
    return HttpResponse(body, content_type='text/plain; charset=utf-8')


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
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Спасибо! Ваше сообщение отправлено. Мы свяжемся с вами в ближайшее время.')
            return redirect('contacts')
    return render(request, 'contacts.html', {'form': form})


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
    # categories берём из catalog_sections (context processor) — убираем дублирующий запрос

    # Фоны: свои из static или дефолтные; слайд «Трейд-ин» — всегда media/hero/tradein.webp
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
    # Абсолютные URL для корректной загрузки фонов во всех контекстах
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

    # Ровно 3 слайда: Цифровой магазин, Трейд-ин (фон tradein.webp), VR Аттракционы
    hero_slides = [
        {
            'title': 'Цифровой магазин',
            'description': 'Цифровые товары и контент для VR. Ключи, подписки и лицензии в одном месте.',
            'url': f'{catalog_url}?section=cifrovye-tovary',
            'btn': 'В каталог',
            'bg_url': mart_bg,  # фон: media/hero/mart.webp
            'bg_position': 'center center',
        },
        {
            'title': 'Трейд-ин',
            'description': 'Сдайте старый шлем и получите скидку на новое оборудование. Выгодный обмен и быстрая оценка.',
            'url': catalog_url,
            'btn': 'Подробнее',
            'bg_url': tradein_bg,  # фон: media/hero/tradein.webp
            'bg_position': 'center center',
        },
        {
            'title': 'VR Аттракционы',
            'description': 'Коммерческие VR-аттракционы: гонки 5D, хоррор-комнаты, сферические симуляторы для парков и ТЦ.',
            'url': f'{catalog_url}?section=vr-attrakciony',
            'btn': 'Аттракционы',
            'bg_url': attractions_bg,  # фон: media/hero/attractions.webp 5760×1800
            'bg_position': '60% center',  # сдвиг вправо
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
