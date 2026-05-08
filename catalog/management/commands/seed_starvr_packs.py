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
)


SECTION_DATA = {
    'name': 'VR Игры и паки',
    'slug': 'vr-games-and-packs',
    'order': 95,
}

CATEGORY_DATA = {
    'games': {
        'name': 'MR / VR Игры',
        'slug': 'mr-vr-games',
    },
    'packs': {
        'name': 'Паки для VR-зон',
        'slug': 'vr-zone-packs',
    },
}

TAG_DATA = [
    {'name': 'Mixed Reality', 'slug': 'mixed-reality', 'order': 200},
    {'name': 'Мультиплеер', 'slug': 'multiplayer', 'order': 201},
    {'name': 'Для VR-зон', 'slug': 'vr-zone', 'order': 202},
]

GAMES = [
    {
        'sku': 'STARVR-GAME-LASERTAG',
        'name': 'Lasertag',
        'description': (
            'Командный mixed reality-шутер для активных матчей в помещении. '
            'Подходит для VR-зон, арен и коротких игровых сессий с быстрым входом.'
        ),
        'characteristics': {
            'Формат': 'Mixed Reality / Командный шутер',
            'Сценарий': 'PvP / Арена',
            'Рекомендуемый формат': 'Клубы, VR-зоны, ивенты',
            'Количество шлемов': 'До 10',
        },
        'tags': ['mixed-reality', 'multiplayer', 'vr-zone'],
        'theme': {'primary': '#111827', 'accent': '#ef4444', 'secondary': '#22d3ee'},
    },
    {
        'sku': 'STARVR-GAME-SPATIAL-OPS',
        'name': 'Spatial Ops',
        'description': (
            'Многопользовательский MR-шутер с перемещением по реальному пространству. '
            'Хорошо работает как базовый соревновательный контент для VR-зоны.'
        ),
        'characteristics': {
            'Формат': 'Mixed Reality / Тактический шутер',
            'Сценарий': 'PvP / Командная игра',
            'Рекомендуемый формат': 'VR-зоны, клубы, корпоративы',
            'Количество шлемов': 'До 10',
        },
        'tags': ['mixed-reality', 'multiplayer', 'vr-zone'],
        'theme': {'primary': '#082f49', 'accent': '#38bdf8', 'secondary': '#14b8a6'},
    },
    {
        'sku': 'STARVR-GAME-HOUSE-DEFENDER',
        'name': 'House Defender: Mixed Reality',
        'description': (
            'MR-игра с защитой дома от волн противников. Подходит для семейной аудитории, '
            'клубного формата и сценариев с понятной механикой.'
        ),
        'characteristics': {
            'Формат': 'Mixed Reality / Defense',
            'Сценарий': 'Co-op / Защита базы',
            'Рекомендуемый формат': 'Семейные зоны, клубы, шоурумы',
            'Количество шлемов': 'До 10',
        },
        'tags': ['mixed-reality', 'vr-zone'],
        'theme': {'primary': '#1f2937', 'accent': '#f59e0b', 'secondary': '#84cc16'},
    },
    {
        'sku': 'STARVR-GAME-LASER-LIMBO',
        'name': 'Laser Limbo - AR Party Battles',
        'description': (
            'Аркадный party-формат в mixed reality для быстрых сессий, соревнований и '
            'развлекательных мероприятий с низким порогом входа.'
        ),
        'characteristics': {
            'Формат': 'AR / Party',
            'Сценарий': 'Мини-матчи / Быстрые сессии',
            'Рекомендуемый формат': 'Ивенты, дни рождения, VR-зоны',
            'Количество шлемов': 'До 10',
        },
        'tags': ['mixed-reality', 'multiplayer', 'vr-zone'],
        'theme': {'primary': '#312e81', 'accent': '#f472b6', 'secondary': '#facc15'},
    },
    {
        'sku': 'STARVR-GAME-ELVEN-ARROWS',
        'name': 'Elven Arrows - Mixed Reality Bow & Arrow',
        'description': (
            'Фэнтези-арчер в mixed reality с механикой стрельбы из лука. Подходит как '
            'для соло-сессий, так и для зрелищного контента в VR-зоне.'
        ),
        'characteristics': {
            'Формат': 'Mixed Reality / Bow & Arrow',
            'Сценарий': 'Аркада / Защита / Точность',
            'Рекомендуемый формат': 'Клубы, семейные зоны, ивенты',
            'Количество шлемов': 'До 10',
        },
        'tags': ['mixed-reality', 'vr-zone'],
        'theme': {'primary': '#14532d', 'accent': '#4ade80', 'secondary': '#f59e0b'},
    },
]

PACKS = [
    {
        'sku': 'STARVR-PACK-BASE',
        'name': 'ПАК "БАЗА"',
        'price': '6990.00',
        'description': (
            'Стартовый пакет для VR-зоны на 10 шлемов с базовым набором MR-игр '
            'для соревновательных, семейных и party-сценариев.'
        ),
        'characteristics': {
            'Кол-во шлемов': '10',
            'Себестоимость за 1 шлем': '3 440 ₽',
            'Продажа за 1 шлем': '6 990 ₽',
            'Маржа за 1 шлем': '3 550 ₽',
            'Продажа за 10 шлемов': '69 900 ₽',
            'Маржа за 10 шлемов': '35 500 ₽',
        },
        'items': [
            {'title': 'Lasertag', 'platform': 'Meta Quest / MR'},
            {'title': 'Spatial Ops', 'platform': 'Meta Quest / MR'},
            {'title': 'House Defender: Mixed Reality', 'platform': 'Meta Quest / MR'},
            {'title': 'Laser Limbo - AR Party Battles', 'platform': 'Meta Quest / AR'},
            {'title': 'Elven Arrows - Mixed Reality Bow & Arrow', 'platform': 'Meta Quest / MR'},
        ],
        'theme': {'primary': '#111827', 'accent': '#06b6d4', 'secondary': '#22c55e'},
    },
    {
        'sku': 'STARVR-PACK-UNIVERSAL',
        'name': 'ПАК "Универсальный"',
        'price': '8990.00',
        'description': (
            'Расширенный пакет для VR-зоны на 10 шлемов: базовый игровой состав плюс '
            'услуга настройки шлема для быстрого запуска площадки.'
        ),
        'characteristics': {
            'Кол-во шлемов': '10',
            'Себестоимость за 1 шлем': '3 440 ₽',
            'Продажа за 1 шлем': '8 990 ₽',
            'Маржа за 1 шлем': '5 550 ₽',
            'Продажа за 10 шлемов': '89 900 ₽',
            'Маржа за 10 шлемов': '55 500 ₽',
        },
        'items': [
            {'title': 'Lasertag', 'platform': 'Meta Quest / MR'},
            {'title': 'Spatial Ops', 'platform': 'Meta Quest / MR'},
            {'title': 'House Defender: Mixed Reality', 'platform': 'Meta Quest / MR'},
            {'title': 'Laser Limbo - AR Party Battles', 'platform': 'Meta Quest / AR'},
            {'title': 'Elven Arrows - Mixed Reality Bow & Arrow', 'platform': 'Meta Quest / MR'},
            {'title': 'Настройка шлема', 'platform': 'Сервис', 'note': 'Подготовка шлемов к запуску'},
        ],
        'theme': {'primary': '#082f49', 'accent': '#38bdf8', 'secondary': '#14b8a6'},
    },
    {
        'sku': 'STARVR-PACK-ALL-IN',
        'name': 'ПАК "Всё включено"',
        'price': '9990.00',
        'description': (
            'Максимальный пакет для VR-зоны на 10 шлемов: базовый состав, настройка '
            'шлемов и дополнительная библиотека игр для VR-зон.'
        ),
        'characteristics': {
            'Кол-во шлемов': '10',
            'Себестоимость за 1 шлем': '3 440 ₽',
            'Продажа за 1 шлем': '9 990 ₽',
            'Маржа за 1 шлем': '6 550 ₽',
            'Продажа за 10 шлемов': '99 900 ₽',
            'Маржа за 10 шлемов': '65 500 ₽',
        },
        'items': [
            {'title': 'Lasertag', 'platform': 'Meta Quest / MR'},
            {'title': 'Spatial Ops', 'platform': 'Meta Quest / MR'},
            {'title': 'House Defender: Mixed Reality', 'platform': 'Meta Quest / MR'},
            {'title': 'Laser Limbo - AR Party Battles', 'platform': 'Meta Quest / AR'},
            {'title': 'Elven Arrows - Mixed Reality Bow & Arrow', 'platform': 'Meta Quest / MR'},
            {'title': 'Настройка шлема', 'platform': 'Сервис', 'note': 'Подготовка шлемов к запуску'},
            {
                'title': 'Игры для VR-зон (20 штук на выбор, или из каталога)',
                'platform': 'Доп. библиотека',
                'note': 'Контент подбирается под площадку и сценарий работы',
            },
        ],
        'theme': {'primary': '#3f1d2e', 'accent': '#fb7185', 'secondary': '#f59e0b'},
    },
]


def _svg_asset(title, subtitle, primary, accent, secondary):
    title = title[:42]
    subtitle = subtitle[:56]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <defs>
    <linearGradient id="bg" x1="0%" x2="100%" y1="0%" y2="100%">
      <stop offset="0%" stop-color="{primary}" />
      <stop offset="55%" stop-color="{accent}" />
      <stop offset="100%" stop-color="{secondary}" />
    </linearGradient>
  </defs>
  <rect width="1600" height="900" fill="url(#bg)" rx="40" />
  <rect x="88" y="88" width="1424" height="724" rx="34" fill="rgba(15,23,42,0.38)" stroke="rgba(255,255,255,0.14)" />
  <circle cx="1260" cy="190" r="154" fill="rgba(255,255,255,0.10)" />
  <circle cx="260" cy="730" r="210" fill="rgba(255,255,255,0.08)" />
  <text x="132" y="210" fill="#f8fafc" font-size="52" font-family="Arial, sans-serif" font-weight="700">{title}</text>
  <text x="132" y="290" fill="#e2e8f0" font-size="28" font-family="Arial, sans-serif">{subtitle}</text>
  <text x="132" y="760" fill="#f8fafc" font-size="24" font-family="Arial, sans-serif">BizonVR</text>
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
        _save_svg(image.image, f'{product.sku}-{index}', product.name, label, theme)
        image.save()


class Command(BaseCommand):
    help = 'Создаёт или обновляет каталог STARVR: 5 игр и 3 готовых пака для VR-зон.'

    @transaction.atomic
    def handle(self, *args, **options):
        section, _ = CatalogSection.objects.update_or_create(
            slug=SECTION_DATA['slug'],
            defaults={'name': SECTION_DATA['name'], 'order': SECTION_DATA['order']},
        )
        games_category, _ = Category.objects.update_or_create(
            slug=CATEGORY_DATA['games']['slug'],
            defaults={'name': CATEGORY_DATA['games']['name'], 'section': section},
        )
        packs_category, _ = Category.objects.update_or_create(
            slug=CATEGORY_DATA['packs']['slug'],
            defaults={'name': CATEGORY_DATA['packs']['name'], 'section': section},
        )

        tag_map = {}
        for tag_data in TAG_DATA:
            tag, _ = ProductTag.objects.update_or_create(
                slug=tag_data['slug'],
                defaults={'name': tag_data['name'], 'order': tag_data['order']},
            )
            tag_map[tag.slug] = tag

        created_games = []
        for game_data in GAMES:
            product, _ = Product.objects.update_or_create(
                sku=game_data['sku'],
                defaults={
                    'category': games_category,
                    'name': game_data['name'],
                    'description': game_data['description'],
                    'price': None,
                    'price_on_request': None,
                    'product_kind': Product.PRODUCT_KIND_PHYSICAL,
                    'is_active': True,
                    'allow_order_on_request': True,
                },
            )
            _save_svg(product.image, game_data['sku'], game_data['name'], 'Карточка игры', game_data['theme'])
            product.save()
            product.tags.set([tag_map[slug] for slug in game_data['tags']])
            _upsert_characteristics(product, game_data['characteristics'])
            _upsert_gallery(product, ['Игровой постер', 'Сценарий использования'], game_data['theme'])
            created_games.append(product)

        created_packs = []
        for pack_data in PACKS:
            product, _ = Product.objects.update_or_create(
                sku=pack_data['sku'],
                defaults={
                    'category': packs_category,
                    'name': pack_data['name'],
                    'description': pack_data['description'],
                    'price': pack_data['price'],
                    'price_on_request': None,
                    'product_kind': Product.PRODUCT_KIND_GAME_PACK,
                    'is_active': True,
                    'allow_order_on_request': False,
                },
            )
            _save_svg(product.image, pack_data['sku'], pack_data['name'], 'Готовый пакет', pack_data['theme'])
            product.save()
            product.tags.set([tag_map['vr-zone'], tag_map['multiplayer']])
            _upsert_characteristics(product, pack_data['characteristics'])
            _upsert_gallery(product, ['Состав пака', 'Коммерческое предложение'], pack_data['theme'])
            GamePackItem.objects.filter(product=product).delete()
            GamePackItem.objects.bulk_create(
                [
                    GamePackItem(
                        product=product,
                        title=item['title'],
                        platform=item.get('platform', ''),
                        note=item.get('note', ''),
                        sort_order=index,
                    )
                    for index, item in enumerate(pack_data['items'], start=1)
                ]
            )
            created_packs.append(product)

        self.stdout.write(
            self.style.SUCCESS(
                f'Готово: создано или обновлено {len(created_games)} игр и {len(created_packs)} паков STARVR.'
            )
        )
