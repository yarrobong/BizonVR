from decimal import Decimal
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    ExpressionWrapper,
    F,
    IntegerField,
    Max,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.urls import reverse

from catalog.models import ProductStock
from manager_portal.models import (
    Cargo,
    CargoItem,
    InventoryBalance,
    InventoryLot,
    InventoryMovement,
    ManagerDeal,
    Reservation,
    ReservationItem,
    Warehouse,
)
from manager_portal.services import rebuild_inventory_balance_cache, receipt_inventory, sync_public_stock_for_warehouse

from .models import WarehouseTransfer, WarehouseTransferLine


ACTIVE_RESERVATION_STATUSES = {
    Reservation.STATUS_DRAFT,
    Reservation.STATUS_ACTIVE,
    Reservation.STATUS_PARTIAL,
}
INBOUND_CARGO_STATUSES = {
    Cargo.STATUS_IN_TRANSIT,
    Cargo.STATUS_ARRIVED_RF,
    Cargo.STATUS_DELIVERY_RF,
    Cargo.STATUS_AWAITING_RECEIPT,
}
SKU_PAGE_SIZE = 25


def build_sku_key(product_id, variant_id=None):
    return f'{int(product_id)}:{int(variant_id or 0)}'


def parse_sku_key(value):
    try:
        product_id_raw, variant_id_raw = str(value).split(':', 1)
        product_id = int(product_id_raw)
        variant_id = int(variant_id_raw)
    except (TypeError, ValueError):
        raise ValidationError('Некорректный SKU ключ.')
    return product_id, (variant_id or None)


def _warehouse_scope(cleaned_data):
    queryset = Warehouse.objects.filter(is_active=True).select_related('pickup_point__city').order_by('name')
    city = cleaned_data.get('city')
    selected = cleaned_data.get('warehouses')
    if city:
        queryset = queryset.filter(pickup_point__city=city)
    if selected:
        queryset = queryset.filter(pk__in=selected.values_list('pk', flat=True))
    return list(queryset)


def _available_expr(prefix=''):
    return ExpressionWrapper(
        F(f'{prefix}quantity') - F(f'{prefix}fulfilled_quantity') - F(f'{prefix}released_quantity'),
        output_field=IntegerField(),
    )


def _remaining_expr(prefix=''):
    return ExpressionWrapper(
        F(f'{prefix}quantity') - F(f'{prefix}received_quantity'),
        output_field=IntegerField(),
    )


def _empty_cell(warehouse):
    return {
        'warehouse': warehouse,
        'on_hand': 0,
        'reserved': 0,
        'available': 0,
        'inbound': 0,
        'inbound_reserved': 0,
        'inbound_available': 0,
        'min_stock': 0,
        'public_published_qty': None,
        'public_expected_qty': 0,
        'public_mismatch': False,
    }


def _ensure_row_meta(row_map, row):
    sku_key = build_sku_key(row['product_id'], row.get('variant_id'))
    meta = row_map.setdefault(
        sku_key,
        {
            'sku_key': sku_key,
            'product_id': row['product_id'],
            'variant_id': row.get('variant_id'),
            'product_name': row.get('product__name') or '',
            'product_slug': row.get('product__slug') or '',
            'variant_name': row.get('variant__name') or '',
            'sku': row.get('variant__sku') or row.get('product__sku') or '',
            'totals': {
                'on_hand': 0,
                'reserved': 0,
                'available': 0,
                'inbound': 0,
                'inbound_reserved': 0,
                'inbound_available': 0,
                'min_stock': 0,
                'public_mismatch_count': 0,
            },
        },
    )
    if not meta['product_name'] and row.get('product__name'):
        meta['product_name'] = row['product__name']
    if not meta['product_slug'] and row.get('product__slug'):
        meta['product_slug'] = row['product__slug']
    if not meta['variant_name'] and row.get('variant__name'):
        meta['variant_name'] = row['variant__name']
    if not meta['sku'] and (row.get('variant__sku') or row.get('product__sku')):
        meta['sku'] = row.get('variant__sku') or row.get('product__sku') or ''
    return meta


def _build_aggregate_payload(warehouses):
    warehouse_ids = [warehouse.pk for warehouse in warehouses]
    row_map = {}
    cell_map = {}

    def ensure_cell(sku_key, warehouse_id):
        key = (sku_key, warehouse_id)
        if key not in cell_map:
            warehouse = next(item for item in warehouses if item.pk == warehouse_id)
            cell_map[key] = _empty_cell(warehouse)
        return cell_map[key]

    balance_rows = list(
        InventoryBalance.objects.filter(warehouse_id__in=warehouse_ids)
        .values(
            'warehouse_id',
            'product_id',
            'variant_id',
            'product__name',
            'product__slug',
            'product__sku',
            'variant__name',
            'variant__sku',
        )
        .annotate(on_hand=Coalesce(Sum('quantity'), Value(0)), min_stock=Coalesce(Max('min_stock'), Value(0)))
    )
    for row in balance_rows:
        meta = _ensure_row_meta(row_map, row)
        cell = ensure_cell(meta['sku_key'], row['warehouse_id'])
        cell['on_hand'] = int(row['on_hand'] or 0)
        cell['min_stock'] = int(row['min_stock'] or 0)

    reserve_rows = list(
        ReservationItem.objects.filter(
            reservation__status__in=ACTIVE_RESERVATION_STATUSES,
            reservation__source_type=Reservation.SOURCE_WAREHOUSE,
            reservation__source_warehouse_id__in=warehouse_ids,
        )
        .values(
            'reservation__source_warehouse_id',
            'product_id',
            'variant_id',
            'product__name',
            'product__slug',
            'product__sku',
            'variant__name',
            'variant__sku',
        )
        .annotate(reserved=Coalesce(Sum(_available_expr()), Value(0)))
    )
    for row in reserve_rows:
        row['warehouse_id'] = row.pop('reservation__source_warehouse_id')
        meta = _ensure_row_meta(row_map, row)
        cell = ensure_cell(meta['sku_key'], row['warehouse_id'])
        cell['reserved'] = int(row['reserved'] or 0)

    inbound_rows = list(
        CargoItem.objects.filter(
            cargo__status__in=INBOUND_CARGO_STATUSES,
            cargo__destination_warehouse_id__in=warehouse_ids,
        )
        .values(
            'cargo__destination_warehouse_id',
            'product_id',
            'variant_id',
            'product__name',
            'product__slug',
            'product__sku',
            'variant__name',
            'variant__sku',
        )
        .annotate(inbound=Coalesce(Sum(_remaining_expr()), Value(0)))
    )
    for row in inbound_rows:
        row['warehouse_id'] = row.pop('cargo__destination_warehouse_id')
        meta = _ensure_row_meta(row_map, row)
        cell = ensure_cell(meta['sku_key'], row['warehouse_id'])
        cell['inbound'] = int(row['inbound'] or 0)

    inbound_reserved_rows = list(
        ReservationItem.objects.filter(
            reservation__status__in=ACTIVE_RESERVATION_STATUSES,
            reservation__source_type=Reservation.SOURCE_CARGO,
            reservation__source_cargo__destination_warehouse_id__in=warehouse_ids,
        )
        .values(
            'reservation__source_cargo__destination_warehouse_id',
            'product_id',
            'variant_id',
            'product__name',
            'product__slug',
            'product__sku',
            'variant__name',
            'variant__sku',
        )
        .annotate(reserved=Coalesce(Sum(_available_expr()), Value(0)))
    )
    for row in inbound_reserved_rows:
        row['warehouse_id'] = row.pop('reservation__source_cargo__destination_warehouse_id')
        meta = _ensure_row_meta(row_map, row)
        cell = ensure_cell(meta['sku_key'], row['warehouse_id'])
        cell['inbound_reserved'] = int(row['reserved'] or 0)

    public_stock_rows = list(
        ProductStock.objects.filter(
            pickup_point_id__in=[warehouse.pickup_point_id for warehouse in warehouses if warehouse.pickup_point_id],
        )
        .values('pickup_point_id', 'product_id', 'variant_id')
        .annotate(quantity=Coalesce(Sum('quantity'), Value(0)))
    )
    public_stock_map = {
        (row['pickup_point_id'], row['product_id'], row['variant_id'] or None): int(row['quantity'] or 0)
        for row in public_stock_rows
    }

    for sku_key, meta in row_map.items():
        totals = meta['totals']
        for warehouse in warehouses:
            cell = cell_map.setdefault((sku_key, warehouse.pk), _empty_cell(warehouse))
            cell['available'] = cell['on_hand'] - cell['reserved']
            cell['inbound_available'] = cell['inbound'] - cell['inbound_reserved']
            if warehouse.pickup_point_id:
                cell['public_published_qty'] = public_stock_map.get(
                    (warehouse.pickup_point_id, meta['product_id'], meta['variant_id']),
                    0,
                )
                cell['public_expected_qty'] = max(cell['available'], 0)
                cell['public_mismatch'] = cell['public_published_qty'] != cell['public_expected_qty']
            totals['on_hand'] += cell['on_hand']
            totals['reserved'] += cell['reserved'] + cell['inbound_reserved']
            totals['available'] += cell['available']
            totals['inbound'] += cell['inbound']
            totals['inbound_reserved'] += cell['inbound_reserved']
            totals['inbound_available'] += cell['inbound_available']
            totals['min_stock'] += cell['min_stock']
            if cell['public_mismatch']:
                totals['public_mismatch_count'] += 1

    return row_map, cell_map


def _filter_rows(row_map, cleaned_data):
    search = (cleaned_data.get('q') or '').strip().lower()
    in_stock = bool(cleaned_data.get('in_stock'))
    out_of_stock = bool(cleaned_data.get('out_of_stock'))
    has_reserve = bool(cleaned_data.get('has_reserve'))
    inbound = bool(cleaned_data.get('inbound'))
    rows = []
    for row in row_map.values():
        haystack = ' '.join(
            [
                row['product_name'],
                row['variant_name'],
                row['sku'],
            ]
        ).lower()
        totals = row['totals']
        if search and search not in haystack:
            continue
        if in_stock and totals['available'] <= 0:
            continue
        if out_of_stock and totals['available'] > 0:
            continue
        if has_reserve and totals['reserved'] <= 0:
            continue
        if inbound and totals['inbound_available'] <= 0 and totals['inbound'] <= 0:
            continue
        row['is_low_stock'] = totals['available'] <= 0 or (totals['min_stock'] > 0 and totals['available'] < totals['min_stock'])
        row['has_problem'] = row['is_low_stock'] or totals['public_mismatch_count'] > 0
        rows.append(row)
    rows.sort(
        key=lambda item: (
            0 if item['has_problem'] else 1,
            item['totals']['available'],
            item['product_name'].lower(),
            item['variant_name'].lower(),
        )
    )
    return rows


def build_matrix_context(cleaned_data, *, page_number=1):
    warehouses = _warehouse_scope(cleaned_data)
    row_map, cell_map = _build_aggregate_payload(warehouses)
    filtered_rows = _filter_rows(row_map, cleaned_data)
    paginator = Paginator(filtered_rows, SKU_PAGE_SIZE)
    page = paginator.get_page(page_number or 1)
    rendered_rows = []
    for row in page.object_list:
        row_cells = [cell_map[(row['sku_key'], warehouse.pk)] for warehouse in warehouses]
        rendered_rows.append(
            {
                **row,
                'cells': row_cells,
                'drawer_url': reverse('admin:warehouse_ui_drawer', args=[row['sku_key']]),
            }
        )

    low_or_zero_count = sum(1 for row in filtered_rows if row['is_low_stock'])
    mismatch_count = sum(1 for row in filtered_rows if row['totals']['public_mismatch_count'] > 0)
    summary = {
        'cards': [
            {'label': 'Всего в наличии', 'value': sum(row['totals']['on_hand'] for row in filtered_rows)},
            {'label': 'Доступно к продаже', 'value': sum(row['totals']['available'] for row in filtered_rows)},
            {'label': 'В резерве', 'value': sum(row['totals']['reserved'] for row in filtered_rows)},
            {'label': 'В пути', 'value': sum(row['totals']['inbound'] for row in filtered_rows)},
            {'label': 'Низкий / нулевой остаток', 'value': low_or_zero_count},
            {'label': 'Расхождения', 'value': mismatch_count},
        ],
    }
    return {
        'summary': summary,
        'page': page,
        'warehouses': warehouses,
        'rows': rendered_rows,
        'page_query': urlencode({'page': page.number}),
    }


def image_url_for_sku(*, product, variant=None):
    image = variant.image if variant and getattr(variant, 'image', None) else product.get_display_image()
    if not image:
        return ''
    try:
        return image.url
    except Exception:
        return ''


def build_drawer_context(sku_key, cleaned_data=None):
    product_id, variant_id = parse_sku_key(sku_key)
    warehouses = _warehouse_scope(cleaned_data or {})
    if not warehouses:
        warehouses = list(Warehouse.objects.filter(is_active=True).select_related('pickup_point__city').order_by('name'))

    row_map, cell_map = _build_aggregate_payload(warehouses)
    base_row = row_map.get(sku_key)
    if base_row is None:
        raise ValidationError('Позиция не найдена.')

    balance_lookup = InventoryBalance.objects.select_related('product', 'variant').filter(product_id=product_id)
    if variant_id:
        balance_lookup = balance_lookup.filter(variant_id=variant_id)
    else:
        balance_lookup = balance_lookup.filter(variant__isnull=True)
    first_balance = balance_lookup.first()
    if not first_balance:
        raise ValidationError('Позиция не найдена.')

    product = first_balance.product
    variant = first_balance.variant
    row = {**base_row, 'cells': [cell_map[(sku_key, warehouse.pk)] for warehouse in warehouses]}

    if variant_id:
        movement_qs = InventoryMovement.objects.filter(product_id=product_id, variant_id=variant_id)
    else:
        movement_qs = InventoryMovement.objects.filter(product_id=product_id, variant__isnull=True)
    movements = list(
        movement_qs.select_related('warehouse', 'author').order_by('-created_at', '-id')[:20]
    )

    reservations_qs = ReservationItem.objects.filter(
        reservation__status__in=ACTIVE_RESERVATION_STATUSES,
        product_id=product_id,
    )
    reservations_qs = reservations_qs.filter(variant_id=variant_id) if variant_id else reservations_qs.filter(variant__isnull=True)
    reservations = list(
        reservations_qs.select_related(
            'reservation',
            'reservation__client',
            'reservation__manager_deal',
            'reservation__source_warehouse',
            'reservation__source_cargo__destination_warehouse',
            'order_item__order',
        ).order_by('-reservation__created_at')[:10]
    )

    cargo_items_qs = CargoItem.objects.filter(
        cargo__status__in=INBOUND_CARGO_STATUSES,
        product_id=product_id,
    )
    cargo_items_qs = cargo_items_qs.filter(variant_id=variant_id) if variant_id else cargo_items_qs.filter(variant__isnull=True)
    cargo_items = list(
        cargo_items_qs.select_related(
            'cargo',
            'cargo__destination_warehouse',
            'purchase_item__purchase',
            'purchase_item__order_item__order',
        ).order_by('cargo__eta', '-cargo__created_at')[:10]
    )

    linked_deals = list(
        ManagerDeal.objects.filter(
            Q(order__items__product_id=product_id, order__items__variant_id=variant_id)
            if variant_id
            else Q(order__items__product_id=product_id, order__items__variant__isnull=True)
        )
        .select_related('order', 'stock_warehouse')
        .distinct()
        .order_by('-deal_created_at')[:10]
    )

    warehouse_choices = Warehouse.objects.filter(is_active=True).order_by('name')
    default_warehouse = next((cell['warehouse'] for cell in row['cells'] if cell['on_hand'] or cell['inbound']), None)
    default_target = next((item for item in warehouse_choices if not default_warehouse or item.pk != default_warehouse.pk), None)
    return {
        'sku_key': sku_key,
        'product': product,
        'variant': variant,
        'image_url': image_url_for_sku(product=product, variant=variant),
        'row': row,
        'movements': movements,
        'reservations': reservations,
        'cargo_items': cargo_items,
        'linked_deals': linked_deals,
        'receipt_form': {
            'sku_key': sku_key,
            'product': product,
            'variant': variant,
            'warehouse': default_warehouse,
        },
        'adjustment_form': {
            'sku_key': sku_key,
            'product': product,
            'variant': variant,
            'warehouse': default_warehouse,
        },
        'transfer_form': {
            'sku_key': sku_key,
            'product': product,
            'variant': variant,
            'source_warehouse': default_warehouse,
            'target_warehouse': default_target,
        },
        'history_url': reverse('admin:warehouse_ui_history', args=[sku_key]),
    }


def build_history_context(sku_key):
    product_id, variant_id = parse_sku_key(sku_key)
    movement_qs = InventoryMovement.objects.filter(product_id=product_id)
    movement_qs = movement_qs.filter(variant_id=variant_id) if variant_id else movement_qs.filter(variant__isnull=True)
    return {
        'movements': list(
            movement_qs.select_related('warehouse', 'author').order_by('-created_at', '-id')[:50]
        ),
        'sku_key': sku_key,
    }


def create_receipt(*, warehouse, product, variant, quantity, unit_cost, author=None, comment=''):
    return receipt_inventory(
        warehouse=warehouse,
        product=product,
        variant=variant,
        quantity=quantity,
        unit_cost=unit_cost or Decimal('0'),
        author=author,
        comment=comment,
        reference_type='warehouse_ui_receipt',
    )


def _lock_matching_lots(*, warehouse, product, variant):
    lot_qs = InventoryLot.objects.select_for_update().filter(warehouse=warehouse, product=product)
    lot_qs = lot_qs.filter(variant=variant) if variant else lot_qs.filter(variant__isnull=True)
    return list(lot_qs.filter(remaining_qty__gt=0).order_by('received_at', 'id'))


def _consume_inventory_fifo(*, warehouse, product, variant, quantity):
    lots = _lock_matching_lots(warehouse=warehouse, product=product, variant=variant)
    remaining = int(quantity)
    consumed = []
    for lot in lots:
        if remaining <= 0:
            break
        available = int(lot.remaining_qty or 0)
        if available <= 0:
            continue
        taken = min(available, remaining)
        lot.remaining_qty = available - taken
        lot.save(update_fields=['remaining_qty', 'updated_at'])
        consumed.append({'lot': lot, 'quantity': taken, 'unit_cost': Decimal(lot.unit_cost_final or lot.unit_cost or 0)})
        remaining -= taken
    if remaining > 0:
        raise ValidationError(f'Недостаточно остатка для операции. Не хватает {remaining} шт.')
    return consumed


def create_adjustment(*, warehouse, product, variant, quantity_delta, author=None, comment=''):
    quantity_delta = int(quantity_delta)
    if quantity_delta == 0:
        raise ValidationError('Изменение не должно быть нулевым.')
    with transaction.atomic():
        if quantity_delta > 0:
            InventoryLot.objects.create(
                warehouse=warehouse,
                product=product,
                variant=variant,
                received_qty=quantity_delta,
                remaining_qty=quantity_delta,
                unit_cost=Decimal('0'),
                unit_cost_base=Decimal('0'),
                unit_cost_final=Decimal('0'),
                reference_type='warehouse_adjustment',
            )
        else:
            _consume_inventory_fifo(
                warehouse=warehouse,
                product=product,
                variant=variant,
                quantity=abs(quantity_delta),
            )
        InventoryMovement.objects.create(
            warehouse=warehouse,
            product=product,
            variant=variant,
            movement_type=InventoryMovement.TYPE_ADJUSTMENT,
            quantity=abs(quantity_delta),
            reference_type='warehouse_adjustment',
            comment=comment,
            author=author,
        )
        rebuild_inventory_balance_cache(warehouse_ids=[warehouse.id])
        sync_public_stock_for_warehouse(warehouse)


def create_transfer(*, source_warehouse, target_warehouse, product, variant, quantity, author=None, comment=''):
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError('Количество должно быть больше нуля.')
    if source_warehouse.pk == target_warehouse.pk:
        raise ValidationError('Склад назначения должен отличаться от склада-источника.')
    with transaction.atomic():
        consumed = _consume_inventory_fifo(
            warehouse=source_warehouse,
            product=product,
            variant=variant,
            quantity=quantity,
        )
        transfer = WarehouseTransfer.objects.create(
            source_warehouse=source_warehouse,
            target_warehouse=target_warehouse,
            comment=comment,
            created_by=author,
        )
        for chunk in consumed:
            target_lot = InventoryLot.objects.create(
                warehouse=target_warehouse,
                product=product,
                variant=variant,
                received_qty=chunk['quantity'],
                remaining_qty=chunk['quantity'],
                unit_cost=chunk['unit_cost'],
                unit_cost_base=chunk['unit_cost'],
                unit_cost_final=chunk['unit_cost'],
                reference_type='warehouse_transfer',
                reference_id=transfer.id,
            )
            WarehouseTransferLine.objects.create(
                transfer=transfer,
                product=product,
                variant=variant,
                source_lot=chunk['lot'],
                target_lot=target_lot,
                quantity=chunk['quantity'],
                unit_cost=chunk['unit_cost'],
            )
        InventoryMovement.objects.create(
            warehouse=source_warehouse,
            product=product,
            variant=variant,
            movement_type=InventoryMovement.TYPE_TRANSFER_OUT,
            quantity=quantity,
            reference_type='warehouse_transfer',
            reference_id=transfer.id,
            comment=comment,
            author=author,
        )
        InventoryMovement.objects.create(
            warehouse=target_warehouse,
            product=product,
            variant=variant,
            movement_type=InventoryMovement.TYPE_TRANSFER_IN,
            quantity=quantity,
            reference_type='warehouse_transfer',
            reference_id=transfer.id,
            comment=comment,
            author=author,
        )
        rebuild_inventory_balance_cache(warehouse_ids=[source_warehouse.id, target_warehouse.id])
        sync_public_stock_for_warehouse(source_warehouse)
        sync_public_stock_for_warehouse(target_warehouse)
        return transfer
