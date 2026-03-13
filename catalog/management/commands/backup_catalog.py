"""
Экспорт полного бэкапа каталога: все модели в JSON + изображения в ZIP архиве.
Запуск: python manage.py backup_catalog [--output backup.zip]
"""
import json
import os
import zipfile
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings

from catalog.models import (
    CatalogSection,
    Category,
    City,
    PickupPoint,
    Product,
    ProductBundle,
    ProductBundleItem,
    ProductCharacteristic,
    ProductImage,
    ProductStock,
    ProductTag,
    ProductVariant,
    ProductVariantCharacteristic,
)


class DecimalEncoder(DjangoJSONEncoder):
    """Кодировщик для Decimal в JSON."""
    def encode(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().encode(obj)


class Command(BaseCommand):
    help = 'Создаёт полный бэкап каталога: все модели в JSON + изображения в ZIP архиве.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default=None,
            help='Имя выходного ZIP файла (по умолчанию: catalog_backup_YYYYMMDD_HHMMSS.zip)',
        )

    def serialize_model(self, queryset, fields=None):
        """Сериализует queryset модели в список словарей."""
        if fields is None:
            fields = [f.name for f in queryset.model._meta.get_fields() if not f.many_to_many and not f.one_to_many]
        
        data = []
        for obj in queryset:
            item = {}
            for field_name in fields:
                if hasattr(obj, field_name):
                    value = getattr(obj, field_name)
                    # Обработка ForeignKey
                    if hasattr(value, 'pk'):
                        item[field_name] = value.pk
                    # Обработка ImageField/FileField
                    elif hasattr(value, 'name'):
                        item[field_name] = value.name if value else None
                    # Обработка DateTimeField
                    elif hasattr(value, 'isoformat'):
                        item[field_name] = value.isoformat() if value else None
                    else:
                        item[field_name] = value
            data.append(item)
        return data

    def handle(self, *args, **options):
        output_file = options['output'] or f'catalog_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        
        self.stdout.write('Начинаю создание бэкапа каталога...')
        
        # Собираем все данные
        backup_data = {
            'version': '1.0',
            'created_at': datetime.now().isoformat(),
            'models': {}
        }
        
        # 1. Разделы каталога
        self.stdout.write('  Экспорт разделов каталога...')
        sections = CatalogSection.objects.all()
        backup_data['models']['catalog_sections'] = self.serialize_model(sections)
        
        # 2. Категории
        self.stdout.write('  Экспорт категорий...')
        categories = Category.objects.select_related('section').all()
        categories_data = []
        for cat in categories:
            categories_data.append({
                'id': cat.id,
                'name': cat.name,
                'slug': cat.slug,
                'section_id': cat.section_id,
            })
        backup_data['models']['categories'] = categories_data
        
        # 3. Теги товаров
        self.stdout.write('  Экспорт тегов...')
        tags = ProductTag.objects.all()
        backup_data['models']['product_tags'] = self.serialize_model(tags)
        
        # 4. Товары
        self.stdout.write('  Экспорт товаров...')
        products = Product.objects.select_related('category').prefetch_related('tags').all()
        products_data = []
        for product in products:
            products_data.append({
                'id': product.id,
                'name': product.name,
                'slug': product.slug,
                'description': product.description,
                'price': str(product.price),
                'image': product.image.name if product.image else None,
                'is_active': product.is_active,
                'allow_order_on_request': product.allow_order_on_request,
                'option_label': product.option_label,
                'category_id': product.category_id,
                'tag_ids': list(product.tags.values_list('id', flat=True)),
                'created_at': product.created_at.isoformat() if product.created_at else None,
                'updated_at': product.updated_at.isoformat() if product.updated_at else None,
            })
        backup_data['models']['products'] = products_data
        
        # 5. Варианты товаров
        self.stdout.write('  Экспорт вариантов товаров...')
        variants = ProductVariant.objects.select_related('product').all()
        variants_data = []
        for variant in variants:
            variants_data.append({
                'id': variant.id,
                'product_id': variant.product_id,
                'name': variant.name,
                'image': variant.image.name if variant.image else None,
                'price_override': str(variant.price_override) if variant.price_override else None,
                'order': variant.order,
            })
        backup_data['models']['product_variants'] = variants_data
        
        # 6. Характеристики товаров
        self.stdout.write('  Экспорт характеристик товаров...')
        characteristics = ProductCharacteristic.objects.select_related('product').all()
        backup_data['models']['product_characteristics'] = self.serialize_model(characteristics, ['id', 'product_id', 'name', 'value'])
        
        # 7. Характеристики вариантов
        self.stdout.write('  Экспорт характеристик вариантов...')
        variant_chars = ProductVariantCharacteristic.objects.select_related('variant').all()
        backup_data['models']['product_variant_characteristics'] = self.serialize_model(variant_chars, ['id', 'variant_id', 'name', 'value'])
        
        # 8. Изображения товаров
        self.stdout.write('  Экспорт изображений товаров...')
        images = ProductImage.objects.select_related('product').all()
        images_data = []
        for img in images:
            images_data.append({
                'id': img.id,
                'product_id': img.product_id,
                'image': img.image.name if img.image else None,
                'order': img.order,
            })
        backup_data['models']['product_images'] = images_data
        
        # 9. Наборы товаров
        self.stdout.write('  Экспорт наборов товаров...')
        bundles = ProductBundle.objects.all()
        backup_data['models']['product_bundles'] = self.serialize_model(bundles, ['id', 'name'])
        
        # 10. Позиции наборов
        self.stdout.write('  Экспорт позиций наборов...')
        bundle_items = ProductBundleItem.objects.select_related('bundle', 'product').all()
        bundle_items_data = []
        for item in bundle_items:
            bundle_items_data.append({
                'id': item.id,
                'bundle_id': item.bundle_id,
                'product_id': item.product_id,
                'quantity': item.quantity,
                'price': str(item.effective_price),
            })
        backup_data['models']['product_bundle_items'] = bundle_items_data
        
        # 11. Города
        self.stdout.write('  Экспорт городов...')
        cities = City.objects.all()
        backup_data['models']['cities'] = self.serialize_model(cities)
        
        # 12. Точки выдачи
        self.stdout.write('  Экспорт точек выдачи...')
        pickup_points = PickupPoint.objects.select_related('city').all()
        backup_data['models']['pickup_points'] = self.serialize_model(pickup_points, ['id', 'city_id', 'name', 'address', 'order'])
        
        # 13. Остатки товаров
        self.stdout.write('  Экспорт остатков товаров...')
        stocks = ProductStock.objects.select_related('product', 'pickup_point', 'variant').all()
        stocks_data = []
        for stock in stocks:
            stocks_data.append({
                'id': stock.id,
                'product_id': stock.product_id,
                'pickup_point_id': stock.pickup_point_id,
                'variant_id': stock.variant_id,
                'quantity': stock.quantity,
            })
        backup_data['models']['product_stocks'] = stocks_data
        
        # Создаём ZIP архив
        self.stdout.write('  Создание ZIP архива...')
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Добавляем JSON с данными
            json_content = json.dumps(backup_data, ensure_ascii=False, indent=2, cls=DecimalEncoder)
            zip_file.writestr('backup.json', json_content.encode('utf-8'))
            
            # Собираем и добавляем изображения
            media_root = settings.MEDIA_ROOT
            images_added = set()
            
            # Изображения товаров
            for product in products:
                if product.image:
                    image_path = product.image.path
                    if os.path.exists(image_path) and image_path not in images_added:
                        archive_name = f'images/products/{product.slug}_main{os.path.splitext(image_path)[1]}'
                        zip_file.write(image_path, archive_name)
                        images_added.add(image_path)
            
            # Изображения вариантов
            for variant in variants:
                if variant.image:
                    variant_image_path = variant.image.path
                    if os.path.exists(variant_image_path) and variant_image_path not in images_added:
                        archive_name = f'images/variants/{variant.id}_{os.path.basename(variant_image_path)}'
                        zip_file.write(variant_image_path, archive_name)
                        images_added.add(variant_image_path)
            
            # Дополнительные изображения товаров
            for img in images:
                if img.image:
                    extra_image_path = img.image.path
                    if os.path.exists(extra_image_path) and extra_image_path not in images_added:
                        archive_name = f'images/product_images/{img.id}_{os.path.basename(extra_image_path)}'
                        zip_file.write(extra_image_path, archive_name)
                        images_added.add(extra_image_path)
        
        # Сохраняем файл
        zip_buffer.seek(0)
        with open(output_file, 'wb') as f:
            f.write(zip_buffer.read())
        
        # Статистика
        stats = {
            'sections': len(backup_data['models']['catalog_sections']),
            'categories': len(backup_data['models']['categories']),
            'tags': len(backup_data['models']['product_tags']),
            'products': len(backup_data['models']['products']),
            'variants': len(backup_data['models']['product_variants']),
            'images': len(images_added),
        }
        
        self.stdout.write(self.style.SUCCESS(
            f'\nБэкап успешно создан: {output_file}\n'
            f'Статистика:\n'
            f'  - Разделов: {stats["sections"]}\n'
            f'  - Категорий: {stats["categories"]}\n'
            f'  - Тегов: {stats["tags"]}\n'
            f'  - Товаров: {stats["products"]}\n'
            f'  - Вариантов: {stats["variants"]}\n'
            f'  - Изображений: {stats["images"]}'
        ))
