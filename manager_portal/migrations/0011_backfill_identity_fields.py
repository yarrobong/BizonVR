from django.db import migrations
from django.utils import timezone


ROOT_WIDTH = 6
CHILD_WIDTH = 2
MONTHS = {
    1: 'январь',
    2: 'февраль',
    3: 'март',
    4: 'апрель',
    5: 'май',
    6: 'июнь',
    7: 'июль',
    8: 'август',
    9: 'сентябрь',
    10: 'октябрь',
    11: 'ноябрь',
    12: 'декабрь',
}


def year_of(value):
    if value is None:
        return timezone.localdate().year
    return getattr(value, 'year', timezone.localdate().year)


def join_title(*parts):
    return ' · '.join(str(part).strip() for part in parts if str(part).strip())


def month_year_label(value):
    if not value:
        return ''
    return f'{MONTHS.get(value.month, value.month)} {value.year}'


def split_code(value):
    parts = (value or '').split('-')
    if len(parts) < 3:
        return None
    return parts


def format_root(prefix, year, sequence):
    return f'{prefix}-{year}-{sequence:0{ROOT_WIDTH}d}'


def format_child(prefix, deal_code, sequence):
    deal_parts = split_code(deal_code)
    if not deal_parts or len(deal_parts) < 3:
        return ''
    return f'{prefix}-{deal_parts[1]}-{deal_parts[2]}-{sequence:0{CHILD_WIDTH}d}'


def bootstrap_root_counters(values):
    counters = {}
    for value in values:
        parts = split_code(value)
        if not parts or len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
            continue
        key = (parts[0], parts[1])
        counters[key] = max(counters.get(key, 0), int(parts[2]))
    return counters


def bootstrap_child_counters(values):
    counters = {}
    for value in values:
        parts = split_code(value)
        if not parts or len(parts) < 4 or not parts[1].isdigit() or not parts[2].isdigit() or not parts[3].isdigit():
            continue
        key = (parts[0], parts[1], parts[2])
        counters[key] = max(counters.get(key, 0), int(parts[3]))
    return counters


def next_root_code(prefix, year, counters):
    key = (prefix, str(year))
    counters[key] = counters.get(key, 0) + 1
    return format_root(prefix, year, counters[key])


def next_child_code(prefix, deal_code, counters):
    deal_parts = split_code(deal_code)
    if not deal_parts or len(deal_parts) < 3:
        return ''
    key = (prefix, deal_parts[1], deal_parts[2])
    counters[key] = counters.get(key, 0) + 1
    return format_child(prefix, deal_code, counters[key])


def deal_customer_name(deal):
    if deal.buyer_type == 'business':
        return deal.business_company_name or deal.business_contact_person
    return deal.individual_full_name


def deal_customer_city(deal):
    if deal.buyer_type == 'business':
        return deal.business_city
    return deal.individual_city


def deal_main_product_label(deal):
    order = getattr(deal, 'order', None)
    if not order:
        return ''
    order_item = order.items.order_by('id').select_related('product', 'variant').first()
    if not order_item:
        return ''
    variant_name = order_item.variant.name if order_item.variant_id else getattr(order_item, 'variant_name', '')
    return join_title(order_item.product.name, variant_name)


def update_instance(instance, **fields):
    changed_fields = []
    for field_name, value in fields.items():
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        instance.save(update_fields=changed_fields)


def backfill_identity_fields(apps, schema_editor):
    ManagerDeal = apps.get_model('manager_portal', 'ManagerDeal')
    Purchase = apps.get_model('manager_portal', 'Purchase')
    Cargo = apps.get_model('manager_portal', 'Cargo')
    TransportLeg = apps.get_model('manager_portal', 'TransportLeg')
    Reservation = apps.get_model('manager_portal', 'Reservation')
    Shipment = apps.get_model('manager_portal', 'Shipment')
    FinanceDeal = apps.get_model('manager_portal', 'FinanceDeal')
    FinanceExpense = apps.get_model('manager_portal', 'FinanceExpense')
    FinancePayout = apps.get_model('manager_portal', 'FinancePayout')
    ContractDocument = apps.get_model('manager_portal', 'ContractDocument')

    root_counters = {}
    root_counters.update(bootstrap_root_counters(Cargo.objects.values_list('cargo_number', flat=True)))
    root_counters.update(bootstrap_root_counters(ContractDocument.objects.values_list('number', flat=True)))

    child_counters = bootstrap_child_counters(ContractDocument.objects.values_list('number', flat=True))

    for deal in ManagerDeal.objects.select_related('order').order_by('deal_created_at', 'id'):
        code = deal.code or next_root_code('DEAL', year_of(deal.deal_created_at or deal.created_at), root_counters)
        title = deal.title or join_title(
            deal.get_deal_type_display(),
            deal_customer_name(deal),
            deal_main_product_label(deal),
            deal_customer_city(deal) or deal.delivery_to_city or getattr(deal.order, 'city_text', ''),
        )
        short_label = deal.short_label or ' / '.join(
            part for part in [deal_customer_name(deal), deal_main_product_label(deal)] if part
        )
        update_instance(deal, code=code, title=title, short_label=short_label)

    for purchase in Purchase.objects.order_by('date', 'id'):
        code = purchase.code or next_root_code('PO', year_of(purchase.date), root_counters)
        title = purchase.title or join_title(
            'Закупка',
            purchase.supplier_name or 'Поставщик не указан',
            month_year_label(purchase.date),
        )
        short_label = purchase.short_label or ' / '.join(
            part for part in [purchase.supplier_name or 'Закупка', month_year_label(purchase.date)] if part
        )
        update_instance(purchase, code=code, title=title, short_label=short_label)

    for cargo in Cargo.objects.select_related('purchase', 'destination_warehouse').order_by('created_at', 'id'):
        cargo_number = cargo.cargo_number or next_root_code('CG', year_of(cargo.created_at), root_counters)
        route = ' → '.join(
            part
            for part in [
                cargo.purchase.supplier_name if cargo.purchase_id and cargo.purchase.supplier_name else '',
                cargo.destination_warehouse.name if cargo.destination_warehouse_id else 'Склад',
            ]
            if part
        )
        title = cargo.title or join_title('Груз', route, month_year_label(cargo.eta or timezone.localdate()))
        short_label = cargo.short_label or ' / '.join(
            part
            for part in [
                cargo.destination_warehouse.name if cargo.destination_warehouse_id else 'Груз',
                month_year_label(cargo.eta or timezone.localdate()),
            ]
            if part
        )
        update_instance(cargo, cargo_number=cargo_number, title=title, short_label=short_label)

    for leg in TransportLeg.objects.select_related('to_warehouse').order_by('created_at', 'id'):
        code = leg.code or next_root_code('LEG', year_of(leg.created_at), root_counters)
        route = ' → '.join(part for part in [leg.from_location, leg.to_warehouse.name if leg.to_warehouse_id else ''] if part)
        title = leg.title or join_title('Этап перевозки', route, leg.method)
        short_label = leg.short_label or route or leg.method or code
        update_instance(leg, code=code, title=title, short_label=short_label)

    for reservation in Reservation.objects.select_related(
        'manager_deal',
        'client',
        'source_warehouse',
        'source_cargo',
    ).order_by('created_at', 'id'):
        deal_code = reservation.manager_deal.code if reservation.manager_deal_id else ''
        if reservation.code:
            code = reservation.code
        elif deal_code:
            code = next_child_code('RSV', deal_code, child_counters)
        else:
            code = next_root_code('RSV', year_of(reservation.created_at), root_counters)
        source_label = (
            reservation.source_warehouse.name
            if reservation.source_warehouse_id
            else reservation.source_cargo.cargo_number if reservation.source_cargo_id else ''
        )
        title = reservation.title or join_title('Бронь', reservation.client.name if reservation.client_id else '', deal_code or source_label)
        short_label = reservation.short_label or ' / '.join(
            part for part in [reservation.client.name if reservation.client_id else '', reservation.get_status_display()] if part
        )
        update_instance(reservation, code=code, title=title, short_label=short_label)

    for shipment in Shipment.objects.select_related('manager_deal', 'client').order_by('created_at', 'id'):
        deal_code = shipment.manager_deal.code if shipment.manager_deal_id else ''
        if shipment.code:
            code = shipment.code
        elif deal_code:
            code = next_child_code('SHP', deal_code, child_counters)
        else:
            code = next_root_code('SHP', year_of(shipment.created_at), root_counters)
        delivery_label = shipment.delivery_method or ''
        title = shipment.title or join_title('Отгрузка', shipment.client.name if shipment.client_id else '', delivery_label, deal_code)
        short_label = shipment.short_label or ' / '.join(
            part for part in [shipment.client.name if shipment.client_id else '', shipment.delivery_method or 'Отгрузка'] if part
        )
        update_instance(shipment, code=code, title=title, short_label=short_label)

    for finance_deal in FinanceDeal.objects.select_related('manager_deal').order_by('date', 'id'):
        deal_code = finance_deal.manager_deal.code if finance_deal.manager_deal_id else ''
        if finance_deal.code:
            code = finance_deal.code
        elif deal_code:
            deal_parts = split_code(deal_code)
            code = f'FIN-{deal_parts[1]}-{deal_parts[2]}'
        else:
            code = next_root_code('FIN', year_of(finance_deal.date), root_counters)
        customer_name = deal_customer_name(finance_deal.manager_deal) if finance_deal.manager_deal_id else ''
        title = finance_deal.title or join_title('Финансы', customer_name, deal_code)
        short_label = finance_deal.short_label or ' / '.join(part for part in [customer_name, 'Финансы'] if part)
        update_instance(finance_deal, code=code, title=title, short_label=short_label)

    for expense in FinanceExpense.objects.select_related('category').order_by('date', 'id'):
        code = expense.code or next_root_code('EXP', year_of(expense.date), root_counters)
        title = expense.title or join_title('Расход', expense.category.name if expense.category_id else '', f'{expense.amount}')
        short_label = expense.short_label or ' / '.join(
            part for part in [expense.category.name if expense.category_id else 'Расход', f'{expense.amount}'] if part
        )
        update_instance(expense, code=code, title=title, short_label=short_label)

    for payout in FinancePayout.objects.select_related('manager_deal').order_by('date', 'id'):
        code = payout.code or next_root_code('PYO', year_of(payout.date), root_counters)
        customer_name = deal_customer_name(payout.manager_deal) if payout.manager_deal_id else ''
        title = payout.title or join_title('Выплата', customer_name, f'{payout.amount}')
        short_label = payout.short_label or ' / '.join(part for part in [customer_name or 'Выплата', f'{payout.amount}'] if part)
        update_instance(payout, code=code, title=title, short_label=short_label)

    prefix_map = {
        'contract': 'DOG',
        'invoice': 'SCH',
        'act': 'ACT',
        'appendix': 'UPD',
        'offer': 'KP',
        'other': 'DOC',
    }
    child_counters = bootstrap_child_counters(ContractDocument.objects.values_list('number', flat=True))
    root_counters.update(bootstrap_root_counters(ContractDocument.objects.values_list('number', flat=True)))
    for document in ContractDocument.objects.select_related('manager_deal', 'manager_client').order_by('issue_date', 'created_at', 'id'):
        prefix = prefix_map.get(document.document_type, 'DOC')
        deal_code = document.manager_deal.code if document.manager_deal_id else ''
        if document.number:
            number = document.number
        elif deal_code:
            number = next_child_code(prefix, deal_code, child_counters)
        else:
            number = next_root_code(prefix, year_of(document.issue_date), root_counters)
        counterparty_name = (
            document.counterparty_name
            or (document.manager_client.name if document.manager_client_id else '')
            or (document.counterparty_data or {}).get('name', '')
        )
        title = document.title or join_title(document.get_document_type_display(), counterparty_name or 'Без контрагента', deal_code)
        short_label = document.short_label or ' / '.join(
            part for part in [document.get_document_type_display(), counterparty_name or 'Без контрагента'] if part
        )
        update_instance(document, number=number, title=title, short_label=short_label)


class Migration(migrations.Migration):

    dependencies = [
        ('manager_portal', '0010_cargo_short_label_cargo_title_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_identity_fields, migrations.RunPython.noop),
    ]
