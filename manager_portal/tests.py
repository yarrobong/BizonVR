import csv
import importlib
from io import BytesIO
import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import CommercialProposalContact, Profile
from catalog.models import Category, City, PickupPoint, Product, ProductStock, ProductVariant
from orders.models import Order, OrderItem

from .forms import (
    CargoFilterForm,
    ContractDocumentForm,
    FinancePeriodForm,
    InventoryReceiptForm,
    ManualOrderForm,
    PurchaseFilterForm,
    ReservationFilterForm,
    ShipmentFilterForm,
    StyledFormMixin,
)
from .access import FINANCE_ADMIN_GROUP, FINANCE_OPERATOR_GROUP
from .models import (
    Cargo,
    CargoItem,
    CargoPhoto,
    ContractCompanyProfile,
    ContractDocument,
    ContractTemplate,
    Expense,
    FinanceDeal,
    FinanceDealType,
    FinanceExpense,
    FinanceExpenseCategory,
    FinancePayout,
    InventoryBalance,
    InventoryMovement,
    LegacyImportBatch,
    DealSavedView,
    ManagerDeal,
    ManagerDealParticipant,
    ManagerClient,
    ManagerPersonAlias,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    Shipment,
    ShipmentItem,
    TradeInItem,
    TransportLeg,
    Warehouse,
)
from .services import (
    build_finance_report_zip,
    create_or_update_reservation_movements,
    create_or_update_shipment_for_order,
    dashboard_stats,
    ensure_manager_deal_for_order,
    ensure_website_order_workflow,
    finance_dashboard_data,
    fulfill_reservation,
    inventory_snapshot_for_warehouse,
    record_deal_activity,
    receive_cargo_item,
    recompute_deal_workflow,
    receipt_inventory,
    set_manager_deal_paid_amount,
    shipments_grouped_by_reservation,
    shipments_rows,
    split_cargo,
    sync_public_stock_for_warehouse,
    update_order_state,
    validate_reservation_availability,
)
from .legacy_imports import import_manager_tabular_sales
from .templatetags.manager_portal_tags import manager_user_label
from .views import _manager_proposal_contact_data

User = get_user_model()

TEST_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00"
    b"\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


class ManagerTableTemplateTagTests(SimpleTestCase):
    def test_manager_table_renders_hover_variant_by_default(self):
        rendered = Template(
            '{% load manager_portal_tags %}'
            '{% manager_table table_class="w-full" wrapper_class="mt-5" %}'
            '<tbody><tr><td>Row</td></tr></tbody>'
            '{% endmanager_table %}'
        ).render(Context())

        self.assertIn('manager-table-shell overflow-x-auto mt-5', rendered)
        self.assertIn('manager-table manager-table--hover w-full', rendered)

    def test_manager_table_supports_zebra_variant(self):
        rendered = Template(
            '{% load manager_portal_tags %}'
            '{% manager_table variant="zebra" %}'
            '<tbody><tr><td>Row</td></tr></tbody>'
            '{% endmanager_table %}'
        ).render(Context())

        self.assertIn('manager-table manager-table--zebra', rendered)


class ManagerUserLabelTemplateTagTests(SimpleTestCase):
    def test_manager_user_label_prefers_profile_name_before_email(self):
        user = SimpleNamespace(
            get_full_name=lambda: '',
            email='manager@example.com',
            username='user_0b117b937e',
            profile=SimpleNamespace(contact_name='Иван Петров'),
        )

        self.assertEqual(manager_user_label(user), 'Иван Петров')

    def test_manager_user_label_falls_back_to_email_when_name_missing(self):
        user = SimpleNamespace(
            get_full_name=lambda: '',
            email='manager@example.com',
            username='user_0b117b937e',
        )

        self.assertEqual(manager_user_label(user), 'manager@example.com')


class ManagerDealPaymentMigrationTests(SimpleTestCase):
    def test_backfill_prefers_latest_payment_state_activity(self):
        migration = importlib.import_module('manager_portal.migrations.0014_managerdeal_last_payment_at')
        updated_at = timezone.now()
        payment_activity_at = updated_at - timedelta(hours=2)

        last_payment_at = migration.estimate_last_payment_at_for_backfill(
            SimpleNamespace(prepayment_amount=Decimal('5000.00'), updated_at=updated_at),
            [
                SimpleNamespace(
                    event_type='workflow.recomputed',
                    payload={'payment_state': {'old': 'unpaid', 'new': 'partial'}},
                    created_at=payment_activity_at,
                ),
                SimpleNamespace(
                    event_type='comment.added',
                    payload={'comment': 'ignored'},
                    created_at=updated_at - timedelta(hours=1),
                ),
            ],
        )

        self.assertEqual(last_payment_at, payment_activity_at)

    def test_backfill_falls_back_to_updated_at_for_paid_deal_without_activity(self):
        migration = importlib.import_module('manager_portal.migrations.0014_managerdeal_last_payment_at')
        updated_at = timezone.now()

        last_payment_at = migration.estimate_last_payment_at_for_backfill(
            SimpleNamespace(prepayment_amount=Decimal('5000.00'), updated_at=updated_at),
            [],
        )

        self.assertEqual(last_payment_at, updated_at)


class FinancePeriodFormTests(SimpleTestCase):
    def test_period_field_prefills_from_initial_year_and_month(self):
        form = FinancePeriodForm(initial={'year': 2026, 'month': 3})

        self.assertEqual(form['period'].value(), '2026-03')

    def test_period_field_accepts_legacy_year_and_month_query_params(self):
        form = FinancePeriodForm(data={'year': '2026', 'month': '0'})

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['period'], '2026-00')
        self.assertEqual(form.cleaned_data['year'], 2026)
        self.assertEqual(form.cleaned_data['month'], 0)


class ManagerFormRenderingTests(SimpleTestCase):
    def test_shared_form_field_partial_renders_status_helper_and_error(self):
        class DemoForm(StyledFormMixin, forms.Form):
            amount = forms.DecimalField(label='Сумма')

            field_metadata = {
                'amount': {
                    'placeholder': 'Например: 15000',
                    'help_text': 'Укажите сумму сделки в рублях.',
                    'autofill_note': 'Поле можно скорректировать позже.',
                }
            }

        form = DemoForm(data={'amount': ''})
        self.assertFalse(form.is_valid())

        rendered = Template(
            '{% include "manager_portal/_form_field.html" with field=form.amount compact=False %}'
        ).render(Context({'form': form}))

        self.assertIn('Обязательно', rendered)
        self.assertIn('Укажите сумму сделки в рублях.', rendered)
        self.assertIn('Поле можно скорректировать позже.', rendered)
        self.assertIn('Обязательное поле.', rendered)

    def test_manual_order_form_exposes_mask_and_helper_metadata(self):
        form = ManualOrderForm()

        self.assertEqual(form.fields['individual_phone'].widget.attrs['data-manager-mask'], 'phone')
        self.assertEqual(form.fields['business_email'].widget.attrs['data-manager-mask'], 'email')
        self.assertEqual(form.fields['customer_deadline'].widget.attrs['data-manager-date-picker'], 'true')
        self.assertEqual(form.fields['individual_messenger'].widget.attrs['data-manager-mask'], 'telegram-loose')
        self.assertIn('Подтянется автоматически текущим менеджером', form.fields['responsible_manager'].manager_autofill_note)

    def test_contract_document_form_exposes_autofill_metadata(self):
        form = ContractDocumentForm()

        self.assertEqual(form.fields['counterparty_phone'].widget.attrs['data-manager-mask'], 'phone')
        self.assertEqual(form.fields['counterparty_email'].widget.attrs['data-manager-mask'], 'email')
        self.assertIn('Подтянется автоматически', form.fields['template'].manager_autofill_note)
        self.assertIn('Внутренняя заметка', form.fields['notes'].manager_helper_text)


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
class ManagerPortalBaseTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79990001122', password='pass1234')
        self.staff_user = User.objects.create_user(username='79990001123', password='pass1234', is_staff=True)
        self.staff_user.user_permissions.add(Permission.objects.get(codename='view_product'))

        self.city = City.objects.create(name='Екатеринбург', slug='ekb')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Главный склад')
        self.other_pickup_point = PickupPoint.objects.create(city=self.city, name='Вторая точка')
        self.category = Category.objects.create(name='Шлемы', slug='helmets')
        self.product = Product.objects.create(
            category=self.category,
            name='Meta Quest 3',
            slug='meta-quest-3',
            price=Decimal('100000.00'),
            is_active=True,
        )
        self.product_two = Product.objects.create(
            category=self.category,
            name='BoboVR S3',
            slug='bobovr-s3',
            price=Decimal('5000.00'),
            is_active=True,
        )
        self.variant = ProductVariant.objects.create(product=self.product, name='128 GB', order=0)
        self.foreign_variant = ProductVariant.objects.create(product=self.product_two, name='Wrong', order=0)

        self.warehouse = Warehouse.objects.create(name='Склад ЕКБ', pickup_point=self.pickup_point)
        self.other_warehouse = Warehouse.objects.create(name='Склад Тюмень', pickup_point=self.other_pickup_point)
        self.unlinked_warehouse = Warehouse.objects.create(name='Буферный склад')

        self.order = self.create_order(
            phone='+7 999 000 11 22',
            email='client@example.com',
            first_name='Иван',
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_COURIER,
            created_at=timezone.now() - timedelta(days=3),
        )
        self.order_two = self.create_order(
            phone='+7 999 000 11 33',
            email='paid@example.com',
            first_name='Петр',
            status=Order.STATUS_DONE,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_PICKUP,
            pickup_point=self.pickup_point,
            created_at=timezone.now() - timedelta(days=1),
        )

        self.manager_client = ManagerClient.objects.create(
            name='ООО Тест',
            email='b2b@example.com',
            phone='+7 912 000 00 00',
            status=ManagerClient.STATUS_ACTIVE,
        )
        self.archived_client = ManagerClient.objects.create(
            name='Архивный клиент',
            email='old@example.com',
            status=ManagerClient.STATUS_ARCHIVED,
        )
        self.manager_client.orders.add(self.order)
        self.finance_deal_type, _ = FinanceDealType.objects.get_or_create(
            name='Партнерская',
            defaults={'partner_share': Decimal('0.5')},
        )
        self.finance_our_category, _ = FinanceExpenseCategory.objects.get_or_create(
            expense_side=FinanceExpenseCategory.SIDE_OURS,
            name='Транспортировка',
        )
        self.finance_partner_category, _ = FinanceExpenseCategory.objects.get_or_create(
            expense_side=FinanceExpenseCategory.SIDE_PARTNER,
            name='Связь',
        )
        self.contract_profile = ContractCompanyProfile.objects.create(
            name='Основной профиль BizonVR',
            legal_type=ContractCompanyProfile.LEGAL_TYPE_IP,
            company_name='ИП Едигарьев Я.А.',
            inn='667907832209',
            email='contracts@example.com',
            phone='+7 922 384-12-59',
            is_active=True,
        )
        self.contract_template = ContractTemplate.objects.create(
            name='Шаблон поставки',
            document_type=ContractTemplate.DOC_TYPE_CONTRACT,
            version='1.0',
            is_active=True,
            content_html='<div><h1>{{ document.number }}</h1><p>{{ counterparty.name }}</p></div>',
        )
        self.contract_document = ContractDocument.objects.create(
            template=self.contract_template,
            company_profile=self.contract_profile,
            manager_client=self.manager_client,
            linked_order=self.order,
            responsible_manager=self.staff_user,
            created_by=self.staff_user,
            number='DOG-2026-0001',
            title='Договор поставки Quest',
            document_type=ContractTemplate.DOC_TYPE_CONTRACT,
            status=ContractDocument.STATUS_REVIEW,
            amount=Decimal('150000.00'),
            subject='Поставка VR-шлемов',
            counterparty_name=self.manager_client.name,
            counterparty_email=self.manager_client.email,
            counterparty_phone=self.manager_client.phone,
            counterparty_inn='6677000000',
            counterparty_address='Екатеринбург',
        )

    def login_staff(self):
        self.client.force_login(self.staff_user)

    def assert_sidebar_labels(self, response):
        self.assertEqual(
            [item['label'] for item in response.context['manager_sidebar_items']],
            [
                'Сделки',
                'Клиенты',
                'Коммерческие предложения',
                'Склады',
                'Остатки',
                'Бронирования',
                'Грузы',
                'Отгрузки',
                'Финансы',
                'Договоры',
                'Закупки',
            ],
        )
        self.assertEqual(
            [(group['label'], [item['label'] for item in group['items']]) for group in response.context['manager_sidebar_groups']],
            [
                ('Продажи', ['Сделки', 'Клиенты', 'Коммерческие предложения']),
                ('Склад и логистика', ['Склады', 'Остатки', 'Бронирования', 'Грузы', 'Отгрузки']),
                ('Финансы и документы', ['Финансы', 'Договоры', 'Закупки']),
            ],
        )
        self.assertContains(response, 'Продажи')
        self.assertContains(response, 'Склад и логистика')
        self.assertContains(response, 'Финансы и документы')

    def test_entry_shell_uses_email_when_name_missing(self):
        self.staff_user.username = 'user_0b117b937e8db4'
        self.staff_user.email = 'staff@example.com'
        self.staff_user.first_name = ''
        self.staff_user.last_name = ''
        self.staff_user.save(update_fields=['username', 'email', 'first_name', 'last_name'])
        self.login_staff()

        response = self.client.get(reverse('manager_portal:entry'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'staff@example.com')
        self.assertContains(response, 'title="staff@example.com"', html=False)

    def test_deal_list_uses_scrollable_kpi_grid_markup(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'manager-deals-kpi-scroller')
        self.assertNotContains(response, 'md:grid-cols-3')

    def test_client_detail_shows_linked_user_email_instead_of_generated_username(self):
        linked_user = User.objects.create_user(
            username='user_0b117b937e8db4',
            email='client-owner@example.com',
            password='pass1234',
        )
        self.manager_client.user = linked_user
        self.manager_client.save(update_fields=['user'])
        self.login_staff()

        response = self.client.get(reverse('manager_portal:client_detail', kwargs={'pk': self.manager_client.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>client-owner@example.com<', html=False)

    def create_order(
        self,
        *,
        phone,
        email,
        first_name,
        status,
        payment_status,
        delivery_type,
        pickup_point=None,
        created_at=None,
    ):
        order = Order.objects.create(
            user=None,
            status=status,
            payment_status=payment_status,
            total=Decimal('100000.00'),
            phone=phone,
            email=email,
            first_name=first_name,
            delivery_type=delivery_type,
            city=self.city,
            pickup_point=pickup_point,
        )
        order.items.create(product=self.product, quantity=1, price=Decimal('100000.00'))
        if created_at is not None:
            Order.objects.filter(pk=order.pk).update(created_at=created_at)
            order.refresh_from_db()
        return order

    def create_reservation(
        self,
        *,
        client=None,
        status=Reservation.STATUS_ACTIVE,
        source_type=Reservation.SOURCE_WAREHOUSE,
        source_warehouse=None,
        source_cargo=None,
        target_warehouse=None,
        linked_order=None,
        comments='',
    ):
        return Reservation.objects.create(
            client=client or self.manager_client,
            linked_order=linked_order,
            status=status,
            source_type=source_type,
            source_warehouse=source_warehouse,
            source_cargo=source_cargo,
            target_warehouse=target_warehouse,
            comments=comments,
        )

    def make_test_image(self, name='cargo.gif'):
        return SimpleUploadedFile(name, TEST_GIF, content_type='image/gif')

    def manual_business_order_payload(self):
        return {
            'deal_type': ManagerDeal.DEAL_SALE_FROM_STOCK,
            'deal_status': ManagerDeal.DEAL_STATUS_NEW,
            'buyer_type': ManagerDeal.BUYER_BUSINESS,
            'responsible_manager': self.staff_user.pk,
            'deal_created_at': '2026-03-10T12:30',
            'customer_source': ManagerDeal.SOURCE_AVITO,
            'deal_comment': 'Срочная отгрузка',
            'business_company_name': 'ООО Вижн',
            'business_inn': '6677001122',
            'business_kpp': '667701001',
            'business_ogrn': '1234567890123',
            'business_legal_address': 'Екатеринбург, Ленина, 1',
            'business_contact_person': 'Иван Петров',
            'business_phone': '+7 912 000 10 10',
            'business_telegram': '@vision_finance',
            'business_whatsapp': '+7 912 000 10 11',
            'business_email': 'sale@vision.test',
            'business_city': 'Екатеринбург',
            'business_delivery_address': 'ПВЗ СДЭК, Малышева, 10',
            'business_checking_account': '40702810900000000001',
            'business_bank_name': 'ПАО Сбербанк',
            'business_bik': '046577674',
            'business_correspondent_account': '30101810500000000674',
            'business_comment': 'Работают по безналу',
            'customer_request': '',
            'customer_deadline': '',
            'customer_request_comment': '',
            'delivery_method': ManagerDeal.DELIVERY_CDEK_PVZ,
            'delivery_from_city': 'Екатеринбург',
            'delivery_to_city': 'Тюмень',
            'delivery_pickup_address': 'Тюмень, ПВЗ СДЭК на Республики, 5',
            'delivery_full_address': '',
            'delivery_cost': '1500.00',
            'delivery_payer': ManagerDeal.DELIVERY_PAYER_INCLUDED,
            'tracking_number': 'CDEK-100500',
            'shipping_comment': 'Позвонить перед выдачей',
            'shipment_status': ManagerDeal.SHIPMENT_PENDING,
            'shipped_at': '2026-03-11',
            'planned_receipt_at': '2026-03-15',
            'prepayment_required_amount': '30000.00',
            'prepayment_amount': '30000.00',
            'stock_warehouse': str(self.warehouse.pk),
            'procurement_origin': '',
            'supplier_name': '',
            'supplier_agent': '',
            'planned_purchase_date': '',
            'expected_arrival_date': '',
            'expected_customer_ship_date': '',
            'avito_listing_url': '',
            'avito_listing_id': '',
            'avito_listing_title': '',
            'avito_contact_channel': '',
            'avito_list_price': '',
            'avito_final_price': '',
            'avito_commission': '',
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            'items-0-product_name': self.product.name,
            'items-0-product': str(self.product.pk),
            'items-0-configuration': '512 GB',
            'items-0-condition': OrderItem.CONDITION_NEW,
            'items-0-quantity': '2',
            'items-0-purchase_price': '70000.00',
            'items-0-sale_price': '95000.00',
            'items-0-discount_amount': '5000.00',
            'items-0-comment': 'Комплект с контроллерами',
            'tradein-TOTAL_FORMS': '1',
            'tradein-INITIAL_FORMS': '0',
            'tradein-MIN_NUM_FORMS': '0',
            'tradein-MAX_NUM_FORMS': '1000',
            'tradein-0-device_type': '',
            'tradein-0-model_name': '',
            'tradein-0-version': '',
            'tradein-0-kit_description': '',
            'tradein-0-condition': '',
            'tradein-0-defects': '',
            'tradein-0-preliminary_estimate': '',
            'tradein-0-final_estimate': '',
        }


class ManagerPortalAccessTests(ManagerPortalBaseTestCase):
    def test_anonymous_redirected_to_login_from_entry(self):
        response = self.client.get(reverse('manager_portal:entry'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))

    def test_non_staff_can_open_entry_but_dashboard_forbidden(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('manager_portal:entry'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['entry_has_staff_access'])
        self.assertContains(response, 'Зайти на сайт')
        self.assertNotContains(response, 'Логистика')

        response = self.client.get(reverse('manager_portal:dashboard'))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')
        self.assertContains(response, 'Нет доступа', status_code=403)

        response = self.client.get(reverse('manager_portal:contracts'))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

        response = self.client.get(reverse('manager_portal:global_search_results'), {'q': 'Quest'})

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')

    def test_entry_renders_theme_toggle_with_light_default(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('manager_portal:entry'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="ru" data-manager-theme="light">', html=False)
        self.assertContains(response, 'data-manager-theme-option="light"')
        self.assertContains(response, 'data-manager-theme-option="dark"')
        self.assertContains(response, "window.managerPortalTheme = {")

    def test_finance_operator_can_open_finance_only_routes(self):
        finance_group, _ = Group.objects.get_or_create(name=FINANCE_OPERATOR_GROUP)
        finance_user = User.objects.create_user(username='finance-operator', password='pass1234')
        finance_user.groups.add(finance_group)
        self.client.force_login(finance_user)

        entry_response = self.client.get(reverse('manager_portal:entry'))
        finance_response = self.client.get(reverse('manager_portal:finance'))
        finance_settings_get = self.client.get(reverse('manager_portal:finance_settings'))
        finance_settings_post = self.client.post(
            reverse('manager_portal:finance_settings'),
            data={
                'action': 'create_deal_type',
                'deal-type-name': 'Новый тип',
                'deal-type-partner_share': '0.3000',
                'deal-type-is_active': 'on',
            },
        )
        dashboard_response = self.client.get(reverse('manager_portal:dashboard'))
        contracts_response = self.client.get(reverse('manager_portal:contracts'))

        self.assertEqual(entry_response.status_code, 200)
        self.assertTrue(entry_response.context['entry_has_finance_access'])
        self.assertFalse(entry_response.context['entry_has_staff_access'])
        self.assert_sidebar_labels(entry_response)
        self.assertContains(entry_response, 'Финансы')
        self.assertNotContains(entry_response, '/manager/deals/')
        self.assertNotContains(entry_response, '/manager/contracts/')
        enabled_sidebar_items = [item['key'] for item in entry_response.context['manager_sidebar_items'] if item['enabled']]
        self.assertEqual(enabled_sidebar_items, ['finance'])

        self.assertEqual(finance_response.status_code, 200)
        self.assert_sidebar_labels(finance_response)
        self.assertContains(finance_response, 'Финансовый обзор')
        self.assertContains(finance_response, 'Финансовый контур')
        finance_item = next(item for item in finance_response.context['manager_sidebar_items'] if item['key'] == 'finance')
        self.assertTrue(finance_item['active'])
        self.assertTrue(finance_item['enabled'])

        self.assertEqual(finance_settings_get.status_code, 200)
        self.assertContains(finance_settings_get, 'finance-admin')
        self.assertEqual(finance_settings_post.status_code, 403)

        self.assertEqual(dashboard_response.status_code, 403)
        self.assertEqual(contracts_response.status_code, 403)

    def test_finance_only_mobile_bottom_nav_is_not_rendered_for_single_destination(self):
        finance_group, _ = Group.objects.get_or_create(name=FINANCE_OPERATOR_GROUP)
        finance_user = User.objects.create_user(username='finance-operator-mobile', password='pass1234')
        finance_user.groups.add(finance_group)
        self.client.force_login(finance_user)

        response = self.client.get(reverse('manager_portal:finance'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['key'] for item in response.context['manager_mobile_primary_nav_items']],
            ['finance'],
        )
        self.assertEqual(response.context['manager_mobile_more_nav_items'], [])
        self.assertFalse(response.context['manager_mobile_bottom_nav_visible'])

    def test_finance_admin_can_update_finance_settings_without_staff_access(self):
        finance_group, _ = Group.objects.get_or_create(name=FINANCE_ADMIN_GROUP)
        finance_user = User.objects.create_user(username='finance-admin', password='pass1234')
        finance_user.groups.add(finance_group)
        self.client.force_login(finance_user)

        response = self.client.post(
            reverse('manager_portal:finance_settings'),
            data={
                'action': 'create_deal_type',
                'deal-type-name': 'Импортный тип',
                'deal-type-partner_share': '0.4200',
                'deal-type-is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(FinanceDealType.objects.filter(name='Импортный тип').exists())

    def test_staff_entry_shows_internal_modules(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:entry'))

        self.assertRedirects(response, reverse('manager_portal:deal_list'))

    def test_staff_dashboard_redirects_to_problematic_deals(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:dashboard'))

        self.assertRedirects(response, f"{reverse('manager_portal:deal_list')}?only_problematic=1")

    def test_staff_mobile_bottom_nav_uses_role_priority_order(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['key'] for item in response.context['manager_mobile_primary_nav_items']],
            ['deals', 'clients', 'warehouses', 'inventory', 'finance'],
        )
        self.assertEqual(
            [item['key'] for item in response.context['manager_mobile_more_nav_items']],
            ['contracts', 'purchases', 'reservations', 'shipments', 'cargos', 'commercial_proposals'],
        )
        self.assertTrue(response.context['manager_mobile_bottom_nav_visible'])

    def test_staff_mobile_bottom_nav_promotes_active_secondary_section(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:contracts_documents'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['key'] for item in response.context['manager_mobile_primary_nav_items']],
            ['deals', 'clients', 'warehouses', 'inventory', 'contracts'],
        )
        self.assertEqual(
            [item['key'] for item in response.context['manager_mobile_more_nav_items']],
            ['finance', 'purchases', 'reservations', 'shipments', 'cargos', 'commercial_proposals'],
        )
        self.assertFalse(response.context['manager_mobile_more_active'])

    def test_staff_can_open_commercial_proposals_module(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:commercial_proposals'))

        self.assertEqual(response.status_code, 200)
        self.assert_sidebar_labels(response)
        self.assertContains(response, 'Генератор КП')
        self.assertContains(response, 'Поиск товара')
        self.assertContains(response, 'Результаты')
        self.assertContains(response, 'Добавленные товары')
        self.assertContains(response, 'Сгенерировать КП')
        self.assertContains(response, 'Сохранить черновик')
        self.assertContains(response, 'id="commercial-proposal-form" hx-boost="false"', html=False)
        active_sidebar_item = next(item for item in response.context['manager_sidebar_items'] if item['active'])
        self.assertEqual(active_sidebar_item['key'], 'commercial_proposals')

    def test_staff_can_open_contracts_module_routes(self):
        self.login_staff()

        finance_response = self.client.get(reverse('manager_portal:finance'))
        contracts_response = self.client.get(reverse('manager_portal:contracts'))
        contracts_documents_response = self.client.get(reverse('manager_portal:contracts_documents'))
        contracts_detail_response = self.client.get(reverse('manager_portal:contracts_detail', args=[self.contract_document.pk]))
        contracts_create_response = self.client.get(reverse('manager_portal:contracts_create'))
        contracts_templates_response = self.client.get(reverse('manager_portal:contracts_templates'))
        contracts_settings_response = self.client.get(reverse('manager_portal:contracts_settings'))
        contracts_app_response = self.client.get(reverse('manager_portal:contracts_app'))
        contracts_api_response = self.client.get(reverse('manager_portal:contracts_api_proxy'))

        self.assertEqual(finance_response.status_code, 200)
        self.assertContains(finance_response, 'Финансовый обзор')
        self.assertContains(finance_response, 'Finance Workspace')
        self.assertEqual(contracts_response.status_code, 200)
        self.assertContains(contracts_response, 'Панель управления документами')
        self.assertContains(contracts_response, 'class="manager-secondary-action"', html=False)
        self.assertNotContains(contracts_response, 'Внутренний кабинет договоров')
        self.assertContains(contracts_response, self.contract_document.number)
        self.assertEqual(contracts_documents_response.status_code, 200)
        self.assertContains(contracts_documents_response, 'Реестр документов')
        self.assertContains(contracts_documents_response, self.contract_document.title)
        self.assertEqual(contracts_detail_response.status_code, 200)
        self.assertContains(contracts_detail_response, self.contract_document.number)
        self.assertContains(contracts_detail_response, 'Предпросмотр')
        self.assertEqual(contracts_create_response.status_code, 200)
        self.assertContains(contracts_create_response, 'Новый документ')
        self.assertContains(contracts_create_response, 'Предпросмотр')
        self.assertContains(contracts_create_response, 'Создать документ')
        self.assertContains(contracts_create_response, 'Показать предпросмотр')
        self.assertContains(contracts_create_response, 'Здесь менеджер видит, какие реквизиты обязательны сразу')
        self.assertEqual(contracts_templates_response.status_code, 200)
        self.assertContains(contracts_templates_response, self.contract_template.name)
        self.assertEqual(contracts_settings_response.status_code, 200)
        self.assertContains(contracts_settings_response, self.contract_profile.name)
        self.assertEqual(contracts_app_response.status_code, 302)
        self.assertEqual(contracts_app_response.url, reverse('manager_portal:contracts'))
        self.assertEqual(contracts_api_response.status_code, 410)
        self.assertContains(contracts_api_response, 'Внешний API договоров недоступен.', status_code=410)
        self.assertNotContains(contracts_api_response, 'внутренний кабинет', status_code=410)

    def test_staff_can_open_finance_subsection_routes(self):
        self.login_staff()

        finance_dashboard_response = self.client.get(reverse('manager_portal:finance'))
        finance_deals_response = self.client.get(reverse('manager_portal:finance_deal_list'))
        finance_expenses_response = self.client.get(reverse('manager_portal:finance_expense_list'))
        finance_payouts_response = self.client.get(reverse('manager_portal:finance_payout_list'))
        finance_archive_response = self.client.get(reverse('manager_portal:finance_archive'))

        self.assertEqual(finance_dashboard_response.status_code, 200)
        self.assertContains(finance_dashboard_response, 'Кассовая лента')
        self.assertContains(finance_dashboard_response, 'Распределение по типам сделок')
        self.assertEqual(finance_deals_response.status_code, 200)
        self.assertContains(finance_deals_response, 'Финансовые кейсы')
        self.assertEqual(finance_expenses_response.status_code, 200)
        self.assertContains(finance_expenses_response, 'Наши расходы')
        self.assertEqual(finance_payouts_response.status_code, 200)
        self.assertContains(finance_payouts_response, 'Журнал выплат')
        self.assertEqual(finance_archive_response.status_code, 200)
        self.assertContains(finance_archive_response, 'Архив операций')

    def test_staff_can_create_contract_document_from_internal_cabinet(self):
        self.login_staff()

        response = self.client.post(
            reverse('manager_portal:contracts_create'),
            data={
                'document_type': ContractTemplate.DOC_TYPE_CONTRACT,
                'status': ContractDocument.STATUS_DRAFT,
                'template': self.contract_template.pk,
                'company_profile': self.contract_profile.pk,
                'manager_client': self.manager_client.pk,
                'linked_order': self.order.pk,
                'responsible_manager': self.staff_user.pk,
                'number': '',
                'title': 'Новый внутренний договор',
                'issue_date': timezone.localdate().isoformat(),
                'effective_until': '',
                'amount': '99000.00',
                'currency': ContractDocument.CURRENCY_RUB,
                'payment_terms': '5',
                'subject': 'Поставка тестовой партии',
                'counterparty_name': 'ООО Новый клиент',
                'counterparty_email': 'new@example.com',
                'counterparty_phone': '+7 900 000 00 00',
                'counterparty_inn': '6677889900',
                'counterparty_kpp': '667701001',
                'counterparty_ogrn': '1234567890123',
                'counterparty_ogrnip': '',
                'counterparty_address': 'Екатеринбург, Тестовая, 1',
                'notes': 'Проверка создания',
            },
        )

        self.assertEqual(response.status_code, 302)
        created_document = ContractDocument.objects.exclude(pk=self.contract_document.pk).latest('id')
        self.assertRedirects(response, reverse('manager_portal:contracts_detail', args=[created_document.pk]))
        self.assertEqual(created_document.created_by, self.staff_user)
        self.assertEqual(created_document.linked_order, self.order)
        self.assertEqual(created_document.company_profile, self.contract_profile)
        self.assertEqual(created_document.template, self.contract_template)
        self.assertTrue(created_document.number.startswith('DOG-'))

    def test_staff_can_preview_contract_document_before_saving(self):
        self.login_staff()

        response = self.client.post(
            reverse('manager_portal:contracts_create'),
            data={
                'action': 'preview',
                'document_type': ContractTemplate.DOC_TYPE_CONTRACT,
                'status': ContractDocument.STATUS_DRAFT,
                'template': self.contract_template.pk,
                'company_profile': self.contract_profile.pk,
                'manager_client': self.manager_client.pk,
                'linked_order': self.order.pk,
                'responsible_manager': self.staff_user.pk,
                'number': '',
                'title': '',
                'issue_date': timezone.localdate().isoformat(),
                'effective_until': '',
                'amount': '99000.00',
                'currency': ContractDocument.CURRENCY_RUB,
                'payment_terms': '5',
                'subject': 'Поставка тестовой партии',
                'counterparty_name': 'ООО Новый клиент',
                'counterparty_email': 'new@example.com',
                'counterparty_phone': '+7 900 000 00 00',
                'counterparty_inn': '6677889900',
                'counterparty_kpp': '667701001',
                'counterparty_ogrn': '1234567890123',
                'counterparty_ogrnip': '',
                'counterparty_address': 'Екатеринбург, Тестовая, 1',
                'notes': 'Проверка preview',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContractDocument.objects.count(), 1)
        self.assertContains(response, 'Предпросмотр')
        self.assertContains(response, f'DOG-{timezone.localdate().year}-0002')
        self.assertContains(response, 'ООО Новый клиент')

    def test_staff_can_search_products_for_commercial_proposal(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:commercial_proposals_search'), {'q': 'Meta'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Meta Quest 3')

    def test_staff_without_product_permission_cannot_use_commercial_proposals(self):
        limited_staff = User.objects.create_user(username='79990005566', password='pass1234', is_staff=True)
        self.client.force_login(limited_staff)

        entry_response = self.client.get(reverse('manager_portal:entry'))
        proposal_response = self.client.get(reverse('manager_portal:commercial_proposals'))
        search_response = self.client.get(reverse('manager_portal:commercial_proposals_search'), {'q': 'Meta'})

        self.assertRedirects(entry_response, reverse('manager_portal:deal_list'))
        self.assertEqual(proposal_response.status_code, 403)
        self.assertEqual(search_response.status_code, 403)

    def test_unknown_route_uses_custom_404_page(self):
        response = self.client.get('/manage')

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, 'Страница не найдена', status_code=404)


class ManagerPortalModelAndFormTests(ManagerPortalBaseTestCase):
    def test_manager_filter_forms_use_flatpickr_date_widget(self):
        form_classes = (
            PurchaseFilterForm,
            CargoFilterForm,
            ReservationFilterForm,
            ShipmentFilterForm,
        )

        for form_class in form_classes:
            form = form_class()
            for field_name in ('date_from', 'date_to'):
                with self.subTest(form=form_class.__name__, field=field_name):
                    field = form.fields[field_name]
                    self.assertEqual(field.widget.attrs['data-manager-date-picker'], 'true')
                    self.assertEqual(field.widget.attrs['placeholder'], 'ДД.ММ.ГГГГ')
                    self.assertIn('bg-slate-800', field.widget.attrs['class'])
                    self.assertIn('%d.%m.%Y', field.input_formats)

    def test_inventory_receipt_form_rejects_foreign_variant(self):
        form = InventoryReceiptForm(
            data={
                'warehouse': self.warehouse.pk,
                'product': self.product.pk,
                'variant': self.foreign_variant.pk,
                'quantity': 1,
                'comment': '',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('variant', form.errors)

    def test_purchase_item_clean_rejects_foreign_variant(self):
        item = PurchaseItem(
            purchase=Purchase.objects.create(date=timezone.localdate()),
            product=self.product,
            variant=self.foreign_variant,
            quantity=1,
            price=Decimal('10.00'),
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_reservation_clean_requires_matching_source_fields(self):
        with self.assertRaises(ValidationError):
            Reservation(
                client=self.manager_client,
                status=Reservation.STATUS_ACTIVE,
                source_type=Reservation.SOURCE_WAREHOUSE,
                source_cargo=Cargo.objects.create(cargo_number='CG-ERR-1'),
            ).full_clean()

        with self.assertRaises(ValidationError):
            Reservation(
                client=self.manager_client,
                status=Reservation.STATUS_ACTIVE,
                source_type=Reservation.SOURCE_CARGO,
                source_warehouse=self.warehouse,
            ).full_clean()

    def test_expense_requires_cargo_or_leg(self):
        expense = Expense(
            category='customs',
            name='Доставка',
            amount=Decimal('100.00'),
            date=timezone.localdate(),
        )

        with self.assertRaises(ValidationError):
            expense.full_clean()

    def test_finance_deal_recalculates_margin_and_partner_share(self):
        finance_deal = FinanceDeal.objects.create(
            date=timezone.localdate(),
            contract_number='BF-001',
            deal_type=self.finance_deal_type,
            revenue=Decimal('1000.00'),
            cost_price=Decimal('200.00'),
            direct_expenses=Decimal('100.00'),
            manager_bonus=Decimal('50.00'),
        )

        self.assertEqual(finance_deal.margin, Decimal('650.00'))
        self.assertEqual(finance_deal.partner_share_amount, Decimal('325.000'))


class ManagerPortalServiceTests(ManagerPortalBaseTestCase):
    def test_manager_proposal_contact_data_prefers_cp_contact_over_profile(self):
        self.staff_user.first_name = 'Ярослав'
        self.staff_user.last_name = 'Едигарьев'
        self.staff_user.email = 'user@example.com'
        self.staff_user.save(update_fields=['first_name', 'last_name', 'email'])
        Profile.objects.create(user=self.staff_user, phone='+7 900 000 00 01')
        CommercialProposalContact.objects.create(
            user=self.staff_user,
            phone='+7 900 000 00 02',
            email='cp@example.com',
        )

        contact_data = _manager_proposal_contact_data(self.staff_user)

        self.assertEqual(contact_data['manager_first_name'], 'Ярослав')
        self.assertEqual(contact_data['manager_last_name'], 'Едигарьев')
        self.assertEqual(contact_data['manager_phone'], '+7 900 000 00 02')
        self.assertEqual(contact_data['manager_email'], 'cp@example.com')

    def test_finance_dashboard_data_calculates_partner_metrics(self):
        manager_deal = ensure_manager_deal_for_order(self.order)
        manager_deal.prepayment_amount = Decimal('250.00')
        manager_deal.payment_state = ManagerDeal.PAYMENT_STATE_PARTIAL
        manager_deal.next_step_code = ManagerDeal.NEXT_STEP_NEEDS_PAYMENT
        manager_deal.problem_flags = [ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE]
        manager_deal.save(
            update_fields=['prepayment_amount', 'payment_state', 'next_step_code', 'problem_flags', 'updated_at']
        )
        finance_deal = FinanceDeal.objects.create(
            manager_deal=manager_deal,
            date=timezone.localdate(),
            contract_number='BF-002',
            deal_type=self.finance_deal_type,
            revenue=Decimal('1000.00'),
            cost_price=Decimal('300.00'),
            direct_expenses=Decimal('100.00'),
            manager_bonus=Decimal('100.00'),
        )
        FinanceExpense.objects.create(
            expense_side=FinanceExpense.SIDE_OURS,
            date=timezone.localdate(),
            category=self.finance_our_category,
            amount=Decimal('50.00'),
            deal=None,
        )
        FinanceExpense.objects.create(
            expense_side=FinanceExpense.SIDE_PARTNER,
            date=timezone.localdate(),
            category=self.finance_partner_category,
            amount=Decimal('20.00'),
            deal=None,
        )
        FinancePayout.objects.create(date=timezone.localdate(), amount=Decimal('80.00'))

        data = finance_dashboard_data(year=timezone.localdate().year, month=timezone.localdate().month)
        report = build_finance_report_zip(year=timezone.localdate().year, month=timezone.localdate().month)

        self.assertEqual(finance_deal.margin, Decimal('500.00'))
        self.assertEqual(data['turnover'], Decimal('1000.00'))
        self.assertEqual(data['total_opex'], Decimal('50.00'))
        self.assertEqual(data['partner_paid_physically'], Decimal('20.00'))
        self.assertEqual(data['already_paid'], Decimal('80.00'))
        self.assertEqual(data['paid_total'], Decimal('250.00'))
        self.assertEqual(data['receivables_total'], Decimal('750.00'))
        self.assertEqual(data['overdue_total'], Decimal('750.00'))
        self.assertEqual(data['cash_balance'], Decimal('120.00'))
        self.assertTrue(data['has_cashflow_activity'])
        self.assertEqual(data['partner_profit'].as_tuple().exponent, -2)
        self.assertEqual(data['final_payout'].as_tuple().exponent, -2)
        self.assertTrue(data['partner_profit'] > 0)
        self.assertTrue(len(report) > 10)

    def test_inventory_snapshot_includes_inbound_and_inbound_reserved(self):
        cargo = Cargo.objects.create(
            cargo_number='CG-001',
            status=Cargo.STATUS_AWAITING_RECEIPT,
            destination_warehouse=self.warehouse,
        )
        CargoItem.objects.create(cargo=cargo, product=self.product, quantity=8)
        reservation = self.create_reservation(
            source_type=Reservation.SOURCE_CARGO,
            source_cargo=cargo,
            target_warehouse=self.other_warehouse,
        )
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=3)

        rows = inventory_snapshot_for_warehouse(self.warehouse)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['inbound'], 8)
        self.assertEqual(rows[0]['inbound_reserved'], 3)
        self.assertEqual(rows[0]['inbound_available'], 5)

    def test_inventory_snapshot_adds_min_stock_public_sync_and_problem_codes(self):
        balance = InventoryBalance.objects.create(
            warehouse=self.warehouse,
            product=self.product,
            quantity=3,
            min_stock=5,
        )
        sync_public_stock_for_warehouse(self.warehouse)
        ProductStock.objects.filter(
            product=self.product,
            pickup_point=self.pickup_point,
            variant__isnull=True,
        ).update(quantity=1)

        rows = inventory_snapshot_for_warehouse(self.warehouse)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['min_stock'], balance.min_stock)
        self.assertEqual(rows[0]['public_published_qty'], 1)
        self.assertEqual(rows[0]['public_expected_qty'], 3)
        self.assertEqual(rows[0]['public_sync_status_code'], 'mismatch')
        self.assertIn('below_min_stock', rows[0]['problem_codes'])
        self.assertIn('public_mismatch', rows[0]['problem_codes'])

    def test_validate_reservation_availability_fails_for_warehouse_source(self):
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=2, author=self.staff_user)
        reservation = self.create_reservation(source_warehouse=self.warehouse)
        item = ReservationItem(reservation=reservation, product=self.product, quantity=3)

        with self.assertRaisesMessage(ValueError, 'Недостаточно доступного остатка'):
            validate_reservation_availability(reservation, items=[item])

    def test_validate_reservation_availability_fails_for_cargo_source(self):
        cargo = Cargo.objects.create(
            cargo_number='CG-002',
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
        )
        CargoItem.objects.create(cargo=cargo, product=self.product, quantity=4)
        reservation = self.create_reservation(source_type=Reservation.SOURCE_CARGO, source_cargo=cargo)
        item = ReservationItem(reservation=reservation, product=self.product, quantity=5)

        with self.assertRaisesMessage(ValueError, 'Недостаточно доступного остатка'):
            validate_reservation_availability(reservation, items=[item])

    def test_dashboard_stats_counts_overdue_and_problem_rows(self):
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=2, author=self.staff_user)
        reservation = self.create_reservation(source_warehouse=self.warehouse)
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=3)
        Cargo.objects.create(
            cargo_number='CG-003',
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
            eta=timezone.localdate() - timedelta(days=1),
        )

        stats = dashboard_stats()

        self.assertEqual(stats['new_orders'], 1)
        self.assertEqual(stats['cargos_in_transit'], 1)
        self.assertEqual(stats['overdue_cargos'], 1)
        self.assertEqual(stats['active_reservations'], 1)
        self.assertEqual(stats['inventory_problem_rows'], 1)
        self.assertTrue(any(row['status'] == Order.STATUS_NEW for row in stats['order_status_rows']))
        self.assertTrue(any(row['status'] == Cargo.STATUS_IN_TRANSIT for row in stats['cargo_status_rows']))

    def test_shipments_rows_and_grouping_ignore_inactive_reservations(self):
        active_reservation = self.create_reservation(
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
        )
        ReservationItem.objects.create(reservation=active_reservation, product=self.product, quantity=2)
        ReservationItem.objects.create(reservation=active_reservation, product=self.product_two, quantity=1)
        cancelled_reservation = self.create_reservation(
            status=Reservation.STATUS_CANCELLED,
            source_warehouse=self.warehouse,
        )
        ReservationItem.objects.create(reservation=cancelled_reservation, product=self.product, quantity=5)

        rows = shipments_rows()
        grouped_rows = shipments_grouped_by_reservation(rows)

        self.assertEqual(len(rows), 2)
        self.assertEqual({row['product'].pk for row in rows}, {self.product.pk, self.product_two.pk})
        self.assertEqual(len(grouped_rows), 1)
        self.assertEqual(grouped_rows[0]['items_total'], 3)

    def test_update_order_state_calls_side_effects_when_state_changes(self):
        with patch('manager_portal.services.sync_order_state_side_effects') as sync_mock:
            update_order_state(
                self.order,
                status=Order.STATUS_CONFIRMED,
                payment_status=Order.PAYMENT_STATUS_PENDING_CONFIRMATION,
            )

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_CONFIRMED)
        self.assertEqual(self.order.payment_status, Order.PAYMENT_STATUS_PENDING_CONFIRMATION)
        sync_mock.assert_called_once()

    def test_update_order_state_skips_side_effects_when_state_unchanged(self):
        with patch('manager_portal.services.sync_order_state_side_effects') as sync_mock:
            update_order_state(
                self.order,
                status=self.order.status,
                payment_status=self.order.payment_status,
            )

        sync_mock.assert_not_called()

    def test_receive_cargo_item_marks_cargo_received_when_fully_received(self):
        cargo = Cargo.objects.create(
            cargo_number='CG-004',
            status=Cargo.STATUS_AWAITING_RECEIPT,
            destination_warehouse=self.warehouse,
        )
        cargo_item = CargoItem.objects.create(cargo=cargo, product=self.product, quantity=2)

        receive_cargo_item(cargo_item, quantity=2, author=self.staff_user)

        cargo.refresh_from_db()
        cargo_item.refresh_from_db()
        balance = InventoryBalance.objects.get(warehouse=self.warehouse, product=self.product, variant__isnull=True)
        self.assertEqual(cargo.status, Cargo.STATUS_RECEIVED)
        self.assertEqual(cargo_item.received_quantity, 2)
        self.assertEqual(balance.quantity, 2)

    def test_website_workflow_creates_client_deal_and_variant_aware_reservation(self):
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, variant=self.variant, quantity=2)
        order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            payment_method=Order.PAYMENT_METHOD_ONLINE,
            total=Decimal('100000.00'),
            phone='+7 999 555 44 33',
            email='site-flow@example.com',
            first_name='Сайт',
            city_text='Екатеринбург',
            delivery_type=Order.DELIVERY_CDEK_PVZ,
            address_line='ПВЗ',
        )
        order_item = OrderItem.objects.create(
            order=order,
            product=self.product,
            variant=self.variant,
            quantity=1,
            price=Decimal('100000.00'),
            variant_name=self.variant.name,
        )

        result = ensure_website_order_workflow(order)

        self.assertEqual(result['client'].orders.get(), order)
        self.assertEqual(result['deal'].deal_type, ManagerDeal.DEAL_SALE_FROM_STOCK)
        self.assertEqual(result['deal'].stock_warehouse, self.warehouse)
        reservation_item = ReservationItem.objects.get(order_item=order_item)
        self.assertEqual(reservation_item.variant, self.variant)
        self.assertEqual(reservation_item.reservation.source_warehouse, self.warehouse)

    def test_receive_cargo_item_updates_procurement_linked_to_order_item(self):
        order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            payment_method=Order.PAYMENT_METHOD_ONLINE,
            total=Decimal('100000.00'),
            phone='+7 999 555 44 00',
            email='supply@example.com',
            first_name='Supply',
            city_text='Екатеринбург',
            delivery_type=Order.DELIVERY_CDEK_PVZ,
            address_line='ПВЗ',
        )
        order_item = OrderItem.objects.create(
            order=order,
            product=self.product,
            variant=self.variant,
            quantity=2,
            price=Decimal('100000.00'),
            variant_name=self.variant.name,
            is_on_request=True,
        )
        ensure_manager_deal_for_order(order)
        purchase = Purchase.objects.create(date=timezone.localdate(), supplier_name='Supplier')
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            variant=self.variant,
            order_item=order_item,
            quantity=2,
            price=Decimal('70000.00'),
        )
        cargo = Cargo.objects.create(
            cargo_number='CG-LINK-1',
            status=Cargo.STATUS_AWAITING_RECEIPT,
            destination_warehouse=self.warehouse,
        )
        cargo_item = CargoItem.objects.create(
            cargo=cargo,
            product=self.product,
            variant=self.variant,
            purchase_item=purchase_item,
            quantity=2,
        )

        receive_cargo_item(cargo_item, quantity=2, author=self.staff_user)

        purchase_item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(purchase_item.received_quantity, 2)
        self.assertEqual(order.manager_deal.deal_status, ManagerDeal.DEAL_STATUS_RECEIVED)

    def test_create_or_update_shipment_for_order_builds_document(self):
        reservation = self.create_reservation(
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
            linked_order=self.order,
        )
        reservation_item = ReservationItem.objects.create(
            reservation=reservation,
            order_item=self.order.items.get(),
            product=self.product,
            quantity=1,
        )

        shipment = create_or_update_shipment_for_order(self.order, reservation=reservation, tracking_number='TRACK-1')

        self.assertEqual(shipment.order, self.order)
        self.assertIn(self.order, shipment.client.orders.all())
        self.assertEqual(shipment.items.get().reservation_item, reservation_item)
        self.assertEqual(shipment.tracking_number, 'TRACK-1')

    def test_receive_cargo_item_rejects_missing_destination_warehouse(self):
        cargo = Cargo.objects.create(cargo_number='CG-005', status=Cargo.STATUS_AWAITING_RECEIPT)
        cargo_item = CargoItem.objects.create(cargo=cargo, product=self.product, quantity=2)

        with self.assertRaisesMessage(ValueError, 'У груза не указан склад назначения.'):
            receive_cargo_item(cargo_item, quantity=1, author=self.staff_user)

    def test_receive_cargo_item_rejects_over_receipt(self):
        cargo = Cargo.objects.create(
            cargo_number='CG-006',
            status=Cargo.STATUS_AWAITING_RECEIPT,
            destination_warehouse=self.warehouse,
        )
        cargo_item = CargoItem.objects.create(cargo=cargo, product=self.product, quantity=2)

        with self.assertRaisesMessage(ValueError, 'Нельзя принять больше, чем осталось в грузе.'):
            receive_cargo_item(cargo_item, quantity=3, author=self.staff_user)

    def test_split_cargo_rejects_quantity_equal_to_remaining(self):
        cargo = Cargo.objects.create(
            cargo_number='CG-007',
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
        )
        cargo_item = CargoItem.objects.create(cargo=cargo, product=self.product, quantity=2)

        with self.assertRaisesMessage(ValueError, 'Для split количество должно быть меньше остатка по позиции.'):
            split_cargo(cargo, cargo_number='CG-007B', cargo_item=cargo_item, quantity=2)


class ManagerPortalViewTests(ManagerPortalBaseTestCase):
    def test_purchase_list_filters_by_russian_date_range(self):
        self.login_staff()
        old_purchase = Purchase.objects.create(
            date=timezone.localdate() - timedelta(days=20),
            supplier_name='Старый поставщик',
        )
        matching_purchase = Purchase.objects.create(
            date=timezone.localdate() - timedelta(days=4),
            supplier_name='Новый поставщик',
        )

        response = self.client.get(
            reverse('manager_portal:purchase_list'),
            {
                'date_from': (timezone.localdate() - timedelta(days=10)).strftime('%d.%m.%Y'),
                'date_to': timezone.localdate().strftime('%d.%m.%Y'),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(matching_purchase, response.context['purchases'])
        self.assertNotIn(old_purchase, response.context['purchases'])

    def test_cargo_list_filters_by_eta_date_range(self):
        self.login_staff()
        old_cargo = Cargo.objects.create(
            destination_warehouse=self.warehouse,
            eta=timezone.localdate() - timedelta(days=12),
        )
        matching_cargo = Cargo.objects.create(
            destination_warehouse=self.warehouse,
            eta=timezone.localdate() - timedelta(days=2),
        )

        response = self.client.get(
            reverse('manager_portal:cargo_list'),
            {'date_from': (timezone.localdate() - timedelta(days=7)).strftime('%d.%m.%Y')},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(matching_cargo, response.context['cargos'])
        self.assertNotIn(old_cargo, response.context['cargos'])

    def test_reservation_list_filters_by_created_at_date_range(self):
        self.login_staff()
        old_reservation = self.create_reservation(source_warehouse=self.warehouse)
        matching_reservation = self.create_reservation(source_warehouse=self.warehouse)
        Reservation.objects.filter(pk=old_reservation.pk).update(created_at=timezone.now() - timedelta(days=14))
        Reservation.objects.filter(pk=matching_reservation.pk).update(created_at=timezone.now() - timedelta(days=2))
        old_reservation.refresh_from_db()
        matching_reservation.refresh_from_db()

        response = self.client.get(
            reverse('manager_portal:reservation_list'),
            {'date_from': (timezone.localdate() - timedelta(days=7)).strftime('%d.%m.%Y')},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(matching_reservation, response.context['reservations'])
        self.assertNotIn(old_reservation, response.context['reservations'])

    def test_shipments_view_filters_by_created_at_date_range(self):
        self.login_staff()
        old_reservation = self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
        )
        ReservationItem.objects.create(reservation=old_reservation, product=self.product, quantity=1)
        matching_reservation = self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
        )
        ReservationItem.objects.create(reservation=matching_reservation, product=self.product, quantity=1)
        Reservation.objects.filter(pk=old_reservation.pk).update(created_at=timezone.now() - timedelta(days=14))
        Reservation.objects.filter(pk=matching_reservation.pk).update(created_at=timezone.now() - timedelta(days=1))
        old_shipment = Shipment.objects.create(order=self.order, client=self.manager_client, source_warehouse=self.warehouse)
        matching_shipment = Shipment.objects.create(order=self.order, client=self.manager_client, source_warehouse=self.warehouse)
        Shipment.objects.filter(pk=old_shipment.pk).update(created_at=timezone.now() - timedelta(days=14))
        Shipment.objects.filter(pk=matching_shipment.pk).update(created_at=timezone.now() - timedelta(days=1))
        old_shipment.refresh_from_db()
        matching_shipment.refresh_from_db()

        response = self.client.get(
            reverse('manager_portal:shipments'),
            {'date_from': (timezone.localdate() - timedelta(days=7)).strftime('%d.%m.%Y')},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(matching_shipment, response.context['shipments'])
        self.assertNotIn(old_shipment, response.context['shipments'])
        self.assertEqual(len(response.context['grouped_rows']), 1)
        self.assertEqual(response.context['grouped_rows'][0]['reservation'], matching_reservation)

    def test_commercial_proposals_search_returns_empty_list_for_short_query(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:commercial_proposals_search'), {'q': 'M'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_commercial_proposals_post_without_products_redirects_back(self):
        self.login_staff()

        response = self.client.post(reverse('manager_portal:commercial_proposals'), {'export_format': 'html'})

        self.assertRedirects(response, reverse('manager_portal:commercial_proposals'))

    @override_settings(SITE_URL='http://localhost:8000')
    def test_commercial_proposal_html_export_downloads_attachment(self):
        self.login_staff()
        self.staff_user.first_name = 'Ярослав'
        self.staff_user.last_name = 'Едигарьев'
        self.staff_user.save(update_fields=['first_name', 'last_name'])
        CommercialProposalContact.objects.create(
            user=self.staff_user,
            phone='+7 900 123 45 67',
            email='kp@example.com',
        )
        self.product.description = 'Подробное описание шлема для коммерческого предложения.'
        self.product.save(update_fields=['description'])

        response = self.client.post(
            reverse('manager_portal:commercial_proposals'),
            {
                'products': [str(self.product.pk)],
                f'qty_{self.product.pk}': '0',
                f'price_{self.product.pk}': '-10',
                'export_format': 'html',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/html; charset=utf-8')
        self.assertIn('attachment; filename="commercial_proposal_', response['Content-Disposition'])
        self.assertIn('.html"', response['Content-Disposition'])
        content = response.content.decode('utf-8')
        self.assertIn('Коммерческое предложение', content)
        self.assertIn('Meta Quest 3', content)
        self.assertIn('Едигарьев Ярослав', content)
        self.assertIn('+7 900 123 45 67', content)
        self.assertIn('https://bizonvr.ru', content)
        self.assertNotIn('http://localhost:8000', content)
        self.assertIn('100 000 ₽', content)

    def test_commercial_proposal_pdf_export_downloads_attachment(self):
        self.login_staff()

        with patch('weasyprint.HTML.write_pdf', return_value=b'%PDF-test%') as write_pdf_mock:
            response = self.client.post(
                reverse('manager_portal:commercial_proposals'),
                {
                    'products': [str(self.product.pk)],
                    f'qty_{self.product.pk}': '2',
                    f'price_{self.product.pk}': '99999',
                    'export_format': 'pdf',
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment; filename="commercial_proposal_', response['Content-Disposition'])
        self.assertIn('.pdf"', response['Content-Disposition'])
        self.assertEqual(response.content, b'%PDF-test%')
        write_pdf_mock.assert_called_once()

    def test_commercial_proposal_pdf_failure_falls_back_to_html_download(self):
        self.login_staff()

        with patch('weasyprint.HTML.write_pdf', side_effect=RuntimeError('boom')):
            response = self.client.post(
                reverse('manager_portal:commercial_proposals'),
                {
                    'products': [str(self.product.pk)],
                    f'qty_{self.product.pk}': '1',
                    f'price_{self.product.pk}': '100000',
                    'export_format': 'pdf',
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/html; charset=utf-8')
        self.assertIn('.html"', response['Content-Disposition'])
        self.assertIn('Meta Quest 3', response.content.decode('utf-8'))

    def test_order_list_filters_by_combined_query(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)
        deal_two = ensure_manager_deal_for_order(self.order_two)

        response = self.client.get(
            reverse('manager_portal:deal_list'),
            {
                'q': self.order_two.phone[-4:],
                'payment_state': ManagerDeal.PAYMENT_STATE_PAID,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['deals'].values_list('pk', flat=True)), [deal_two.pk])
        self.assertEqual(response.context['total_deals'], 1)

    def test_order_alias_routes_redirect_to_canonical_deal_routes(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        list_response = self.client.get(reverse('manager_portal:order_list'))
        detail_response = self.client.get(reverse('manager_portal:order_detail', kwargs={'pk': self.order.pk}))

        self.assertRedirects(list_response, reverse('manager_portal:deal_list'))
        self.assertRedirects(detail_response, reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

    def test_deal_list_hides_bulk_toolbar_until_selection(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="bulk-toolbar"', html=False)
        self.assertContains(response, 'class="manager-bulk-toolbar"', html=False)
        self.assertContains(response, 'Снять выделение')
        self.assertContains(response, '>Экспорт</button>', html=False)
        self.assertNotContains(response, 'Экспорт selection')

    def test_manager_pages_include_navigation_progress_assets(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'https://unpkg.com/nprogress@0.2.0/nprogress.css', html=False)
        self.assertContains(response, 'https://unpkg.com/nprogress@0.2.0/nprogress.js', html=False)
        self.assertContains(response, 'manager-portal:navigation-pending', html=False)
        self.assertContains(response, 'showSpinner: false', html=False)

    def test_deal_list_bulk_assign_updates_responsible_manager(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        second_manager = User.objects.create_user(username='79990001199', password='pass1234', is_staff=True)

        response = self.client.post(
            reverse('manager_portal:deal_list'),
            {
                'action': 'bulk_assign',
                'deal_ids': str(deal.pk),
                'responsible_manager': second_manager.pk,
            },
        )

        self.assertRedirects(response, reverse('manager_portal:deal_list'))
        deal.refresh_from_db()
        self.assertEqual(deal.responsible_manager, second_manager)
        self.assertIsNotNone(deal.assigned_at)

    def test_deal_list_bulk_case_status_updates_case_status(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.post(
            reverse('manager_portal:deal_list'),
            {
                'action': 'bulk_case_status',
                'deal_ids': str(deal.pk),
                'case_status': ManagerDeal.CASE_STATUS_IN_PROGRESS,
            },
        )

        self.assertRedirects(response, reverse('manager_portal:deal_list'))
        deal.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(deal.case_status, ManagerDeal.CASE_STATUS_IN_PROGRESS)
        self.assertEqual(self.order.status, Order.STATUS_CONFIRMED)

    def test_deal_list_can_render_kanban_view(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.case_status = ManagerDeal.CASE_STATUS_CONFIRMED
        deal.save(update_fields=['case_status', 'updated_at'])

        response = self.client.get(reverse('manager_portal:deal_list'), {'view': 'kanban'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-manager-deal-board', html=False)
        self.assertContains(response, 'data-deal-card', html=False)
        self.assertContains(response, deal.customer_name)
        self.assertContains(response, deal.get_case_status_display())

    def test_deal_list_kanban_excludes_avito_and_avito_has_table_view(self):
        self.login_staff()
        regular_deal = ensure_manager_deal_for_order(self.order)
        avito_deal = ensure_manager_deal_for_order(self.order_two)
        ManagerDeal.objects.filter(pk=regular_deal.pk).update(
            deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
            deal_status=ManagerDeal.DEAL_STATUS_NEW,
            case_status=ManagerDeal.CASE_STATUS_CONFIRMED,
        )
        ManagerDeal.objects.filter(pk=avito_deal.pk).update(
            deal_type=ManagerDeal.DEAL_AVITO,
            deal_status=ManagerDeal.DEAL_STATUS_NEW,
            case_status=ManagerDeal.CASE_STATUS_CONFIRMED,
        )
        regular_deal.refresh_from_db()
        avito_deal.refresh_from_db()

        response = self.client.get(reverse('manager_portal:deal_list'), {'view': 'kanban'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Сделки / Заказы')
        self.assertContains(response, 'Канбан')
        self.assertContains(response, regular_deal.customer_name)
        self.assertNotContains(response, avito_deal.customer_name)

        avito_response = self.client.get(
            reverse('manager_portal:deal_list'),
            {'scope': 'avito'},
        )
        self.assertEqual(avito_response.status_code, 200)
        self.assertNotContains(avito_response, 'data-manager-deal-board', html=False)
        self.assertContains(avito_response, '>Avito<', html=False)
        self.assertEqual(
            [stat['label'] for stat in avito_response.context['page_header_stats']],
            ['Найдено', 'Страница'],
        )
        self.assertContains(avito_response, avito_deal.customer_name)
        self.assertNotContains(avito_response, regular_deal.customer_name)

    def test_deal_move_view_updates_case_status_and_returns_card_html(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.post(
            reverse('manager_portal:deal_move', kwargs={'pk': deal.pk}),
            {
                'case_status': ManagerDeal.CASE_STATUS_IN_PROGRESS,
                'return_query': 'view=kanban',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode('utf-8'))
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['case_status'], ManagerDeal.CASE_STATUS_IN_PROGRESS)
        self.assertIn('data-deal-card', payload['html'])
        deal.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(deal.case_status, ManagerDeal.CASE_STATUS_IN_PROGRESS)
        self.assertEqual(self.order.status, Order.STATUS_CONFIRMED)

    def test_deal_list_bulk_export_returns_csv_for_selected_deals(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.post(
            reverse('manager_portal:deal_list'),
            {
                'action': 'bulk_export',
                'deal_ids': str(deal.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment;', response['Content-Disposition'])
        content = response.content.decode('utf-8-sig')
        self.assertIn(str(deal.order_id), content)
        self.assertIn(deal.next_step_label, content)

    def test_deal_list_sorts_by_sla_due_at(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal_two = ensure_manager_deal_for_order(self.order_two)
        now = timezone.now()
        ManagerDeal.objects.filter(pk=deal.pk).update(
            sla_due_at=now + timedelta(days=2),
            last_activity_at=now - timedelta(hours=3),
        )
        ManagerDeal.objects.filter(pk=deal_two.pk).update(
            sla_due_at=now + timedelta(hours=1),
            last_activity_at=now - timedelta(hours=1),
        )

        response = self.client.get(reverse('manager_portal:deal_list'), {'sort': 'sla_due_at'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['deals'].values_list('pk', flat=True)), [deal_two.pk, deal.pk])

    def test_deal_list_sorts_by_last_activity_at(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal_two = ensure_manager_deal_for_order(self.order_two)
        now = timezone.now()
        ManagerDeal.objects.filter(pk=deal.pk).update(
            sla_due_at=now + timedelta(days=1),
            last_activity_at=now - timedelta(days=1),
        )
        ManagerDeal.objects.filter(pk=deal_two.pk).update(
            sla_due_at=now + timedelta(days=2),
            last_activity_at=now - timedelta(minutes=15),
        )

        response = self.client.get(reverse('manager_portal:deal_list'), {'sort': '-last_activity_at'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['deals'].values_list('pk', flat=True)), [deal_two.pk, deal.pk])

    def test_deal_list_filters_unassigned_problematic_and_action_today(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal_two = ensure_manager_deal_for_order(self.order_two)
        now = timezone.now()
        ManagerDeal.objects.filter(pk=deal.pk).update(
            responsible_manager=None,
            case_status=ManagerDeal.CASE_STATUS_IN_PROGRESS,
            problem_flags=[ManagerDeal.PROBLEM_FLAG_PAYMENT_BLOCKED],
            sla_due_at=now,
            last_activity_at=now,
        )
        ManagerDeal.objects.filter(pk=deal_two.pk).update(
            responsible_manager=self.staff_user,
            case_status=ManagerDeal.CASE_STATUS_IN_PROGRESS,
            problem_flags=[],
            sla_due_at=now + timedelta(days=3),
            last_activity_at=now - timedelta(hours=2),
        )

        response = self.client.get(
            reverse('manager_portal:deal_list'),
            {
                'only_unassigned': '1',
                'only_problematic': '1',
                'action_today': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['deals'].values_list('pk', flat=True)), [deal.pk])
        self.assertEqual(response.context['active_queue_chip'], '')
        self.assertTrue(response.context['deal_advanced_filters_open'])

    def test_deal_list_problem_view_filters_reserved_unpaid(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal_two = ensure_manager_deal_for_order(self.order_two)
        now = timezone.now()
        ManagerDeal.objects.filter(pk=deal.pk).update(
            case_status=ManagerDeal.CASE_STATUS_IN_PROGRESS,
            fulfillment_status=ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK,
            payment_state=ManagerDeal.PAYMENT_STATE_UNPAID,
            reserve_created_at=now - timedelta(hours=50),
        )
        ManagerDeal.objects.filter(pk=deal_two.pk).update(
            case_status=ManagerDeal.CASE_STATUS_IN_PROGRESS,
            fulfillment_status=ManagerDeal.FULFILLMENT_STATUS_RESERVED_STOCK,
            payment_state=ManagerDeal.PAYMENT_STATE_PAID,
            reserve_created_at=now - timedelta(hours=50),
        )

        response = self.client.get(
            reverse('manager_portal:deal_list'),
            {'problem_view': 'reserved_unpaid'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['deals'].values_list('pk', flat=True)), [deal.pk])
        self.assertContains(response, 'Активные фильтры')

    def test_deal_list_overview_separates_kpis_queues_and_signals(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [metric['label'] for metric in response.context['deal_kpis']],
            ['Новые', 'Подтверждены', 'В работе', 'Ждут клиента', 'Готовы к отправке'],
        )
        self.assertEqual(
            [metric['query_string'] for metric in response.context['deal_kpis']],
            [
                'case_status=new',
                'case_status=confirmed',
                'case_status=in_progress',
                'case_status=waiting_client',
                'case_status=ready_to_ship',
            ],
        )
        self.assertEqual(
            [chip['label'] for chip in response.context['queue_chips']],
            ['В работе', 'Без ответственного', 'Ждут оплату', 'Ждут резерв', 'Ждут документы', 'Готовы к отгрузке', 'Проблемные'],
        )
        self.assertEqual(
            [stat['label'] for stat in response.context['page_header_stats']],
            ['Найдено', 'Страница'],
        )
        self.assertEqual(response.context['active_filter_chips'], [])
        self.assertFalse(response.context['problem_views_expanded'])
        self.assertContains(response, 'Очереди')
        self.assertContains(response, 'Фильтры')

    def test_deal_list_header_exposes_saved_views_and_filter_search(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)
        DealSavedView.objects.create(
            owner=self.staff_user,
            name='Ждут оплату',
            query_string='queue=needs_payment',
        )

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Компактная строка по этапам')
        self.assertContains(response, 'Быстрый поиск по фильтрам')
        self.assertContains(response, 'data-filter-search-input', html=False)
        self.assertContains(response, 'data-scroll-fade', html=False)
        self.assertContains(response, 'Ждут оплату')
        self.assertContains(response, 'queue=needs_payment', html=False)
        self.assertContains(response, 'manager-deals-saved-views-trigger', html=False)
        self.assertFalse(response.context['deal_kpi_panel_open'])

    def test_deal_list_status_kpis_show_weekly_trend_and_filter_by_case_status(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)
        previous_order = self.create_order(
            phone='+7 999 310 00 11',
            email='previous-new@example.com',
            first_name='Прошлый',
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_COURIER,
            created_at=timezone.now() - timedelta(days=10),
        )
        extra_recent_order = self.create_order(
            phone='+7 999 310 00 22',
            email='recent-new@example.com',
            first_name='Текущий',
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_COURIER,
            created_at=timezone.now() - timedelta(days=1),
        )
        confirmed_order = self.create_order(
            phone='+7 999 310 00 33',
            email='confirmed@example.com',
            first_name='Подтвержденный',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_COURIER,
            created_at=timezone.now() - timedelta(days=2),
        )
        ensure_manager_deal_for_order(previous_order)
        ensure_manager_deal_for_order(extra_recent_order)
        confirmed_deal = ensure_manager_deal_for_order(confirmed_order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        metrics = {metric['status']: metric for metric in response.context['deal_kpis']}
        new_metric = metrics[ManagerDeal.CASE_STATUS_NEW]
        confirmed_metric = metrics[ManagerDeal.CASE_STATUS_CONFIRMED]
        self.assertEqual(new_metric['count'], 3)
        self.assertEqual(new_metric['query_string'], 'case_status=new')
        self.assertEqual(new_metric['trend']['direction'], 'up')
        self.assertEqual(new_metric['trend']['text'], '+100% к прошлой неделе')
        self.assertEqual(new_metric['trend']['current_period_count'], 2)
        self.assertEqual(new_metric['trend']['previous_period_count'], 1)
        self.assertFalse(confirmed_metric['is_active'])
        self.assertContains(response, '+100% к прошлой неделе')

        filtered_response = self.client.get(
            reverse('manager_portal:deal_list'),
            {'case_status': ManagerDeal.CASE_STATUS_CONFIRMED},
        )

        self.assertEqual(filtered_response.status_code, 200)
        self.assertEqual(list(filtered_response.context['deals'].values_list('pk', flat=True)), [confirmed_deal.pk])
        filtered_metrics = {metric['status']: metric for metric in filtered_response.context['deal_kpis']}
        self.assertTrue(filtered_metrics[ManagerDeal.CASE_STATUS_CONFIRMED]['is_active'])
        self.assertTrue(filtered_response.context['deal_kpi_panel_open'])

    def test_deal_list_kanban_cards_show_context_without_opening_detail(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_list'), {'view': 'kanban'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'draggable="true"', html=False)
        self.assertContains(response, self.product.name)
        self.assertContains(response, deal.get_payment_state_display())
        self.assertContains(response, deal.get_fulfillment_status_display())

    def test_deal_list_collapsible_panels_are_closed_without_active_filters(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['deal_advanced_filters_open'])

    def test_deal_list_uses_compact_queue_strip(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [chip['label'] for chip in response.context['queue_chips']],
            ['В работе', 'Без ответственного', 'Ждут оплату', 'Ждут резерв', 'Ждут документы', 'Готовы к отгрузке', 'Проблемные'],
        )
        self.assertContains(response, 'Сделки / Заказы')
        self.assertContains(response, 'Очереди')
        self.assertEqual(response.context['active_queue_chip'], 'all')

    def test_deal_list_wraps_status_kpis_in_mobile_scroller(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'manager-deals-kpi-scroller', html=False)
        self.assertContains(response, 'manager-deals-kpi-grid', html=False)

    def test_deal_list_renders_compact_rows_with_expandable_preview(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        payment_changed_at = timezone.now() - timedelta(hours=3)
        set_manager_deal_paid_amount(
            deal,
            paid_amount=Decimal('25000.00'),
            changed_at=payment_changed_at,
        )

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="deal-compact-list"', html=False)
        self.assertContains(response, 'Сделка')
        self.assertContains(response, 'Клиент / Контекст')
        self.assertContains(response, 'Primary status')
        self.assertContains(response, 'Secondary status')
        self.assertContains(response, 'Риск')
        self.assertContains(response, 'Оплата')
        self.assertContains(response, 'Ответственный')
        self.assertContains(response, 'Действия')
        self.assertContains(response, 'Контекст сделки')
        self.assertContains(response, 'Следующий шаг и блокеры')
        self.assertContains(response, 'Комментарии и логистика')
        self.assertContains(response, 'Канал')
        self.assertContains(response, 'Доставка')
        self.assertContains(response, 'Комментарии')
        self.assertContains(response, f'data-row-toggle="deal-{deal.pk}"', html=False)
        self.assertContains(response, f'data-row-detail="deal-{deal.pk}"', html=False)
        self.assertContains(response, deal.code)
        self.assertContains(response, deal.short_label)
        self.assertContains(response, 'Развернуть строку сделки')
        self.assertContains(response, 'Частично оплачено')
        self.assertContains(response, 'Оплачено')
        self.assertContains(response, 'К оплате')
        self.assertContains(response, 'Последний платеж')
        self.assertContains(response, 'manager-deal-payment-value', html=False)
        self.assertContains(response, 'manager-mobile-deal-payment-card-partial', html=False)
        self.assertNotContains(response, '>Activity<', html=False)
        self.assertNotContains(response, '>Blockers<', html=False)

    def test_set_manager_deal_paid_amount_updates_and_clears_last_payment_at(self):
        deal = ensure_manager_deal_for_order(self.order)
        first_payment_at = timezone.now() - timedelta(hours=4)
        second_payment_at = first_payment_at + timedelta(hours=2)

        set_manager_deal_paid_amount(
            deal,
            paid_amount=Decimal('1000.00'),
            changed_at=first_payment_at,
        )
        deal.refresh_from_db()
        self.assertEqual(deal.prepayment_amount, Decimal('1000.00'))
        self.assertEqual(deal.last_payment_at, first_payment_at)

        set_manager_deal_paid_amount(
            deal,
            paid_amount=Decimal('2500.00'),
            changed_at=second_payment_at,
        )
        deal.refresh_from_db()
        self.assertEqual(deal.prepayment_amount, Decimal('2500.00'))
        self.assertEqual(deal.last_payment_at, second_payment_at)

        set_manager_deal_paid_amount(
            deal,
            paid_amount=Decimal('0.00'),
            changed_at=timezone.now(),
        )
        deal.refresh_from_db()
        self.assertEqual(deal.prepayment_amount, Decimal('0.00'))
        self.assertIsNone(deal.last_payment_at)

    def test_ensure_manager_deal_for_order_sets_last_payment_at_for_paid_site_order(self):
        paid_order = self.create_order(
            phone='+7 999 555 11 22',
            email='paid-sync@example.com',
            first_name='Оплаченный',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_COURIER,
        )
        paid_timestamp = timezone.now() - timedelta(hours=1)
        Order.objects.filter(pk=paid_order.pk).update(updated_at=paid_timestamp)
        paid_order.refresh_from_db()

        deal = ensure_manager_deal_for_order(paid_order)

        self.assertEqual(deal.prepayment_amount, paid_order.total_with_delivery)
        self.assertEqual(deal.last_payment_at, paid_timestamp)

    def test_order_state_update_sets_last_payment_at_from_paid_amount(self):
        self.login_staff()
        manual_order = self.create_order(
            phone='+7 999 123 00 00',
            email='payment-update@example.com',
            first_name='Мария',
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_CDEK_PVZ,
        )
        deal = ManagerDeal.objects.create(
            order=manual_order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
            deal_status=ManagerDeal.DEAL_STATUS_RESERVED,
            buyer_type=ManagerDeal.BUYER_INDIVIDUAL,
            customer_source=ManagerDeal.SOURCE_WEBSITE,
            individual_full_name='Мария Тест',
            individual_phone='+7 999 123 00 00',
            individual_city='Екатеринбург',
            customer_request='Quest 3 128 GB',
            delivery_method=ManagerDeal.DELIVERY_CDEK_PVZ,
            delivery_pickup_address='ПВЗ',
        )

        response = self.client.post(
            reverse('manager_portal:order_state_update', kwargs={'pk': manual_order.pk}),
            {
                'deal_status': ManagerDeal.DEAL_STATUS_RESERVED,
                'payment_status': Order.PAYMENT_STATUS_UNPAID,
                'paid_amount': '3500.00',
                'tracking_number': '',
            },
            follow=True,
        )

        deal.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(deal.prepayment_amount, Decimal('3500.00'))
        self.assertIsNotNone(deal.last_payment_at)

    def test_deal_list_defaults_to_all_queue_chip_without_active_filters(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_queue_chip'], 'all')

    def test_deal_list_defaults_to_active_deals_only(self):
        self.login_staff()
        active_deal = ensure_manager_deal_for_order(self.order)
        ensure_manager_deal_for_order(self.order_two)
        cancelled_order = self.create_order(
            phone='+7 999 555 44 33',
            email='cancelled@example.com',
            first_name='Отмена',
            status=Order.STATUS_CANCELLED,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_COURIER,
        )
        ensure_manager_deal_for_order(cancelled_order)

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['deals'].values_list('pk', flat=True)), [active_deal.pk])
        self.assertEqual(response.context['total_deals'], 1)

    def test_deal_list_completed_filter_includes_cancelled_deals(self):
        self.login_staff()
        active_deal = ensure_manager_deal_for_order(self.order)
        completed_deal = ensure_manager_deal_for_order(self.order_two)
        cancelled_order = self.create_order(
            phone='+7 999 555 00 11',
            email='closed@example.com',
            first_name='Завершение',
            status=Order.STATUS_CANCELLED,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_COURIER,
        )
        cancelled_deal = ensure_manager_deal_for_order(cancelled_order)

        response = self.client.get(
            reverse('manager_portal:deal_list'),
            {'case_status': ManagerDeal.CASE_STATUS_COMPLETED},
        )

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            list(response.context['deals'].values_list('pk', flat=True)),
            [completed_deal.pk, cancelled_deal.pk],
        )
        self.assertNotContains(response, active_deal.code)

    def test_deal_list_uses_pagination_instead_of_first_100_slice(self):
        self.login_staff()
        ensure_manager_deal_for_order(self.order)
        ensure_manager_deal_for_order(self.order_two)
        for index in range(51):
            order = self.create_order(
                phone=f'+7 999 200 {index:02d} 00',
                email=f'bulk-{index}@example.com',
                first_name=f'Клиент {index}',
                status=Order.STATUS_NEW,
                payment_status=Order.PAYMENT_STATUS_UNPAID,
                delivery_type=Order.DELIVERY_COURIER,
            )
            ensure_manager_deal_for_order(order)

        response = self.client.get(reverse('manager_portal:deal_list'), {'page': 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_deals'], 52)
        self.assertEqual(response.context['deals_page'].number, 2)
        self.assertEqual(response.context['deals_page'].paginator.num_pages, 2)
        self.assertEqual(len(response.context['deals_page'].object_list), 2)
        self.assertEqual(response.context['page_header_stats'][1]['label'], 'Страница')
        self.assertEqual(response.context['page_header_stats'][1]['value'], '2 / 2')
        self.assertContains(response, '2 / 2')
        self.assertContains(response, 'Назад')

    def test_deal_list_active_filter_chips_clear_single_filter(self):
        self.login_staff()

        response = self.client.get(
            reverse('manager_portal:deal_list'),
            {
                'q': 'Quest',
                'queue': ManagerDeal.NEXT_STEP_NEEDS_PAYMENT,
                'only_problematic': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [chip['label'] for chip in response.context['active_filter_chips']],
            ['Поиск: Quest', 'Только проблемные'],
        )
        self.assertContains(response, 'Сбросить всё')
        search_chip, problem_chip = response.context['active_filter_chips']
        self.assertEqual(parse_qs(search_chip['clear_query_string']), {'queue': [ManagerDeal.NEXT_STEP_NEEDS_PAYMENT], 'only_problematic': ['1']})
        self.assertEqual(parse_qs(problem_chip['clear_query_string']), {'q': ['Quest'], 'queue': [ManagerDeal.NEXT_STEP_NEEDS_PAYMENT]})

    def test_deal_list_view_switch_links_preserve_queue_and_filters(self):
        self.login_staff()

        response = self.client.get(
            reverse('manager_portal:deal_list'),
            {
                'q': 'Quest',
                'queue': ManagerDeal.NEXT_STEP_NEEDS_PAYMENT,
                'only_problematic': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            parse_qs(response.context['kanban_view_query_string']),
            {
                'q': ['Quest'],
                'queue': [ManagerDeal.NEXT_STEP_NEEDS_PAYMENT],
                'only_problematic': ['1'],
                'view': ['kanban'],
            },
        )
        self.assertEqual(
            parse_qs(response.context['avito_view_query_string']),
            {
                'q': ['Quest'],
                'queue': [ManagerDeal.NEXT_STEP_NEEDS_PAYMENT],
                'only_problematic': ['1'],
                'scope': ['avito'],
            },
        )
        self.assertEqual(
            parse_qs(response.context['list_view_query_string']),
            {
                'q': ['Quest'],
                'queue': [ManagerDeal.NEXT_STEP_NEEDS_PAYMENT],
                'only_problematic': ['1'],
            },
        )

    def test_global_search_results_find_variant_sku(self):
        self.login_staff()
        self.variant.sku = 'MQ3-128'
        self.variant.save(update_fields=['sku'])
        order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            payment_method=Order.PAYMENT_METHOD_ONLINE,
            total=Decimal('100000.00'),
            phone='+7 999 777 66 55',
            email='sku@example.com',
            first_name='SKU',
            city_text='Екатеринбург',
            delivery_type=Order.DELIVERY_CDEK_PVZ,
            address_line='ПВЗ',
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            variant=self.variant,
            quantity=1,
            price=Decimal('100000.00'),
            variant_name=self.variant.name,
        )
        deal = ensure_website_order_workflow(order)['deal']

        response = self.client.get(reverse('manager_portal:global_search_results'), {'q': 'MQ3-128'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'MQ3-128')
        self.assertContains(response, reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

    def test_legacy_deal_search_route_redirects_to_deal_list(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_search'), follow=True)

        self.assertRedirects(response, reverse('manager_portal:deal_list'))
        self.assertContains(response, 'Глобальный поиск открывается по / или Cmd+K.')

    def test_legacy_deal_search_route_preserves_query_in_deal_list_redirect(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_search'), {'q': 'Quest'}, follow=True)

        self.assertRedirects(response, f"{reverse('manager_portal:deal_list')}?q=Quest")
        self.assertContains(response, 'Глобальный поиск открывается по / или Cmd+K.')

    def test_staff_can_open_manual_order_create_page(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:order_create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ручное создание заказа')
        self.assertContains(response, 'Что хочет клиент')
        self.assertContains(response, 'Товары в заказе')
        self.assertContains(response, 'Логистика, резервы и сценарные детали заполняются уже в карточке сделки.')
        self.assertContains(response, 'data-manager-mask="phone"', html=False)
        self.assertContains(response, 'data-manager-date-picker="true"', html=False)
        self.assertContains(response, '@client_username или WhatsApp', html=False)
        self.assertContains(response, 'manual-order-product-catalog', html=False)
        self.assertContains(response, 'manual-order-product-names', html=False)
        self.assertNotContains(response, 'Логистика заказа')
        self.assertNotContains(response, 'Продажа под заказ')
        self.assertNotContains(response, 'Продажа из наличия')
        self.assertNotContains(response, 'Трейд-ин')
        self.assertNotContains(response, 'Продажа Avito')

    def test_order_create_prefills_client_profile_and_latest_items(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.buyer_type = ManagerDeal.BUYER_BUSINESS
        deal.deal_type = ManagerDeal.DEAL_SALE_FROM_STOCK
        deal.deal_status = ManagerDeal.DEAL_STATUS_RESERVED
        deal.customer_source = ManagerDeal.SOURCE_TELEGRAM
        deal.responsible_manager = self.staff_user
        deal.delivery_method = ManagerDeal.DELIVERY_CITY
        deal.delivery_payer = ManagerDeal.DELIVERY_PAYER_INCLUDED
        deal.delivery_from_city = 'Екатеринбург'
        deal.delivery_to_city = 'Тюмень'
        deal.delivery_full_address = 'Тюмень, Ленина, 15'
        deal.shipping_comment = 'Позвонить за час'
        deal.stock_warehouse = self.warehouse
        deal.business_contact_person = 'Иван Петров'
        deal.business_inn = '6677001122'
        deal.business_kpp = '667701001'
        deal.business_ogrn = '1234567890123'
        deal.business_city = 'Екатеринбург'
        deal.business_legal_address = 'Екатеринбург, Ленина, 1'
        deal.business_delivery_address = 'Тюмень, Ленина, 15'
        deal.save()
        order_item = self.order.items.get()
        order_item.purchase_price = Decimal('65000.00')
        order_item.discount_amount = Decimal('1000.00')
        order_item.comment = 'Нужна предпродажная проверка'
        order_item.save(update_fields=['purchase_price', 'discount_amount', 'comment'])

        response = self.client.get(reverse('manager_portal:order_create'), {'client': self.manager_client.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form']['buyer_type'].value(), ManagerDeal.BUYER_BUSINESS)
        self.assertEqual(response.context['form']['customer_source'].value(), ManagerDeal.SOURCE_TELEGRAM)
        first_item_form = response.context['formset'].forms[0]
        self.assertEqual(first_item_form.initial['product_name'], self.product.name)
        self.assertEqual(first_item_form.initial['product'], self.product.pk)
        self.assertEqual(first_item_form.initial['quantity'], 1)
        self.assertEqual(first_item_form.initial['purchase_price'], Decimal('65000.00'))
        self.assertContains(response, 'Последняя сделка')
        self.assertNotContains(response, 'Доставка')
        self.assertNotContains(response, 'Trade-in')

    def test_order_create_renders_short_initial_flow_without_logistics_and_scenario_blocks(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:order_create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Сценарий заказа')
        self.assertContains(response, 'Общие данные')
        self.assertContains(response, 'Что хочет клиент')
        self.assertNotContains(response, 'Логистика заказа')
        self.assertNotContains(response, 'data-deal-section="trade_in"', html=False)
        self.assertNotContains(response, 'data-deal-section="sale_on_request"', html=False)
        self.assertNotContains(response, 'data-deal-section="sale_from_stock"', html=False)
        self.assertNotContains(response, 'data-deal-section="avito_sale"', html=False)

    def test_staff_can_create_manual_business_order(self):
        self.login_staff()
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, quantity=5)

        response = self.client.post(reverse('manager_portal:order_create'), self.manual_business_order_payload())

        manual_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).get()
        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': manual_order.manager_deal.pk}))
        self.assertEqual(manual_order.payment_method, Order.PAYMENT_METHOD_MANAGER_PAYMENT)
        self.assertEqual(manual_order.delivery_type, ManagerDeal.DELIVERY_CDEK_PVZ)
        self.assertEqual(manual_order.total, Decimal('180000.00'))
        self.assertEqual(manual_order.delivery_cost, Decimal('0.00'))
        self.assertEqual(manual_order.recipient_name, 'ООО Вижн')

        line = manual_order.items.get()
        self.assertEqual(line.product_name, self.product.name)
        self.assertEqual(line.condition, OrderItem.CONDITION_NEW)
        self.assertEqual(line.purchase_price, Decimal('70000.00'))
        self.assertEqual(line.discount_amount, Decimal('5000.00'))
        self.assertEqual(line.subtotal, Decimal('180000.00'))

    def test_staff_can_create_manual_order_item_from_name_without_hidden_product(self):
        self.login_staff()
        payload = self.manual_business_order_payload()
        payload['items-0-product'] = ''
        payload['items-0-product_name'] = self.product.name
        payload['items-0-sale_price'] = ''

        response = self.client.post(reverse('manager_portal:order_create'), payload)

        manual_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).latest('pk')
        line = manual_order.items.get()

        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': manual_order.manager_deal.pk}))
        self.assertEqual(line.product, self.product)
        self.assertEqual(line.product_name, self.product.name)
        self.assertEqual(line.price, self.product.price)

    def test_staff_can_create_manual_order_item_without_catalog_match(self):
        self.login_staff()
        payload = self.manual_business_order_payload()
        payload['items-0-product'] = ''
        payload['items-0-product_name'] = 'Индивидуальный комплект клиента'
        payload['items-0-sale_price'] = '12345.00'
        payload['items-0-purchase_price'] = '9000.00'
        payload['items-0-discount_amount'] = '345.00'
        payload['items-0-quantity'] = '3'

        response = self.client.post(reverse('manager_portal:order_create'), payload)

        manual_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).latest('pk')
        line = manual_order.items.get()

        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': manual_order.manager_deal.pk}))
        self.assertIsNone(line.product)
        self.assertEqual(line.product_name, 'Индивидуальный комплект клиента')
        self.assertEqual(line.price, Decimal('12345.00'))
        self.assertEqual(line.subtotal, Decimal('36000.00'))

        deal = manual_order.manager_deal
        self.assertEqual(deal.responsible_manager, self.staff_user)
        self.assertEqual(deal.customer_source, ManagerDeal.SOURCE_AVITO)
        self.assertEqual(deal.business_company_name, 'ООО Вижн')
        self.assertEqual(deal.business_checking_account, '40702810900000000001')
        self.assertEqual(deal.business_bank_name, 'ПАО Сбербанк')
        self.assertEqual(deal.business_bik, '046577674')
        self.assertEqual(deal.business_correspondent_account, '30101810500000000674')
        self.assertEqual(deal.business_telegram, '@vision_finance')
        self.assertEqual(deal.business_whatsapp, '+7 912 000 10 11')
        self.assertEqual(deal.deal_status, ManagerDeal.DEAL_STATUS_NEW)
        self.assertEqual(deal.prepayment_amount, Decimal('30000.00'))
        self.assertIsNone(deal.stock_warehouse)
        self.assertIsNone(deal.reservation)
        self.assertEqual(deal.grand_total, Decimal('180000.00'))
        self.assertEqual(deal.balance_due, Decimal('150000.00'))

    def test_staff_can_create_sale_from_stock_with_stray_trade_in_payload_ignored(self):
        self.login_staff()
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, quantity=5)
        payload = self.manual_business_order_payload()
        payload.update(
            {
                'customer_source': ManagerDeal.SOURCE_WEBSITE,
                'tradein-0-device_type': 'VR шлем',
                'tradein-0-model_name': 'Meta Quest 2',
                'tradein-0-version': '128 GB',
                'tradein-0-kit_description': 'Шлем и контроллеры',
                'tradein-0-condition': 'б/у',
                'tradein-0-defects': 'Потёртости',
                'tradein-0-preliminary_estimate': '30000.00',
                'tradein-0-final_estimate': '25000.00',
            }
        )

        response = self.client.post(reverse('manager_portal:order_create'), payload)

        manual_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).latest('pk')
        deal = manual_order.manager_deal
        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))
        self.assertEqual(deal.deal_type, ManagerDeal.DEAL_SALE_FROM_STOCK)
        self.assertEqual(deal.deal_status, ManagerDeal.DEAL_STATUS_NEW)
        self.assertFalse(deal.trade_in_items.exists())
        self.assertEqual(deal.grand_total, Decimal('180000.00'))
        self.assertEqual(deal.balance_due, Decimal('150000.00'))

    def test_staff_can_create_manual_business_order_via_htmx_redirect(self):
        self.login_staff()
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, quantity=5)

        response = self.client.post(
            reverse('manager_portal:order_create'),
            data=self.manual_business_order_payload(),
            HTTP_HX_REQUEST='true',
        )

        manual_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).get()

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response['HX-Redirect'],
            reverse('manager_portal:deal_detail', kwargs={'pk': manual_order.manager_deal.pk}),
        )

    def test_deal_list_create_cta_links_to_create_page(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Новая сделка', count=1)
        self.assertContains(response, f'href="{reverse("manager_portal:deal_create")}"', html=False)
        self.assertNotContains(response, 'data-drawer-target="#manager-remote-drawer"', html=False)
        self.assertNotContains(response, f'hx-get="{reverse("manager_portal:deal_create")}"', html=False)

    def test_registry_create_pages_render_without_drawer_markup(self):
        self.login_staff()

        for url_name, heading in (
            ('client_create', 'Новый клиент'),
            ('warehouse_create', 'Новый склад'),
            ('purchase_create', 'Новая закупка'),
            ('cargo_create', 'Новый груз'),
            ('reservation_create', 'Новая бронь'),
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(f'manager_portal:{url_name}'))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertNotContains(response, 'data-drawer-target="#manager-remote-drawer"', html=False)
                if url_name != 'client_create':
                    self.assertNotContains(response, 'aria-label="Шаги формы клиента"', html=False)

    def test_client_create_renders_four_sections_with_stepper(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:client_create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Шаги формы клиента"', html=False)
        self.assertContains(response, '4 секции в порядке работы менеджера')
        for heading, count in (
            ('Основное', 2),
            ('Контакты', 2),
            ('Адрес и комментарий', 2),
            ('Связанные заказы', 3),
        ):
            self.assertContains(response, heading, count=count)

        content = response.content.decode('utf-8')
        self.assertLess(content.index('>Имя / компания<'), content.index('>Статус<'))
        self.assertLess(content.index('>Статус<'), content.index('>Пользователь сайта<'))
        self.assertLess(content.index('>Телефон<'), content.index('>Email<'))
        self.assertLess(content.index('>Email<'), content.index('>Telegram<'))
        self.assertLess(content.index('>Адрес<'), content.index('>Комментарий<'))
        self.assertLess(content.index('>Комментарий<'), content.index('>Связанные заказы<', content.index('>Комментарий<')))
        self.assertNotContains(response, '<details class="manager-collapsible-panel', html=False)

    def test_client_create_invalid_post_keeps_section_layout_and_field_errors(self):
        self.login_staff()

        response = self.client.post(
            reverse('manager_portal:client_create'),
            {
                'user': '',
                'name': '',
                'email': 'not-an-email',
                'phone': '+7 900 123 45 67',
                'telegram': '@vip',
                'address': 'Екатеринбург',
                'comments': 'Проверка',
                'status': ManagerClient.STATUS_ACTIVE,
                'orders': [self.order.pk],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Шаги формы клиента"', html=False)
        self.assertContains(response, 'Обязательное поле.')
        self.assertContains(response, 'Введите правильный адрес электронной почты.')
        for section_id in (
            'client-step-basic',
            'client-step-contacts',
            'client-step-address',
            'client-step-orders',
        ):
            self.assertContains(response, f'id="{section_id}"', html=False)

    def test_deal_list_renders_page_context_stats_and_inline_shell_search(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SLA просрочен')
        self.assertContains(response, 'Без ответственного')
        self.assertContains(response, 'Последняя синхронизация')
        self.assertContains(response, 'manager-unified-topbar', html=False)
        self.assertNotContains(response, 'Операционный контур')
        self.assertContains(response, 'id="manager-global-search-input-inline"', html=False)
        self.assertNotContains(response, 'data-global-search-open', html=False)
        self.assertNotContains(response, 'Операционный shell: поиск, быстрые действия, сигналы и общий PostgreSQL всегда наверху.')

    def test_warehouse_list_does_not_render_deal_only_shell_metrics(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:warehouse_list'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'SLA просрочен')
        self.assertNotContains(response, 'Без ответственного')
        self.assertNotContains(response, 'Последняя синхронизация')
        self.assertNotContains(response, 'Операционный shell: поиск, быстрые действия, сигналы и общий PostgreSQL всегда наверху.')

    def test_deal_detail_exposes_related_clients_and_reservations(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        self.manager_client.comments = 'VIP клиент, предпочитает Telegram'
        self.manager_client.save(update_fields=['comments', 'updated_at'])
        reservation = self.create_reservation(
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
            linked_order=self.order,
        )
        reservation.manager_deal = deal
        reservation.save(update_fields=['manager_deal', 'updated_at'])

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['deal_client'], self.manager_client)
        self.assertEqual(response.context['client_comment'], 'VIP клиент, предпочитает Telegram')
        self.assertContains(response, 'Клиент')
        self.assertContains(response, 'Изменить вручную')
        self.assertContains(response, reverse('manager_portal:client_detail', kwargs={'pk': self.manager_client.pk}))
        self.assertEqual(list(response.context['reservations']), [reservation])

    def test_deal_detail_management_form_updates_workflow_and_manual_override(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        second_manager = User.objects.create_user(username='79990001199', password='pass1234', is_staff=True)

        response = self.client.post(
            reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}),
            {
                'action': 'update_management',
                'case_status': ManagerDeal.CASE_STATUS_IN_PROGRESS,
                'responsible_manager': second_manager.pk,
                'customer_deadline': '2026-03-15',
                'next_step_code': ManagerDeal.NEXT_STEP_NEEDS_PAYMENT,
                'manager_comment': 'Ждем оплату по счёту от клиента',
            },
        )

        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))
        deal.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(deal.case_status, ManagerDeal.CASE_STATUS_IN_PROGRESS)
        self.assertEqual(deal.responsible_manager, second_manager)
        self.assertEqual(str(deal.customer_deadline), '2026-03-15')
        self.assertEqual(deal.next_step_source, ManagerDeal.NEXT_STEP_SOURCE_MANUAL)
        self.assertEqual(deal.next_step_code, ManagerDeal.NEXT_STEP_NEEDS_PAYMENT)
        self.assertEqual(deal.next_step_reason_snapshot, 'Ждем оплату по счёту от клиента')

    def test_deal_detail_exposes_related_supply_chain_and_shipments(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        order_item = self.order.items.get()
        purchase = Purchase.objects.create(date=timezone.localdate(), supplier_name='Supplier')
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            order_item=order_item,
            quantity=1,
            price=Decimal('500.00'),
        )
        cargo = Cargo.objects.create(cargo_number='CG-DETAIL-1', destination_warehouse=self.warehouse)
        cargo_item = CargoItem.objects.create(cargo=cargo, product=self.product, purchase_item=purchase_item, quantity=1)
        reservation = self.create_reservation(source_warehouse=self.warehouse, linked_order=self.order)
        reservation_item = ReservationItem.objects.create(
            reservation=reservation,
            order_item=order_item,
            product=self.product,
            quantity=1,
        )
        reservation.manager_deal = deal
        reservation.save(update_fields=['manager_deal', 'updated_at'])
        shipment = Shipment.objects.create(order=self.order, client=self.manager_client, reservation=reservation, manager_deal=deal)
        ShipmentItem.objects.create(shipment=shipment, reservation_item=reservation_item, product=self.product, quantity=1)

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['purchase_items']), [purchase_item])
        self.assertEqual(list(response.context['cargo_items']), [cargo_item])
        self.assertEqual(list(response.context['shipments']), [shipment])
        self.assertEqual(response.context['order_items'][0]['linked_entities'][1]['status'], '1/1')
        self.assertEqual(response.context['order_items'][0]['linked_entities'][2]['status'], '1/1')
        self.assertEqual(response.context['order_items'][0]['linked_entities'][3]['status'], '1/1')
        self.assertEqual(response.context['order_items'][0]['position_status'], 'В отгрузке')
        self.assertEqual(response.context['order_items'][0]['next_step'], 'Контролировать доставку')
        self.assertEqual(response.context['order_items'][0]['quick_actions'][0]['label'], 'Отгрузка')
        self.assertContains(response, 'Обеспечение и поставка')
        self.assertContains(response, 'Ближайший ETA')
        self.assertContains(response, 'Источник проблемы')
        self.assertContains(response, 'Главное действие')
        self.assertContains(response, purchase_item.purchase.code)
        self.assertContains(response, shipment.code)
        self.assertContains(response, 'SKU не заполнен')
        self.assertContains(response, 'PO 1/1')
        self.assertContains(response, 'CG 1/1')
        self.assertContains(response, 'SHP 1/1')
        self.assertContains(response, 'Статус позиции')
        self.assertContains(response, 'В shipment уже 1/1 шт.')
        self.assertContains(response, 'Риск')
        self.assertContains(response, 'Закупки')
        self.assertContains(response, 'Грузы')
        self.assertContains(response, 'Резервы')
        self.assertContains(response, cargo.cargo_number)

    def test_deal_detail_renders_sections_in_workflow_order(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        markers = [
            'id="deal-sticky-header"',
            'id="deal-next-step-panel"',
            'id="deal-tabs"',
            'id="goods"',
            'id="deal-history"',
            'id="deal-side-rail"',
            'id="deal-quick-actions"',
        ]
        content = response.content.decode()
        for marker in markers:
            self.assertIn(marker, content)
        self.assertNotContains(response, 'Контакт и контекст')

    def test_deal_detail_renders_summary_actions_and_compact_meta(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        self.contract_document.delete()

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, deal.code)
        self.assertContains(response, deal.short_label)
        self.assertContains(response, 'Следующий шаг')
        self.assertContains(response, 'Сделка')
        self.assertContains(response, 'Риски')
        self.assertContains(response, 'Дедлайн')
        self.assertContains(response, 'Изменить вручную')
        self.assertContains(response, 'Еще действия')
        self.assertContains(response, 'Обзор')
        self.assertContains(response, 'Снабжение')
        self.assertContains(response, 'Финансы')
        self.assertContains(response, 'История')
        self.assertContains(response, 'Полная история')
        self.assertContains(response, 'Товары заказа')
        self.assertContains(response, 'Короткая финансовая сводка')
        self.assertContains(response, 'Статус позиции')
        self.assertContains(response, 'Обеспечение')
        self.assertContains(response, 'Действия')
        self.assertContains(response, 'Сумма')
        self.assertContains(response, 'Оплачено')
        self.assertContains(response, 'Себестоимость')
        self.assertContains(response, 'Расходы')
        self.assertContains(response, 'Маржа')
        self.assertContains(response, 'Открыть остатки')
        self.assertContains(response, 'Открыть клиента')
        self.assertContains(response, 'Телефон')
        self.assertContains(response, 'Последнее событие')

    def test_deal_detail_shows_row_status_and_quick_actions_for_available_stock(self):
        self.login_staff()
        ProductStock.objects.create(product=self.product, pickup_point=self.pickup_point, quantity=3)
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        row = response.context['order_items'][0]
        self.assertEqual(row['position_status'], 'В наличии')
        self.assertEqual(row['next_step'], 'Создать бронь')
        self.assertEqual(row['quick_actions'][0]['label'], 'Резерв')
        self.assertEqual(row['quick_actions'][1]['label'], 'Открыть остатки')
        self.assertIn(reverse('manager_portal:inventory'), row['quick_actions'][1]['url'])
        self.assertContains(response, 'Свободно 3 шт.')
        self.assertContains(response, 'Резерв')
        self.assertContains(response, 'Открыть остатки')

    def test_identity_fields_persist_on_partial_save(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        ManagerDeal.objects.filter(pk=deal.pk).update(code=None, title='', short_label='')
        deal.refresh_from_db()
        deal.responsible_manager = self.staff_user
        deal.save(update_fields=['responsible_manager', 'updated_at'])
        deal.refresh_from_db()

        self.assertTrue(deal.code.startswith(f'DEAL-{timezone.localdate().year}-'))
        self.assertTrue(deal.title)
        self.assertTrue(deal.short_label)

        self.contract_document.manager_deal = deal
        ContractDocument.objects.filter(pk=self.contract_document.pk).update(number='', short_label='')
        self.contract_document.refresh_from_db()
        self.contract_document.manager_deal = deal
        self.contract_document.save(update_fields=['manager_deal', 'updated_at'])
        self.contract_document.refresh_from_db()

        self.assertTrue(self.contract_document.number.startswith(f'DOG-{deal.code.split("-")[1]}-{deal.code.split("-")[2]}-'))
        self.assertTrue(self.contract_document.short_label)

    def test_deal_detail_overview_shows_latest_event_actor_and_time(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        record_deal_activity(
            deal,
            event_type='comment.added',
            source='user',
            actor=self.staff_user,
            payload={'comment': 'Документ переведен в черновик'},
        )

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Последнее событие')
        self.assertContains(response, 'Комментарий')
        self.assertContains(response, 'Документ переведен в черновик')
        self.assertContains(response, self.staff_user.get_username())

    def test_deal_detail_documents_and_finance_tabs_show_operational_summary(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        self.contract_document.manager_deal = deal
        self.contract_document.save(update_fields=['manager_deal', 'updated_at'])
        finance_deal = FinanceDeal.objects.create(
            manager_deal=deal,
            responsible_manager=self.staff_user,
            linked_document=self.contract_document,
            deal_type=self.finance_deal_type,
            contract_number='FIN-2026-01',
            payment_method='SBP',
            payment_state='paid',
            revenue=Decimal('150000.00'),
            cost_price=Decimal('90000.00'),
            direct_expenses=Decimal('5000.00'),
            manager_bonus=Decimal('2000.00'),
            snapshot_data={'items': [{'sku': 'MQ3'}]},
        )
        FinanceExpense.objects.create(
            manager_deal=deal,
            deal=finance_deal,
            expense_side=FinanceExpense.SIDE_OURS,
            category=self.finance_our_category,
            amount=Decimal('3500.00'),
            created_by=self.staff_user,
        )
        FinancePayout.objects.create(
            manager_deal=deal,
            amount=Decimal('1200.00'),
            comment='Выплата партнеру',
            created_by=self.staff_user,
        )

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Требуется')
        self.assertContains(response, 'Шаблон поставки')
        self.assertContains(response, 'Последний редактор')
        self.assertContains(response, 'Открыть последний документ')
        self.assertContains(response, 'Последние документы')
        self.assertContains(response, 'DOG-2026-0001')
        self.assertContains(response, 'Статус: ОК')
        self.assertContains(response, '100000')
        self.assertContains(response, '90000')
        self.assertContains(response, '5000')
        self.assertContains(response, '53000')
        self.assertContains(response, '3500')
        self.assertContains(response, '1200')
        self.assertContains(response, '51800')
        self.assertContains(response, reverse('manager_portal:finance_payout_list'))

    def test_deal_detail_uses_tab_query_string_for_initial_panel(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}), {'tab': 'finance'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['deal_tab_initial'], 'finance')
        self.assertContains(response, 'data-tab-initial="finance"', html=False)
        self.assertContains(response, 'data-tab-url-key="tab"', html=False)

    def test_deal_detail_related_actions_use_direct_links(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        self.contract_document.delete()

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("manager_portal:deal_reservation_action", kwargs={"pk": deal.pk})}"',
            html=False,
        )
        self.assertContains(
            response,
            f'href="{reverse("manager_portal:deal_document_action", kwargs={"pk": deal.pk, "document_type": "contract"})}"',
            html=False,
        )
        self.assertContains(
            response,
            f'href="{reverse("manager_portal:deal_shipment_action", kwargs={"pk": deal.pk})}"',
            html=False,
        )
        self.assertContains(
            response,
            f'href="{reverse("manager_portal:deal_finance_action", kwargs={"pk": deal.pk})}"',
            html=False,
        )

    def test_deal_list_primary_cta_switches_to_assign_self_for_unassigned_deal(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.responsible_manager = None
        deal.save(update_fields=['responsible_manager', 'updated_at'])

        response = self.client.get(reverse('manager_portal:deal_list'))

        self.assertEqual(response.status_code, 200)
        deal_row = next(row for row in response.context['deals_page'].object_list if row.pk == deal.pk)
        self.assertEqual(deal_row.list_actions['primary_action']['label'], 'Назначить себя')
        self.assertContains(response, 'Назначить себя')

    def test_deal_detail_primary_cta_uses_confirm_form(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.responsible_manager = self.staff_user
        deal.save(update_fields=['responsible_manager', 'updated_at'])

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_step_panel']['primary_action']['label'], 'Подтвердить')
        self.assertEqual(response.context['next_step_panel']['primary_action']['kind'], 'form')
        self.assertContains(response, 'name="action" value="confirm_case"', html=False)

    def test_deal_detail_blockers_render_fix_actions(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.responsible_manager = None
        deal.problem_flags = [
            ManagerDeal.PROBLEM_FLAG_NO_ASSIGNEE,
            ManagerDeal.PROBLEM_FLAG_STOCK_CONFLICT,
            ManagerDeal.PROBLEM_FLAG_MISSING_DOCUMENTS,
        ]
        deal.save(update_fields=['responsible_manager', 'problem_flags', 'updated_at'])
        self.contract_document.delete()

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Назначить себя')
        self.assertContains(response, 'Открыть обеспечение')
        self.assertContains(response, 'Создать договор')
        self.assertContains(response, 'name="action" value="assign_self"', html=False)
        self.assertContains(
            response,
            f'href="{reverse("manager_portal:deal_detail", kwargs={"pk": deal.pk})}?tab=supply#goods"',
            html=False,
        )

    def test_deal_document_action_redirects_to_prefilled_create_when_document_missing(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        self.contract_document.delete()

        response = self.client.get(reverse('manager_portal:deal_document_action', kwargs={'pk': deal.pk, 'document_type': 'contract'}))

        self.assertRedirects(
            response,
            f"{reverse('manager_portal:contracts_create')}?createFromDeal={deal.pk}&document_type=contract",
        )

    def test_deal_finance_action_redirects_to_prefilled_create_when_finance_missing(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:deal_finance_action', kwargs={'pk': deal.pk}))

        self.assertRedirects(
            response,
            f"{reverse('manager_portal:finance_deal_list')}?createFromDeal={deal.pk}",
        )

    def test_contracts_create_prefills_template_profile_and_autofill_summary(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.buyer_type = ManagerDeal.BUYER_BUSINESS
        deal.business_company_name = self.manager_client.name
        deal.business_inn = '6677001122'
        deal.business_kpp = '667701001'
        deal.business_ogrn = '1234567890123'
        deal.business_legal_address = 'Екатеринбург, Ленина, 1'
        deal.responsible_manager = self.staff_user
        deal.save()

        response = self.client.get(
            reverse('manager_portal:contracts_create'),
            {'createFromDeal': deal.pk, 'document_type': ContractTemplate.DOC_TYPE_CONTRACT},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.context['contract_form']['template'].value()), str(self.contract_template.pk))
        self.assertEqual(str(response.context['contract_form']['company_profile'].value()), str(self.contract_profile.pk))
        self.assertEqual(str(response.context['contract_form']['responsible_manager'].value()), str(self.staff_user.pk))
        self.assertContains(response, 'Автозаполнение')
        self.assertContains(response, 'Подтянется автоматически')

    def test_finance_deal_list_prefills_hints_from_deal(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.delivery_payer = ManagerDeal.DELIVERY_PAYER_INCLUDED
        deal.avito_commission = Decimal('500.00')
        deal.responsible_manager = self.staff_user
        deal.save(update_fields=['delivery_payer', 'avito_commission', 'responsible_manager', 'updated_at'])
        self.order.delivery_cost = Decimal('1500.00')
        self.order.save(update_fields=['delivery_cost', 'updated_at'])

        response = self.client.get(reverse('manager_portal:finance_deal_list'), {'createFromDeal': deal.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.context['finance_deal_form']['revenue'].value()), deal.grand_total)
        self.assertContains(response, 'Проверь расход на доставку')

    def test_sale_on_request_state_blocks_supplier_order_without_required_prepayment(self):
        self.login_staff()
        manual_order = self.create_order(
            phone='+7 999 123 00 00',
            email='manual@example.com',
            first_name='Мария',
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_CDEK_PVZ,
        )
        deal = ManagerDeal.objects.create(
            order=manual_order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_SALE_ON_REQUEST,
            deal_status=ManagerDeal.DEAL_STATUS_AWAITING_PREPAYMENT,
            buyer_type=ManagerDeal.BUYER_INDIVIDUAL,
            customer_source=ManagerDeal.SOURCE_WEBSITE,
            individual_full_name='Мария Тест',
            individual_phone='+7 999 123 00 00',
            individual_city='Екатеринбург',
            customer_request='Quest 3 512 GB',
            procurement_origin='Китай',
            supplier_agent='Поставщик',
            prepayment_required_amount=Decimal('5000.00'),
            prepayment_amount=Decimal('0.00'),
            delivery_method=ManagerDeal.DELIVERY_CDEK_PVZ,
            delivery_pickup_address='ПВЗ',
        )

        response = self.client.post(
            reverse('manager_portal:order_state_update', kwargs={'pk': manual_order.pk}),
            {
                'deal_status': ManagerDeal.DEAL_STATUS_SUPPLIER_ORDERED,
                'payment_status': Order.PAYMENT_STATUS_UNPAID,
                'paid_amount': '0',
                'tracking_number': '',
            },
            follow=True,
        )

        deal.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(deal.deal_status, ManagerDeal.DEAL_STATUS_AWAITING_PREPAYMENT)
        messages = list(response.context['messages'])
        self.assertTrue(any('Нельзя запускать закупку без суммы предоплаты' in str(message) for message in messages))

    def test_staff_can_create_sale_on_request_with_stray_trade_in_payload_ignored(self):
        self.login_staff()
        payload = self.manual_business_order_payload()
        payload.update(
            {
                'deal_type': ManagerDeal.DEAL_SALE_ON_REQUEST,
                'deal_status': ManagerDeal.DEAL_STATUS_NEW_REQUEST,
                'customer_source': ManagerDeal.SOURCE_WEBSITE,
                'stock_warehouse': '',
                'customer_request': 'Quest 3 512 GB',
                'procurement_origin': 'Склад партнёра',
                'supplier_agent': 'ИП Поставка',
                'supplier_name': '',
                'tradein-0-device_type': 'VR шлем',
                'tradein-0-model_name': 'Meta Quest 2',
                'tradein-0-version': '128 GB',
                'tradein-0-kit_description': 'Шлем и контроллеры',
                'tradein-0-condition': 'б/у',
                'tradein-0-defects': 'Потёртости',
                'tradein-0-preliminary_estimate': '30000.00',
                'tradein-0-final_estimate': '25000.00',
            }
        )

        response = self.client.post(reverse('manager_portal:order_create'), payload)

        manual_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).latest('pk')
        deal = manual_order.manager_deal
        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))
        self.assertEqual(deal.deal_type, ManagerDeal.DEAL_SALE_ON_REQUEST)
        self.assertFalse(deal.trade_in_items.exists())
        self.assertEqual(deal.grand_total, Decimal('180000.00'))
        self.assertEqual(deal.balance_due, Decimal('150000.00'))

    def test_avito_status_choices_are_compact(self):
        self.assertEqual(
            [code for code, _label in ManagerDeal.allowed_status_choices(ManagerDeal.DEAL_AVITO)],
            [
                ManagerDeal.DEAL_STATUS_NEW,
                ManagerDeal.DEAL_STATUS_SHIPPED,
                ManagerDeal.DEAL_STATUS_RECEIVED_BY_CUSTOMER,
                ManagerDeal.DEAL_STATUS_RETURNED,
            ],
        )

    def test_avito_source_uses_avito_status_choices_even_for_stock_deal(self):
        self.assertEqual(
            [code for code, _label in ManagerDeal.allowed_status_choices(ManagerDeal.DEAL_SALE_FROM_STOCK, ManagerDeal.SOURCE_AVITO)],
            [
                ManagerDeal.DEAL_STATUS_NEW,
                ManagerDeal.DEAL_STATUS_SHIPPED,
                ManagerDeal.DEAL_STATUS_RECEIVED_BY_CUSTOMER,
                ManagerDeal.DEAL_STATUS_RETURNED,
            ],
        )

    def test_staff_can_create_avito_source_order_with_participants(self):
        self.login_staff()
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, quantity=5)
        answered_alias = ManagerPersonAlias.objects.create(display_name='Эрика', slug='erika')
        shipped_alias = ManagerPersonAlias.objects.create(display_name='Ярослав Е', slug='yaroslav-e')
        payload = self.manual_business_order_payload()
        payload.update(
            {
                'buyer_type': ManagerDeal.BUYER_INDIVIDUAL,
                'individual_full_name': 'Иван Avito',
                'individual_phone': '+7 912 000 10 10',
                'individual_additional_phone': '',
                'individual_city': 'Екатеринбург',
                'individual_messenger': '@avito',
                'individual_comment': '',
                'business_company_name': '',
                'business_inn': '',
                'business_kpp': '',
                'business_ogrn': '',
                'business_legal_address': '',
                'business_contact_person': '',
                'business_phone': '',
                'business_email': '',
                'business_city': '',
                'business_comment': '',
                'answered_person_alias': answered_alias.pk,
                'shipped_person_alias': shipped_alias.pk,
            }
        )

        response = self.client.post(reverse('manager_portal:order_create'), payload)

        manual_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).latest('pk')
        deal = manual_order.manager_deal
        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))
        self.assertEqual(deal.customer_source, ManagerDeal.SOURCE_AVITO)
        self.assertEqual(deal.individual_full_name, 'Иван Avito')
        self.assertEqual(deal.deal_status, ManagerDeal.DEAL_STATUS_NEW)
        self.assertTrue(
            ManagerDealParticipant.objects.filter(
                manager_deal=deal,
                role=ManagerDealParticipant.ROLE_ANSWERED,
                person_alias=answered_alias,
                order_item__isnull=True,
            ).exists()
        )
        self.assertTrue(
            ManagerDealParticipant.objects.filter(
                manager_deal=deal,
                role=ManagerDealParticipant.ROLE_SHIPPED,
                person_alias=shipped_alias,
                order_item__isnull=True,
            ).exists()
        )

    def test_order_state_update_allows_avito_shipped_without_tracking_number(self):
        self.login_staff()
        self.order.payment_method = Order.PAYMENT_METHOD_MANAGER_PAYMENT
        self.order.save(update_fields=['payment_method', 'updated_at'])
        deal = ManagerDeal.objects.create(
            order=self.order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_AVITO,
            deal_status=ManagerDeal.DEAL_STATUS_NEW,
            buyer_type=ManagerDeal.BUYER_INDIVIDUAL,
            customer_source=ManagerDeal.SOURCE_AVITO,
            individual_full_name='Иван Тест',
            individual_phone=self.order.phone,
            individual_city='Екатеринбург',
            delivery_method=ManagerDeal.DELIVERY_CDEK_PVZ,
            delivery_pickup_address='Тюмень, ПВЗ',
            avito_listing_url='https://www.avito.ru/item',
            avito_listing_title='Meta Quest 3',
        )

        response = self.client.post(
            reverse('manager_portal:order_state_update', kwargs={'pk': self.order.pk}),
            {
                'deal_status': ManagerDeal.DEAL_STATUS_SHIPPED,
                'payment_status': Order.PAYMENT_STATUS_UNPAID,
                'paid_amount': '0',
                'tracking_number': '',
            },
            follow=True,
        )

        deal.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(deal.deal_status, ManagerDeal.DEAL_STATUS_SHIPPED)
        messages = list(response.context['messages'])
        self.assertTrue(any('Состояние заказа обновлено.' in str(message) for message in messages))

    def test_avito_detail_hides_documents_and_shipment_sections(self):
        self.login_staff()
        self.order.payment_method = Order.PAYMENT_METHOD_MANAGER_PAYMENT
        self.order.save(update_fields=['payment_method', 'updated_at'])
        deal = ManagerDeal.objects.create(
            order=self.order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_AVITO,
            deal_status=ManagerDeal.DEAL_STATUS_NEW,
            buyer_type=ManagerDeal.BUYER_INDIVIDUAL,
            customer_source=ManagerDeal.SOURCE_AVITO,
            individual_full_name='Иван Тест',
            individual_phone=self.order.phone,
            individual_city='Екатеринбург',
            delivery_method=ManagerDeal.DELIVERY_CDEK_PVZ,
            delivery_pickup_address='Тюмень, ПВЗ',
            avito_listing_url='https://www.avito.ru/item',
            avito_listing_title='Meta Quest 3',
        )
        recompute_deal_workflow(deal)

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Договоры и счета внутри карточки сделки.')
        self.assertNotContains(response, 'Отправление еще не создано.')
        self.assertContains(response, 'Финансы')

    def test_avito_return_to_stock_restores_fulfilled_inventory(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=1, author=self.staff_user)
        order = self.create_order(
            phone='+7 999 700 11 22',
            email='avito-return@example.com',
            first_name='Игорь',
            status=Order.STATUS_CONFIRMED,
            payment_status=Order.PAYMENT_STATUS_PAID,
            delivery_type=Order.DELIVERY_CDEK_PVZ,
            pickup_point=self.pickup_point,
        )
        order.payment_method = Order.PAYMENT_METHOD_MANAGER_PAYMENT
        order.save(update_fields=['payment_method', 'updated_at'])
        order_item = order.items.get()
        deal = ManagerDeal.objects.create(
            order=order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_AVITO,
            deal_status=ManagerDeal.DEAL_STATUS_SHIPPED,
            buyer_type=ManagerDeal.BUYER_INDIVIDUAL,
            customer_source=ManagerDeal.SOURCE_AVITO,
            individual_full_name='Игорь Тест',
            individual_phone=order.phone,
            individual_city='Екатеринбург',
            delivery_method=ManagerDeal.DELIVERY_CDEK_PVZ,
            delivery_pickup_address='Тюмень, ПВЗ',
            stock_warehouse=self.warehouse,
            avito_listing_url='https://www.avito.ru/item',
            avito_listing_title='Meta Quest 3',
        )
        reservation = self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            linked_order=order,
        )
        reservation.manager_deal = deal
        reservation.save(update_fields=['manager_deal', 'updated_at'])
        ReservationItem.objects.create(
            reservation=reservation,
            order_item=order_item,
            product=self.product,
            quantity=1,
        )
        create_or_update_reservation_movements(
            reservation,
            movement_type=InventoryMovement.TYPE_RESERVE,
            author=self.staff_user,
            comment='Резерв под Avito-сделку',
        )
        sync_public_stock_for_warehouse(self.warehouse)
        fulfill_reservation(reservation, author=self.staff_user)
        deal.primary_reservation = reservation
        deal.deal_status = ManagerDeal.DEAL_STATUS_RETURNED
        deal.save(update_fields=['primary_reservation', 'deal_status', 'updated_at'])
        order.status = Order.STATUS_CANCELLED
        order.payment_status = Order.PAYMENT_STATUS_REFUNDED
        order.save(update_fields=['status', 'payment_status', 'updated_at'])
        recompute_deal_workflow(deal)

        response = self.client.post(
            reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}),
            {'action': 'return_to_stock'},
            follow=True,
        )

        deal.refresh_from_db()
        balance = InventoryBalance.objects.get(warehouse=self.warehouse, product=self.product, variant__isnull=True)
        stock = ProductStock.objects.get(product=self.product, pickup_point=self.pickup_point, variant__isnull=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(deal.next_step_code, ManagerDeal.NEXT_STEP_COMPLETED)
        self.assertIsNotNone(deal.returned_to_stock_at)
        self.assertEqual(balance.quantity, 1)
        self.assertEqual(stock.quantity, 1)
        self.assertTrue(
            InventoryMovement.objects.filter(
                warehouse=self.warehouse,
                product=self.product,
                movement_type=InventoryMovement.TYPE_RECEIPT,
                reference_type='avito_return',
                reference_id=deal.pk,
            ).exists()
        )

    def test_trade_in_creation_uses_short_form_without_incoming_device_items(self):
        self.login_staff()

        response = self.client.post(
            reverse('manager_portal:order_create'),
            {
                'deal_type': ManagerDeal.DEAL_TRADE_IN,
                'deal_status': ManagerDeal.DEAL_STATUS_AWAITING_EVALUATION,
                'buyer_type': ManagerDeal.BUYER_INDIVIDUAL,
                'responsible_manager': self.staff_user.pk,
                'deal_created_at': '2026-03-10T13:00',
                'customer_source': ManagerDeal.SOURCE_TELEGRAM,
                'deal_comment': 'Trade-in по Telegram',
                'individual_full_name': 'Иван Иванов',
                'individual_phone': '+7 900 100 20 30',
                'individual_additional_phone': '',
                'individual_city': 'Тюмень',
                'individual_messenger': '@ivan',
                'individual_comment': '',
                'customer_request': 'Обменять старый шлем на новый',
                'customer_request_comment': 'Клиент готов отправить завтра',
                'prepayment_required_amount': '0',
                'prepayment_amount': '5000.00',
                'items-TOTAL_FORMS': '1',
                'items-INITIAL_FORMS': '0',
                'items-MIN_NUM_FORMS': '0',
                'items-MAX_NUM_FORMS': '1000',
                'items-0-product': str(self.product.pk),
                'items-0-configuration': '128 GB',
                'items-0-condition': OrderItem.CONDITION_NEW,
                'items-0-quantity': '1',
                'items-0-purchase_price': '70000.00',
                'items-0-sale_price': '100000.00',
                'items-0-discount_amount': '0',
                'items-0-comment': '',
            },
        )

        trade_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk]).latest('pk')
        self.assertRedirects(response, reverse('manager_portal:deal_detail', kwargs={'pk': trade_order.manager_deal.pk}))
        deal = trade_order.manager_deal
        self.assertEqual(deal.deal_type, ManagerDeal.DEAL_TRADE_IN)
        self.assertFalse(deal.trade_in_items.exists())
        self.assertEqual(deal.trade_in_value, Decimal('0.00'))
        self.assertEqual(deal.grand_total, Decimal('100000.00'))
        self.assertEqual(deal.balance_due, Decimal('95000.00'))

    def test_non_trade_in_submission_ignores_prefilled_trade_in_values_from_latest_client_deal(self):
        self.login_staff()
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, quantity=5)
        previous_order = self.create_order(
            phone=self.manager_client.phone,
            email=self.manager_client.email,
            first_name='Клиент',
            status=Order.STATUS_NEW,
            payment_status=Order.PAYMENT_STATUS_UNPAID,
            delivery_type=Order.DELIVERY_CDEK_COURIER,
        )
        self.manager_client.orders.add(previous_order)
        previous_deal = ManagerDeal.objects.create(
            order=previous_order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_TRADE_IN,
            deal_status=ManagerDeal.DEAL_STATUS_AWAITING_EVALUATION,
            buyer_type=ManagerDeal.BUYER_BUSINESS,
            customer_source=ManagerDeal.SOURCE_TELEGRAM,
            business_company_name=self.manager_client.name,
            business_contact_person='Иван Петров',
            business_phone=self.manager_client.phone,
            business_email=self.manager_client.email,
            business_city='Екатеринбург',
            delivery_method=ManagerDeal.DELIVERY_CDEK_COURIER,
            delivery_from_city='Екатеринбург',
            delivery_to_city='Тюмень',
            delivery_full_address='Тюмень, Ленина, 15',
            delivery_payer=ManagerDeal.DELIVERY_PAYER_CLIENT,
            shipment_status=ManagerDeal.SHIPMENT_DRAFT,
        )
        TradeInItem.objects.create(
            deal=previous_deal,
            device_type='VR шлем',
            model_name='Meta Quest 2',
            version='128 GB',
            kit_description='Шлем, контроллеры, ремешок',
            condition='б/у',
            defects='Мелкие потертости',
            preliminary_estimate=Decimal('30000.00'),
            final_estimate=Decimal('28000.00'),
        )

        response = self.client.get(reverse('manager_portal:order_create'), {'client': self.manager_client.pk})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Принимаемая позиция')
        self.assertNotContains(response, 'Meta Quest 2')

        payload = self.manual_business_order_payload()
        payload.update(
            {
                'deal_type': ManagerDeal.DEAL_SALE_FROM_STOCK,
                'customer_source': ManagerDeal.SOURCE_WEBSITE,
                'business_company_name': self.manager_client.name,
                'business_phone': self.manager_client.phone,
                'business_email': self.manager_client.email,
                'tradein-0-device_type': 'VR шлем',
                'tradein-0-model_name': 'Meta Quest 2',
                'tradein-0-version': '128 GB',
                'tradein-0-kit_description': 'Шлем, контроллеры, ремешок',
                'tradein-0-condition': 'б/у',
                'tradein-0-defects': 'Мелкие потертости',
                'tradein-0-preliminary_estimate': '30000.00',
                'tradein-0-final_estimate': '28000.00',
            }
        )

        post_response = self.client.post(reverse('manager_portal:order_create'), payload)

        new_order = Order.objects.exclude(pk__in=[self.order.pk, self.order_two.pk, previous_order.pk]).latest('pk')
        new_deal = new_order.manager_deal
        self.assertRedirects(post_response, reverse('manager_portal:deal_detail', kwargs={'pk': new_deal.pk}))
        self.assertEqual(new_deal.deal_type, ManagerDeal.DEAL_SALE_FROM_STOCK)
        self.assertFalse(new_deal.trade_in_items.exists())
        self.assertEqual(new_deal.grand_total, Decimal('180000.00'))

    def test_client_list_filters_by_orders_and_status(self):
        self.login_staff()
        reserved_client = ManagerClient.objects.create(name='С бронью', status=ManagerClient.STATUS_ACTIVE)
        reservation = self.create_reservation(client=reserved_client, source_warehouse=self.warehouse)
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=1)
        ManagerDeal.objects.create(
            order=self.order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
            deal_status=ManagerDeal.DEAL_STATUS_RESERVED,
            case_status=ManagerDeal.CASE_STATUS_CONFIRMED,
            buyer_type=ManagerDeal.BUYER_BUSINESS,
            customer_source=ManagerDeal.SOURCE_AVITO,
            business_company_name=self.manager_client.name,
            business_contact_person='Иван',
            business_phone=self.manager_client.phone,
            business_email=self.manager_client.email,
            business_city='Екатеринбург',
            last_activity_at=timezone.now(),
        )

        response = self.client.get(
            reverse('manager_portal:client_list'),
            {'has_orders': '1', 'status': ManagerClient.STATUS_ACTIVE},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['clients']), [self.manager_client])
        self.assertEqual(response.context['client_metrics']['with_orders'], 1)

        response = self.client.get(reverse('manager_portal:client_list'), {'has_reservations': '1'})

        self.assertEqual(list(response.context['clients']), [reserved_client])

        response = self.client.get(
            reverse('manager_portal:client_list'),
            {
                'buyer_type': ManagerDeal.BUYER_BUSINESS,
                'customer_source': ManagerDeal.SOURCE_AVITO,
                'responsible_manager': self.staff_user.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['clients']), [self.manager_client])
        self.assertEqual(response.context['highlighted_client'].pk, self.manager_client.pk)
        self.assertEqual(response.context['highlighted_client'].crm_source_label, 'Avito')

    def test_client_list_renders_collapsed_desktop_filters_with_count(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:client_list'), {'q': self.manager_client.name})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['client_filters_count'], 1)
        self.assertContains(response, 'data-client-filters-root')
        self.assertContains(response, 'data-client-filters-open="false"')
        self.assertContains(response, 'data-client-filters-toggle')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'data-client-filters-count')
        self.assertContains(response, 'Активных фильтров: 1')

    def test_client_list_uses_dense_scan_fields_in_directory_and_mobile_card(self):
        self.login_staff()
        self.manager_client.user = self.user
        self.manager_client.comments = 'Просит счёт на юрлицо'
        self.manager_client.save(update_fields=['user', 'comments', 'updated_at'])

        response = self.client.get(
            reverse('manager_portal:client_list'),
            {'client': self.manager_client.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['highlighted_client'].pk, self.manager_client.pk)
        client = response.context['clients'][0]
        self.assertEqual(client.crm_summary_tags, ['Аккаунт', 'Есть комментарий'])
        self.assertEqual(client.list_last_order_label, f'Заказ #{self.order.pk} · {timezone.localtime(self.order.created_at).strftime("%d.%m.%Y")}')
        self.assertContains(response, 'Имя / компания')
        self.assertContains(response, 'Следующее действие')
        self.assertContains(response, 'data-client-row-mobile')
        self.assertNotContains(response, 'manager-client-directory-summary-text')
        self.assertNotContains(response, 'Заказы: 1 · Брони: 0 · Документы: 1')

    def test_client_list_exposes_row_targets_without_inline_actions(self):
        self.login_staff()
        self.manager_client.telegram = '@bizon_client'
        self.manager_client.save(update_fields=['telegram', 'updated_at'])
        deal = ensure_manager_deal_for_order(self.order, responsible_manager=self.staff_user)

        response = self.client.get(reverse('manager_portal:client_list'))

        self.assertEqual(response.status_code, 200)
        client = next(item for item in response.context['clients'] if item.pk == self.manager_client.pk)
        self.assertEqual(client.detail_url, reverse('manager_portal:client_detail', kwargs={'pk': self.manager_client.pk}))
        self.assertEqual(client.phone_href, 'tel:+79120000000')
        self.assertEqual(client.telegram_url, 'https://t.me/bizon_client')
        self.assertTrue(client.can_assign_responsible)
        self.assertEqual(client.latest_deal_id, deal.pk)
        self.assertContains(response, f'data-client-row-desktop="{self.manager_client.pk}"')
        self.assertContains(response, f'data-client-row-mobile="{self.manager_client.pk}"')
        self.assertContains(response, f'href="{client.select_url}"', html=False)
        self.assertContains(response, f'href="{client.detail_url}"', html=False)
        self.assertNotContains(response, 'data-copy-text=')
        self.assertNotContains(response, reverse('manager_portal:client_quick_comment', kwargs={'pk': self.manager_client.pk}))
        self.assertNotContains(response, reverse('manager_portal:client_quick_assign', kwargs={'pk': self.manager_client.pk}))
        self.assertNotContains(response, 'manager-client-directory-actions-cell', html=False)

    def test_client_list_hides_missing_contact_action_text_in_dense_mode(self):
        self.login_staff()
        lead = ManagerClient.objects.create(name='Без контактов', status=ManagerClient.STATUS_ACTIVE)

        response = self.client.get(reverse('manager_portal:client_list'), {'q': lead.name})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Без контактов')
        self.assertNotContains(response, 'Телефон не указан')
        self.assertNotContains(response, 'Telegram не указан')
        self.assertNotContains(response, 'Нет сделки для назначения')

    def test_client_list_hides_empty_preview_column_when_no_rows_match(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:client_list'), {'q': 'несуществующий клиент'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['clients']), [])
        self.assertIsNone(response.context['highlighted_client'])
        self.assertEqual(response.context['client_filters_count'], 1)
        self.assertContains(response, 'По текущему фильтру клиенты не найдены.')
        self.assertNotContains(response, 'Добавьте клиента или ослабьте фильтры, чтобы увидеть preview и быстрые действия.')
        self.assertNotContains(response, 'Карточка клиента')

    def test_client_list_preview_uses_contract_cta_for_document_step(self):
        self.login_staff()
        self.manager_client.comments = 'Нужно быстро подготовить документы и подтвердить реквизиты.'
        self.manager_client.save(update_fields=['comments'])
        deal = ManagerDeal.objects.create(
            order=self.order,
            responsible_manager=None,
            deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
            deal_status=ManagerDeal.DEAL_STATUS_NEW,
            case_status=ManagerDeal.CASE_STATUS_CONFIRMED,
            buyer_type=ManagerDeal.BUYER_BUSINESS,
            customer_source=ManagerDeal.SOURCE_REPEAT,
            business_company_name=self.manager_client.name,
            business_contact_person='Иван',
            business_phone=self.manager_client.phone,
            business_email=self.manager_client.email,
            business_city='Екатеринбург',
            next_step_code=ManagerDeal.NEXT_STEP_NEEDS_DOCUMENTS,
            next_step_reason_snapshot='Для заказа требуется договорный пакет.',
            prepayment_amount=Decimal('30000.00'),
            last_activity_at=timezone.now(),
            problem_flags=['documents_missing'],
        )

        response = self.client.get(reverse('manager_portal:client_list'), {'client': self.manager_client.pk})

        self.assertEqual(response.status_code, 200)
        highlighted_client = response.context['highlighted_client']
        self.assertEqual(highlighted_client.preview_primary_action['label'], 'Подготовить договор')
        self.assertEqual(highlighted_client.preview_finance['sum_total'], deal.grand_total)
        self.assertEqual(highlighted_client.preview_finance['amount_paid'], deal.amount_paid)
        self.assertEqual(highlighted_client.preview_finance['balance_due'], deal.balance_due)
        self.assertEqual(highlighted_client.preview_finance['payment_status_label'], self.order.get_payment_status_display())
        self.assertIn('Назначить себя', [action['label'] for action in highlighted_client.preview_secondary_actions])
        self.assertContains(response, 'Основное')
        self.assertContains(response, 'Активная сделка')
        self.assertContains(response, 'Финансы')
        self.assertContains(response, 'Последние действия')
        self.assertContains(response, 'Документы и брони')

    def test_client_list_preview_uses_open_deal_cta_for_existing_deal(self):
        self.login_staff()
        ManagerDeal.objects.create(
            order=self.order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
            deal_status=ManagerDeal.DEAL_STATUS_RESERVED,
            case_status=ManagerDeal.CASE_STATUS_CONFIRMED,
            buyer_type=ManagerDeal.BUYER_BUSINESS,
            customer_source=ManagerDeal.SOURCE_AVITO,
            business_company_name=self.manager_client.name,
            business_contact_person='Иван',
            business_phone=self.manager_client.phone,
            business_email=self.manager_client.email,
            business_city='Екатеринбург',
            next_step_code=ManagerDeal.NEXT_STEP_NEEDS_PAYMENT,
            next_step_reason_snapshot='Ждем оплату от клиента.',
            last_activity_at=timezone.now(),
        )

        response = self.client.get(reverse('manager_portal:client_list'), {'client': self.manager_client.pk})

        self.assertEqual(response.status_code, 200)
        highlighted_client = response.context['highlighted_client']
        secondary_labels = [action['label'] for action in highlighted_client.preview_secondary_actions]
        self.assertEqual(highlighted_client.preview_primary_action['label'], 'Открыть сделку')
        self.assertIn('Запросить оплату', secondary_labels)
        self.assertNotIn('Открыть сделку', secondary_labels)

    def test_client_list_preview_uses_create_order_cta_without_deal(self):
        self.login_staff()
        client_without_deal = ManagerClient.objects.create(
            name='Клиент без сделки',
            email='new@example.com',
            phone='+7 912 555 44 33',
            comments='Ждет первый заказ.',
            status=ManagerClient.STATUS_ACTIVE,
        )
        client_without_deal.orders.add(self.order_two)

        response = self.client.get(reverse('manager_portal:client_list'), {'client': client_without_deal.pk})

        self.assertEqual(response.status_code, 200)
        highlighted_client = response.context['highlighted_client']
        self.assertEqual(highlighted_client.preview_primary_action['label'], 'Создать заказ')
        self.assertEqual(highlighted_client.preview_finance['sum_total'], self.order_two.total_to_pay)
        self.assertIsNone(highlighted_client.preview_finance['amount_paid'])
        self.assertIsNone(highlighted_client.preview_finance['balance_due'])
        self.assertEqual(highlighted_client.preview_finance['payment_status_label'], self.order_two.get_payment_status_display())

    def test_client_list_renders_compact_scan_fields_and_row_targets(self):
        self.login_staff()
        ManagerDeal.objects.create(
            order=self.order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
            deal_status=ManagerDeal.DEAL_STATUS_AWAITING_PAYMENT,
            case_status=ManagerDeal.CASE_STATUS_CONFIRMED,
            buyer_type=ManagerDeal.BUYER_BUSINESS,
            customer_source=ManagerDeal.SOURCE_AVITO,
            next_step_code=ManagerDeal.NEXT_STEP_NEEDS_PAYMENT,
            problem_flags=[ManagerDeal.PROBLEM_FLAG_PAYMENT_BLOCKED],
            business_company_name=self.manager_client.name,
            business_contact_person='Иван',
            business_phone=self.manager_client.phone,
            business_email=self.manager_client.email,
            business_city='Екатеринбург',
            last_activity_at=timezone.now(),
        )

        response = self.client.get(reverse('manager_portal:client_list'), {'client': self.manager_client.pk})

        self.assertEqual(response.status_code, 200)
        client = response.context['clients'][0]
        self.assertEqual(client.list_client_type_label, 'Юр. лицо')
        self.assertEqual(client.list_main_status_label, 'Ожидает оплату')
        self.assertEqual(client.list_responsible_label, self.staff_user.username)
        self.assertEqual(client.list_next_action_label, 'Получить оплату')
        self.assertEqual(client.list_risk_label, 'Блокировка оплаты')
        self.assertTrue(client.list_last_order_label.startswith(f'Заказ #{self.order.pk}'))
        self.assertContains(response, 'Имя / компания')
        self.assertContains(response, f'data-client-row-desktop="{self.manager_client.pk}"')
        self.assertContains(response, f'data-client-row-mobile="{self.manager_client.pk}"')
        self.assertContains(response, 'Блокировка оплаты')

    def test_client_list_uses_fallback_values_when_client_has_no_deals(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:client_list'), {'status': ManagerClient.STATUS_ARCHIVED})

        self.assertEqual(response.status_code, 200)
        client = response.context['clients'][0]
        self.assertEqual(client, self.archived_client)
        self.assertEqual(client.list_main_status_label, 'Архив')
        self.assertEqual(client.list_last_order_label, 'Без заказов')
        self.assertEqual(client.list_next_action_label, 'Нет действия')
        self.assertEqual(client.list_risk_label, '—')

    def test_deal_create_prefills_from_client_query(self):
        self.login_staff()
        ManagerDeal.objects.create(
            order=self.order,
            responsible_manager=self.staff_user,
            deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
            deal_status=ManagerDeal.DEAL_STATUS_RESERVED,
            case_status=ManagerDeal.CASE_STATUS_CONFIRMED,
            buyer_type=ManagerDeal.BUYER_BUSINESS,
            customer_source=ManagerDeal.SOURCE_REPEAT,
            business_company_name=self.manager_client.name,
            business_contact_person='Иван',
            business_phone=self.manager_client.phone,
            business_email=self.manager_client.email,
            business_city='Екатеринбург',
            last_activity_at=timezone.now(),
        )

        response = self.client.get(reverse('manager_portal:deal_create'), {'client': self.manager_client.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form']['buyer_type'].value(), ManagerDeal.BUYER_BUSINESS)
        self.assertEqual(response.context['form']['customer_source'].value(), ManagerDeal.SOURCE_REPEAT)
        self.assertEqual(response.context['form']['business_company_name'].value(), self.manager_client.name)
        self.assertEqual(response.context['form']['business_phone'].value(), self.manager_client.phone)

    def test_client_detail_post_updates_client(self):
        self.login_staff()

        response = self.client.post(
            reverse('manager_portal:client_detail', kwargs={'pk': self.manager_client.pk}),
            {
                'user': '',
                'name': 'ООО Обновлено',
                'email': 'new@example.com',
                'phone': '+7 900 123 45 67',
                'telegram': '@new',
                'address': 'Екатеринбург',
                'comments': 'VIP',
                'status': ManagerClient.STATUS_ACTIVE,
                'orders': [self.order.pk, self.order_two.pk],
            },
        )

        self.assertRedirects(response, reverse('manager_portal:client_detail', kwargs={'pk': self.manager_client.pk}))
        self.manager_client.refresh_from_db()
        self.assertEqual(self.manager_client.name, 'ООО Обновлено')
        self.assertEqual(set(self.manager_client.orders.values_list('pk', flat=True)), {self.order.pk, self.order_two.pk})

    def test_client_quick_comment_appends_note_and_redirects_to_next(self):
        self.login_staff()
        self.manager_client.comments = 'Старый комментарий'
        self.manager_client.save(update_fields=['comments', 'updated_at'])
        next_url = f"{reverse('manager_portal:client_list')}?client={self.manager_client.pk}"

        response = self.client.post(
            reverse('manager_portal:client_quick_comment', kwargs={'pk': self.manager_client.pk}),
            {
                'comment': 'Новый комментарий',
                'next': next_url,
            },
        )

        self.assertRedirects(response, next_url)
        self.manager_client.refresh_from_db()
        self.assertIn('Новый комментарий', self.manager_client.comments)
        self.assertIn('Старый комментарий', self.manager_client.comments)
        self.assertTrue(self.manager_client.comments.index('Новый комментарий') < self.manager_client.comments.index('Старый комментарий'))

    def test_client_quick_assign_updates_latest_deal_manager(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        second_manager = User.objects.create_user(username='79990001144', password='pass1234', is_staff=True)
        next_url = f"{reverse('manager_portal:client_list')}?client={self.manager_client.pk}"

        response = self.client.post(
            reverse('manager_portal:client_quick_assign', kwargs={'pk': self.manager_client.pk}),
            {
                'responsible_manager': second_manager.pk,
                'next': next_url,
            },
        )

        self.assertRedirects(response, next_url)
        deal.refresh_from_db()
        self.assertEqual(deal.responsible_manager, second_manager)

    def test_client_quick_assign_without_deal_renders_fallback_and_does_not_assign(self):
        self.login_staff()
        lead = ManagerClient.objects.create(name='Без сделки', status=ManagerClient.STATUS_ACTIVE)
        next_url = f"{reverse('manager_portal:client_list')}?client={lead.pk}"

        response = self.client.get(reverse('manager_portal:client_quick_assign', kwargs={'pk': lead.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Быстрое назначение работает только через последнюю сделку клиента.')
        self.assertContains(response, f"{reverse('manager_portal:deal_create')}?client={lead.pk}", html=False)

        response = self.client.post(
            reverse('manager_portal:client_quick_assign', kwargs={'pk': lead.pk}),
            {
                'responsible_manager': self.staff_user.pk,
                'next': next_url,
            },
        )

        self.assertRedirects(response, next_url)
        self.assertFalse(ManagerDeal.objects.filter(order__manager_client_links=lead).exists())

    def test_warehouse_list_filters_by_status_and_public_link(self):
        self.login_staff()
        self.unlinked_warehouse.is_active = False
        self.unlinked_warehouse.save(update_fields=['is_active'])

        response = self.client.get(
            reverse('manager_portal:warehouse_list'),
            {'status': 'inactive', 'public_link': 'unlinked'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([card['instance'] for card in response.context['warehouses']], [self.unlinked_warehouse])

    def test_warehouse_list_applies_quick_filters_and_builds_summary(self):
        self.login_staff()
        self.warehouse.address = 'Екатеринбург, ул. Ленина, 1'
        self.other_warehouse.address = 'Тюмень, ул. Республики, 10'
        self.warehouse.save(update_fields=['address'])
        self.other_warehouse.save(update_fields=['address'])
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=1, author=self.staff_user)
        reservation = self.create_reservation(source_warehouse=self.warehouse)
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=2)

        response = self.client.get(reverse('manager_portal:warehouse_list'))

        self.assertContains(response, 'data-warehouse-summary-filter="only_missing_address"', html=False)
        self.assertContains(response, f'data-warehouse-actions="{self.warehouse.pk}"', html=False)
        self.assertContains(response, 'title="Остаток на сайте еще не синхронизирован"', html=False)

        response = self.client.get(reverse('manager_portal:warehouse_list'), {'only_unlinked': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([card['instance'] for card in response.context['warehouses']], [self.unlinked_warehouse])
        self.assertEqual(response.context['warehouse_summary']['total'], 1)
        self.assertEqual(response.context['warehouse_summary']['unlinked_count'], 1)
        self.assertEqual(response.context['warehouse_summary']['missing_address_count'], 1)
        self.assertTrue(next(badge['active'] for badge in response.context['summary_badges'] if badge['key'] == 'only_unlinked'))

        response = self.client.get(reverse('manager_portal:warehouse_list'), {'only_missing_address': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([card['instance'] for card in response.context['warehouses']], [self.unlinked_warehouse])
        self.assertTrue(next(badge['active'] for badge in response.context['summary_badges'] if badge['key'] == 'only_missing_address'))

        response = self.client.get(reverse('manager_portal:warehouse_list'), {'only_problematic': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([card['instance'] for card in response.context['warehouses']], [self.warehouse])
        self.assertEqual(response.context['warehouse_summary']['critical_signal_count'], 1)
        self.assertTrue(next(chip['active'] for chip in response.context['quick_filters'] if chip['key'] == 'only_problematic'))

    def test_warehouse_detail_post_updates_and_syncs_public_stock(self):
        self.login_staff()

        with patch('manager_portal.views.sync_public_stock_for_warehouse') as sync_mock:
            response = self.client.post(
                reverse('manager_portal:warehouse_detail', kwargs={'pk': self.warehouse.pk}),
                {
                    'name': 'Склад ЕКБ Updated',
                    'address': 'ул. Ленина, 1',
                    'pickup_point': self.pickup_point.pk,
                    'is_active': 'on',
                },
            )

        self.assertRedirects(response, reverse('manager_portal:warehouse_detail', kwargs={'pk': self.warehouse.pk}))
        self.warehouse.refresh_from_db()
        self.assertEqual(self.warehouse.name, 'Склад ЕКБ Updated')
        sync_mock.assert_called_once_with(self.warehouse)

    def test_inventory_view_filters_problematic_rows(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=1, author=self.staff_user)
        reservation = self.create_reservation(source_warehouse=self.warehouse)
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=2)
        receipt_inventory(warehouse=self.other_warehouse, product=self.product_two, quantity=4, author=self.staff_user)

        response = self.client.get(
            reverse('manager_portal:inventory'),
            {
                'warehouse': self.warehouse.pk,
                'problematic': '1',
                'q': 'quest',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['inventory_rows']), 1)
        self.assertEqual(response.context['inventory_rows'][0]['available'], -1)

    def test_inventory_receipt_page_prefills_selected_warehouse(self):
        self.login_staff()

        response = self.client.get(
            reverse('manager_portal:inventory_receipt'),
            {
                'warehouse': self.warehouse.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial['warehouse'], self.warehouse)
        self.assertContains(response, 'Ручной приход')
        self.assertContains(response, self.warehouse.name)

    def test_inventory_view_keeps_advanced_filters_collapsed_by_default(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:inventory'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['inventory_filters_open'])
        self.assertEqual(response.context['inventory_advanced_filter_count'], 0)
        self.assertFalse(response.context['inventory_problem_filters_open'])

    def test_inventory_view_supports_quick_product_search(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=2, author=self.staff_user)
        receipt_inventory(warehouse=self.other_warehouse, product=self.product_two, quantity=3, author=self.staff_user)

        response = self.client.get(
            reverse('manager_portal:inventory'),
            {
                'product_q': 'quest 3',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['inventory_rows']), 1)
        self.assertEqual(response.context['inventory_rows'][0]['product_id'], self.product.pk)
        self.assertEqual(response.context['product_search'], 'quest 3')
        self.assertFalse(response.context['inventory_filters_open'])
        self.assertEqual(response.context['inventory_advanced_filter_count'], 0)

    def test_inventory_view_supports_precise_problem_filters_and_summary(self):
        self.login_staff()
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, quantity=3, min_stock=5)
        sync_public_stock_for_warehouse(self.warehouse)
        ProductStock.objects.filter(
            product=self.product,
            pickup_point=self.pickup_point,
            variant__isnull=True,
        ).update(quantity=1)
        receipt_inventory(warehouse=self.other_warehouse, product=self.product_two, quantity=4, author=self.staff_user)

        response = self.client.get(
            reverse('manager_portal:inventory'),
            {
                'below_min_stock': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['inventory_rows']), 1)
        self.assertEqual(response.context['inventory_rows'][0]['warehouse_id'], self.warehouse.pk)
        self.assertEqual(response.context['selected_problem_filters'], ['below_min_stock'])
        self.assertEqual(response.context['inventory_summary']['problem_sku_count'], 1)
        self.assertEqual(response.context['inventory_summary']['sellable_sku_count'], 1)
        self.assertEqual(response.context['inventory_summary']['below_min_stock_count'], 1)
        self.assertEqual(response.context['inventory_summary']['negative_available_count'], 0)
        self.assertEqual(response.context['inventory_summary']['public_mismatch_count'], 1)
        self.assertTrue(response.context['inventory_filters_open'])
        self.assertTrue(response.context['inventory_problem_filters_open'])
        self.assertEqual(response.context['inventory_advanced_filter_count'], 1)

    def test_inventory_view_rows_include_operational_details(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=5, author=self.staff_user, comment='Стартовый приход')
        deal = ensure_manager_deal_for_order(self.order)
        reservation = self.create_reservation(source_warehouse=self.warehouse)
        reservation.manager_deal = deal
        reservation.save(update_fields=['manager_deal', 'updated_at'])
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=2)
        purchase = Purchase.objects.create(date=timezone.localdate(), supplier_name='Supplier')
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            order_item=self.order.items.get(),
            quantity=4,
        )
        cargo = Cargo.objects.create(
            cargo_number='CG-DETAIL',
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
        )
        CargoItem.objects.create(
            cargo=cargo,
            product=self.product,
            purchase_item=purchase_item,
            quantity=4,
        )

        response = self.client.get(
            reverse('manager_portal:inventory'),
            {'warehouse': self.warehouse.pk, 'q': 'quest'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['inventory_rows']), 1)
        row = response.context['inventory_rows'][0]
        self.assertEqual(len(row['active_reservations']), 1)
        self.assertGreaterEqual(len(row['recent_movements']), 1)
        self.assertEqual(len(row['incoming_cargos']), 1)
        self.assertGreaterEqual(len(row['linked_deals']), 1)
        self.assertEqual(row['last_change']['author_name'], self.staff_user.username)
        self.assertEqual(row['row_status']['code'], 'site_mismatch')
        self.assertEqual(row['promise_capacity'], 7)
        self.assertGreaterEqual(len(row['detail_reasons']), 3)

    def test_inventory_view_highlights_low_stock_rows(self):
        self.login_staff()
        InventoryBalance.objects.create(warehouse=self.warehouse, product=self.product, quantity=2, min_stock=5)

        response = self.client.get(reverse('manager_portal:inventory'))

        self.assertEqual(response.status_code, 200)
        row = response.context['inventory_rows'][0]
        self.assertContains(response, 'manager-risk-block-attention')
        self.assertTrue(row['is_low_stock'])
        self.assertEqual(row['row_status']['tone'], 'attention')
        self.assertEqual(row['risk_summary']['tone'], 'attention')

    def test_inventory_view_exports_csv_for_current_slice(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=2, author=self.staff_user)
        receipt_inventory(warehouse=self.other_warehouse, product=self.product_two, quantity=3, author=self.staff_user)

        response = self.client.get(
            reverse('manager_portal:inventory'),
            {
                'product_q': 'quest',
                'export': 'csv',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="inventory-', response['Content-Disposition'])
        decoded = response.content.decode('utf-8-sig')
        rows = list(csv.reader(decoded.splitlines()))
        self.assertEqual(rows[0][0], 'Склад')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], self.product.name)

    def test_inventory_view_exports_excel_for_current_slice(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=2, author=self.staff_user)

        response = self.client.get(
            reverse('manager_portal:inventory'),
            {
                'product_q': 'quest',
                'export': 'excel',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertIn('.xlsx"', response['Content-Disposition'])
        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook.active
        self.assertEqual(sheet.title, 'Inventory')
        self.assertEqual(sheet['A1'].value, 'Склад')
        self.assertEqual(sheet['B2'].value, self.product.name)

    def test_inventory_receipt_view_creates_balance_and_movement(self):
        self.login_staff()

        response = self.client.post(
            reverse('manager_portal:inventory_receipt'),
            {
                'warehouse': self.warehouse.pk,
                'product': self.product.pk,
                'variant': '',
                'quantity': 5,
                'comment': 'Ручной приход',
            },
        )

        self.assertRedirects(response, f"{reverse('manager_portal:inventory')}?warehouse={self.warehouse.pk}")
        balance = InventoryBalance.objects.get(warehouse=self.warehouse, product=self.product, variant__isnull=True)
        movement = InventoryMovement.objects.get(warehouse=self.warehouse, product=self.product)
        self.assertEqual(balance.quantity, 5)
        self.assertEqual(movement.movement_type, InventoryMovement.TYPE_RECEIPT)
        self.assertEqual(movement.comment, 'Ручной приход')

    def test_purchase_create_view_creates_purchase(self):
        self.login_staff()

        response = self.client.post(
            reverse('manager_portal:purchase_create'),
            {
                'date': timezone.localdate().isoformat(),
                'supplier_name': 'Shenzhen Supplier',
                'agent': 'Ирина',
                'status': Purchase.STATUS_ORDERED,
                'currency': 'CNY',
                'total_amount': '1000.00',
                'comments': 'Первая закупка',
            },
        )

        purchase = Purchase.objects.get(supplier_name='Shenzhen Supplier')
        self.assertRedirects(response, reverse('manager_portal:purchase_detail', kwargs={'pk': purchase.pk}))

    def test_purchase_list_hides_filter_reset_without_active_filters(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:purchase_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_filter_count'], 0)
        self.assertEqual(response.context['active_filter_chips'], [])
        self.assertFalse(response.context['show_filter_panel'])
        self.assertContains(response, 'Создать первую закупку')
        self.assertNotContains(response, 'Сбросить все фильтры')

    def test_purchase_list_shows_active_filter_indicators(self):
        self.login_staff()
        purchase_date = timezone.localdate()
        Purchase.objects.create(
            date=purchase_date,
            supplier_name='Shenzhen Supplier',
            status=Purchase.STATUS_ORDERED,
        )

        response = self.client.get(
            reverse('manager_portal:purchase_list'),
            {
                'q': 'Shenzhen',
                'status': Purchase.STATUS_ORDERED,
                'date_from': purchase_date.isoformat(),
                'date_to': purchase_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_filter_count'], 4)
        self.assertEqual(
            [chip['label'] for chip in response.context['active_filter_chips']],
            [
                'Поиск: Shenzhen',
                'Статус: Заказано',
                f'Дата от: {purchase_date:%d.%m.%Y}',
                f'Дата до: {purchase_date:%d.%m.%Y}',
            ],
        )
        self.assertEqual(response.context['clear_all_filters_url'], reverse('manager_portal:purchase_list'))
        self.assertContains(response, 'Фильтры (4)')
        self.assertContains(response, 'Сбросить все фильтры')
        self.assertContains(response, 'Поиск: Shenzhen')
        self.assertContains(response, 'Статус: Заказано')

    def test_registry_pages_show_empty_cta_instead_of_filters_without_records(self):
        self.login_staff()

        responses = [
            self.client.get(reverse('manager_portal:purchase_list')),
            self.client.get(reverse('manager_portal:cargo_list')),
            self.client.get(reverse('manager_portal:reservation_list')),
            self.client.get(reverse('manager_portal:shipments')),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context['show_filter_panel'])
            self.assertNotContains(response, 'Фильтры')

        self.assertContains(responses[0], 'Создать первую закупку')
        self.assertContains(responses[1], 'Создать первый груз')
        self.assertContains(responses[2], 'Создать первую бронь')
        self.assertContains(responses[3], 'Открыть бронирования')

    def test_purchase_list_keeps_filters_visible_for_empty_filtered_slice(self):
        self.login_staff()

        response = self.client.get(reverse('manager_portal:purchase_list'), {'q': 'nothing'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['show_filter_panel'])
        self.assertContains(response, 'Фильтры (1)')
        self.assertContains(response, 'Закупки не найдены')

    def test_purchase_list_renders_calendar_trigger_for_filter_dates(self):
        self.login_staff()
        Purchase.objects.create(date=timezone.localdate(), supplier_name='Supplier')

        response = self.client.get(reverse('manager_portal:purchase_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-manager-date-picker-trigger')
        self.assertContains(response, 'manager-date-picker-shell')

    def test_purchase_add_item_view_creates_item(self):
        self.login_staff()
        purchase = Purchase.objects.create(date=timezone.localdate(), supplier_name='Supplier')

        response = self.client.post(
            reverse('manager_portal:purchase_add_item', kwargs={'pk': purchase.pk}),
            {
                'product': self.product.pk,
                'variant': self.variant.pk,
                'quantity': 3,
                'price': '500.00',
            },
        )

        self.assertRedirects(response, reverse('manager_portal:purchase_detail', kwargs={'pk': purchase.pk}))
        item = purchase.items.get()
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.variant, self.variant)
        self.assertEqual(item.quantity, 3)

    def test_cargo_list_filters_overdue_and_reservations(self):
        self.login_staff()
        matching_cargo = Cargo.objects.create(
            cargo_number='CG-100',
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
            eta=timezone.localdate() - timedelta(days=2),
        )
        CargoItem.objects.create(cargo=matching_cargo, product=self.product, quantity=5)
        other_cargo = Cargo.objects.create(
            cargo_number='CG-101',
            status=Cargo.STATUS_CREATED,
            destination_warehouse=self.warehouse,
        )
        reservation = self.create_reservation(source_type=Reservation.SOURCE_CARGO, source_cargo=matching_cargo)
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=1)
        CargoItem.objects.create(cargo=other_cargo, product=self.product, quantity=1)

        response = self.client.get(
            reverse('manager_portal:cargo_list'),
            {'overdue': 'on', 'has_reservations': 'on'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['cargos']), [matching_cargo])
        self.assertEqual(response.context['overdue_count'], 1)
        self.assertEqual(response.context['active_filter_count'], 2)
        self.assertEqual(
            [chip['label'] for chip in response.context['active_filter_chips']],
            ['Просрочен по ETA', 'Есть брони'],
        )
        self.assertContains(response, 'Фильтры (2)')
        self.assertContains(response, 'Сбросить все фильтры')

    def test_cargo_add_item_view_creates_item(self):
        self.login_staff()
        cargo = Cargo.objects.create(cargo_number='CG-102', destination_warehouse=self.warehouse)

        response = self.client.post(
            reverse('manager_portal:cargo_add_item', kwargs={'pk': cargo.pk}),
            {
                'product': self.product.pk,
                'variant': self.variant.pk,
                'quantity': 4,
            },
        )

        self.assertRedirects(response, reverse('manager_portal:cargo_detail', kwargs={'pk': cargo.pk}))
        self.assertEqual(cargo.items.get().quantity, 4)

    def test_cargo_receive_item_view_invalid_quantity_keeps_state(self):
        self.login_staff()
        cargo = Cargo.objects.create(
            cargo_number='CG-103',
            status=Cargo.STATUS_AWAITING_RECEIPT,
            destination_warehouse=self.warehouse,
        )
        item = CargoItem.objects.create(cargo=cargo, product=self.product, quantity=4)

        response = self.client.post(
            reverse('manager_portal:cargo_receive_item', kwargs={'pk': cargo.pk, 'item_id': item.pk}),
            {'quantity': 0},
        )

        self.assertRedirects(response, reverse('manager_portal:cargo_detail', kwargs={'pk': cargo.pk}))
        item.refresh_from_db()
        self.assertEqual(item.received_quantity, 0)
        self.assertFalse(InventoryBalance.objects.exists())

    def test_cargo_split_view_creates_split_cargo(self):
        self.login_staff()
        cargo = Cargo.objects.create(
            cargo_number='CG-104',
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
        )
        item = CargoItem.objects.create(cargo=cargo, product=self.product, quantity=6)

        response = self.client.post(
            reverse('manager_portal:cargo_split', kwargs={'pk': cargo.pk}),
            {
                'cargo_number': 'CG-104B',
                'item': item.pk,
                'quantity': 2,
            },
        )

        self.assertRedirects(response, reverse('manager_portal:cargo_detail', kwargs={'pk': cargo.pk}))
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)
        self.assertTrue(Cargo.objects.filter(cargo_number='CG-104B').exists())

    def test_cargo_add_photo_view_uploads_photo(self):
        self.login_staff()
        cargo = Cargo.objects.create(cargo_number='CG-105', destination_warehouse=self.warehouse)

        response = self.client.post(
            reverse('manager_portal:cargo_add_photo', kwargs={'pk': cargo.pk}),
            {'image': self.make_test_image(), 'caption': 'Фото коробки'},
        )

        self.assertRedirects(response, reverse('manager_portal:cargo_detail', kwargs={'pk': cargo.pk}))
        photo = CargoPhoto.objects.get(cargo=cargo)
        self.assertEqual(photo.caption, 'Фото коробки')

    def test_cargo_add_leg_view_creates_leg(self):
        self.login_staff()
        cargo = Cargo.objects.create(cargo_number='CG-106', destination_warehouse=self.warehouse)

        response = self.client.post(
            reverse('manager_portal:cargo_add_leg', kwargs={'pk': cargo.pk}),
            {
                'from_location': 'Шэньчжэнь',
                'to_warehouse': self.warehouse.pk,
                'method': 'air',
                'track_number': 'TRACK-1',
                'cost': '700.00',
                'status': TransportLeg.STATUS_IN_TRANSIT,
                'departed_at': '',
                'arrived_at': '',
                'comments': 'Первый этап',
            },
        )

        self.assertRedirects(response, reverse('manager_portal:cargo_detail', kwargs={'pk': cargo.pk}))
        leg = TransportLeg.objects.get(cargo=cargo)
        self.assertEqual(leg.method, 'air')
        self.assertEqual(leg.status, TransportLeg.STATUS_IN_TRANSIT)

    def test_cargo_add_expense_view_creates_expense(self):
        self.login_staff()
        cargo = Cargo.objects.create(cargo_number='CG-107', destination_warehouse=self.warehouse)

        response = self.client.post(
            reverse('manager_portal:cargo_add_expense', kwargs={'pk': cargo.pk}),
            {
                'category': 'delivery',
                'name': 'Доставка до склада',
                'amount': '350.00',
                'date': timezone.localdate().isoformat(),
            },
        )

        self.assertRedirects(response, reverse('manager_portal:cargo_detail', kwargs={'pk': cargo.pk}))
        expense = Expense.objects.get(cargo=cargo)
        self.assertEqual(expense.amount, Decimal('350.00'))

    def test_reservation_list_filters_and_prefills_client(self):
        self.login_staff()
        matching_reservation = self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
        )
        other_reservation = self.create_reservation(
            client=self.archived_client,
            source_warehouse=self.warehouse,
        )

        response = self.client.get(
            reverse('manager_portal:reservation_list'),
            {'client': self.manager_client.pk, 'createFromClient': self.manager_client.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['reservations']), [matching_reservation])
        self.assertEqual(str(response.context['form']['client'].value()), str(self.manager_client.pk))
        self.assertNotIn(other_reservation, response.context['reservations'])
        self.assertEqual(response.context['active_filter_count'], 1)
        self.assertEqual(
            [chip['label'] for chip in response.context['active_filter_chips']],
            [f'Клиент: {self.manager_client.name}'],
        )
        self.assertEqual(
            response.context['clear_all_filters_url'],
            f'{reverse("manager_portal:reservation_list")}?createFromClient={self.manager_client.pk}',
        )
        self.assertContains(response, 'Фильтры (1)')
        self.assertContains(response, 'Сбросить все фильтры')

    def test_reservation_list_collapses_advanced_filters_without_secondary_values(self):
        self.login_staff()
        self.create_reservation(client=self.manager_client, source_warehouse=self.warehouse)

        response = self.client.get(reverse('manager_portal:reservation_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['show_filter_panel'])
        self.assertFalse(response.context['reservation_advanced_filters_open'])
        self.assertContains(response, 'По умолчанию оставлены только поиск и статус.')
        self.assertNotContains(response, '<details class="manager-collapsible-panel" open>', html=False)

    def test_reservation_list_opens_advanced_filters_when_secondary_filter_is_active(self):
        self.login_staff()
        matching_reservation = self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
        )
        self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.warehouse,
        )

        response = self.client.get(
            reverse('manager_portal:reservation_list'),
            {'target_warehouse': self.other_warehouse.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['reservations']), [matching_reservation])
        self.assertTrue(response.context['reservation_advanced_filters_open'])
        self.assertEqual(response.context['reservation_advanced_filter_count'], 1)
        self.assertContains(response, '<details class="manager-collapsible-panel" open>', html=False)

    def test_reservation_create_view_prefills_from_deal(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)

        response = self.client.get(reverse('manager_portal:reservation_create'), {'createFromDeal': deal.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.context['form']['linked_order'].value()), str(deal.order.pk))
        self.assertEqual(str(response.context['form']['client'].value()), str(self.manager_client.pk))
        self.assertContains(response, f'Новая бронь будет связана со сделкой #{deal.order_id}.')
        self.assertContains(response, self.product.name)

    def test_reservation_created_from_deal_autofills_order_items(self):
        self.login_staff()
        deal = ensure_manager_deal_for_order(self.order)
        deal.stock_warehouse = self.warehouse
        deal.save(update_fields=['stock_warehouse', 'updated_at'])

        response = self.client.post(
            reverse('manager_portal:reservation_create'),
            {
                'createFromDeal': deal.pk,
                'client': self.manager_client.pk,
                'linked_order': self.order.pk,
                'status': Reservation.STATUS_DRAFT,
                'source_type': Reservation.SOURCE_WAREHOUSE,
                'source_warehouse': self.warehouse.pk,
                'target_warehouse': self.warehouse.pk,
                'comments': 'Ручной резерв',
            },
        )

        self.assertEqual(
            response.status_code,
            302,
            response.context['form'].errors.as_json() if response.context else response.content.decode(),
        )

        reservation = Reservation.objects.latest('id')

        self.assertRedirects(response, f'{reverse("manager_portal:deal_detail", kwargs={"pk": deal.pk})}#reservation')
        self.assertEqual(reservation.items.count(), 1)
        reservation_item = reservation.items.get()
        self.assertEqual(reservation_item.order_item.order, self.order)
        self.assertEqual(reservation_item.product, self.product)

    def test_reservation_add_item_view_rejects_unavailable_quantity(self):
        self.login_staff()
        reservation = self.create_reservation(source_warehouse=self.warehouse)

        response = self.client.post(
            reverse('manager_portal:reservation_add_item', kwargs={'pk': reservation.pk}),
            {
                'product': self.product.pk,
                'variant': '',
                'quantity': 1,
            },
        )

        self.assertRedirects(response, reverse('manager_portal:reservation_detail', kwargs={'pk': reservation.pk}))
        self.assertFalse(reservation.items.exists())
        self.assertFalse(InventoryMovement.objects.filter(reference_id=reservation.pk).exists())

    def test_reservation_add_item_view_creates_movement_and_updates_public_stock(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=5, author=self.staff_user)
        reservation = self.create_reservation(source_warehouse=self.warehouse)

        response = self.client.post(
            reverse('manager_portal:reservation_add_item', kwargs={'pk': reservation.pk}),
            {
                'product': self.product.pk,
                'variant': '',
                'quantity': 2,
            },
        )

        self.assertRedirects(response, reverse('manager_portal:reservation_detail', kwargs={'pk': reservation.pk}))
        self.assertEqual(reservation.items.get().quantity, 2)
        movement = InventoryMovement.objects.get(reference_id=reservation.pk)
        stock = ProductStock.objects.get(product=self.product, pickup_point=self.pickup_point, variant__isnull=True)
        self.assertEqual(movement.movement_type, InventoryMovement.TYPE_RESERVE)
        self.assertEqual(stock.quantity, 3)
        self.warehouse.refresh_from_db()
        self.assertIsNotNone(self.warehouse.public_stock_synced_at)

    def test_reservation_detail_post_rejects_source_change_without_stock(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=5, author=self.staff_user)
        reservation = self.create_reservation(source_warehouse=self.warehouse, target_warehouse=self.other_warehouse)
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=4)

        response = self.client.post(
            reverse('manager_portal:reservation_detail', kwargs={'pk': reservation.pk}),
            {
                'client': self.manager_client.pk,
                'linked_order': '',
                'status': Reservation.STATUS_ACTIVE,
                'source_type': Reservation.SOURCE_WAREHOUSE,
                'source_warehouse': self.other_warehouse.pk,
                'source_cargo': '',
                'target_warehouse': self.other_warehouse.pk,
                'comments': 'Переносим источник',
            },
        )

        self.assertEqual(response.status_code, 200)
        reservation.refresh_from_db()
        self.assertEqual(reservation.source_warehouse, self.warehouse)

    def test_reservation_status_update_releases_and_reactivates_reserve(self):
        self.login_staff()
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=5, author=self.staff_user)
        reservation = self.create_reservation(source_warehouse=self.warehouse)
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=2)
        sync_public_stock_for_warehouse(self.warehouse)

        response = self.client.post(
            reverse('manager_portal:reservation_status_update', kwargs={'pk': reservation.pk}),
            {'status': Reservation.STATUS_CANCELLED},
        )

        self.assertRedirects(response, reverse('manager_portal:reservation_detail', kwargs={'pk': reservation.pk}))
        release_movement = InventoryMovement.objects.get(reference_id=reservation.pk, movement_type=InventoryMovement.TYPE_RELEASE)
        stock = ProductStock.objects.get(product=self.product, pickup_point=self.pickup_point, variant__isnull=True)
        self.assertEqual(release_movement.quantity, 2)
        self.assertEqual(stock.quantity, 5)

        response = self.client.post(
            reverse('manager_portal:reservation_status_update', kwargs={'pk': reservation.pk}),
            {'status': Reservation.STATUS_ACTIVE},
        )

        self.assertRedirects(response, reverse('manager_portal:reservation_detail', kwargs={'pk': reservation.pk}))
        reserve_movement = InventoryMovement.objects.filter(
            reference_id=reservation.pk,
            movement_type=InventoryMovement.TYPE_RESERVE,
        ).latest('id')
        stock.refresh_from_db()
        self.assertEqual(reserve_movement.quantity, 2)
        self.assertEqual(stock.quantity, 3)

    def test_shipments_view_filters_by_client_and_view_mode(self):
        self.login_staff()
        reservation = self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
        )
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=2)
        other_reservation = self.create_reservation(
            client=self.archived_client,
            source_warehouse=self.other_warehouse,
            target_warehouse=self.warehouse,
        )
        ReservationItem.objects.create(reservation=other_reservation, product=self.product_two, quantity=1)

        response = self.client.get(
            reverse('manager_portal:shipments'),
            {
                'client': self.manager_client.pk,
                'warehouse': self.warehouse.pk,
                'view_mode': 'items',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['view_mode'], 'items')
        self.assertEqual(len(response.context['rows']), 1)
        self.assertEqual(response.context['rows'][0]['reservation'], reservation)
        self.assertEqual(response.context['active_filter_count'], 3)
        self.assertEqual(
            [chip['label'] for chip in response.context['active_filter_chips']],
            [
                f'Склад-источник: {self.warehouse.name}',
                f'Клиент: {self.manager_client.name}',
                'Режим: По позициям',
            ],
        )
        self.assertContains(response, 'Фильтры (3)')
        self.assertContains(response, 'Сбросить все фильтры')
        self.assertContains(response, 'Режим: По позициям')

    def test_registry_pages_render_desktop_tables_and_mobile_cards(self):
        self.login_staff()
        purchase = Purchase.objects.create(
            date=timezone.localdate(),
            supplier_name='Shenzhen Supplier',
            agent='Ирина',
            status=Purchase.STATUS_ORDERED,
            currency='CNY',
            total_amount=Decimal('1000.00'),
        )
        PurchaseItem.objects.create(
            purchase=purchase,
            product=self.product,
            variant=self.variant,
            quantity=2,
            price=Decimal('500.00'),
        )
        cargo = Cargo.objects.create(
            cargo_number='CG-RESP-1',
            purchase=purchase,
            status=Cargo.STATUS_IN_TRANSIT,
            destination_warehouse=self.warehouse,
            eta=timezone.localdate() + timedelta(days=3),
        )
        CargoItem.objects.create(cargo=cargo, product=self.product, quantity=2)
        reservation = self.create_reservation(
            client=self.manager_client,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
        )
        ReservationItem.objects.create(reservation=reservation, product=self.product, quantity=1)
        shipment = Shipment.objects.create(
            order=self.order,
            client=self.manager_client,
            reservation=reservation,
            source_warehouse=self.warehouse,
            target_warehouse=self.other_warehouse,
            tracking_number='TRACK-RESP-1',
            status=Shipment.STATUS_PENDING,
        )
        ShipmentItem.objects.create(shipment=shipment, order_item=self.order.items.get(), product=self.product, quantity=1)
        receipt_inventory(warehouse=self.warehouse, product=self.product, quantity=5, author=self.staff_user)

        responses = [
            self.client.get(reverse('manager_portal:purchase_list')),
            self.client.get(reverse('manager_portal:cargo_list')),
            self.client.get(reverse('manager_portal:reservation_list')),
            self.client.get(reverse('manager_portal:shipments'), {'view_mode': 'items'}),
            self.client.get(reverse('manager_portal:inventory')),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'manager-responsive-card')
            self.assertContains(response, 'md:table')

    def test_shipment_detail_page_renders_document(self):
        self.login_staff()
        shipment = Shipment.objects.create(order=self.order, client=self.manager_client, source_warehouse=self.warehouse)
        ShipmentItem.objects.create(shipment=shipment, order_item=self.order.items.get(), product=self.product, quantity=1)

        response = self.client.get(reverse('manager_portal:shipment_detail', kwargs={'pk': shipment.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Отгрузка #')
        self.assertContains(response, 'Meta Quest 3')

    def test_finance_pages_format_turnover_with_thousands_separator(self):
        self.login_staff()
        self.finance_deal_type.partner_share = Decimal('1.0')
        self.finance_deal_type.save(update_fields=['partner_share'])
        FinanceDeal.objects.create(
            date=timezone.localdate(),
            contract_number='BF-TURNOVER',
            deal_type=self.finance_deal_type,
            payment_state='paid',
            revenue=Decimal('1761718.00'),
            cost_price=Decimal('1456431.00'),
            direct_expenses=Decimal('2300.00'),
            manager_bonus=Decimal('100.00'),
        )

        dashboard_response = self.client.get(
            reverse('manager_portal:finance'),
            {
                'year': timezone.localdate().year,
                'month': timezone.localdate().month,
            },
        )
        report_response = self.client.get(
            reverse('manager_portal:finance_report'),
            {
                'year': timezone.localdate().year,
                'month': timezone.localdate().month,
            },
        )

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, 'Баланс')
        self.assertContains(dashboard_response, 'Задолженность')
        self.assertContains(dashboard_response, 'Оплачено')
        self.assertContains(dashboard_response, 'Просрочено')
        self.assertContains(dashboard_response, 'data-finance-cashflow-chart', html=False)
        self.assertContains(dashboard_response, '1 761 718,00')
        self.assertContains(dashboard_response, '302 887,00')
        self.assertEqual(report_response.status_code, 200)
        self.assertContains(report_response, '1 761 718,00')
        self.assertContains(report_response, '302 887,00')

    def test_finance_report_view_downloads_zip(self):
        self.login_staff()
        FinanceDeal.objects.create(
            date=timezone.localdate(),
            contract_number='BF-REPORT',
            deal_type=self.finance_deal_type,
            revenue=Decimal('900.00'),
            cost_price=Decimal('200.00'),
            direct_expenses=Decimal('50.00'),
            manager_bonus=Decimal('50.00'),
        )

        response = self.client.get(
            reverse('manager_portal:finance_report'),
            {
                'year': timezone.localdate().year,
                'month': timezone.localdate().month,
                'download': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertIn('finance-report-', response['Content-Disposition'])


class ManagerPortalTabularImportTests(ManagerPortalBaseTestCase):
    def _write_csv(self, path, fieldnames, rows):
        with open(path, 'w', encoding='utf-8', newline='') as destination:
            writer = csv.DictWriter(destination, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _build_import_dir(self, *, include_supply_date=True):
        tmpdir = tempfile.TemporaryDirectory()
        base_path = tmpdir.name
        avito_rows = [
            {
                'external_key': 'AVITO-T-001',
                'date': '2026-02-10',
                'delivery_provider_name': 'Почта России',
                'product_name': 'Avito Harness',
                'quantity': '1',
                'cost_price_unit': '1200',
                'sale_price_unit': '2100',
                'answered_by': 'Эрика',
                'shipped_by': 'Ярослав Е',
                'received_at': '2026-02-14',
                'expense_total': '300',
                'listing_url': '',
                'listing_id': 'AVITO-T-001',
                'listing_title': 'Avito Harness',
                'contact_channel': 'Avito',
            }
        ]
        supply_rows = [
            {
                'row_key': 'SUP-001-1',
                'deal_key': 'SUP-001',
                'client_name': 'ООО Ромашка',
                'order_date': '2026-03-03' if include_supply_date else '',
                'product_name': 'Known Supply',
                'quantity': '1',
                'cost_price': '4000',
                'sale_price': '5500',
                'owner_name': 'Сергей П',
                'shipping_status': 'not_shipped',
                'payment_status': 'unpaid',
                'delivery_provider_name': 'СДЭК',
                'answered_by': '',
                'shipped_by': '',
            },
            {
                'row_key': 'SUP-001-2',
                'deal_key': 'SUP-001',
                'client_name': 'ООО Ромашка',
                'order_date': '2026-03-03' if include_supply_date else '',
                'product_name': 'Unknown Supply',
                'quantity': '2',
                'cost_price': '300',
                'sale_price': '500',
                'owner_name': 'BIZON',
                'shipping_status': 'not_shipped',
                'payment_status': 'unpaid',
                'delivery_provider_name': 'СДЭК',
                'answered_by': '',
                'shipped_by': '',
            },
        ]
        supply_allocations = [
            {
                'allocation_key': 'SUP-001-A1',
                'deal_key': 'SUP-001',
                'person_name': 'Сергей',
                'amount': '1000',
                'quantity_basis': '2',
            },
            {
                'allocation_key': 'SUP-001-A2',
                'deal_key': 'SUP-001',
                'person_name': 'Артём Ч',
                'amount': '500',
                'quantity_basis': '2',
            },
        ]
        product_aliases = {
            'Avito Harness': {'product_slug': self.product.slug},
            'Known Supply': {'product_slug': self.product_two.slug},
        }
        people_aliases = {
            'Эрика': {'slug': 'erika'},
            'Ярослав Е': {'slug': 'yaroslav-e'},
            'Сергей П': {'slug': 'sergey-p'},
            'Сергей': {'slug': 'sergey'},
            'Артём Ч': {'slug': 'artem-ch'},
            'BIZON': {'slug': 'bizon'},
        }
        self._write_csv(
            f'{base_path}/avito_deals.csv',
            [
                'external_key',
                'date',
                'delivery_provider_name',
                'product_name',
                'quantity',
                'cost_price_unit',
                'sale_price_unit',
                'answered_by',
                'shipped_by',
                'received_at',
                'expense_total',
                'listing_url',
                'listing_id',
                'listing_title',
                'contact_channel',
            ],
            avito_rows,
        )
        self._write_csv(
            f'{base_path}/supply_deals.csv',
            [
                'row_key',
                'deal_key',
                'client_name',
                'order_date',
                'product_name',
                'quantity',
                'cost_price',
                'sale_price',
                'owner_name',
                'shipping_status',
                'payment_status',
                'delivery_provider_name',
                'answered_by',
                'shipped_by',
            ],
            supply_rows,
        )
        self._write_csv(
            f'{base_path}/supply_allocations.csv',
            ['allocation_key', 'deal_key', 'person_name', 'amount', 'quantity_basis'],
            supply_allocations,
        )
        with open(f'{base_path}/product_aliases.json', 'w', encoding='utf-8') as destination:
            json.dump(product_aliases, destination, ensure_ascii=False, indent=2)
        with open(f'{base_path}/people_aliases.json', 'w', encoding='utf-8') as destination:
            json.dump(people_aliases, destination, ensure_ascii=False, indent=2)
        return tmpdir

    def test_import_manager_tabular_sales_dry_run_does_not_persist_entities(self):
        source_dir = self._build_import_dir()
        call_command('import_manager_tabular_sales', source_dir=source_dir.name, dry_run=True)

        self.assertEqual(LegacyImportBatch.objects.filter(source_system=LegacyImportBatch.SOURCE_TABULAR_SALES).count(), 1)
        self.assertFalse(ManagerDeal.objects.filter(customer_source=ManagerDeal.SOURCE_AVITO, individual_full_name__startswith='Avito ·').exists())
        self.assertFalse(ManagerPersonAlias.objects.filter(display_name='Эрика').exists())
        source_dir.cleanup()

    def test_import_manager_tabular_sales_imports_avito_row_with_placeholder_client_and_participants(self):
        source_dir = self._build_import_dir()

        batch = import_manager_tabular_sales(source_dir.name, dry_run=False)

        self.assertEqual(batch.status, LegacyImportBatch.STATUS_COMPLETED)
        deal = ManagerDeal.objects.get(customer_source=ManagerDeal.SOURCE_AVITO, individual_full_name='Avito · Avito Harness · 10.02.2026')
        self.assertEqual(deal.delivery_provider_name, 'Почта России')
        self.assertEqual(deal.order.payment_status, Order.PAYMENT_STATUS_PAID)
        self.assertTrue(FinanceDeal.objects.filter(manager_deal=deal, partner_share_amount=Decimal('600.00')).exists())
        self.assertTrue(
            ManagerDealParticipant.objects.filter(
                manager_deal=deal,
                role=ManagerDealParticipant.ROLE_ANSWERED,
                person_alias__display_name='Эрика',
            ).exists()
        )
        self.assertTrue(
            ManagerDealParticipant.objects.filter(
                manager_deal=deal,
                role=ManagerDealParticipant.ROLE_SHIPPED,
                person_alias__display_name='Ярослав Е',
            ).exists()
        )
        source_dir.cleanup()

    def test_import_manager_tabular_sales_imports_supply_group_and_allocations(self):
        source_dir = self._build_import_dir()

        import_manager_tabular_sales(source_dir.name, dry_run=False)

        deal = ManagerDeal.objects.get(business_company_name='ООО Ромашка')
        self.assertEqual(deal.order.items.count(), 2)
        self.assertEqual(deal.order.payment_status, Order.PAYMENT_STATUS_UNPAID)
        self.assertTrue(
            ManagerDealParticipant.objects.filter(
                manager_deal=deal,
                role=ManagerDealParticipant.ROLE_ITEM_OWNER,
                person_alias__display_name='Сергей П',
            ).exists()
        )
        allocations = list(
            ManagerDealParticipant.objects.filter(
                manager_deal=deal,
                role=ManagerDealParticipant.ROLE_PLANNED_PROFIT_SHARE,
            ).order_by('person_alias__display_name')
        )
        self.assertEqual(len(allocations), 2)
        self.assertEqual(sum((allocation.amount for allocation in allocations), Decimal('0')), Decimal('1500.00'))
        finance_deal = FinanceDeal.objects.get(manager_deal=deal)
        self.assertEqual(finance_deal.partner_share_amount, finance_deal.margin)
        source_dir.cleanup()

    def test_import_manager_tabular_sales_creates_placeholder_product_for_unknown_alias(self):
        source_dir = self._build_import_dir()

        import_manager_tabular_sales(source_dir.name, dry_run=False)

        placeholder_product = Product.objects.get(name='Unknown Supply')
        self.assertFalse(placeholder_product.is_active)
        self.assertEqual(placeholder_product.category.name, 'Импортированные товары')
        source_dir.cleanup()

    def test_import_manager_tabular_sales_skips_supply_without_order_date(self):
        source_dir = self._build_import_dir(include_supply_date=False)

        batch = import_manager_tabular_sales(source_dir.name, dry_run=False)

        self.assertEqual(batch.status, LegacyImportBatch.STATUS_COMPLETED)
        self.assertFalse(ManagerDeal.objects.filter(business_company_name='ООО Ромашка').exists())
        self.assertTrue(
            LegacyImportBatch.objects.filter(
                pk=batch.pk,
                conflicts__conflict_type='missing_date',
            ).exists()
        )
        source_dir.cleanup()

    def test_import_manager_tabular_sales_is_idempotent(self):
        source_dir = self._build_import_dir()

        import_manager_tabular_sales(source_dir.name, dry_run=False)
        import_manager_tabular_sales(source_dir.name, dry_run=False)

        self.assertEqual(ManagerDeal.objects.filter(customer_source=ManagerDeal.SOURCE_AVITO, individual_full_name__startswith='Avito ·').count(), 1)
        self.assertEqual(ManagerDeal.objects.filter(business_company_name='ООО Ромашка').count(), 1)
        self.assertEqual(
            ManagerDealParticipant.objects.filter(role=ManagerDealParticipant.ROLE_PLANNED_PROFIT_SHARE).count(),
            2,
        )
        source_dir.cleanup()

    def test_deal_detail_renders_imported_participants_and_allocations(self):
        source_dir = self._build_import_dir()
        import_manager_tabular_sales(source_dir.name, dry_run=False)
        deal = ManagerDeal.objects.get(business_company_name='ООО Ромашка')
        self.login_staff()

        response = self.client.get(reverse('manager_portal:deal_detail', kwargs={'pk': deal.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Участники')
        self.assertContains(response, 'Сергей')
        self.assertContains(response, 'Плановые начисления')
        source_dir.cleanup()
