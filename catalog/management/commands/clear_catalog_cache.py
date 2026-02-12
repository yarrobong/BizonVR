"""Сброс кэша каталога (разделы, города). Полезно, если в админке изменили города, а на сайте старый список."""

from django.core.management.base import BaseCommand

from catalog.cache_utils import CACHE_KEY_CITIES, CACHE_KEY_SECTIONS, invalidate_catalog_cache
from catalog.models import City


class Command(BaseCommand):
    help = 'Сбрасывает кэш каталога (города, разделы). После этого список городов на сайте подтянется из БД.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cities-only',
            action='store_true',
            help='Сбросить только кэш городов',
        )

    def handle(self, *args, **options):
        from django.core.cache import cache

        if options['cities_only']:
            cache.delete(CACHE_KEY_CITIES)
            self.stdout.write('Кэш городов сброшен.')
        else:
            invalidate_catalog_cache()
            self.stdout.write('Кэш каталога сброшен (разделы, города, теги).')

        count = City.objects.count()
        self.stdout.write(self.style.SUCCESS(f'В БД сейчас городов: {count}'))
        if count > 0:
            names = list(City.objects.order_by('order', 'name').values_list('name', flat=True))
            self.stdout.write('  ' + ', '.join(names))
