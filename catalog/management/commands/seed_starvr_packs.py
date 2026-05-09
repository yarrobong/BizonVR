from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from catalog.models import (
    CatalogSection,
    Category,
    GamePack,
    GamePackEntry,
    GamePackItem,
    GamePackServiceEntry,
    Product,
    ProductCharacteristic,
    ProductGameMetadata,
    ProductImage,
    ProductTag,
    Service,
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

GAME_UNIT_PRICE = Decimal('1398.00')

GAMES = [
    {
        'sku': 'STARVR-GAME-LASERTAG',
        'name': 'Lasertag',
        'price': GAME_UNIT_PRICE,
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
        'metadata': {
            'devices': 'Meta Quest 3, Meta Quest 3S',
            'genres': 'MR, PvP, Shooter',
            'min_players': 2,
            'max_players': 10,
            'age_rating': '12+',
            'club_format': ProductGameMetadata.FORMAT_CLUB,
            'is_multiplayer': True,
            'b2b_note': 'Быстрый командный сценарий для активных матчей и потока гостей.',
        },
        'theme': {'primary': '#111827', 'accent': '#ef4444', 'secondary': '#22d3ee'},
    },
    {
        'sku': 'STARVR-GAME-SPATIAL-OPS',
        'name': 'Spatial Ops',
        'price': GAME_UNIT_PRICE,
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
        'metadata': {
            'devices': 'Meta Quest 3, Meta Quest 3S',
            'genres': 'MR, Shooter, Multiplayer',
            'min_players': 2,
            'max_players': 10,
            'age_rating': '12+',
            'club_format': ProductGameMetadata.FORMAT_CLUB,
            'is_multiplayer': True,
            'b2b_note': 'Mixed reality-шутер с понятной wow-подачей для клубов и VR-зон.',
        },
        'theme': {'primary': '#082f49', 'accent': '#38bdf8', 'secondary': '#14b8a6'},
    },
    {
        'sku': 'STARVR-GAME-HOUSE-DEFENDER',
        'name': 'House Defender: Mixed Reality',
        'price': GAME_UNIT_PRICE,
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
        'metadata': {
            'devices': 'Meta Quest 3, Meta Quest 3S',
            'genres': 'MR, Defense, Co-op',
            'min_players': 1,
            'max_players': 6,
            'age_rating': '10+',
            'club_format': ProductGameMetadata.FORMAT_CLUB,
            'is_multiplayer': True,
            'b2b_note': 'Волновой кооперативный сценарий для семейной аудитории и понятного старта.',
        },
        'theme': {'primary': '#1f2937', 'accent': '#f59e0b', 'secondary': '#84cc16'},
    },
    {
        'sku': 'STARVR-GAME-LASER-LIMBO',
        'name': 'Laser Limbo - AR Party Battles',
        'price': GAME_UNIT_PRICE,
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
        'metadata': {
            'devices': 'Meta Quest 3, Meta Quest 3S',
            'genres': 'AR, Party, Arcade',
            'min_players': 2,
            'max_players': 8,
            'age_rating': '8+',
            'club_format': ProductGameMetadata.FORMAT_CLUB,
            'is_multiplayer': True,
            'b2b_note': 'Легкий party-формат для коротких раундов и быстрого вовлечения гостей.',
        },
        'theme': {'primary': '#312e81', 'accent': '#f472b6', 'secondary': '#facc15'},
    },
    {
        'sku': 'STARVR-GAME-ELVEN-ARROWS',
        'name': 'Elven Arrows - Mixed Reality Bow & Arrow',
        'price': GAME_UNIT_PRICE,
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
        'metadata': {
            'devices': 'Meta Quest 3, Meta Quest 3S',
            'genres': 'MR, Archery, Casual',
            'min_players': 1,
            'max_players': 4,
            'age_rating': '8+',
            'club_format': ProductGameMetadata.FORMAT_CLUB,
            'is_multiplayer': False,
            'b2b_note': 'Фэнтези-аркада с простым входом для казуальной аудитории и семейных сессий.',
        },
        'theme': {'primary': '#14532d', 'accent': '#4ade80', 'secondary': '#f59e0b'},
    },
]

SERVICES = [
    {
        'name': 'Настройка шлема',
        'short_description': 'Подготовка шлема Meta Quest к работе в клубе или VR-зоне.',
        'description': (
            'Подготовим шлем к коммерческому использованию: базовая настройка, проверка '
            'mixed reality-сценариев и готовность к запуску площадки.'
        ),
        'icon': 'headset',
        'price': Decimal('2000.00'),
        'price_from': '2 000 ₽',
        'service_kind': Service.KIND_HEADSET_SETUP,
        'order': 100,
    },
    {
        'name': 'Игры для VR-Зон (20 штук на выбор, или из каталога)',
        'short_description': 'Подбор дополнительной библиотеки игр под формат площадки.',
        'description': (
            'Собираем расширенный список игр для VR-зоны под ваш формат, аудиторию и '
            'конкретные шлемы: 20 позиций на выбор или из каталога.'
        ),
        'icon': 'gamepad-2',
        'price': Decimal('1000.00'),
        'price_from': '1 000 ₽',
        'service_kind': Service.KIND_GENERAL,
        'order': 110,
    },
]

PACKS = [
    {
        'sku': 'STARVR-PACK-BASE',
        'game_pack_slug': 'starvr-base',
        'name': 'ПАК "БАЗА"',
        'price': Decimal('6990.00'),
        'tariff': GamePack.TARIFF_START,
        'description': (
            'Стартовый пакет для VR-зоны на 10 шлемов с базовым набором MR-игр '
            'для соревновательных, семейных и party-сценариев.'
        ),
        'commercial_pitch': 'Базовый коммерческий комплект с пятью MR/AR-играми для быстрого запуска VR-зоны.',
        'included_summary': (
            'Lasertag\n'
            'Spatial Ops\n'
            'House Defender: Mixed Reality\n'
            'Laser Limbo - AR Party Battles\n'
            'Elven Arrows - Mixed Reality Bow & Arrow'
        ),
        'characteristics': {
            'Кол-во шлемов': '10',
            'Себестоимость за 1 шлем': '3 440 ₽',
            'Продажа за 1 шлем': '6 990 ₽',
            'Маржа за 1 шлем': '3 550 ₽',
            'Продажа за 10 шлемов': '69 900 ₽',
            'Маржа за 10 шлемов': '35 500 ₽',
        },
        'games': [
            {'title': 'Lasertag', 'platform': 'Meta Quest / MR'},
            {'title': 'Spatial Ops', 'platform': 'Meta Quest / MR'},
            {'title': 'House Defender: Mixed Reality', 'platform': 'Meta Quest / MR'},
            {'title': 'Laser Limbo - AR Party Battles', 'platform': 'Meta Quest / AR'},
            {'title': 'Elven Arrows - Mixed Reality Bow & Arrow', 'platform': 'Meta Quest / MR'},
        ],
        'services': [],
        'theme': {'primary': '#111827', 'accent': '#06b6d4', 'secondary': '#22c55e'},
    },
    {
        'sku': 'STARVR-PACK-UNIVERSAL',
        'game_pack_slug': 'starvr-universal',
        'name': 'ПАК "Универсальный"',
        'price': Decimal('8990.00'),
        'tariff': GamePack.TARIFF_CLUB,
        'description': (
            'Расширенный пакет для VR-зоны на 10 шлемов: базовый игровой состав плюс '
            'услуга настройки шлема для быстрого запуска площадки.'
        ),
        'commercial_pitch': 'Сбалансированный пакет: базовый контент плюс настройка шлемов перед запуском.',
        'included_summary': (
            'Lasertag\n'
            'Spatial Ops\n'
            'House Defender: Mixed Reality\n'
            'Laser Limbo - AR Party Battles\n'
            'Elven Arrows - Mixed Reality Bow & Arrow\n'
            'Настройка шлема'
        ),
        'characteristics': {
            'Кол-во шлемов': '10',
            'Себестоимость за 1 шлем': '3 440 ₽',
            'Продажа за 1 шлем': '8 990 ₽',
            'Маржа за 1 шлем': '5 550 ₽',
            'Продажа за 10 шлемов': '89 900 ₽',
            'Маржа за 10 шлемов': '55 500 ₽',
        },
        'games': [
            {'title': 'Lasertag', 'platform': 'Meta Quest / MR'},
            {'title': 'Spatial Ops', 'platform': 'Meta Quest / MR'},
            {'title': 'House Defender: Mixed Reality', 'platform': 'Meta Quest / MR'},
            {'title': 'Laser Limbo - AR Party Battles', 'platform': 'Meta Quest / AR'},
            {'title': 'Elven Arrows - Mixed Reality Bow & Arrow', 'platform': 'Meta Quest / MR'},
        ],
        'services': [
            {'title': 'Настройка шлема', 'platform': 'Сервис', 'service_name': 'Настройка шлема', 'note': 'Подготовка шлемов к запуску'},
        ],
        'theme': {'primary': '#082f49', 'accent': '#38bdf8', 'secondary': '#14b8a6'},
    },
    {
        'sku': 'STARVR-PACK-ALL-IN',
        'game_pack_slug': 'starvr-all-inclusive',
        'name': 'ПАК "Всё включено"',
        'price': Decimal('9990.00'),
        'tariff': GamePack.TARIFF_MAXIMUM,
        'description': (
            'Максимальный пакет для VR-зоны на 10 шлемов: базовый состав, настройка '
            'шлемов и дополнительная библиотека игр для VR-зон.'
        ),
        'commercial_pitch': 'Максимальный пакет с настройкой шлемов и расширенной библиотекой игр для VR-зон.',
        'included_summary': (
            'Lasertag\n'
            'Spatial Ops\n'
            'House Defender: Mixed Reality\n'
            'Laser Limbo - AR Party Battles\n'
            'Elven Arrows - Mixed Reality Bow & Arrow\n'
            'Настройка шлема\n'
            'Игры для VR-Зон (20 штук на выбор, или из каталога)'
        ),
        'characteristics': {
            'Кол-во шлемов': '10',
            'Себестоимость за 1 шлем': '3 440 ₽',
            'Продажа за 1 шлем': '9 990 ₽',
            'Маржа за 1 шлем': '6 550 ₽',
            'Продажа за 10 шлемов': '99 900 ₽',
            'Маржа за 10 шлемов': '65 500 ₽',
        },
        'games': [
            {'title': 'Lasertag', 'platform': 'Meta Quest / MR'},
            {'title': 'Spatial Ops', 'platform': 'Meta Quest / MR'},
            {'title': 'House Defender: Mixed Reality', 'platform': 'Meta Quest / MR'},
            {'title': 'Laser Limbo - AR Party Battles', 'platform': 'Meta Quest / AR'},
            {'title': 'Elven Arrows - Mixed Reality Bow & Arrow', 'platform': 'Meta Quest / MR'},
        ],
        'services': [
            {'title': 'Настройка шлема', 'platform': 'Сервис', 'service_name': 'Настройка шлема', 'note': 'Подготовка шлемов к запуску'},
            {
                'title': 'Игры для VR-Зон (20 штук на выбор, или из каталога)',
                'platform': 'Доп. библиотека',
                'service_name': 'Игры для VR-Зон (20 штук на выбор, или из каталога)',
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


def _upsert_product_game_metadata(product, metadata):
    ProductGameMetadata.objects.update_or_create(
        product=product,
        defaults={
            'devices': metadata['devices'],
            'genres': metadata['genres'],
            'min_players': metadata['min_players'],
            'max_players': metadata['max_players'],
            'age_rating': metadata['age_rating'],
            'club_format': metadata['club_format'],
            'is_pcvr': False,
            'is_standalone': True,
            'is_multiplayer': metadata['is_multiplayer'],
            'b2b_note': metadata['b2b_note'],
            'is_active': True,
        },
    )


class Command(BaseCommand):
    help = 'Создаёт или обновляет каталог STARVR: игры, услуги и готовые паки для VR-зон.'

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

        service_map = {}
        for service_data in SERVICES:
            service, _ = Service.objects.update_or_create(
                name=service_data['name'],
                defaults={
                    'short_description': service_data['short_description'],
                    'description': service_data['description'],
                    'icon': service_data['icon'],
                    'price': service_data['price'],
                    'price_from': service_data['price_from'],
                    'service_kind': service_data['service_kind'],
                    'is_vr_club_service': True,
                    'order': service_data['order'],
                    'is_active': True,
                },
            )
            service_map[service.name] = service

        created_games = []
        game_lookup = {}
        for game_data in GAMES:
            product, _ = Product.objects.update_or_create(
                sku=game_data['sku'],
                defaults={
                    'category': games_category,
                    'name': game_data['name'],
                    'description': game_data['description'],
                    'price': game_data['price'],
                    'price_on_request': game_data['price'],
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
            _upsert_product_game_metadata(product, game_data['metadata'])
            created_games.append(product)
            game_lookup[product.name] = product

        created_product_packs = []
        created_game_packs = []
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
            product_pack_items = pack_data['games'] + [
                {
                    'title': service_item['title'],
                    'platform': service_item.get('platform', ''),
                    'note': service_item.get('note', ''),
                }
                for service_item in pack_data['services']
            ]
            GamePackItem.objects.bulk_create(
                [
                    GamePackItem(
                        product=product,
                        title=item['title'],
                        platform=item.get('platform', ''),
                        note=item.get('note', ''),
                        sort_order=index,
                    )
                    for index, item in enumerate(product_pack_items, start=1)
                ]
            )
            created_product_packs.append(product)

            game_pack, _ = GamePack.objects.update_or_create(
                slug=pack_data['game_pack_slug'],
                defaults={
                    'category': packs_category,
                    'name': pack_data['name'],
                    'description': pack_data['description'],
                    'price': pack_data['price'],
                    'price_on_request': None,
                    'allow_order_on_request': False,
                    'is_active': True,
                    'vr_club_tariff': pack_data['tariff'],
                    'show_on_vr_club_page': True,
                    'club_format': 'VR-зона',
                    'devices': 'Meta Quest 3, Meta Quest 3S',
                    'genres': 'MR, AR, Multiplayer, Party',
                    'age_rating': '8+',
                    'players_count': 10,
                    'play_places_count': 10,
                    'commercial_pitch': pack_data['commercial_pitch'],
                    'included_summary': pack_data['included_summary'],
                },
            )
            _save_svg(game_pack.image, f'club-{pack_data["sku"]}', pack_data['name'], 'Тариф VR-зоны', pack_data['theme'])
            game_pack.save()
            game_pack.tags.set([tag_map['vr-zone'], tag_map['multiplayer']])

            GamePackEntry.objects.filter(game_pack=game_pack).delete()
            GamePackEntry.objects.bulk_create(
                [
                    GamePackEntry(
                        game_pack=game_pack,
                        product=game_lookup[item['title']],
                        quantity=1,
                        note=item.get('note', ''),
                        sort_order=index,
                    )
                    for index, item in enumerate(pack_data['games'], start=1)
                ]
            )

            GamePackServiceEntry.objects.filter(game_pack=game_pack).delete()
            GamePackServiceEntry.objects.bulk_create(
                [
                    GamePackServiceEntry(
                        game_pack=game_pack,
                        service=service_map[item['service_name']],
                        quantity=1,
                        note=item.get('note', ''),
                        sort_order=index,
                    )
                    for index, item in enumerate(pack_data['services'], start=1)
                ]
            )
            created_game_packs.append(game_pack)

        self.stdout.write(
            self.style.SUCCESS(
                'Готово: синхронизированы позиции STARVR '
                f'(игры: {len(created_games)}, услуги: {len(service_map)}, '
                f'товарные паки: {len(created_product_packs)}, B2B-паки: {len(created_game_packs)}).'
            )
        )
