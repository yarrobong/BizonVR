from django.core.management.base import BaseCommand, CommandError

from catalog.cache_utils import invalidate_catalog_cache
from catalog.filter_bootstrap import (
    bootstrap_category_filter_configs,
    bootstrap_section_filter_configs,
    resolve_catalog_category,
    resolve_catalog_section,
)


class Command(BaseCommand):
    help = 'Создаёт отсутствующие CategoryFilterConfig/SectionFilterConfig по реально встречающимся характеристикам.'

    def add_arguments(self, parser):
        scope_group = parser.add_mutually_exclusive_group(required=True)
        scope_group.add_argument('--category', help='ID или slug категории.')
        scope_group.add_argument('--section', help='ID или slug раздела.')
        parser.add_argument('--apply', action='store_true', help='Применить изменения. По умолчанию только preview.')
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            default=True,
            help='Не трогать уже существующие конфиги.',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        skip_existing = options['skip_existing']

        try:
            if options['category']:
                category = resolve_catalog_category(options['category'])
                results = bootstrap_category_filter_configs(category, apply=apply, skip_existing=skip_existing)
                scope_label = f'category={category.slug}'
            else:
                section = resolve_catalog_section(options['section'])
                results = bootstrap_section_filter_configs(section, apply=apply, skip_existing=skip_existing)
                scope_label = f'section={section.slug}'
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        created = sum(1 for result in results if result['action'] == 'created')
        would_create = sum(1 for result in results if result['action'] == 'would_create')
        existing = sum(1 for result in results if result['action'] == 'existing')

        mode = 'APPLY' if apply else 'DRY-RUN'
        self.stdout.write(f'[{mode}] Filter config bootstrap for {scope_label}')
        for result in results:
            definition = result['definition']
            self.stdout.write(f"- {result['action']}: {definition.code} / {definition.source_name}")

        if apply and created:
            invalidate_catalog_cache()
        summary = created if apply else would_create
        self.stdout.write(
            self.style.SUCCESS(
                f'Итог: {summary} {"создано" if apply else "будет создано"}, существующих: {existing}'
            )
        )
