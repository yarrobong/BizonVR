import json

from django.core.management.base import BaseCommand, CommandError

from catalog.filter_bootstrap import build_alias_suggestions, resolve_characteristic_definition


class Command(BaseCommand):
    help = 'Показывает suggested grouping raw values для CharacteristicDefinition.'

    def add_arguments(self, parser):
        parser.add_argument('--definition', required=True, help='ID или code CharacteristicDefinition.')
        parser.add_argument(
            '--format',
            default='table',
            choices=('table', 'json'),
            help='Формат вывода preview.',
        )

    def handle(self, *args, **options):
        try:
            definition = resolve_characteristic_definition(options['definition'])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        suggestions = build_alias_suggestions(definition)
        if options['format'] == 'json':
            payload = [
                {
                    'normalized_key': suggestion['normalized_key'],
                    'suggested_display': suggestion['suggested_display'],
                    'product_count': suggestion['product_count'],
                    'already_covered': suggestion['already_covered'],
                    'raw_values': [
                        {
                            'raw_value': raw_value.raw_value,
                            'product_count': raw_value.product_count,
                            'alias_exists': raw_value.alias_exists,
                            'alias_is_active': raw_value.alias_is_active,
                            'existing_normalized_value': raw_value.existing_normalized_value,
                            'existing_display_value': raw_value.existing_display_value,
                        }
                        for raw_value in suggestion['raw_values']
                    ],
                }
                for suggestion in suggestions
            ]
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(
            f'Предложения алиасов для {definition.name} ({definition.code}) / source_name="{definition.source_name}"'
        )
        for suggestion in suggestions:
            self.stdout.write(
                f"- {suggestion['normalized_key']} -> {suggestion['suggested_display']} "
                f"(товаров: {suggestion['product_count']}, covered: {suggestion['already_covered']})"
            )
            for raw_value in suggestion['raw_values']:
                status = 'existing'
                if raw_value.alias_exists and not raw_value.alias_is_active:
                    status = 'existing-inactive'
                elif not raw_value.alias_exists:
                    status = 'missing'
                self.stdout.write(f"    * {raw_value.raw_value} ({raw_value.product_count}) [{status}]")
