from decimal import Decimal

from django.template import Context, Template
from django.test import SimpleTestCase

from config.formatting import format_amount, format_currency_amount, format_decimal_amount


class MoneyFormattingTests(SimpleTestCase):
    def test_format_amount_without_fraction(self):
        self.assertEqual(format_amount(Decimal('581700.00')), '581 700')

    def test_format_amount_with_fraction(self):
        self.assertEqual(format_amount(Decimal('581700.50')), '581 700,50')

    def test_format_currency_amount_for_rubles(self):
        self.assertEqual(format_currency_amount(Decimal('581700.00')), '581 700 ₽')

    def test_format_decimal_amount_keeps_trailing_zeroes(self):
        self.assertEqual(format_decimal_amount(Decimal('581700.00')), '581 700,00')

    def test_template_filters_are_available_globally(self):
        rendered = Template(
            '{{ rubles|rub }} | {{ decimal_value|price_format }} | {{ amount|currency_amount:currency }} | {{ rubles|decimal_format }}'
        ).render(
            Context(
                {
                    'rubles': Decimal('581700'),
                    'decimal_value': Decimal('581700.50'),
                    'amount': Decimal('1250.25'),
                    'currency': 'USD',
                }
            )
        )

        self.assertEqual(rendered, '581 700 ₽ | 581 700,50 | 1 250,25 USD | 581 700,00')
