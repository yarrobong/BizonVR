"""
Экспорт каталога товаров в CSV: название, цена, артикул (slug), категория, описание, характеристики.
Запуск: python manage.py export_catalog
В Docker: docker compose exec web python manage.py export_catalog
"""
import csv
from django.core.management.base import BaseCommand
from catalog.models import Product


class Command(BaseCommand):
    help = 'Экспортирует каталог товаров в CSV файл: название, цена, артикул, категория, описание, характеристики.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default='catalog_export.csv',
            help='Имя выходного CSV файла (по умолчанию: catalog_export.csv)',
        )
        parser.add_argument(
            '--active-only',
            action='store_true',
            help='Экспортировать только активные товары',
        )

    def handle(self, *args, **options):
        output_file = options['output']
        active_only = options['active_only']

        # Получаем товары
        products = Product.objects.select_related('category').prefetch_related('characteristics')
        if active_only:
            products = products.filter(is_active=True)

        products = products.order_by('category__name', 'name')

        # Создаём CSV файл
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile, delimiter=';', quoting=csv.QUOTE_MINIMAL)

            # Заголовки
            writer.writerow([
                'Название',
                'Цена продажи',
                'Артикул (slug)',
                'Категория',
                'Описание',
                'Характеристики',
            ])

            # Данные товаров
            for product in products:
                # Собираем характеристики в строку: "Название: Значение; Название: Значение"
                characteristics = []
                for char in product.characteristics.all().order_by('name'):
                    characteristics.append(f'{char.name}: {char.value}')
                characteristics_str = '; '.join(characteristics)

                writer.writerow([
                    product.name,
                    str(product.price),
                    product.slug,
                    product.category.name,
                    product.description or '',
                    characteristics_str,
                ])

        self.stdout.write(
            self.style.SUCCESS(
                f'Экспорт завершён: {products.count()} товаров сохранено в {output_file}'
            )
        )
