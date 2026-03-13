"""
Очистка всех данных менеджерского портала: сделки, клиенты, грузы, закупки, брони, отгрузки.
Использование: python manage.py clear_manager_data [--confirm]
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from manager_portal.models import (
    Cargo,
    ContractDocument,
    DealActivity,
    FinanceDeal,
    FinanceExpense,
    FinancePayout,
    ManagerClient,
    ManagerDeal,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    Shipment,
    ShipmentItem,
    TradeInItem,
)
from orders.models import Order


class Command(BaseCommand):
    help = 'Очистить все сделки, клиентов, грузы, закупки, брони, отгрузки менеджерского портала'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Подтвердить удаление (без этого флага команда только показывает, что будет удалено)',
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            orders = Order.objects.filter(manager_deal__isnull=False)
            order_ids = list(orders.values_list('id', flat=True))
            deal_count = ManagerDeal.objects.count()
            client_count = ManagerClient.objects.count()
            purchase_count = Purchase.objects.count()
            cargo_count = Cargo.objects.count()
            reservation_count = Reservation.objects.count()
            shipment_count = Shipment.objects.count()

        if not options['confirm']:
            self.stdout.write(
                self.style.WARNING(
                    'Будет удалено (без --confirm ничего не удаляется):'
                )
            )
            self.stdout.write(f'  Сделок: {deal_count}')
            self.stdout.write(f'  Заказов: {len(order_ids)}')
            self.stdout.write(f'  Клиентов: {client_count}')
            self.stdout.write(f'  Закупок: {purchase_count}')
            self.stdout.write(f'  Грузов: {cargo_count}')
            self.stdout.write(f'  Броней: {reservation_count}')
            self.stdout.write(f'  Отгрузок: {shipment_count}')
            self.stdout.write('')
            self.stdout.write(
                self.style.NOTICE(
                    'Запустите с --confirm для выполнения: python manage.py clear_manager_data --confirm'
                )
            )
            return

        with transaction.atomic():
            # 1. Отгрузки
            ShipmentItem.objects.all().delete()
            Shipment.objects.all().delete()
            self.stdout.write(f'  Удалено отгрузок: {shipment_count}')

            # 2. Брони
            ReservationItem.objects.all().delete()
            Reservation.objects.all().delete()
            self.stdout.write(f'  Удалено броней: {reservation_count}')

            # 3. Грузы (каскадно: CargoItem, CargoPhoto, TransportLeg, Expense)
            Cargo.objects.all().delete()
            self.stdout.write(f'  Удалено грузов: {cargo_count}')

            # 4. Закупки
            PurchaseItem.objects.all().delete()
            Purchase.objects.all().delete()
            self.stdout.write(f'  Удалено закупок: {purchase_count}')

            # 5. Документы и финансы
            ContractDocument.objects.all().delete()
            FinanceExpense.objects.all().delete()
            FinancePayout.objects.all().delete()
            FinanceDeal.objects.all().delete()
            self.stdout.write('  Удалены документы и финансы')

            # 6. Сделки
            DealActivity.objects.all().delete()
            TradeInItem.objects.all().delete()
            ManagerDeal.objects.all().delete()
            self.stdout.write(f'  Удалено сделок: {deal_count}')

            # 7. Заказы (связанные со сделками)
            deleted_orders, _ = Order.objects.filter(id__in=order_ids).delete()
            self.stdout.write(f'  Удалено заказов: {deleted_orders}')

            # 8. Клиенты (очистить M2M и удалить)
            for client in ManagerClient.objects.all():
                client.orders.clear()
            ManagerClient.objects.all().delete()
            self.stdout.write(f'  Удалено клиентов: {client_count}')

        self.stdout.write(self.style.SUCCESS('Успешно очищено.'))
