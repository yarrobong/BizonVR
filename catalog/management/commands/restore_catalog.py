"""
Восстановление каталога из бэкапа (ZIP архив с JSON и изображениями).
Запуск: python manage.py restore_catalog backup.zip [--clear]
В Docker: docker compose exec web python manage.py restore_catalog backup.zip
"""
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, UnidentifiedImageError

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


class Command(BaseCommand):
    help = 'Восстанавливает каталог из бэкапа (ZIP архив с JSON и изображениями).'
    ALLOWED_IMAGE_EXTENSIONS = {
        '.jpg': ('JPEG', '.jpg'),
        '.jpeg': ('JPEG', '.jpg'),
        '.png': ('PNG', '.png'),
        '.webp': ('WEBP', '.webp'),
    }
    MAX_IMAGE_MEMBERS = 500
    MAX_SINGLE_IMAGE_BYTES = 15 * 1024 * 1024
    MAX_TOTAL_IMAGE_BYTES = 100 * 1024 * 1024

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file',
            type=str,
            help='Путь к ZIP файлу с бэкапом',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Очистить существующие данные каталога перед восстановлением',
        )

    def _normalize_image_bytes(self, file_data, source_name):
        extension = os.path.splitext(source_name)[1].lower()
        if extension not in self.ALLOWED_IMAGE_EXTENSIONS:
            raise CommandError(
                f'Недопустимый тип файла в архиве: {source_name}. '
                'Разрешены только JPG, JPEG, PNG и WEBP.'
            )
        if len(file_data) > self.MAX_SINGLE_IMAGE_BYTES:
            raise CommandError(f'Файл {source_name} превышает допустимый размер.')

        target_format, safe_extension = self.ALLOWED_IMAGE_EXTENSIONS[extension]
        try:
            with Image.open(BytesIO(file_data)) as image:
                image.load()
                if target_format == 'JPEG':
                    if image.mode not in ('RGB', 'L'):
                        image = image.convert('RGB')
                elif target_format == 'PNG':
                    if image.mode not in ('RGB', 'RGBA', 'L', 'LA'):
                        image = image.convert('RGBA')
                elif target_format == 'WEBP':
                    if image.mode not in ('RGB', 'RGBA'):
                        image = image.convert('RGBA')

                output = BytesIO()
                save_kwargs = {'format': target_format}
                if target_format == 'JPEG':
                    save_kwargs.update({'quality': 90, 'optimize': True})
                image.save(output, **save_kwargs)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise CommandError(f'Файл {source_name} не является корректным изображением.') from exc

        return output.getvalue(), safe_extension

    def extract_images_from_zip(self, zip_file, temp_dir):
        """Извлекает изображения из ZIP архива во временную директорию."""
        images_map = {}  # {archive_path: local_path}
        total_image_bytes = 0
        image_members = 0

        for member in zip_file.infolist():
            if member.is_dir() or not member.filename.startswith('images/'):
                continue

            image_members += 1
            if image_members > self.MAX_IMAGE_MEMBERS:
                raise CommandError('Архив содержит слишком много файлов изображений.')

            total_image_bytes += member.file_size
            if total_image_bytes > self.MAX_TOTAL_IMAGE_BYTES:
                raise CommandError('Архив изображений превышает допустимый суммарный размер.')

            source_name = os.path.basename(member.filename)
            if not source_name:
                continue

            file_data = zip_file.read(member.filename)
            normalized_bytes, safe_extension = self._normalize_image_bytes(file_data, source_name)
            local_path = os.path.join(temp_dir, f'{uuid.uuid4().hex}{safe_extension}')
            with open(local_path, 'wb') as f:
                f.write(normalized_bytes)
            images_map[member.filename] = local_path

        return images_map

    def _store_restored_image(self, local_image_path):
        extension = os.path.splitext(local_image_path)[1].lower()
        relative_path = os.path.join('products', f'{uuid.uuid4().hex}{extension}')
        media_path = os.path.join(settings.MEDIA_ROOT, relative_path)
        os.makedirs(os.path.dirname(media_path), exist_ok=True)
        shutil.copy2(local_image_path, media_path)
        return relative_path.replace(os.sep, '/')

    def handle(self, *args, **options):
        backup_file = options['backup_file']
        clear = options['clear']
        
        if not os.path.exists(backup_file):
            raise CommandError(f'Файл бэкапа не найден: {backup_file}')
        
        self.stdout.write(f'Чтение бэкапа: {backup_file}...')
        
        # Открываем ZIP архив
        with zipfile.ZipFile(backup_file, 'r') as zip_file:
            # Читаем JSON
            if 'backup.json' not in zip_file.namelist():
                raise CommandError('В архиве не найден файл backup.json')
            
            json_content = zip_file.read('backup.json').decode('utf-8')
            backup_data = json.loads(json_content)
            
            # Проверяем версию
            version = backup_data.get('version', '1.0')
            self.stdout.write(f'Версия бэкапа: {version}')
            
            # Очистка данных при необходимости
            if clear:
                self.stdout.write(self.style.WARNING('Очистка существующих данных...'))
                ProductStock.objects.all().delete()
                ProductVariantCharacteristic.objects.all().delete()
                ProductCharacteristic.objects.all().delete()
                ProductImage.objects.all().delete()
                ProductVariant.objects.all().delete()
                ProductBundleItem.objects.all().delete()
                ProductBundle.objects.all().delete()
                Product.objects.all().delete()
                PickupPoint.objects.all().delete()
                City.objects.all().delete()
                Category.objects.all().delete()
                CatalogSection.objects.all().delete()
                ProductTag.objects.all().delete()
                self.stdout.write('  Данные очищены.')
            
            # Создаём временную директорию для изображений
            temp_dir = tempfile.mkdtemp()
            try:
                images_map = self.extract_images_from_zip(zip_file, temp_dir)
                self.stdout.write(f'  Извлечено изображений: {len(images_map)}')
                
                # Восстанавливаем данные в транзакции
                with transaction.atomic():
                    # 1. Разделы каталога
                    self.stdout.write('Восстановление разделов каталога...')
                    sections_map = {}  # {old_id: new_obj}
                    for item in backup_data['models'].get('catalog_sections', []):
                        section, _ = CatalogSection.objects.get_or_create(
                            slug=item['slug'],
                            defaults={
                                'name': item['name'],
                                'order': item.get('order', 0),
                            }
                        )
                        sections_map[item['id']] = section
                    
                    # 2. Категории
                    self.stdout.write('Восстановление категорий...')
                    categories_map = {}
                    for item in backup_data['models'].get('categories', []):
                        section = sections_map.get(item.get('section_id')) if item.get('section_id') else None
                        category, _ = Category.objects.get_or_create(
                            slug=item['slug'],
                            defaults={
                                'name': item['name'],
                                'section': section,
                            }
                        )
                        if section and not category.section_id:
                            category.section = section
                            category.save()
                        categories_map[item['id']] = category
                    
                    # 3. Теги
                    self.stdout.write('Восстановление тегов...')
                    tags_map = {}
                    for item in backup_data['models'].get('product_tags', []):
                        tag, _ = ProductTag.objects.get_or_create(
                            slug=item['slug'],
                            defaults={
                                'name': item['name'],
                                'order': item.get('order', 0),
                            }
                        )
                        tags_map[item['id']] = tag
                    
                    # 4. Товары
                    self.stdout.write('Восстановление товаров...')
                    products_map = {}
                    for item in backup_data['models'].get('products', []):
                        category = categories_map.get(item['category_id'])
                        if not category:
                            self.stdout.write(self.style.WARNING(f'  Пропущен товар {item["name"]}: категория не найдена'))
                            continue
                        
                        product, created = Product.objects.update_or_create(
                            slug=item['slug'],
                            defaults={
                                'name': item['name'],
                                'description': item.get('description', ''),
                                'price': Decimal(item['price']),
                                'is_active': item.get('is_active', True),
                                'allow_order_on_request': item.get('allow_order_on_request', True),
                                'option_label': item.get('option_label', ''),
                                'category': category,
                            }
                        )
                        
                        # Восстанавливаем изображение товара
                        if item.get('image'):
                            image_archive_path = f"images/products/{item['slug']}_main{os.path.splitext(item['image'])[1]}"
                            if image_archive_path in images_map:
                                local_image_path = images_map[image_archive_path]
                                product.image = self._store_restored_image(local_image_path)
                                product.save()
                        
                        # Восстанавливаем теги
                        tag_ids = item.get('tag_ids', [])
                        product.tags.set([tags_map[tid] for tid in tag_ids if tid in tags_map])
                        
                        products_map[item['id']] = product
                    
                    # 5. Варианты товаров
                    self.stdout.write('Восстановление вариантов товаров...')
                    variants_map = {}
                    for item in backup_data['models'].get('product_variants', []):
                        product = products_map.get(item['product_id'])
                        if not product:
                            continue
                        
                        variant = ProductVariant.objects.create(
                            product=product,
                            name=item['name'],
                            price_override=Decimal(item['price_override']) if item.get('price_override') else None,
                            order=item.get('order', 0),
                        )
                        
                        # Восстанавливаем изображение варианта
                        if item.get('image'):
                            variant_image_name = os.path.basename(item['image'])
                            for archive_path, local_path in images_map.items():
                                if variant_image_name in archive_path and 'variants' in archive_path:
                                    variant.image = self._store_restored_image(local_path)
                                    variant.save()
                                    break
                        
                        variants_map[item['id']] = variant
                    
                    # 6. Характеристики товаров
                    self.stdout.write('Восстановление характеристик товаров...')
                    for item in backup_data['models'].get('product_characteristics', []):
                        product = products_map.get(item['product_id'])
                        if product:
                            ProductCharacteristic.objects.create(
                                product=product,
                                name=item['name'],
                                value=item['value'],
                            )
                    
                    # 7. Характеристики вариантов
                    self.stdout.write('Восстановление характеристик вариантов...')
                    for item in backup_data['models'].get('product_variant_characteristics', []):
                        variant = variants_map.get(item['variant_id'])
                        if variant:
                            ProductVariantCharacteristic.objects.create(
                                variant=variant,
                                name=item['name'],
                                value=item['value'],
                            )
                    
                    # 8. Изображения товаров
                    self.stdout.write('Восстановление изображений товаров...')
                    for item in backup_data['models'].get('product_images', []):
                        product = products_map.get(item['product_id'])
                        if product and item.get('image'):
                            image_name = os.path.basename(item['image'])
                            for archive_path, local_path in images_map.items():
                                if image_name in archive_path and 'product_images' in archive_path:
                                    ProductImage.objects.create(
                                        product=product,
                                        image=self._store_restored_image(local_path),
                                        order=item.get('order', 0),
                                    )
                                    break
                    
                    # 9. Наборы товаров
                    self.stdout.write('Восстановление наборов товаров...')
                    bundles_map = {}
                    for item in backup_data['models'].get('product_bundles', []):
                        bundle = ProductBundle.objects.create(
                            name=item.get('name', ''),
                        )
                        bundles_map[item['id']] = bundle
                    
                    # 10. Позиции наборов
                    self.stdout.write('Восстановление позиций наборов...')
                    for item in backup_data['models'].get('product_bundle_items', []):
                        bundle = bundles_map.get(item['bundle_id'])
                        product = products_map.get(item['product_id'])
                        if bundle and product:
                            ProductBundleItem.objects.create(
                                bundle=bundle,
                                product=product,
                                quantity=item['quantity'],
                            )
                    
                    # 11. Города
                    self.stdout.write('Восстановление городов...')
                    cities_map = {}
                    for item in backup_data['models'].get('cities', []):
                        city, _ = City.objects.get_or_create(
                            slug=item['slug'],
                            defaults={
                                'name': item['name'],
                                'order': item.get('order', 0),
                            }
                        )
                        cities_map[item['id']] = city
                    
                    # 12. Точки выдачи
                    self.stdout.write('Восстановление точек выдачи...')
                    pickup_points_map = {}
                    for item in backup_data['models'].get('pickup_points', []):
                        city = cities_map.get(item['city_id'])
                        if city:
                            pickup_point, _ = PickupPoint.objects.get_or_create(
                                city=city,
                                name=item['name'],
                                defaults={
                                    'address': item.get('address', ''),
                                    'order': item.get('order', 0),
                                }
                            )
                            pickup_points_map[item['id']] = pickup_point
                    
                    # 13. Остатки товаров
                    self.stdout.write('Восстановление остатков товаров...')
                    for item in backup_data['models'].get('product_stocks', []):
                        product = products_map.get(item['product_id'])
                        pickup_point = pickup_points_map.get(item['pickup_point_id'])
                        variant = variants_map.get(item['variant_id']) if item.get('variant_id') else None
                        
                        if product and pickup_point:
                            ProductStock.objects.update_or_create(
                                product=product,
                                pickup_point=pickup_point,
                                variant=variant,
                                defaults={'quantity': item['quantity']},
                            )
                
            finally:
                # Удаляем временную директорию
                shutil.rmtree(temp_dir, ignore_errors=True)
        
        self.stdout.write(self.style.SUCCESS('\nВосстановление завершено успешно!'))
