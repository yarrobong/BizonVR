"""Подключение к БД, запросы и инициализация схемы."""
import bcrypt
import psycopg2

from config import DATABASE_URL, ADMIN_INITIAL_PASSWORD


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def run_query(query, params=(), fetch=False):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(query, params)
        if fetch:
            return c.fetchall()
        conn.commit()
    finally:
        conn.close()


def run_query_one(query, params=()):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(query, params)
        return c.fetchone()
    finally:
        conn.close()


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'operator')),
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS deal_types (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        partner_share NUMERIC(5, 4) NOT NULL CHECK (partner_share >= 0 AND partner_share <= 1)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS our_expense_categories (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS partner_expense_categories (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS deals (
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
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id SERIAL PRIMARY KEY,
        expense_side TEXT,
        date DATE,
        category TEXT,
        amount NUMERIC(14, 2),
        who_paid TEXT,
        partner_expense_share NUMERIC(14, 2),
        comment TEXT
    )""")

    c.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'expenses' AND column_name = 'expense_side'
    """)
    if c.fetchone() is None:
        c.execute("ALTER TABLE expenses ADD COLUMN expense_side TEXT")
        c.execute("""
            UPDATE expenses SET expense_side = CASE
                WHEN who_paid = 'Партнер (Свои деньги)' THEN 'partner'
                ELSE 'ours'
            END
            WHERE expense_side IS NULL
        """)

    c.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'expenses' AND column_name = 'deal_id'
    """)
    if c.fetchone() is None:
        c.execute("ALTER TABLE expenses ADD COLUMN deal_id INTEGER REFERENCES deals(id)")

    c.execute("""CREATE TABLE IF NOT EXISTS payouts (
        id SERIAL PRIMARY KEY,
        date DATE,
        amount NUMERIC(14, 2),
        comment TEXT
    )""")

    # OAuth 2.0 / ZenMoney: храним токены, полученные через авторизацию
    c.execute(
        """CREATE TABLE IF NOT EXISTS zenmoney_tokens (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            token_type TEXT,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )"""
    )

    c.execute("SELECT 1 FROM users LIMIT 1")
    if c.fetchone() is None:
        pw = bcrypt.hashpw(ADMIN_INITIAL_PASSWORD.encode(), bcrypt.gensalt()).decode()
        c.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            ("admin", pw, "admin"),
        )

    c.execute("SELECT 1 FROM deal_types LIMIT 1")
    if c.fetchone() is None:
        for name, share in [("Партнерская", 0.5), ("Трейд-ин / Из наличия", 0.3), ("Моя личная", 0)]:
            c.execute("INSERT INTO deal_types (name, partner_share) VALUES (%s, %s)", (name, share))

    default_our = [
        "Расходники", "Транспортировка", "Транспортные расходы", "ЗП Ярика", "Сдек", "CDEK",
        "TradeIn", "Ярослав Е", "Ярослав П", "Егор Д", "Обучение план-факт", "Покупка План-факта",
        "Модуль сделок", "Доплата План-Факт", "Настройка рекламы", "Связь реклама", "ЗП Максим Т",
        "ЗП Ярослав П", "ЗП Ярослав Е", "ЗП Егор Д", "Московский человек", "Реклама яндекс",
        "Юрист", "Брак", "Докуп", "Возврат", "Ярослав",
    ]
    c.execute("SELECT 1 FROM our_expense_categories LIMIT 1")
    if c.fetchone() is None:
        for n in default_our:
            c.execute("INSERT INTO our_expense_categories (name) VALUES (%s)", (n,))

    default_partner = [
        "Оплата менеджеру", "Связь", "Учетные записи и программа для работы",
        "Затраты прямые на лидген через конкурентов",
    ]
    c.execute("SELECT 1 FROM partner_expense_categories LIMIT 1")
    if c.fetchone() is None:
        for n in default_partner:
            c.execute("INSERT INTO partner_expense_categories (name) VALUES (%s)", (n,))

    # Исторические расходы (август — декабрь 2025), только если таблица пуста
    c.execute("SELECT COUNT(*) FROM expenses")
    if c.fetchone()[0] == 0:
        _seed_historical_expenses(c)

    conn.commit()
    conn.close()


def _seed_historical_expenses(cursor):
    """Вставка исторических расходов: август — декабрь 2025 (наши + партнёр Артём)."""
    WHO_PAID_OURS = "Я (Из кассы бизнеса/свои)"
    WHO_PAID_PARTNER = "Партнер (Свои деньги)"
    rows_ours = [
        ("2025-08-01", "Расходники", 3000),
        ("2025-08-01", "Транспортировка", 700),
        ("2025-08-01", "ЗП Ярика", 12500),
        ("2025-08-01", "Сдек", 6139),
        ("2025-09-01", "Транспортировка", 23444),
        ("2025-09-01", "TradeIn", 5600),
        ("2025-09-01", "Ярослав Е", 30000),
        ("2025-09-01", "Ярослав П", 22000),
        ("2025-09-01", "Егор Д", 2282.6),
        ("2025-09-01", "Обучение план-факт", 20000),
        ("2025-09-01", "Покупка План-факта", 11760),
        ("2025-09-01", "Модуль сделок", 2822),
        ("2025-09-01", "Модуль сделок", 2822),
        ("2025-10-01", "Доплата План-Факт", 20000),
        ("2025-10-01", "Ярослав Е", 30000),
        ("2025-10-01", "Ярослав П", 14917),
        ("2025-10-01", "Егор Д", 12000),
        ("2025-10-01", "Транспортировка", 5306),
        ("2025-10-01", "TradeIn", 5600),
        ("2025-11-01", "Настройка рекламы", 37500),
        ("2025-11-01", "Связь реклама", 8000),
        ("2025-11-01", "Сдек", 9590),
        ("2025-11-01", "TradeIn", 5600),
        ("2025-11-01", "ЗП Максим Т", 25000),
        ("2025-11-01", "ЗП Ярослав П", 25000),
        ("2025-11-01", "Московский человек", 3500),
        ("2025-11-01", "ЗП Ярослав Е", 10000),
        ("2025-11-01", "ЗП Егор Д", 5000),
        ("2025-11-01", "Реклама яндекс", 15000),
        ("2025-11-01", "Юрист", 7650),
        ("2025-11-01", "Брак", 12000),
        ("2025-11-01", "Докуп", 4630),
        ("2025-11-01", "Возврат", 37000),
        ("2025-12-01", "ЗП Максим Т", 35000),
        ("2025-12-01", "CDEK", 23000),
        ("2025-12-01", "TradeIn", 5600),
        ("2025-12-01", "Московский человек", 3500),
        ("2025-12-01", "ЗП Егор Д", 28000),
        ("2025-12-01", "Транспортные расходы", 4000),
        ("2025-12-01", "Ярослав", 4500),
    ]
    rows_partner = [
        # Затраты Артём, август 2025
        ("2025-08-01", "Оплата менеджеру", 14000),
        ("2025-08-01", "Связь", 869),
        ("2025-08-01", "Учетные записи и программа для работы", 2250),
        ("2025-08-01", "Затраты прямые на лидген через конкурентов", 15127),
        # Сентябрь 2025
        ("2025-09-01", "Оплата менеджеру", 13937.144),
        ("2025-09-01", "Связь", 495),
        ("2025-09-01", "Учетные записи и программа для работы", 2250),
        ("2025-09-01", "Затраты прямые на лидген через конкурентов", 16974),
        # Октябрь 2025
        ("2025-10-01", "Оплата менеджеру", 11707.44),
        ("2025-10-01", "Связь", 372),
        ("2025-10-01", "Учетные записи и программа для работы", 2250),
        ("2025-10-01", "Затраты прямые на лидген через конкурентов", 16654),
        # Ноябрь 2025
        ("2025-11-01", "Оплата менеджеру", 14640),
        ("2025-11-01", "Связь", 1000),
        ("2025-11-01", "Учетные записи и программа для работы", 2250),
        ("2025-11-01", "Затраты прямые на лидген через конкурентов", 31744),
        # Декабрь 2025
        ("2025-12-01", "Оплата менеджеру", 3878),
        ("2025-12-01", "Связь", 900),
        ("2025-12-01", "Учетные записи и программа для работы", 2250),
        ("2025-12-01", "Затраты прямые на лидген через конкурентов", 42780),
    ]
    ins = """INSERT INTO expenses (expense_side, date, category, amount, who_paid,
               partner_expense_share, comment, deal_id) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)"""
    for date_s, category, amount in rows_ours:
        cursor.execute(ins, ("ours", date_s, category, amount, WHO_PAID_OURS, 0, ""))
    for date_s, category, amount in rows_partner:
        cursor.execute(ins, ("partner", date_s, category, amount, WHO_PAID_PARTNER, 0, ""))
