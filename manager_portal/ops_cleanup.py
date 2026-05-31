from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from django.db import transaction
from django.db.models import Q

from manager_portal.models import (
    Cargo,
    CargoItem,
    DealActivity,
    FinanceDeal,
    FinanceDealLine,
    InventoryBalance,
    InventoryLot,
    InventoryMovement,
    ManagerClient,
    ManagerDeal,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    SaleLineAllocation,
    Shipment,
    ShipmentItem,
    Warehouse,
)
from manager_portal.services import rebuild_inventory_balance_cache, sync_public_stock_for_warehouse
from orders.models import Order


@dataclass(frozen=True)
class CleanupWarning:
    code: str
    message: str
    blocking: bool = True


@dataclass
class DealCleanupPlan:
    bitrix_deal_id: str
    deal: ManagerDeal | None = None
    order: Order | None = None
    order_items: list = field(default_factory=list)
    purchase_items: list = field(default_factory=list)
    purchases: list = field(default_factory=list)
    cargo_items: list = field(default_factory=list)
    cargos: list = field(default_factory=list)
    reservation_items: list = field(default_factory=list)
    reservations: list = field(default_factory=list)
    shipment_items: list = field(default_factory=list)
    shipments: list = field(default_factory=list)
    activities: list = field(default_factory=list)
    finance_deals: list = field(default_factory=list)
    finance_lines: list = field(default_factory=list)
    inventory_movements: list = field(default_factory=list)
    inventory_lots: list = field(default_factory=list)
    sale_line_allocations: list = field(default_factory=list)
    balances: list = field(default_factory=list)
    manager_clients: list = field(default_factory=list)
    deletable_purchase_ids: set[int] = field(default_factory=set)
    deletable_cargo_ids: set[int] = field(default_factory=set)
    deletable_manager_client_ids: set[int] = field(default_factory=set)
    restorable_external_lot_ids: set[int] = field(default_factory=set)
    touched_warehouse_ids: set[int] = field(default_factory=set)
    warnings: list[CleanupWarning] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def exists(self) -> bool:
        return self.deal is not None

    @property
    def has_blocking_warnings(self) -> bool:
        return any(warning.blocking for warning in self.warnings)


def _unique_by_id(objects: Iterable) -> list:
    unique = {}
    for obj in objects:
        unique[obj.pk] = obj
    return list(unique.values())


def _variant_key(variant_id):
    return variant_id or 0


def _cargo_item_key(cargo_id, product_id, variant_id):
    return cargo_id, product_id, _variant_key(variant_id)


def build_cleanup_plan(bitrix_deal_id) -> DealCleanupPlan:
    normalized_deal_id = str(bitrix_deal_id).strip()
    plan = DealCleanupPlan(bitrix_deal_id=normalized_deal_id)
    deal = ManagerDeal.objects.select_related('order').filter(bitrix_deal_id=normalized_deal_id).first()
    if deal is None:
        return plan

    plan.deal = deal
    plan.order = deal.order
    order = deal.order

    plan.order_items = list(order.items.select_related('product', 'variant').order_by('id'))
    order_item_ids = [item.id for item in plan.order_items]

    plan.purchase_items = list(
        PurchaseItem.objects.select_related('purchase', 'product', 'variant', 'order_item')
        .filter(order_item_id__in=order_item_ids)
        .order_by('id')
    )
    purchase_item_ids = [item.id for item in plan.purchase_items]
    purchase_ids = sorted({item.purchase_id for item in plan.purchase_items if item.purchase_id})
    plan.purchases = list(Purchase.objects.filter(id__in=purchase_ids).order_by('id'))

    plan.cargo_items = list(
        CargoItem.objects.select_related('cargo', 'purchase_item', 'product', 'variant')
        .filter(purchase_item_id__in=purchase_item_ids)
        .order_by('id')
    )
    cargo_item_ids = [item.id for item in plan.cargo_items]
    cargo_ids = sorted({item.cargo_id for item in plan.cargo_items if item.cargo_id})
    plan.cargos = list(Cargo.objects.filter(id__in=cargo_ids).order_by('id'))

    plan.reservations = list(
        Reservation.objects.select_related(
            'client',
            'source_warehouse',
            'source_cargo',
            'target_warehouse',
            'linked_order',
        )
        .filter(Q(manager_deal=deal) | Q(linked_order=order))
        .distinct()
        .order_by('id')
    )
    reservation_ids = [reservation.id for reservation in plan.reservations]

    plan.reservation_items = list(
        ReservationItem.objects.select_related('reservation', 'order_item', 'product', 'variant')
        .filter(Q(reservation_id__in=reservation_ids) | Q(order_item_id__in=order_item_ids))
        .distinct()
        .order_by('id')
    )
    reservation_item_ids = [item.id for item in plan.reservation_items]

    plan.shipments = list(
        Shipment.objects.select_related(
            'manager_deal',
            'order',
            'reservation',
            'client',
            'source_warehouse',
            'target_warehouse',
        )
        .filter(Q(manager_deal=deal) | Q(order=order) | Q(reservation_id__in=reservation_ids))
        .distinct()
        .order_by('id')
    )
    shipment_ids = [shipment.id for shipment in plan.shipments]

    plan.shipment_items = list(
        ShipmentItem.objects.select_related('shipment', 'order_item', 'reservation_item', 'product', 'variant')
        .filter(
            Q(shipment_id__in=shipment_ids)
            | Q(order_item_id__in=order_item_ids)
            | Q(reservation_item_id__in=reservation_item_ids)
        )
        .distinct()
        .order_by('id')
    )

    plan.activities = list(DealActivity.objects.filter(manager_deal=deal).order_by('id'))
    plan.finance_deals = list(FinanceDeal.objects.filter(manager_deal=deal).order_by('id'))
    finance_deal_ids = [finance_deal.id for finance_deal in plan.finance_deals]
    plan.finance_lines = list(
        FinanceDealLine.objects.filter(
            Q(finance_deal_id__in=finance_deal_ids) | Q(order_item_id__in=order_item_ids)
        )
        .distinct()
        .order_by('id')
    )

    cargo_keys = {
        _cargo_item_key(item.cargo_id, item.product_id, item.variant_id)
        for item in plan.cargo_items
        if item.cargo_id and item.product_id
    }
    cargo_lot_candidates = list(
        InventoryLot.objects.select_related('warehouse', 'product', 'variant', 'purchase_item')
        .filter(reference_type='cargo', reference_id__in=cargo_ids)
        .order_by('id')
    )
    inventory_lots = [
        lot
        for lot in cargo_lot_candidates
        if _cargo_item_key(lot.reference_id, lot.product_id, lot.variant_id) in cargo_keys
    ]
    purchase_lots = list(
        InventoryLot.objects.select_related('warehouse', 'product', 'variant', 'purchase_item')
        .filter(purchase_item_id__in=purchase_item_ids)
        .order_by('id')
    )
    plan.inventory_lots = _unique_by_id([*inventory_lots, *purchase_lots])
    lot_ids = [lot.id for lot in plan.inventory_lots]

    plan.sale_line_allocations = list(
        SaleLineAllocation.objects.select_related('order_item', 'inventory_lot')
        .filter(Q(order_item_id__in=order_item_ids) | Q(inventory_lot_id__in=lot_ids))
        .distinct()
        .order_by('id')
    )

    movement_candidates = list(
        InventoryMovement.objects.select_related('warehouse', 'product', 'variant')
        .filter(
            Q(reference_type='shipment', reference_id__in=shipment_ids)
            | Q(reference_type='reservation', reference_id__in=reservation_ids)
            | Q(reference_type='cargo', reference_id__in=cargo_ids)
        )
        .order_by('id')
    )
    plan.inventory_movements = [
        movement
        for movement in movement_candidates
        if movement.reference_type != 'cargo'
        or _cargo_item_key(movement.reference_id, movement.product_id, movement.variant_id) in cargo_keys
    ]

    balance_keys = set()
    for lot in plan.inventory_lots:
        plan.touched_warehouse_ids.add(lot.warehouse_id)
        balance_keys.add((lot.warehouse_id, lot.product_id, lot.variant_id))
    for movement in plan.inventory_movements:
        plan.touched_warehouse_ids.add(movement.warehouse_id)
        balance_keys.add((movement.warehouse_id, movement.product_id, movement.variant_id))

    plan.balances = [
        InventoryBalance.objects.filter(
            warehouse_id=warehouse_id,
            product_id=product_id,
            variant_id=variant_id,
        ).first()
        for warehouse_id, product_id, variant_id in sorted(balance_keys)
    ]
    plan.balances = [balance for balance in plan.balances if balance is not None]

    client_ids = set(ManagerClient.objects.filter(orders=order).values_list('id', flat=True))
    client_ids.update(reservation.client_id for reservation in plan.reservations if reservation.client_id)
    client_ids.update(shipment.client_id for shipment in plan.shipments if shipment.client_id)
    plan.manager_clients = list(ManagerClient.objects.filter(id__in=client_ids).distinct().order_by('id'))

    _collect_plan_warnings(
        plan=plan,
        order_item_ids=order_item_ids,
        purchase_item_ids=purchase_item_ids,
        cargo_item_ids=cargo_item_ids,
        reservation_ids=reservation_ids,
        cargo_keys=cargo_keys,
        lot_ids=lot_ids,
    )
    _populate_deletion_sets(
        plan=plan,
        order=order,
        cargo_item_ids=cargo_item_ids,
        purchase_item_ids=purchase_item_ids,
        reservation_ids=reservation_ids,
        shipment_ids=shipment_ids,
    )
    return plan


def _collect_plan_warnings(
    *,
    plan: DealCleanupPlan,
    order_item_ids: list[int],
    purchase_item_ids: list[int],
    cargo_item_ids: list[int],
    reservation_ids: list[int],
    cargo_keys: set[tuple[int, int, int]],
    lot_ids: list[int],
):
    for cargo in plan.cargos:
        target_items = [item for item in plan.cargo_items if item.cargo_id == cargo.id]
        target_keys = {_cargo_item_key(item.cargo_id, item.product_id, item.variant_id) for item in target_items}
        foreign_items = list(cargo.items.exclude(id__in=cargo_item_ids).values('product_id', 'variant_id'))
        for row in foreign_items:
            candidate_key = _cargo_item_key(cargo.id, row['product_id'], row['variant_id'])
            if candidate_key in target_keys:
                plan.warnings.append(
                    CleanupWarning(
                        code='shared_cargo_product',
                        message=(
                            f'Груз {cargo.cargo_number} содержит целевую и чужую позицию '
                            'с одинаковыми product/variant. Нельзя безопасно отделить receipt movement.'
                        ),
                    )
                )
                break

    foreign_allocations = list(
        SaleLineAllocation.objects.select_related('inventory_lot', 'order_item')
        .filter(inventory_lot_id__in=lot_ids)
        .exclude(order_item_id__in=order_item_ids)
        .order_by('id')
    )
    if foreign_allocations:
        details = ', '.join(
            f'alloc#{allocation.id}->order_item#{allocation.order_item_id}'
            for allocation in foreign_allocations[:5]
        )
        plan.warnings.append(
            CleanupWarning(
                code='shared_inventory_lot',
                message=(
                    'Лоты этой сделки уже используются другими строками заказа '
                    f'({details}). Cleanup автоматически остановлен.'
                ),
            )
        )

    for lot in plan.inventory_lots:
        if lot.reference_type and lot.reference_type != 'cargo':
            plan.warnings.append(
                CleanupWarning(
                    code='non_cargo_lot_reference',
                    message=(
                        f'Лот #{lot.id} создан с reference_type={lot.reference_type!r}. '
                        'Лот будет удалён по purchase_item, но движение склада без прямой связи не удаляется автоматически.'
                    ),
                    blocking=False,
                )
            )

    unmanaged_movements = list(
        InventoryMovement.objects.filter(
            warehouse_id__in=plan.touched_warehouse_ids,
            product_id__in={item.product_id for item in plan.cargo_items if item.product_id},
        )
        .exclude(id__in=[movement.id for movement in plan.inventory_movements])
        .exclude(
            Q(reference_type='reservation', reference_id__in=reservation_ids)
            | Q(reference_type='cargo', reference_id__in=[cargo.id for cargo in plan.cargos])
            | Q(reference_type='shipment', reference_id__in=[shipment.id for shipment in plan.shipments])
        )
        .order_by('id')[:10]
    )
    if unmanaged_movements:
        preview = ', '.join(
            f'mv#{movement.id}:{movement.reference_type or "manual"}'
            for movement in unmanaged_movements
        )
        plan.notes.append(
            'Есть другие движения по затронутым товарам/складам вне cleanup scope: '
            f'{preview}. Они не будут тронуты.'
        )


def _populate_deletion_sets(
    *,
    plan: DealCleanupPlan,
    order: Order,
    cargo_item_ids: list[int],
    purchase_item_ids: list[int],
    reservation_ids: list[int],
    shipment_ids: list[int],
):
    lot_ids = {lot.id for lot in plan.inventory_lots}
    for allocation in plan.sale_line_allocations:
        if (
            allocation.status == SaleLineAllocation.STATUS_SHIPPED
            and allocation.shipped_qty > 0
            and allocation.inventory_lot_id not in lot_ids
        ):
            plan.restorable_external_lot_ids.add(allocation.inventory_lot_id)
            if allocation.inventory_lot_id:
                plan.touched_warehouse_ids.add(allocation.inventory_lot.warehouse_id)

    for cargo in plan.cargos:
        has_foreign_items = cargo.items.exclude(id__in=cargo_item_ids).exists()
        has_foreign_reservations = cargo.cargo_reservations.exclude(id__in=reservation_ids).exists()
        if not has_foreign_items and not has_foreign_reservations:
            plan.deletable_cargo_ids.add(cargo.id)
        else:
            plan.notes.append(
                f'Груз {cargo.cargo_number} не будет удалён целиком: у него есть связи вне этой сделки.'
            )

    for purchase in plan.purchases:
        has_foreign_items = purchase.items.exclude(id__in=purchase_item_ids).exists()
        has_foreign_cargos = purchase.cargos.exclude(id__in=plan.deletable_cargo_ids).exists()
        if not has_foreign_items and not has_foreign_cargos:
            plan.deletable_purchase_ids.add(purchase.id)
        else:
            plan.notes.append(
                f'Закупка {purchase.code or purchase.id} не будет удалена целиком: у неё есть связи вне этой сделки.'
            )

    for client in plan.manager_clients:
        if client.orders.exclude(pk=order.pk).exists():
            continue
        if client.reservations.exclude(id__in=reservation_ids).exists():
            continue
        if client.shipments.exclude(id__in=shipment_ids).exists():
            continue
        if client.contract_documents.exists():
            plan.notes.append(
                f'Клиент #{client.id} не будет удалён автоматически: на нём висят contract documents.'
            )
            continue
        plan.deletable_manager_client_ids.add(client.id)


def execute_cleanup_plan(plan: DealCleanupPlan) -> dict:
    if not plan.exists:
        return {'status': 'not_found', 'bitrix_deal_id': plan.bitrix_deal_id}
    if plan.has_blocking_warnings:
        raise ValueError('Cleanup stopped because the plan contains blocking warnings.')

    shipment_ids = [shipment.id for shipment in plan.shipments]
    reservation_ids = [reservation.id for reservation in plan.reservations]
    cargo_ids = [cargo.id for cargo in plan.cargos]
    purchase_ids = [purchase.id for purchase in plan.purchases]
    order_item_ids = [item.id for item in plan.order_items]
    client_ids = [client.id for client in plan.manager_clients]
    lot_ids = [lot.id for lot in plan.inventory_lots]
    allocation_ids = [allocation.id for allocation in plan.sale_line_allocations]
    movement_ids = [movement.id for movement in plan.inventory_movements]
    finance_line_ids = [line.id for line in plan.finance_lines]
    finance_deal_ids = [finance_deal.id for finance_deal in plan.finance_deals]
    activity_ids = [activity.id for activity in plan.activities]

    with transaction.atomic():
        restored_by_lot = defaultdict(int)
        external_allocations = list(
            SaleLineAllocation.objects.select_related('inventory_lot')
            .filter(id__in=allocation_ids, inventory_lot_id__in=plan.restorable_external_lot_ids)
            .order_by('id')
        )
        for allocation in external_allocations:
            shipped_qty = int(allocation.shipped_qty or 0)
            if shipped_qty <= 0:
                continue
            lot = allocation.inventory_lot
            lot.remaining_qty = int(lot.remaining_qty or 0) + shipped_qty
            lot.save(update_fields=['remaining_qty', 'updated_at'])
            restored_by_lot[lot.id] += shipped_qty

        ShipmentItem.objects.filter(id__in=[item.id for item in plan.shipment_items]).delete()
        Shipment.objects.filter(id__in=shipment_ids).delete()

        ReservationItem.objects.filter(id__in=[item.id for item in plan.reservation_items]).delete()
        Reservation.objects.filter(id__in=reservation_ids).delete()

        SaleLineAllocation.objects.filter(id__in=allocation_ids).delete()
        InventoryMovement.objects.filter(id__in=movement_ids).delete()
        InventoryLot.objects.filter(id__in=lot_ids).delete()

        CargoItem.objects.filter(id__in=[item.id for item in plan.cargo_items]).delete()
        Cargo.objects.filter(id__in=plan.deletable_cargo_ids).delete()

        PurchaseItem.objects.filter(id__in=[item.id for item in plan.purchase_items]).delete()
        Purchase.objects.filter(id__in=plan.deletable_purchase_ids).delete()

        FinanceDealLine.objects.filter(id__in=finance_line_ids).delete()
        FinanceDeal.objects.filter(id__in=finance_deal_ids).delete()
        DealActivity.objects.filter(id__in=activity_ids).delete()

        if plan.deal is not None:
            ManagerDeal.objects.filter(pk=plan.deal.pk).delete()
        if plan.order is not None:
            Order.objects.filter(pk=plan.order.pk).delete()

        for client_id in client_ids:
            if client_id not in plan.deletable_manager_client_ids:
                continue
            client = ManagerClient.objects.filter(pk=client_id).first()
            if client is not None:
                client.delete()

    if plan.touched_warehouse_ids:
        warehouse_ids = sorted(plan.touched_warehouse_ids)
        rebuild_inventory_balance_cache(warehouse_ids=warehouse_ids)
        for warehouse in Warehouse.objects.filter(id__in=warehouse_ids):
            sync_public_stock_for_warehouse(warehouse)

    return {
        'status': 'deleted',
        'bitrix_deal_id': plan.bitrix_deal_id,
        'restored_external_lots': dict(restored_by_lot),
        'deleted': {
            'deal_id': plan.deal.pk if plan.deal else None,
            'order_id': plan.order.pk if plan.order else None,
            'order_items': len(order_item_ids),
            'purchase_items': len(plan.purchase_items),
            'purchases': len(purchase_ids),
            'cargo_items': len(plan.cargo_items),
            'cargos': len(cargo_ids),
            'reservation_items': len(plan.reservation_items),
            'reservations': len(reservation_ids),
            'shipment_items': len(plan.shipment_items),
            'shipments': len(shipment_ids),
            'inventory_lots': len(lot_ids),
            'sale_line_allocations': len(allocation_ids),
            'inventory_movements': len(movement_ids),
            'finance_deals': len(finance_deal_ids),
            'finance_lines': len(finance_line_ids),
            'activities': len(activity_ids),
            'manager_clients': len(plan.deletable_manager_client_ids),
        },
        'retained': {
            'purchases': sorted(set(purchase_ids) - set(plan.deletable_purchase_ids)),
            'cargos': sorted(set(cargo_ids) - set(plan.deletable_cargo_ids)),
            'manager_clients': sorted(set(client_ids) - set(plan.deletable_manager_client_ids)),
        },
        'touched_warehouses': sorted(plan.touched_warehouse_ids),
    }
