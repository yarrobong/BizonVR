"""
Синтетические данные для каталога: разделы, категории, товары, города, точки выдачи, остатки, теги.
Запуск: python manage.py load_catalog_data
В Docker: docker compose exec web python manage.py load_catalog_data
"""
import random
from decimal import Decimal

from django.core.management.base import BaseCommand

from catalog.models import (
    CatalogSection,
    Category,
    City,
    PickupPoint,
    Product,
    ProductCharacteristic,
    ProductStock,
    ProductTag,
)


# Разделы каталога (если нет — создаются)
SECTIONS = [
    {'name': 'Решения для VR бизнеса', 'slug': 'resheniya-dlya-vr-biznesa', 'order': 1},
    {'name': 'VR-аттракционы', 'slug': 'vr-attrakciony', 'order': 2},
    {'name': 'VR-оборудование', 'slug': 'vr-oborudovanie', 'order': 3},
]

# Категории: name, section_slug (или None)
CATEGORIES = [
    {'name': 'VR-Шлема', 'section_slug': 'vr-oborudovanie'},
    {'name': 'VR-Аттракционы', 'section_slug': 'vr-attrakciony'},
]

# Товары: категория — VR-Шлема (0) или VR-Аттракционы (1)
# tag_slugs: bestseller, expert-choice, new, sale (опционально)
PRODUCTS = [
    # --- Из блока «Лучшие предложения» (карточки), категория VR-Шлема ---
    {
        'name': 'Крепление BOBOVR M3 Pro Battery Head Strap для Oculus Quest 3',
        'category_index': 0,
        'price': Decimal('6990.00'),
        'tag_slugs': ['bestseller', 'new'],
        'description': 'Удобное крепление с встроенной батареей для Meta Quest 3. Увеличивает время автономной работы и улучшает распределение веса.',
        'characteristics': [
            ('Бренд', 'BOBOVR'),
            ('Совместимость', 'Oculus Quest 3'),
            ('Тип', 'Ремень с батареей'),
        ],
    },
    {
        'name': 'Кабель AMVR Upgraded Oculus Link с зарядным портом',
        'category_index': 0,
        'price': Decimal('2190.00'),
        'tag_slugs': ['sale'],
        'description': 'Кабель для подключения шлема к ПК с поддержкой одновременной зарядки. Стабильная передача данных и питания.',
        'characteristics': [
            ('Бренд', 'AMVR'),
            ('Длина', '5 м'),
            ('Интерфейс', 'USB Type-C'),
        ],
    },
    {
        'name': 'Маска AMVR для Pico 4 экокожа',
        'tag_slugs': [],
        'category_index': 0,
        'price': Decimal('2590.00'),
        'description': 'Запасная маска из экокожи для Pico 4. Повышает комфорт и гигиену при длительном использовании.',
        'characteristics': [
            ('Бренд', 'AMVR'),
            ('Совместимость', 'Pico 4'),
            ('Материал', 'Экокожа'),
        ],
    },
    {
        'name': 'Лицевой интерфейс / маска AMVR для Oculus Quest 3',
        'category_index': 0,
        'price': Decimal('2290.00'),
        'description': 'Сменный лицевой интерфейс для Quest 3. Улучшенная вентиляция и удобство.',
        'characteristics': [
            ('Бренд', 'AMVR'),
            ('Совместимость', 'Oculus Quest 3'),
        ],
    },
    {
        'name': 'Чехлы BizonVR XR Controller Grips Cover для Oculus Quest 3',
        'category_index': 0,
        'price': Decimal('1790.00'),
        'description': 'Чехлы-накладки на контроллеры Quest 3. Надёжный хват и защита от ударов.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Совместимость', 'Oculus Quest 3'),
        ],
    },
    {
        'name': 'Чехлы на контроллеры AMVR для Oculus Meta Quest 3',
        'category_index': 0,
        'price': Decimal('1790.00'),
        'description': 'Эргономичные чехлы для контроллеров Meta Quest 3. Улучшают хват и защищают от сколов.',
        'characteristics': [
            ('Бренд', 'AMVR'),
            ('Совместимость', 'Meta Quest 3'),
        ],
    },
    {
        'name': 'Кабель AMVR VR Link Cable для Oculus Quest 2/3/Pro',
        'category_index': 0,
        'price': Decimal('1690.00'),
        'description': 'Кабель для связи шлема с компьютером. Поддержка Quest 2, Quest 3 и Quest Pro.',
        'characteristics': [
            ('Бренд', 'AMVR'),
            ('Совместимость', 'Quest 2 / Quest 3 / Quest Pro'),
            ('Длина', '5 м'),
        ],
    },
    {
        'name': 'Кабель BizonVR XR VR Link - Type-C (5 метров)',
        'category_index': 0,
        'price': Decimal('1990.00'),
        'description': 'Кабель VR Link длиной 5 метров. Type-C для стабильного подключения к ПК.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Длина', '5 м'),
            ('Интерфейс', 'USB Type-C'),
        ],
    },
    # --- Из блока FeatureRow (лендинг), категория VR-Шлема ---
    {
        'name': 'Крепление BizonVR XR Battery Head Strap для Oculus Quest 3/3S',
        'category_index': 0,
        'price': Decimal('7490.00'),
        'tag_slugs': ['bestseller', 'expert-choice'],
        'description': 'Значительно улучшает комфорт, увеличивает время игры за счёт встроенного аккумулятора 8 000 mAh.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Совместимость', 'Oculus Quest 3 / Quest 3S'),
            ('Ёмкость батареи', '8 000 mAh'),
        ],
    },
    {
        'name': 'Чехлы BizonVR XR Controller Grips Cover для Oculus Quest 3/3S',
        'category_index': 0,
        'price': Decimal('1790.00'),
        'description': 'Беспрерывный гейминг с быстрой заменой АКБ. Премиум материалы и эргономичный дизайн.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Совместимость', 'Oculus Quest 3 / Quest 3S'),
        ],
    },
    {
        'name': 'Лицевой интерфейс / маска BizonVR XR для Oculus Quest 3',
        'category_index': 0,
        'price': Decimal('2490.00'),
        'description': 'Комфорт и удобство с обновлённой вентиляцией. Сменные гипоаллергенные накладки.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Совместимость', 'Oculus Quest 3'),
        ],
    },
    {
        'name': 'Кейс чехол BizonVR XR для Oculus Quest 2/3 PICO 4',
        'category_index': 0,
        'price': Decimal('3990.00'),
        'description': 'Надёжная защита и идеальная совместимость со всеми популярными аксессуарами.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Совместимость', 'Quest 2 / Quest 3 / PICO 4'),
        ],
    },
    {
        'name': 'Кабель с адаптером BizonVR XR VR Link Extra для Quest 2/3 PICO 4',
        'category_index': 0,
        'price': Decimal('2290.00'),
        'description': 'Прочная конструкция и стабильное соединение. В комплекте адаптер для универсального использования.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Совместимость', 'Quest 2 / Quest 3 / PICO 4'),
        ],
    },
    {
        'name': 'Кабель BizonVR XR VR Link для Oculus Quest 2/3 PICO 4',
        'category_index': 0,
        'price': Decimal('1990.00'),
        'description': 'Разработан для VR. Стабильное соединение и улучшенная передача данных до 5 Гбит/с.',
        'characteristics': [
            ('Бренд', 'BizonVR XR'),
            ('Совместимость', 'Quest 2 / Quest 3 / PICO 4'),
            ('Скорость передачи', 'до 5 Гбит/с'),
        ],
    },
    # --- VR-Аттракционы (синтетические карточки) ---
    {
        'name': 'VR-аттракцион «Космическая станция»',
        'category_index': 1,
        'price': Decimal('125000.00'),
        'tag_slugs': ['expert-choice', 'new'],
        'description': 'Коммерческий VR-аттракцион для торговых центров и парков развлечений. Сценарий полёта на МКС.',
        'characteristics': [
            ('Тип', 'Стационарный аттракцион'),
            ('Количество посадочных мест', '2'),
            ('Рекомендуемый возраст', '12+'),
        ],
    },
    {
        'name': 'VR-симулятор гонок 5D',
        'category_index': 1,
        'price': Decimal('89000.00'),
        'description': 'Многопользовательский симулятор автогонок с подвижной платформой и тактильной обратной связью.',
        'characteristics': [
            ('Тип', 'Симулятор с подвижной платформой'),
            ('Степени свободы', '5D'),
            ('Количество мест', '2'),
        ],
    },
    {
        'name': 'VR-аттракцион «Хоррор-комната»',
        'category_index': 1,
        'price': Decimal('78000.00'),
        'description': 'Иммерсивный аттракцион в жанре хоррор для квестов и развлекательных центров.',
        'characteristics': [
            ('Тип', 'Передвижная VR-комната'),
            ('Вместимость', 'до 4 человек'),
            ('Жанр', 'Хоррор'),
        ],
    },
    {
        'name': 'VR-башня для парка развлечений',
        'category_index': 1,
        'price': Decimal('250000.00'),
        'description': 'Крупногабаритный аттракцион с подъёмной платформой и групповым VR-контентом.',
        'characteristics': [
            ('Тип', 'Башенный аттракцион'),
            ('Вместимость', '6 человек'),
            ('Высота подъёма', '8 м'),
        ],
    },
]


# Города и точки выдачи
CITIES = [
    {'name': 'Москва', 'slug': 'moscow', 'pickup_points': [
        {'name': 'Пункт выдачи на Арбате', 'address': 'ул. Арбат, 1'},
        {'name': 'Склад на Тверской', 'address': 'ул. Тверская, 10'},
    ]},
    {'name': 'Санкт-Петербург', 'slug': 'spb', 'pickup_points': [
        {'name': 'Пункт на Невском', 'address': 'Невский пр., 50'},
    ]},
]


class Command(BaseCommand):
    help = 'Загружает синтетические данные: разделы, категории, товары, города, точки выдачи, остатки, теги.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Перед загрузкой удалить все данные каталога (товары, категории, остатки, точки, города).',
        )

    def handle(self, *args, **options):
        if options['clear']:
            ProductStock.objects.all().delete()
            ProductCharacteristic.objects.all().delete()
            Product.objects.all().delete()
            PickupPoint.objects.all().delete()
            City.objects.all().delete()
            Category.objects.all().delete()
            self.stdout.write(self.style.WARNING('Каталог очищен.'))

        # Разделы
        sections = {}
        for s in SECTIONS:
            sec, _ = CatalogSection.objects.get_or_create(
                slug=s['slug'],
                defaults={'name': s['name'], 'order': s['order']},
            )
            sections[s['slug']] = sec

        # Категории
        categories = []
        for cat_data in CATEGORIES:
            section = sections.get(cat_data['section_slug']) if cat_data.get('section_slug') else None
            cat, created = Category.objects.get_or_create(
                name=cat_data['name'],
                defaults={'name': cat_data['name'], 'section': section},
            )
            if section and not cat.section_id:
                cat.section = section
                cat.save()
            categories.append(cat)
            if created:
                self.stdout.write(f'  Категория: {cat.name}')

        # Товары
        for p_data in PRODUCTS:
            product, created = Product.objects.update_or_create(
                name=p_data['name'],
                defaults={
                    'category': categories[p_data['category_index']],
                    'price': p_data['price'],
                    'description': p_data.get('description', ''),
                    'is_active': True,
                },
            )
            product.characteristics.all().delete()
            for ch_name, ch_value in p_data.get('characteristics', []):
                ProductCharacteristic.objects.create(
                    product=product,
                    name=ch_name,
                    value=ch_value,
                )
            # Теги
            tag_slugs = p_data.get('tag_slugs', [])
            if tag_slugs:
                tags = list(ProductTag.objects.filter(slug__in=tag_slugs))
                product.tags.set(tags)
            self.stdout.write(f'  Товар: {product.name} ({product.price} ₽)')

        # Города, точки выдачи, остатки
        products = list(Product.objects.all())
        pickup_points = []
        for city_data in CITIES:
            city, _ = City.objects.get_or_create(
                slug=city_data['slug'],
                defaults={'name': city_data['name']},
            )
            for pp_data in city_data['pickup_points']:
                pp, _ = PickupPoint.objects.get_or_create(
                    city=city,
                    name=pp_data['name'],
                    defaults={'address': pp_data.get('address', '')},
                )
                pickup_points.append(pp)

        # Остатки: случайное количество для каждого товара в каждой точке (variant=None — для товаров без вариантов)
        for product in products:
            for pp in pickup_points:
                ProductStock.objects.update_or_create(
                    product=product,
                    pickup_point=pp,
                    variant=None,
                    defaults={'quantity': random.randint(0, 15)},
                )
        self.stdout.write(f'  Города: {len(CITIES)}, точек: {len(pickup_points)}, остатки заполнены')

        self.stdout.write(self.style.SUCCESS(
            f'Готово: {len(categories)} категорий, {len(PRODUCTS)} товаров, {len(pickup_points)} точек выдачи.'
        ))
