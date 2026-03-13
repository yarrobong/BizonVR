import os
import sqlite3
import tempfile
from decimal import Decimal

import psycopg2
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from accounts.models import BalanceTransaction, Profile
from catalog.models import CatalogSection, Category, City, PickupPoint, Product, ProductStock, ProductTag, ProductVariant
from orders.models import Order, OrderItem

from .access import FINANCE_ADMIN_GROUP, FINANCE_OPERATOR_GROUP
from .models import (
    ContractCompanyProfile,
    ContractDocument,
    ContractTemplate,
    FinanceDeal,
    FinanceDealType,
    FinanceExpense,
    FinanceExpenseCategory,
    FinancePayout,
    LegacyImportBatch,
    LegacyImportConflict,
    LegacyImportRecord,
)
from .single_db_contract import collect_single_db_contract_violations


User = get_user_model()


class LegacyImportCommandTests(TestCase):
    maxDiff = None

    def make_sqlite_db(self):
        handle = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        return handle.name

    def business_finance_dsn(self):
        settings_dict = connection.settings_dict
        password = settings_dict.get('PASSWORD') or ''
        host = settings_dict.get('HOST') or 'localhost'
        port = settings_dict.get('PORT') or '5432'
        return f"dbname={settings_dict['NAME']} user={settings_dict['USER']} password={password} host={host} port={port}"

    def create_business_finance_source_tables(self):
        statements = [
            'DROP TABLE IF EXISTS zenmoney_tokens',
            'DROP TABLE IF EXISTS payouts',
            'DROP TABLE IF EXISTS expenses',
            'DROP TABLE IF EXISTS deals',
            'DROP TABLE IF EXISTS partner_expense_categories',
            'DROP TABLE IF EXISTS our_expense_categories',
            'DROP TABLE IF EXISTS deal_types',
            'DROP TABLE IF EXISTS users',
            """
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE deal_types (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                partner_share NUMERIC(5, 4) NOT NULL
            )
            """,
            "CREATE TABLE our_expense_categories (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL)",
            "CREATE TABLE partner_expense_categories (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL)",
            """
            CREATE TABLE deals (
                id SERIAL PRIMARY KEY,
                date DATE,
                contract_number TEXT,
                deal_type TEXT,
                revenue NUMERIC(14, 2),
                cost_price NUMERIC(14, 2),
                direct_expenses NUMERIC(14, 2),
                manager_bonus NUMERIC(14, 2),
                margin NUMERIC(14, 2),
                partner_share NUMERIC(14, 2),
                comment TEXT
            )
            """,
            """
            CREATE TABLE expenses (
                id SERIAL PRIMARY KEY,
                expense_side TEXT,
                date DATE,
                category TEXT,
                amount NUMERIC(14, 2),
                who_paid TEXT,
                partner_expense_share NUMERIC(14, 2),
                comment TEXT,
                deal_id INTEGER
            )
            """,
            """
            CREATE TABLE payouts (
                id SERIAL PRIMARY KEY,
                date DATE,
                amount NUMERIC(14, 2),
                comment TEXT
            )
            """,
            """
            CREATE TABLE zenmoney_tokens (
                user_id INTEGER PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_type TEXT,
                expires_at TIMESTAMPTZ
            )
            """,
        ]
        with psycopg2.connect(self.business_finance_dsn()) as source_conn:
            source_conn.autocommit = True
            with source_conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                    ['bf-admin', 'bcrypt-hash', 'admin'],
                )
                cursor.execute(
                    "INSERT INTO deal_types (name, partner_share) VALUES (%s, %s)",
                    ['Партнерская', Decimal('0.5000')],
                )
                cursor.execute("INSERT INTO our_expense_categories (name) VALUES (%s)", ['Транспортировка'])
                cursor.execute("INSERT INTO partner_expense_categories (name) VALUES (%s)", ['Связь'])
                cursor.execute(
                    """
                    INSERT INTO deals (date, contract_number, deal_type, revenue, cost_price, direct_expenses, manager_bonus, margin, partner_share, comment)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    ['2026-03-01', 'BF-1', 'Партнерская', '1000.00', '400.00', '50.00', '25.00', '525.00', '262.50', 'legacy deal'],
                )
                cursor.execute(
                    """
                    INSERT INTO expenses (expense_side, date, category, amount, who_paid, partner_expense_share, comment, deal_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    ['ours', '2026-03-02', 'Транспортировка', '100.00', 'Я (Из кассы бизнеса/свои)', '0', 'legacy expense', 1],
                )
                cursor.execute(
                    "INSERT INTO payouts (date, amount, comment) VALUES (%s, %s, %s)",
                    ['2026-03-03', '50.00', 'legacy payout'],
                )
                cursor.execute(
                    """
                    INSERT INTO zenmoney_tokens (user_id, access_token, refresh_token, token_type, expires_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    """,
                    [1, 'token', 'refresh', 'bearer'],
                )

        def cleanup():
            with psycopg2.connect(self.business_finance_dsn()) as source_conn:
                source_conn.autocommit = True
                with source_conn.cursor() as cursor:
                    for table_name in (
                        'zenmoney_tokens',
                        'payouts',
                        'expenses',
                        'deals',
                        'partner_expense_categories',
                        'our_expense_categories',
                        'deal_types',
                        'users',
                    ):
                        cursor.execute(f'DROP TABLE IF EXISTS {table_name}')

        self.addCleanup(cleanup)

    def test_import_legacy_docuflow_dry_run_and_apply_are_idempotent(self):
        path = self.make_sqlite_db()
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE app_settings (id INTEGER PRIMARY KEY, payload_json TEXT);
            CREATE TABLE templates (
                id TEXT PRIMARY KEY,
                sort_order INTEGER,
                name TEXT,
                type TEXT,
                version TEXT,
                is_active INTEGER,
                content_html TEXT,
                css_text TEXT,
                variables_json TEXT,
                updated_at TEXT
            );
            CREATE TABLE counterparties (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT,
                phone TEXT,
                inn TEXT,
                kpp TEXT,
                ogrn TEXT,
                ogrnip TEXT,
                address TEXT
            );
            CREATE TABLE invoices (
                id TEXT PRIMARY KEY,
                supplier_profile_id TEXT,
                counterparty_id TEXT,
                number TEXT,
                sort_order INTEGER,
                status TEXT,
                date TEXT,
                amount REAL,
                currency TEXT,
                vat_rate TEXT,
                vat_mode TEXT,
                items_json TEXT,
                commission_percent REAL,
                payment_due_date TEXT
            );
            CREATE TABLE contracts (
                id TEXT PRIMARY KEY,
                supplier_profile_id TEXT,
                template_id TEXT,
                invoice_id TEXT,
                number TEXT,
                title TEXT,
                type TEXT,
                status TEXT,
                created_at TEXT,
                amount REAL,
                payment_terms INTEGER,
                include_delivery INTEGER,
                delivery_date TEXT,
                vat_rate TEXT,
                vat_mode TEXT,
                markup_percent REAL,
                markup_mode TEXT,
                markup_calc_mode TEXT,
                counterparty_json TEXT,
                contract_data_json TEXT,
                html_snapshot TEXT,
                snapshot_css TEXT,
                sort_order INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO app_settings (id, payload_json) VALUES (?, ?)",
            [
                1,
                '{"companyProfiles":[{"id":"profile-1","companyName":"BizonVR","legalType":"ip","inn":"667907832209","email":"contracts@example.com"}],"activeCompanyProfileId":"profile-1"}',
            ],
        )
        conn.execute(
            """
            INSERT INTO templates (id, sort_order, name, type, version, is_active, content_html, css_text, variables_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ['tpl-1', 1, 'Шаблон поставки', 'Договор поставки', '1.0', 1, '<div>ok</div>', '', '[]', '2026-03-01T10:00:00+00:00'],
        )
        conn.execute(
            """
            INSERT INTO counterparties (id, name, email, phone, inn, kpp, ogrn, ogrnip, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ['cp-1', 'ООО Клиент', 'client@example.com', '+7 900 000 00 01', '6677000000', '', '', '', 'Екатеринбург'],
        )
        conn.execute(
            """
            INSERT INTO invoices (id, supplier_profile_id, counterparty_id, number, sort_order, status, date, amount, currency, vat_rate, vat_mode, items_json, commission_percent, payment_due_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ['inv-1', 'profile-1', 'cp-1', 'SCH-1', 1, 'Не оплачен', '2026-03-05', 100000, 'RUB', 'none', 'included', '[]', 0, '2026-03-15'],
        )
        conn.execute(
            """
            INSERT INTO contracts (id, supplier_profile_id, template_id, invoice_id, number, title, type, status, created_at, amount, payment_terms, include_delivery, delivery_date, vat_rate, vat_mode, markup_percent, markup_mode, markup_calc_mode, counterparty_json, contract_data_json, html_snapshot, snapshot_css, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                'doc-1',
                'profile-1',
                'tpl-1',
                'inv-1',
                'DOG-1',
                'Договор',
                'Договор поставки',
                'Черновик',
                '2026-03-04T10:00:00+00:00',
                120000,
                10,
                0,
                None,
                'none',
                'included',
                6,
                'per_item',
                'simple',
                '{"name":"ООО Клиент","email":"client@example.com","phone":"+7 900 000 00 01","inn":"6677000000","address":"Екатеринбург"}',
                '{"subject":"Поставка VR"}',
                '<div>snapshot</div>',
                '',
                1,
            ],
        )
        conn.commit()
        conn.close()

        call_command('import_legacy_docuflow', '--source', path, '--dry-run')

        self.assertEqual(ContractDocument.objects.count(), 0)
        self.assertEqual(LegacyImportBatch.objects.filter(source_system='docuflow').count(), 1)

        call_command('import_legacy_docuflow', '--source', path, '--apply')
        call_command('import_legacy_docuflow', '--source', path, '--apply')

        self.assertEqual(ContractCompanyProfile.objects.count(), 1)
        self.assertEqual(ContractTemplate.objects.count(), 1)
        self.assertEqual(ContractDocument.objects.count(), 1)
        self.assertTrue(LegacyImportRecord.objects.filter(source_system='docuflow', source_model='contracts', source_pk='doc-1').exists())
        self.assertEqual(ContractDocument.objects.get().number, 'DOG-1')

    def test_import_legacy_business_finance_apply_creates_finance_rows_and_groups(self):
        self.create_business_finance_source_tables()

        call_command('import_legacy_business_finance', '--source-dsn', self.business_finance_dsn(), '--apply')
        call_command('import_legacy_business_finance', '--source-dsn', self.business_finance_dsn(), '--apply')

        imported_user = User.objects.get(username='legacy-finance-1-bf-admin')
        self.assertFalse(imported_user.is_active)
        self.assertFalse(imported_user.has_usable_password())
        self.assertTrue(imported_user.groups.filter(name=FINANCE_ADMIN_GROUP).exists())
        self.assertTrue(Group.objects.filter(name=FINANCE_OPERATOR_GROUP).exists())

        self.assertTrue(FinanceDealType.objects.filter(name='Партнерская').exists())
        self.assertEqual(FinanceDeal.objects.filter(contract_number='BF-1').count(), 1)
        self.assertEqual(FinanceExpense.objects.filter(comment='legacy expense').count(), 1)
        self.assertEqual(FinancePayout.objects.filter(comment='legacy payout').count(), 1)
        self.assertTrue(Profile.objects.filter(user=imported_user).exists())
        self.assertTrue(LegacyImportRecord.objects.filter(source_system='business_finance', source_model='users', source_pk='1').exists())

    def test_import_legacy_site_sqlite_apply_imports_domain_rows(self):
        path = self.make_sqlite_db()
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE auth_user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                password varchar(128) NOT NULL,
                last_login datetime NULL,
                is_superuser bool NOT NULL,
                username varchar(150) NOT NULL UNIQUE,
                last_name varchar(150) NOT NULL,
                email varchar(254) NOT NULL,
                is_staff bool NOT NULL,
                is_active bool NOT NULL,
                date_joined datetime NOT NULL,
                first_name varchar(150) NOT NULL
            );
            CREATE TABLE accounts_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone varchar(20) NOT NULL UNIQUE,
                user_id integer NOT NULL UNIQUE REFERENCES auth_user(id),
                balance decimal NOT NULL,
                contact_name varchar(255) NOT NULL,
                privacy_agreed_at datetime NULL
            );
            CREATE TABLE catalog_catalogsection (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name varchar(200) NOT NULL,
                slug varchar(200) NOT NULL UNIQUE,
                "order" integer NOT NULL
            );
            CREATE TABLE catalog_category (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name varchar(200) NOT NULL,
                slug varchar(200) NOT NULL UNIQUE,
                section_id integer NULL REFERENCES catalog_catalogsection(id)
            );
            CREATE TABLE catalog_producttag (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name varchar(100) NOT NULL,
                slug varchar(100) NOT NULL UNIQUE,
                "order" integer NOT NULL
            );
            CREATE TABLE catalog_city (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name varchar(200) NOT NULL,
                slug varchar(200) NOT NULL UNIQUE,
                "order" integer NOT NULL
            );
            CREATE TABLE catalog_pickuppoint (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name varchar(255) NOT NULL,
                address text NOT NULL,
                "order" integer NOT NULL,
                city_id integer NOT NULL REFERENCES catalog_city(id)
            );
            CREATE TABLE catalog_product (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name varchar(300) NOT NULL,
                slug varchar(300) NOT NULL UNIQUE,
                description text NOT NULL,
                price decimal NOT NULL,
                image varchar(100) NULL,
                is_active bool NOT NULL,
                created_at datetime NOT NULL,
                updated_at datetime NOT NULL,
                category_id integer NOT NULL REFERENCES catalog_category(id),
                allow_order_on_request bool NOT NULL,
                option_label varchar(100) NOT NULL
            );
            CREATE TABLE catalog_productvariant (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name varchar(100) NOT NULL,
                image varchar(100) NULL,
                price_override decimal NULL,
                "order" integer NOT NULL,
                product_id integer NOT NULL REFERENCES catalog_product(id)
            );
            CREATE TABLE catalog_product_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id integer NOT NULL REFERENCES catalog_product(id),
                producttag_id integer NOT NULL REFERENCES catalog_producttag(id)
            );
            CREATE TABLE catalog_productstock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quantity integer NOT NULL,
                pickup_point_id integer NOT NULL REFERENCES catalog_pickuppoint(id),
                product_id integer NOT NULL REFERENCES catalog_product(id)
            );
            CREATE TABLE orders_order (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status varchar(20) NOT NULL,
                total decimal NOT NULL,
                phone varchar(20) NOT NULL,
                email varchar(254) NOT NULL,
                first_name varchar(150) NOT NULL,
                last_name varchar(150) NOT NULL,
                address text NOT NULL,
                comment text NOT NULL,
                created_at datetime NOT NULL,
                updated_at datetime NOT NULL,
                user_id integer NULL REFERENCES auth_user(id)
            );
            CREATE TABLE orders_orderitem (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quantity integer NOT NULL,
                price decimal NOT NULL,
                order_id integer NOT NULL REFERENCES orders_order(id),
                product_id integer NOT NULL REFERENCES catalog_product(id)
            );
            CREATE TABLE accounts_balancetransaction (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind varchar(20) NOT NULL,
                amount decimal NOT NULL,
                created_at datetime NOT NULL,
                order_id integer NULL REFERENCES orders_order(id),
                user_id integer NOT NULL REFERENCES auth_user(id)
            );
            """
        )
        conn.execute(
            "INSERT INTO auth_user (password, last_login, is_superuser, username, last_name, email, is_staff, is_active, date_joined, first_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ['pbkdf2_sha256$600000$hash', '2026-03-01T10:00:00', 0, '79990001122', 'Иванов', 'legacy@example.com', 0, 1, '2026-03-01T09:00:00', 'Иван'],
        )
        conn.execute(
            "INSERT INTO accounts_profile (phone, user_id, balance, contact_name, privacy_agreed_at) VALUES (?, ?, ?, ?, ?)",
            ['+7 999 000 11 22', 1, 1500, 'Иван Иванов', '2026-03-01T09:30:00'],
        )
        conn.execute("INSERT INTO catalog_catalogsection (name, slug, \"order\") VALUES (?, ?, ?)", ['Шлемы', 'helmets-section', 1])
        conn.execute("INSERT INTO catalog_category (name, slug, section_id) VALUES (?, ?, ?)", ['Шлемы', 'helmets', 1])
        conn.execute("INSERT INTO catalog_producttag (name, slug, \"order\") VALUES (?, ?, ?)", ['Хит', 'hit', 1])
        conn.execute("INSERT INTO catalog_city (name, slug, \"order\") VALUES (?, ?, ?)", ['Екатеринбург', 'ekb', 1])
        conn.execute("INSERT INTO catalog_pickuppoint (name, address, \"order\", city_id) VALUES (?, ?, ?, ?)", ['Главный склад', 'ул. Тестовая, 1', 1, 1])
        conn.execute(
            """
            INSERT INTO catalog_product (name, slug, description, price, image, is_active, created_at, updated_at, category_id, allow_order_on_request, option_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ['Meta Quest 3', 'meta-quest-3', 'legacy product', 100000, '', 1, '2026-03-01T10:00:00', '2026-03-01T10:30:00', 1, 1, 'Модель'],
        )
        conn.execute(
            "INSERT INTO catalog_productvariant (name, image, price_override, \"order\", product_id) VALUES (?, ?, ?, ?, ?)",
            ['128 GB', '', None, 0, 1],
        )
        conn.execute("INSERT INTO catalog_product_tags (product_id, producttag_id) VALUES (?, ?)", [1, 1])
        conn.execute("INSERT INTO catalog_productstock (quantity, pickup_point_id, product_id) VALUES (?, ?, ?)", [3, 1, 1])
        conn.execute(
            """
            INSERT INTO orders_order (status, total, phone, email, first_name, last_name, address, comment, created_at, updated_at, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ['new', 100000, '+7 999 000 11 22', 'legacy@example.com', 'Иван', 'Иванов', 'ул. Тестовая, 1', 'legacy order', '2026-03-02T10:00:00', '2026-03-02T10:05:00', 1],
        )
        conn.execute(
            "INSERT INTO orders_orderitem (quantity, price, order_id, product_id) VALUES (?, ?, ?, ?)",
            [1, 100000, 1, 1],
        )
        conn.execute(
            "INSERT INTO accounts_balancetransaction (kind, amount, created_at, order_id, user_id) VALUES (?, ?, ?, ?, ?)",
            ['topup', 500, '2026-03-03T10:00:00', 1, 1],
        )
        conn.commit()
        conn.close()

        call_command('import_legacy_site_sqlite', '--source', path, '--apply')
        call_command('import_legacy_site_sqlite', '--source', path, '--apply')

        self.assertTrue(User.objects.filter(username='79990001122').exists())
        self.assertTrue(Profile.objects.filter(phone='9990001122').exists())
        self.assertTrue(CatalogSection.objects.filter(slug='helmets-section').exists())
        self.assertTrue(Category.objects.filter(slug='helmets').exists())
        self.assertTrue(ProductTag.objects.filter(slug='hit').exists())
        self.assertTrue(City.objects.filter(slug='ekb').exists())
        self.assertTrue(PickupPoint.objects.filter(name='Главный склад').exists())
        self.assertEqual(Product.objects.filter(slug='meta-quest-3').count(), 1)
        self.assertEqual(ProductVariant.objects.filter(name='128 GB').count(), 1)
        self.assertEqual(ProductStock.objects.filter(product__slug='meta-quest-3').count(), 1)
        self.assertEqual(Order.objects.filter(comment='legacy order').count(), 1)
        self.assertEqual(OrderItem.objects.filter(order__comment='legacy order').count(), 1)
        self.assertEqual(BalanceTransaction.objects.filter(kind='topup', amount=Decimal('500')).count(), 1)

    def test_single_db_contract_helper_passes_for_archived_layout(self):
        violations = collect_single_db_contract_violations()
        self.assertEqual(violations, [])
        self.assertFalse(LegacyImportConflict.objects.exists())
