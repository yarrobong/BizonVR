from django.core.management.base import BaseCommand

from catalog.filter_audit import sync_catalog_filter_audit_snapshots


class Command(BaseCommand):
    help = 'Пересчитывает live-audit для dashboard фильтров каталога.'

    def handle(self, *args, **options):
        stats = sync_catalog_filter_audit_snapshots()
        self.stdout.write(
            self.style.SUCCESS(
                'Live audit фильтров каталога готов. '
                f"Uncovered sources: {stats['uncovered_source_count']}, "
                f"uncovered values: {stats['uncovered_value_count']}."
            )
        )
