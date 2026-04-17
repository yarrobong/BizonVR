"""
Восстановление каталога из бэкапа (ZIP архив с JSON и изображениями).
Запуск: python manage.py restore_catalog backup.zip [--clear]
"""
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from io import BytesIO

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, UnidentifiedImageError

from catalog.importers import CatalogDataImporter, CatalogImportError
from catalog.models import (
    CatalogSection,
    Category,
    City,
    PickupPoint,
    Product,
    ProductBundle,
    ProductBundleItem,
    ProductCharacteristic,
    ProductContentBlock,
    ProductImage,
    ProductStock,
    ProductTag,
    ProductVariant,
    ProductVariantCharacteristic,
    ProductVideo,
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

    def _build_media_resolver(self, images_map):
        def resolve(collection_name, item, field_name, payload_value):
            extension = os.path.splitext(payload_value)[1]
            archive_candidates = []

            if collection_name == 'products':
                archive_candidates.append(f'images/products/{item["slug"]}_main{extension}')
            elif collection_name == 'product_variants':
                image_name = os.path.basename(payload_value)
                archive_candidates.extend(
                    [
                        f'images/variants/{item.get("id")}_{image_name}',
                        f'images/variants/{image_name}',
                    ]
                )
            elif collection_name == 'product_images':
                image_name = os.path.basename(payload_value)
                archive_candidates.extend(
                    [
                        f'images/product_images/{item.get("id")}_{image_name}',
                        f'images/product_images/{image_name}',
                    ]
                )
            elif collection_name == 'product_content_blocks':
                image_name = os.path.basename(payload_value)
                archive_candidates.extend(
                    [
                        f'images/content_blocks/{item.get("id")}_{image_name}',
                        f'images/content_blocks/{image_name}',
                    ]
                )
            elif collection_name == 'product_bundles':
                image_name = os.path.basename(payload_value)
                archive_candidates.extend(
                    [
                        f'images/bundles/{item.get("slug") or item.get("id")}_{image_name}',
                        f'images/bundles/{image_name}',
                    ]
                )

            local_image_path = None
            for archive_path in archive_candidates:
                if archive_path in images_map:
                    local_image_path = images_map[archive_path]
                    break

            if local_image_path is None:
                file_name = os.path.basename(payload_value)
                for archive_path, candidate_path in images_map.items():
                    if os.path.basename(archive_path) == file_name:
                        local_image_path = candidate_path
                        break

            if local_image_path is None:
                return None

            return self._store_restored_image(local_image_path)

        return resolve

    def handle(self, *args, **options):
        backup_file = options['backup_file']
        clear = options['clear']

        if not os.path.exists(backup_file):
            raise CommandError(f'Файл бэкапа не найден: {backup_file}')

        self.stdout.write(f'Чтение бэкапа: {backup_file}...')

        try:
            with zipfile.ZipFile(backup_file, 'r') as zip_file:
                if 'backup.json' not in zip_file.namelist():
                    raise CommandError('В архиве не найден файл backup.json')

                json_content = zip_file.read('backup.json').decode('utf-8')
                backup_data = json.loads(json_content)

                version = backup_data.get('version', '1.0')
                self.stdout.write(f'Версия бэкапа: {version}')

                if clear:
                    self.stdout.write(self.style.WARNING('Очистка существующих данных...'))
                    ProductStock.objects.all().delete()
                    ProductContentBlock.objects.all().delete()
                    ProductVideo.objects.all().delete()
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

                temp_dir = tempfile.mkdtemp()
                try:
                    images_map = self.extract_images_from_zip(zip_file, temp_dir)
                    self.stdout.write(f'  Извлечено изображений: {len(images_map)}')
                    importer = CatalogDataImporter(
                        backup_data,
                        media_resolver=self._build_media_resolver(images_map),
                    )
                    report = importer.import_data()
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
        except CatalogImportError as exc:
            raise CommandError(str(exc)) from exc

        for label, bucket in report.sections():
            if bucket:
                self.stdout.write(f'{label}: {bucket}')
        for warning in report.warnings:
            self.stdout.write(self.style.WARNING(f'Предупреждение: {warning}'))

        self.stdout.write(self.style.SUCCESS('\nВосстановление завершено успешно!'))
