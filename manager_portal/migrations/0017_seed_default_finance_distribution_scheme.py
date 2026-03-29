from decimal import Decimal

from django.db import migrations
from django.utils.text import slugify


SCHEME_NAME = 'Основная схема распределения'


def _alias(models, display_name):
    ManagerPersonAlias = models['alias']
    alias, _ = ManagerPersonAlias.objects.get_or_create(
        display_name=display_name,
        defaults={
            'slug': slugify(display_name, allow_unicode=True),
            'is_active': True,
        },
    )
    if not alias.slug:
        alias.slug = slugify(display_name, allow_unicode=True)
        alias.save(update_fields=['slug', 'updated_at'])
    return alias


def seed_default_scheme(apps, schema_editor):
    ManagerPersonAlias = apps.get_model('manager_portal', 'ManagerPersonAlias')
    FinanceDistributionScheme = apps.get_model('manager_portal', 'FinanceDistributionScheme')
    FinanceDistributionRule = apps.get_model('manager_portal', 'FinanceDistributionRule')

    models = {'alias': ManagerPersonAlias}
    sergey = _alias(models, 'Сергей')
    sergey_owner = _alias(models, 'Сергей П')
    yaroslav_p = _alias(models, 'Ярослав П')
    maxim_t = _alias(models, 'Максим Т')
    yaroslav_e = _alias(models, 'Ярослав Е')
    artem_ch = _alias(models, 'Артём Ч')

    FinanceDistributionScheme.objects.filter(is_active=True).update(is_active=False)
    scheme, created = FinanceDistributionScheme.objects.get_or_create(
        name=SCHEME_NAME,
        version=1,
        defaults={
            'is_active': True,
            'description': 'Стартовая версия расчёта долей по участникам.',
        },
    )
    if not scheme.is_active:
        scheme.is_active = True
        scheme.save(update_fields=['is_active', 'updated_at'])

    sergey_rule, _ = FinanceDistributionRule.objects.get_or_create(
        scheme=scheme,
        participant_alias=sergey,
        defaults={
            'position': 10,
            'rule_type': 'percent_owner_margin',
            'percent': Decimal('0.2500'),
            'owner_alias': sergey_owner,
            'note': '25% от маржи товаров Сергея П',
            'is_active': True,
        },
    )
    yaroslav_p_rule, _ = FinanceDistributionRule.objects.get_or_create(
        scheme=scheme,
        participant_alias=yaroslav_p,
        defaults={
            'position': 20,
            'rule_type': 'percent_remainder_after_rule',
            'percent': Decimal('0.1500'),
            'reference_rule': sergey_rule,
            'note': '15% от остатка после Сергея',
            'is_active': True,
        },
    )
    if yaroslav_p_rule.reference_rule_id != sergey_rule.id:
        yaroslav_p_rule.reference_rule = sergey_rule
        yaroslav_p_rule.save(update_fields=['reference_rule', 'updated_at'])
    FinanceDistributionRule.objects.get_or_create(
        scheme=scheme,
        participant_alias=maxim_t,
        defaults={
            'position': 30,
            'rule_type': 'percent_total_margin',
            'percent': Decimal('0.0400'),
            'note': '4% от общей маржи',
            'is_active': True,
        },
    )
    FinanceDistributionRule.objects.get_or_create(
        scheme=scheme,
        participant_alias=yaroslav_e,
        defaults={
            'position': 40,
            'rule_type': 'equal_split_remainder',
            'percent': Decimal('0'),
            'note': 'Половина остатка',
            'is_active': True,
        },
    )
    FinanceDistributionRule.objects.get_or_create(
        scheme=scheme,
        participant_alias=artem_ch,
        defaults={
            'position': 50,
            'rule_type': 'equal_split_remainder',
            'percent': Decimal('0'),
            'note': 'Половина остатка',
            'is_active': True,
        },
    )


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0016_financedeal_distribution_scheme_name_snapshot_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_default_scheme, noop_reverse),
    ]
