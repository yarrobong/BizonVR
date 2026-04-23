from django.core.management.base import BaseCommand

from catalog.models import Product
from catalog.product_descriptions import migrate_legacy_blocks


class Command(BaseCommand):
    help = 'Создаёт новые ProductDescription из Product.description и legacy ProductContentBlock.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Создать записи. Без флага выполняется dry-run.')
        parser.add_argument('--activate', action='store_true', help='Сразу включить новые описания на витрине.')
        parser.add_argument('--product-id', type=int, action='append', dest='product_ids', help='Ограничить перенос конкретным товаром. Можно указать несколько раз.')

    def handle(self, *args, **options):
        apply_changes = options['apply']
        activate = options['activate']
        product_ids = options.get('product_ids') or []

        products = Product.objects.all().prefetch_related('content_blocks')
        if product_ids:
            products = products.filter(pk__in=product_ids)

        total = products.count()
        would_create = 0
        created = 0
        skipped = 0

        for product in products:
            has_payload = bool((product.description or '').strip() or product.content_blocks.exists())
            if not has_payload:
                skipped += 1
                continue
            if hasattr(product, 'product_description'):
                skipped += 1
                continue
            would_create += 1
            if apply_changes:
                _, was_created = migrate_legacy_blocks(product, activate=activate)
                if was_created:
                    created += 1

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(
                f'Готово. Проверено товаров: {total}. Создано описаний: {created}. Пропущено: {skipped}.'
            ))
        else:
            self.stdout.write(
                f'DRY-RUN. Проверено товаров: {total}. Будет создано описаний: {would_create}. Пропущено: {skipped}.'
            )
            self.stdout.write('Запустите с --apply, чтобы создать записи. По умолчанию они будут скрыты на витрине.')
