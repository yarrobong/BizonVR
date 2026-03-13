"""
Создание тестовой сделки «Продажа под заказ» с закупкой и грузом для проверки сценария менеджера.
Запуск: python manage.py seed_manager_test_deal
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from django.contrib.auth import get_user_model

from catalog.models import Product, ProductVariant
from orders.models import Order, OrderItem
from manager_portal.models import (
    Cargo,
    CargoItem,
    ManagerDeal,
    ManagerClient,
    Purchase,
    PurchaseItem,
    Warehouse,
)


class Command(BaseCommand):
    help = 'Создать тестовую сделку «Продажа под заказ» с закупкой и грузом'

    def handle(self, *args, **options):
        with transaction.atomic():
            product = Product.objects.filter(name__icontains='Зарядный').first()
            if not product:
                product = Product.objects.first()
            if not product:
                self.stderr.write(self.style.ERROR('Нет товаров в каталоге.'))
                return

            variant = product.variants.first()
            warehouse = Warehouse.objects.filter(is_active=True).first()
            staff_user = get_user_model().objects.filter(is_staff=True).first()
            if not staff_user:
                self.stderr.write(self.style.ERROR('Нет staff-пользователя.'))
                return

            # Order
            order = Order.objects.create(
                user=None,
                status='new',
                total=Decimal('5000'),
                promo_discount=Decimal('0'),
                payment_method='manager_payment',
                payment_status='unpaid',
                delivery_type='cdek_pvz',
                phone='+79001234567',
                email='test@test.ru',
                first_name='Тест',
                last_name='Клиент',
                recipient_name='Тест Клиент',
                recipient_phone='+79001234567',
                recipient_is_customer=True,
                country='Россия',
                city_text='Екатеринбург',
                address_line='ПВЗ СДЭК, ул. Малышева, 10',
                address='ПВЗ СДЭК, ул. Малышева, 10',
                delivery_cost=Decimal('0'),
            )

            OrderItem.objects.create(
                order=order,
                product=product,
                variant=variant,
                quantity=1,
                price=Decimal('5000'),
                variant_name=variant.name if variant else '',
                condition='new',
                purchase_price=Decimal('3000'),
                discount_amount=Decimal('0'),
                is_on_request=True,
            )

            # ManagerDeal
            deal = ManagerDeal.objects.create(
                order=order,
                responsible_manager=staff_user,
                deal_type='sale_on_request',
                deal_status='supplier_ordered',
                case_status='in_progress',
                payment_state='paid',
                fulfillment_status='procurement_required',
                buyer_type='individual',
                individual_full_name='Тест Клиент',
                individual_phone='+79001234567',
                individual_city='Екатеринбург',
                customer_request='Зарядный кейс Quest 3',
                procurement_origin='AliExpress',
                supplier_name='Поставщик Китай',
                prepayment_required_amount=Decimal('5000'),
                prepayment_amount=Decimal('5000'),
                next_step_code='needs_procurement',
            )

            # ManagerClient
            client = ManagerClient.objects.create(
                name='Тест Клиент',
                phone='+79001234567',
                email='test@test.ru',
                status='active',
            )
            client.orders.add(order)

            # Purchase
            purchase = Purchase.objects.create(
                date=timezone.localdate(),
                supplier_name='Поставщик Китай',
                status='ordered',
                currency='CNY',
                total_amount=Decimal('3000'),
            )

            order_item = order.items.first()
            purchase_item = PurchaseItem.objects.create(
                purchase=purchase,
                product=product,
                variant=variant,
                order_item=order_item,
                quantity=1,
                price=Decimal('3000'),
            )

            # Cargo
            cargo = Cargo.objects.create(
                cargo_number=f'CARGO-{timezone.localdate().year}-001',
                purchase=purchase,
                status='in_transit',
                eta=timezone.localdate() + timezone.timedelta(days=14),
                destination_warehouse=warehouse,
            )

            CargoItem.objects.create(
                cargo=cargo,
                product=product,
                variant=variant,
                purchase_item=purchase_item,
                quantity=1,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'Создано: заказ #{order.pk}, сделка #{deal.pk}, '
                f'закупка #{purchase.pk}, груз {cargo.cargo_number}'
            )
        )
        self.stdout.write(f'  Карточка сделки: http://127.0.0.1:8000/manager/deals/{deal.pk}/')
        self.stdout.write(f'  Закупки: http://127.0.0.1:8000/manager/purchases/')
        self.stdout.write(f'  Грузы: http://127.0.0.1:8000/manager/cargos/')
