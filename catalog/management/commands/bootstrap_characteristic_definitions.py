from django.core.management.base import BaseCommand

from catalog.cache_utils import invalidate_catalog_cache
from catalog.filter_bootstrap import bootstrap_characteristic_definitions


class Command(BaseCommand):
    help = 'Создаёт отсутствующие CharacteristicDefinition по текущим ProductCharacteristic.name.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Применить изменения. По умолчанию только preview.')
        parser.add_argument(
            '--only-missing',
            action='store_true',
            default=True,
            help='Создавать только отсутствующие записи (поведение по умолчанию).',
        )
        parser.add_argument('--source-name', default='', help='Точное имя характеристики для bootstrap.')
        parser.add_argument('--starts-with', default='', help='Фильтр по началу имени характеристики.')
        parser.add_argument('--contains', default='', help='Фильтр по подстроке в имени характеристики.')

    def handle(self, *args, **options):
        results = bootstrap_characteristic_definitions(
            apply=options['apply'],
            only_missing=options['only_missing'],
            source_name=options['source_name'],
            starts_with=options['starts_with'],
            contains=options['contains'],
        )
        created = sum(1 for result in results if result['action'] == 'created')
        would_create = sum(1 for result in results if result['action'] == 'would_create')
        existing = sum(1 for result in results if result['action'] == 'existing')

        mode = 'APPLY' if options['apply'] else 'DRY-RUN'
        self.stdout.write(f'[{mode}] CharacteristicDefinition bootstrap')
        for result in results:
            self.stdout.write(f"- {result['action']}: {result['source_name']} -> {result['code']}")

        if options['apply'] and created:
            invalidate_catalog_cache()
        summary = created if options['apply'] else would_create
        self.stdout.write(
            self.style.SUCCESS(
                f'Итог: {summary} {"создано" if options["apply"] else "будет создано"}, существующих: {existing}'
            )
        )
