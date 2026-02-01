"""
Синтетические данные для каталога: 2 категории (VR-Шлема, VR-Аттракционы)
и товары с названиями из landing.html; остальные поля заполнены логичными значениями.
Запуск: python manage.py load_catalog_data
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from catalog.models import Category, Product, ProductCharacteristic


# Категории (ровно две)
CATEGORIES = [
    {'name': 'VR-Шлема'},
    {'name': 'VR-Аттракционы'},
]

# Товары: названия с landing.html, цена с лендинга или логичная; категория — VR-Шлема (аксессуары) или VR-Аттракционы
# (slug заполняется автоматически в модели)
PRODUCTS = [
    # --- Из блока «Лучшие предложения» (карточки), категория VR-Шлема ---
    {
        'name': 'Крепление BOBOVR M3 Pro Battery Head Strap для Oculus Quest 3',
        'category_index': 0,
        'price': Decimal('6990.00'),
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
        'description': 'Кабель для подключения шлема к ПК с поддержкой одновременной зарядки. Стабильная передача данных и питания.',
        'characteristics': [
            ('Бренд', 'AMVR'),
            ('Длина', '5 м'),
            ('Интерфейс', 'USB Type-C'),
        ],
    },
    {
        'name': 'Маска AMVR для Pico 4 экокожа',
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


class Command(BaseCommand):
    help = 'Загружает синтетические категории и товары (названия с landing.html + логичные поля).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Перед загрузкой удалить все товары и категории каталога.',
        )

    def handle(self, *args, **options):
        if options['clear']:
            ProductCharacteristic.objects.all().delete()
            Product.objects.all().delete()
            Category.objects.all().delete()
            self.stdout.write(self.style.WARNING('Каталог очищен.'))

        categories = []
        for cat_data in CATEGORIES:
            cat, created = Category.objects.get_or_create(
                name=cat_data['name'],
                defaults={'name': cat_data['name']},
            )
            categories.append(cat)
            if created:
                self.stdout.write(f'  Категория: {cat.name}')

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
            self.stdout.write(f'  Товар: {product.name} ({product.price} ₽)')

        self.stdout.write(self.style.SUCCESS(
            f'Готово: {len(categories)} категорий, {len(PRODUCTS)} товаров.'
        ))
