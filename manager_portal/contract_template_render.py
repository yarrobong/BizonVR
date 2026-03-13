"""
Рендер шаблонов договоров: конвертация Handlebars (legacy DocuFlow) в Django template syntax
и построение контекста с переменными legacy-шаблонов.
"""
import re
from decimal import Decimal

from django.conf import settings
from django.template import Context, Template
from django.utils import timezone

from config.formatting import format_currency_amount


# Переменные внутри {{#each items}}, которые нужно маппить на item.xxx или forloop
_EACH_ITEM_VARS = frozenset({'index', 'name', 'qty', 'quantity', 'unit', 'price', 'line_total'})


def _convert_handlebars_to_django(html: str) -> str:
    """
    Конвертирует Handlebars-подобный синтаксис в Django template syntax.
    Поддерживает: {{#if var}}, {{/if}}, {{#each items}}, {{/each}}.
    Внутри #each: {{index}} -> forloop.counter, {{name}}, {{qty}} и т.д. -> item.xxx
    """
    result = html

    # 1. {{#each items}}...{{/each}} — обрабатываем от внутренних к внешним
    # Используем функцию для замены, чтобы обработать вложенный контент
    def replace_each(match):
        path = match.group(1).strip()
        block = match.group(2)
        # Внутри блока: item-переменные -> item.var или forloop.counter
        inner = block
        inner = re.sub(r'\{\{\s*index\s*\}\}', r'{{ forloop.counter }}', inner)
        for var in ('name', 'qty', 'quantity', 'unit', 'price', 'line_total'):
            inner = re.sub(
                rf'\{{\{{\s*{re.escape(var)}\s*\}}\}}',
                rf'{{{{ item.{var} }}}}',
                inner,
            )
        return f'{{% for item in {path} %}}{inner}{{% endfor %}}'

    result = re.sub(
        r'\{\{#each\s+([a-zA-Z0-9_.]+)\}\}([\s\S]*?)\{\{/each\}\}',
        replace_each,
        result,
    )

    # 2. {{#if var}}...{{/if}}
    result = re.sub(
        r'\{\{#if\s+([a-zA-Z0-9_.]+)\}\}',
        r'{% if \1 %}',
        result,
    )
    result = re.sub(r'\{\{/if\}\}', r'{% endif %}', result)

    # 3. {{#unless var}}...{{/unless}}
    result = re.sub(
        r'\{\{#unless\s+([a-zA-Z0-9_.]+)\}\}',
        r'{% if not \1 %}',
        result,
    )
    result = re.sub(r'\{\{/unless\}\}', r'{% endif %}', result)

    return result


def _format_amount(amount, currency='RUB'):
    """Форматирует сумму для отображения в шаблоне."""
    if amount is None:
        return ''
    return format_currency_amount(amount, currency, default='')


def _build_contract_items(document) -> list[dict]:
    """Строит список позиций для шаблона (items) из заказа или invoice_data."""
    items = []
    # 1. Из invoice_data (legacy импорт)
    invoice_data = document.invoice_data or {}
    raw_items = invoice_data.get('items') or []
    if raw_items:
        for i, row in enumerate(raw_items, start=1):
            if isinstance(row, dict):
                qty = row.get('quantity') or row.get('qty') or 1
                price = row.get('price') or row.get('unitPrice') or 0
                line_total = row.get('line_total') or row.get('lineTotal') or (float(qty) * float(price))
                items.append({
                    'index': i,
                    'name': row.get('name') or row.get('description') or '',
                    'qty': qty,
                    'quantity': qty,
                    'unit': row.get('unit') or 'шт.',
                    'price': _format_amount(Decimal(str(price))),
                    'line_total': _format_amount(Decimal(str(line_total))),
                })
            else:
                items.append({'index': i, 'name': str(row), 'qty': 1, 'quantity': 1, 'unit': 'шт.', 'price': '', 'line_total': ''})

    # 2. Из linked_order
    if not items and document.linked_order_id:
        order = document.linked_order
        for i, oi in enumerate(order.items.select_related('product', 'variant').all(), start=1):
            name = oi.product.name
            if oi.variant_id:
                name = f'{name} ({oi.variant.name})'
            unit_price = oi.unit_price or oi.sale_price or oi.purchase_price or Decimal('0')
            qty = int(oi.quantity or 1)
            line_total = (unit_price * qty) if unit_price else Decimal('0')
            items.append({
                'index': i,
                'name': name,
                'qty': qty,
                'quantity': qty,
                'unit': 'шт.',
                'price': _format_amount(unit_price),
                'line_total': _format_amount(line_total),
            })

    return items


def build_contract_preview_context(document, *, profile=None):
    """
    Строит контекст для рендера шаблона договора.
    Включает как Django-стиль (document, company, counterparty), так и legacy-переменные
    (supplier_*, buyer_*, contract_number, items и т.д.) для совместимости с DocuFlow.
    """
    from .models import ContractCompanyProfile

    profile = profile or document.company_profile
    if not profile:
        profile = ContractCompanyProfile.objects.filter(is_active=True).order_by('-updated_at', '-id').first()
    if not profile:
        profile = ContractCompanyProfile(company_name='', legal_type='ip')

    counterparty = {
        'name': document.counterparty_name or '',
        'email': document.counterparty_email or '',
        'phone': document.counterparty_phone or '',
        'inn': document.counterparty_inn or '',
        'kpp': document.counterparty_kpp or '',
        'ogrn': document.counterparty_ogrn or '',
        'ogrnip': document.counterparty_ogrnip or '',
        'address': document.counterparty_address or '',
    }

    # Определяем тип юридического лица
    def _reg_label(legal_type):
        if legal_type == 'ip':
            return 'ОГРНИП'
        return 'ОГРН'

    def _reg_number(prof):
        return prof.ogrnip or prof.ogrn or ''

    supplier_is_ip = profile.legal_type == 'ip'
    supplier_is_company = profile.legal_type in ('ooo', 'ao', 'other')
    supplier_has_kpp = bool(profile.kpp)
    buyer_has_kpp = bool(counterparty['kpp'])
    buyer_is_ip = bool(counterparty.get('ogrnip'))
    buyer_is_company = bool(counterparty.get('ogrn'))

    items = _build_contract_items(document)
    has_items = len(items) > 0
    has_prepayment = bool(document.payment_terms and document.amount)
    has_delivery = bool(document.include_delivery and document.delivery_date)
    has_penalty = False  # legacy-флаг, по умолчанию нет

    issue_date = document.issue_date or timezone.localdate()
    created_date = issue_date.strftime('%d.%m.%Y')
    created_date_long = issue_date.strftime('%d.%m.%Y')

    # Город — из документа или настроек
    city = getattr(settings, 'SITE_CITY', 'Екатеринбург')
    contract_signing_city = city

    total_amount_formatted = _format_amount(document.amount, document.currency or 'RUB')

    # Legacy-переменные для совместимости с DocuFlow
    legacy = {
        'contract_number': document.number or '',
        'contract_type': document.get_document_type_display() if hasattr(document, 'get_document_type_display') else '',
        'created_date': created_date,
        'created_date_long': created_date_long,
        'city': city,
        'contract_signing_city': contract_signing_city,
        # supplier (company)
        'supplier_name': profile.company_name or '',
        'supplier_director_genitive': profile.director_genitive or '',
        'supplier_registration_label': _reg_label(profile.legal_type),
        'supplier_registration_number': _reg_number(profile),
        'supplier_inn': profile.inn or '',
        'supplier_kpp': profile.kpp or '',
        'supplier_phone': profile.phone or '',
        'supplier_email': profile.email or '',
        'supplier_address': profile.legal_address or profile.registration_address or '',
        'supplier_bank_name': profile.bank_name or '',
        'supplier_bik': profile.bik or '',
        'supplier_checking_account': profile.checking_account or '',
        'supplier_correspondent_account': profile.correspondent_account or '',
        'supplier_signer_position': '',
        'supplier_signer_name': profile.director_genitive or '',
        'supplier_signer_basis': 'устава' if supplier_is_company else 'свидетельства',
        'supplier_has_kpp': supplier_has_kpp,
        'supplier_is_ip': supplier_is_ip,
        'supplier_is_company': supplier_is_company,
        'supplier_address_display': profile.legal_address or profile.registration_address or '',
        'supplier_checking_account_display': profile.checking_account or '',
        'supplier_bank_name_display': profile.bank_name or '',
        'supplier_correspondent_account_display': profile.correspondent_account or '',
        'supplier_bik_display': profile.bik or '',
        'supplier_email_display': profile.email or '',
        'seller_ip_name': profile.company_name or profile.director_genitive or '',
        # buyer (counterparty)
        'buyer_name': counterparty['name'],
        'buyer_inn': counterparty['inn'],
        'buyer_kpp': counterparty['kpp'],
        'buyer_has_kpp': buyer_has_kpp,
        'buyer_registration_label': _reg_label('ip') if buyer_is_ip else 'ОГРН',
        'buyer_registration_number': counterparty.get('ogrnip') or counterparty.get('ogrn') or '',
        'buyer_phone': counterparty['phone'],
        'buyer_email': counterparty['email'],
        'buyer_address': counterparty['address'],
        'buyer_signer_position': '',
        'buyer_signer_name': '',
        'buyer_signer_basis': '',
        'buyer_is_ip': buyer_is_ip,
        'buyer_is_company': buyer_is_company,
        'buyer_email_display': counterparty['email'],
        # document
        'total_amount_formatted': total_amount_formatted,
        'payment_terms': document.payment_terms or '',
        'prepayment_percent': '',
        'delivery_date': document.delivery_date.strftime('%d.%m.%Y') if document.delivery_date else '',
        'vat_rate': document.vat_rate or 'none',
        'vat_mode': document.vat_mode or 'included',
        'delivery_term_days': '',
        'delivery_term_basis': '',
        'goods_sale_vat_clause_text': '',
        'selected_payment_terms_clause': f'Оплата в течение {document.payment_terms or 5} календарных дней' if document.payment_terms else 'Оплата по согласованию',
        'penalty_percent_per_day': '',
        # flags
        'has_prepayment': has_prepayment,
        'has_delivery': has_delivery,
        'has_items': has_items,
        'has_penalty': has_penalty,
        # items
        'items': items,
    }

    return {
        'document': document,
        'company': profile,
        'counterparty': counterparty,
        'manager_client': document.manager_client,
        'order': document.linked_order,
        'site': {
            'brand': getattr(settings, 'SITE_BRAND', ''),
            'phone': getattr(settings, 'SITE_CONTACT_PHONE', ''),
            'email': getattr(settings, 'SITE_CONTACT_EMAIL', ''),
        },
        **legacy,
    }


def render_contract_template(template_html: str, document, *, css_text: str = '') -> str:
    """
    Рендерит HTML шаблон договора. Если шаблон использует Handlebars-синтаксис,
    конвертирует его в Django и рендерит. Возвращает HTML (с опциональным <style>).
    """
    # Проверка на Handlebars
    if '{{#' in template_html or '{{/' in template_html:
        template_html = _convert_handlebars_to_django(template_html)

    context = build_contract_preview_context(document)
    try:
        rendered = Template(template_html).render(Context(context, autoescape=False))
    except Exception as exc:
        return (
            '<div class="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-100">'
            f'Ошибка рендера шаблона: {exc}'
            '</div>'
        )

    if css_text and css_text.strip():
        return f'<style>{css_text.strip()}</style>{rendered}'
    return rendered
