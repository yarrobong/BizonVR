from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from catalog.models import (
    CatalogSection,
    Category,
    GamePackItem,
    Product,
    ProductCharacteristic,
    ProductImage,
    ProductTag,
    ProductVideo,
)



DIGITAL_SECTION = {
    'name': '\u0426\u0438\u0444\u0440\u043e\u0432\u044b\u0435 \u0442\u043e\u0432\u0430\u0440\u044b',
    'slug': 'cifrovye-tovary',
    'order': 90,
}

BUSINESS_SECTION = {
    'name': '\u0420\u0435\u0448\u0435\u043d\u0438\u044f \u0434\u043b\u044f VR \u0431\u0438\u0437\u043d\u0435\u0441\u0430',
    'slug': 'resheniya-dlya-vr-biznesa',
    'order': 10,
}

GAME_CATEGORIES = {
    'games': {
        'name': 'MR / VR \u0418\u0433\u0440\u044b',
        'slug': 'mr-vr-games',
    },
    'packs': {
        'name': '\u041f\u0430\u043a\u0438 \u0434\u043b\u044f VR-\u0437\u043e\u043d',
        'slug': 'vr-zone-packs',
    },
}

GAME_TAGS = [
    {'name': 'Тестовый каталог', 'slug': 'test-catalog', 'order': 100},
    {'name': 'Кооператив', 'slug': 'co-op', 'order': 101},
    {'name': 'Для детей', 'slug': 'kids', 'order': 102},
    {'name': 'Для вечеринки', 'slug': 'party', 'order': 103},
    {'name': 'Экшен', 'slug': 'action', 'order': 104},
]

VIDEO_PRESETS = {
    'rhythm': 'https://www.youtube.com/embed/M7lc1UVf-VE',
    'shooter': 'https://www.youtube.com/embed/aqz-KE-bpKQ',
    'party': 'https://www.youtube.com/embed/ysz5S6PUM-U',
    'kids': 'https://www.youtube.com/embed/jNQXAC9IVRw',
    'racing': 'https://www.youtube.com/embed/ScMzIvxBSi4',
}

TEST_GAMES = [
    {
        'sku': 'GAME-NEON-RHYTHM',
        'name': 'Neon Rhythm Arena',
        'price': Decimal('2490.00'),
        'description': 'Музыкальная VR-игра с неоновыми аренами, соревновательными режимами и высокой реиграбельностью.',
        'tags': ['test-catalog', 'party'],
        'characteristics': {
            'Жанр': 'Ритм / Аркада',
            'Игровые режимы': 'Соло, PvP, Турнир',
            'Совместимые устройства': 'Meta Quest 3, Meta Quest 3S, Pico 4',
            'Количество игроков': '1-4',
            'Длительность сессии': '10-20 минут',
        },
        'theme': {'primary': '#0f172a', 'accent': '#22d3ee', 'secondary': '#a855f7'},
        'video_key': 'rhythm',
        'gallery': ['Арена', 'Турнирный режим'],
    },
    {
        'sku': 'GAME-ZOMBIE-LAB',
        'name': 'Zombie Lab Escape',
        'price': Decimal('2890.00'),
        'description': 'Кооперативный хоррор-шутер про побег из лаборатории с волнами противников и сценарными заданиями.',
        'tags': ['test-catalog', 'co-op', 'action'],
        'characteristics': {
            'Жанр': 'Хоррор / Шутер',
            'Игровые режимы': 'Соло, Кооператив, Выживание',
            'Совместимые устройства': 'Meta Quest 3, Meta Quest Pro, Pico 4 Ultra',
            'Количество игроков': '1-4',
            'Длительность сессии': '20-35 минут',
        },
        'theme': {'primary': '#111827', 'accent': '#ef4444', 'secondary': '#f59e0b'},
        'video_key': 'shooter',
        'gallery': ['Лаборатория', 'Режим выживания'],
    },
    {
        'sku': 'GAME-COSMIC-CHEF',
        'name': 'Cosmic Chef VR',
        'price': Decimal('1990.00'),
        'description': 'Весёлая игра для вечеринок, где игроки готовят блюда на космической кухне и спасают ресторан от хаоса.',
        'tags': ['test-catalog', 'party'],
        'characteristics': {
            'Жанр': 'Party / Симулятор',
            'Игровые режимы': 'Соло, Кооператив, Party',
            'Совместимые устройства': 'Meta Quest 2, Meta Quest 3, Pico 4',
            'Количество игроков': '1-4',
            'Длительность сессии': '15-25 минут',
        },
        'theme': {'primary': '#082f49', 'accent': '#f97316', 'secondary': '#fde047'},
        'video_key': 'party',
        'gallery': ['Космическая кухня', 'Командный режим'],
    },
    {
        'sku': 'GAME-JUNGLE-RESCUE',
        'name': 'Jungle Rescue Kids',
        'price': Decimal('1790.00'),
        'description': 'Семейное VR-приключение со спасением животных, простым управлением и короткими миссиями для детей.',
        'tags': ['test-catalog', 'kids'],
        'characteristics': {
            'Жанр': 'Приключение / Детская',
            'Игровые режимы': 'Соло, Семейный режим',
            'Совместимые устройства': 'Meta Quest 2, Meta Quest 3S, Pico 4',
            'Количество игроков': '1-2',
            'Длительность сессии': '8-15 минут',
        },
        'theme': {'primary': '#14532d', 'accent': '#4ade80', 'secondary': '#facc15'},
        'video_key': 'kids',
        'gallery': ['Джунгли', 'Спасение животных'],
    },
    {
        'sku': 'GAME-PIRATE-PLANK',
        'name': 'Pirate Plank Co-op',
        'price': Decimal('2590.00'),
        'description': 'Кооперативное приключение про пиратский корабль, баланс, головоломки и мини-игры для компании.',
        'tags': ['test-catalog', 'co-op', 'party'],
        'characteristics': {
            'Жанр': 'Приключение / Кооператив',
            'Игровые режимы': 'Кооператив, Party, Командный режим',
            'Совместимые устройства': 'Meta Quest 3, Meta Quest 3S, Pico 4 Ultra',
            'Количество игроков': '2-4',
            'Длительность сессии': '15-30 минут',
        },
        'theme': {'primary': '#1e3a8a', 'accent': '#38bdf8', 'secondary': '#f59e0b'},
        'video_key': 'party',
        'gallery': ['Корабль', 'Командное испытание'],
    },
    {
        'sku': 'GAME-CYBER-DRIFT',
        'name': 'Cyber Drift League',
        'price': Decimal('2690.00'),
        'description': 'Аркадные гонки в VR с футуристичными трассами, дрифтом и матчами на скорость.',
        'tags': ['test-catalog', 'action'],
        'characteristics': {
            'Жанр': 'Гонки / Аркада',
            'Игровые режимы': 'Соло, PvP, Time Attack',
            'Совместимые устройства': 'Meta Quest 3, Meta Quest Pro, Pico 4 Ultra',
            'Количество игроков': '1-6',
            'Длительность сессии': '10-18 минут',
        },
        'theme': {'primary': '#0f172a', 'accent': '#60a5fa', 'secondary': '#f43f5e'},
        'video_key': 'racing',
        'gallery': ['Трасса', 'Гоночный режим'],
    },
]

TEST_PACKS = [
    {
        'sku': 'PACK-PARTY',
        'name': 'Party VR Pack',
        'price': Decimal('6990.00'),
        'description': 'Набор для вечеринок, корпоративов и коротких ярких сессий с быстрым входом в игру.',
        'tags': ['test-catalog', 'party'],
        'characteristics': {
            'Формат пака': 'Вечеринка / Ивенты',
            'Игровые режимы': 'Party, Кооператив, Турнир',
            'Совместимые устройства': 'Meta Quest 3, Meta Quest 3S, Pico 4',
            'Количество игр': '3',
        },
        'games': [
            {'title': 'Neon Rhythm Arena', 'platform': 'Meta Quest / Pico'},
            {'title': 'Cosmic Chef VR', 'platform': 'Meta Quest / Pico'},
            {'title': 'Pirate Plank Co-op', 'platform': 'Meta Quest / Pico'},
        ],
        'theme': {'primary': '#111827', 'accent': '#22d3ee', 'secondary': '#f97316'},
    },
    {
        'sku': 'PACK-FAMILY',
        'name': 'Family VR Pack',
        'price': Decimal('5490.00'),
        'description': 'Подборка безопасных и дружелюбных VR-игр для семейного использования, детей и клубов.',
        'tags': ['test-catalog', 'kids'],
        'characteristics': {
            'Формат пака': 'Семейный / Детский',
            'Игровые режимы': 'Соло, Семейный режим, Кооператив',
            'Совместимые устройства': 'Meta Quest 2, Meta Quest 3S, Pico 4',
            'Количество игр': '3',
        },
        'games': [
            {'title': 'Jungle Rescue Kids', 'platform': 'Meta Quest / Pico'},
            {'title': 'Cosmic Chef VR', 'platform': 'Meta Quest / Pico'},
            {'title': 'Pirate Plank Co-op', 'platform': 'Meta Quest / Pico'},
        ],
        'theme': {'primary': '#14532d', 'accent': '#4ade80', 'secondary': '#facc15'},
    },
    {
        'sku': 'PACK-ACTION',
        'name': 'Action VR Pack',
        'price': Decimal('7590.00'),
        'description': 'Пак для тех, кто любит драйв, высокую интенсивность и соревновательные сессии.',
        'tags': ['test-catalog', 'action', 'co-op'],
        'characteristics': {
            'Формат пака': 'Экшен / Соревнование',
            'Игровые режимы': 'PvP, Кооператив, Выживание',
            'Совместимые устройства': 'Meta Quest 3, Meta Quest Pro, Pico 4 Ultra',
            'Количество игр': '3',
        },
        'games': [
            {'title': 'Zombie Lab Escape', 'platform': 'Meta Quest / Pico'},
            {'title': 'Cyber Drift League', 'platform': 'Meta Quest / Pico'},
            {'title': 'Neon Rhythm Arena', 'platform': 'Meta Quest / Pico'},
        ],
        'theme': {'primary': '#111827', 'accent': '#ef4444', 'secondary': '#60a5fa'},
    },
]


def _svg_asset(title, subtitle, primary, accent, secondary):
    title = title[:42]
    subtitle = subtitle[:52]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <defs>
    <linearGradient id="bg" x1="0%" x2="100%" y1="0%" y2="100%">
      <stop offset="0%" stop-color="{primary}" />
      <stop offset="55%" stop-color="{accent}" />
      <stop offset="100%" stop-color="{secondary}" />
    </linearGradient>
  </defs>
  <rect width="1600" height="900" fill="url(#bg)" rx="42" />
  <circle cx="1280" cy="170" r="160" fill="rgba(255,255,255,0.12)" />
  <circle cx="280" cy="730" r="220" fill="rgba(255,255,255,0.10)" />
  <rect x="96" y="96" width="1408" height="708" rx="36" fill="rgba(15,23,42,0.38)" stroke="rgba(255,255,255,0.16)" />
  <text x="128" y="220" fill="#f8fafc" font-size="46" font-family="Arial, sans-serif" font-weight="700">{title}</text>
  <text x="128" y="288" fill="#e2e8f0" font-size="28" font-family="Arial, sans-serif">{subtitle}</text>
  <text x="128" y="760" fill="#f8fafc" font-size="24" font-family="Arial, sans-serif">BizonVR Demo Catalog</text>
</svg>"""


def _save_svg(field_file, stem, title, subtitle, theme):
    if field_file:
        return
    content = _svg_asset(title, subtitle, theme['primary'], theme['accent'], theme['secondary']).encode('utf-8')
    field_file.save(f'{slugify(stem)}.svg', ContentFile(content), save=False)


def _upsert_characteristics(product, characteristics):
    product.characteristics.all().delete()
    ProductCharacteristic.objects.bulk_create(
        [
            ProductCharacteristic(product=product, name=name, value=value)
            for name, value in characteristics.items()
        ]
    )


def _upsert_gallery(product, labels, theme):
    product.images.all().delete()
    for index, label in enumerate(labels, start=1):
        image = ProductImage(product=product, order=index)
        _save_svg(
            image.image,
            f'{product.sku}-{index}',
            product.name,
            label,
            theme,
        )
        image.save()


def _upsert_video(product, video_key):
    product.videos.all().delete()
    ProductVideo.objects.bulk_create(
        [
            ProductVideo(
                product=product,
                rutube_url=f'https://rutube.ru/video/{slugify(product.sku)}/',
                rutube_video_id=slugify(product.sku),
                embed_url=VIDEO_PRESETS[video_key],
                thumbnail_url=product.image.url if product.image else '',
                title=f'{product.name} — трейлер',
                order=1,
            )
        ]
    )


def _set_tags(product, tag_map, slugs):
    product.tags.set([tag_map[slug] for slug in slugs])


def _create_or_update_game(category, tag_map, payload):
    product, _created = Product.objects.update_or_create(
        sku=payload['sku'],
        defaults={
            'category': category,
            'name': payload['name'],
            'description': payload['description'],
            'price': payload['price'],
            'price_on_request': payload['price'],
            'product_kind': Product.PRODUCT_KIND_PHYSICAL,
            'is_active': True,
            'allow_order_on_request': True,
        },
    )
    _save_svg(product.image, payload['sku'], payload['name'], 'Главный постер', payload['theme'])
    product.save()
    _set_tags(product, tag_map, payload['tags'])
    _upsert_characteristics(product, payload['characteristics'])
    _upsert_gallery(product, payload['gallery'], payload['theme'])
    _upsert_video(product, payload['video_key'])
    return product


def _create_or_update_pack(category, tag_map, payload):
    product, _created = Product.objects.update_or_create(
        sku=payload['sku'],
        defaults={
            'category': category,
            'name': payload['name'],
            'description': payload['description'],
            'price': payload['price'],
            'price_on_request': None,
            'product_kind': Product.PRODUCT_KIND_GAME_PACK,
            'is_active': True,
            'allow_order_on_request': True,
        },
    )
    _save_svg(product.image, payload['sku'], payload['name'], 'Промо-обложка', payload['theme'])
    product.save()
    _set_tags(product, tag_map, payload['tags'])
    _upsert_characteristics(product, payload['characteristics'])
    _upsert_gallery(product, ['Состав пака', 'Промо-слайд'], payload['theme'])
    GamePackItem.objects.filter(product=product).delete()
    GamePackItem.objects.bulk_create(
        [
            GamePackItem(
                product=product,
                title=item['title'],
                platform=item['platform'],
                sort_order=index,
            )
            for index, item in enumerate(payload['games'], start=1)
        ]
    )
    return product


class Command(BaseCommand):
    help = 'Создаёт тестовый каталог VR-игр и игровых паков с фото, видео и характеристиками.'

    def handle(self, *args, **options):
        with transaction.atomic():
            digital_section, _ = CatalogSection.objects.update_or_create(
                slug=DIGITAL_SECTION['slug'],
                defaults={'name': DIGITAL_SECTION['name'], 'order': DIGITAL_SECTION['order']},
            )
            business_section, _ = CatalogSection.objects.update_or_create(
                slug=BUSINESS_SECTION['slug'],
                defaults={'name': BUSINESS_SECTION['name'], 'order': BUSINESS_SECTION['order']},
            )
            games_category, _ = Category.objects.update_or_create(
                slug=GAME_CATEGORIES['games']['slug'],
                defaults={'name': GAME_CATEGORIES['games']['name'], 'section': digital_section},
            )
            packs_category, _ = Category.objects.update_or_create(
                slug=GAME_CATEGORIES['packs']['slug'],
                defaults={'name': GAME_CATEGORIES['packs']['name'], 'section': business_section},
            )
            tag_map = {}
            for tag_payload in GAME_TAGS:
                tag, _ = ProductTag.objects.update_or_create(
                    slug=tag_payload['slug'],
                    defaults={'name': tag_payload['name'], 'order': tag_payload['order']},
                )
                tag_map[tag.slug] = tag

            created_games = []
            for game_payload in TEST_GAMES:
                created_games.append(_create_or_update_game(games_category, tag_map, game_payload))

            created_packs = []
            for pack_payload in TEST_PACKS:
                created_packs.append(_create_or_update_pack(packs_category, tag_map, pack_payload))

        self.stdout.write(
            self.style.SUCCESS(
                f'Готово: {len(created_games)} тестовых игр и {len(created_packs)} игровых паков созданы или обновлены.'
            )
        )
