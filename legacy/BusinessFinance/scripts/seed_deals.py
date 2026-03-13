"""
Скрипт однократной вставки сделок (август–декабрь 2024) в БД.
Запуск: python -m scripts.seed_deals (из корня проекта) или python scripts/seed_deals.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import get_conn, run_query

YEAR = 2024

# Типы сделок: (название, доля партнёра 0–1). Trade-IN -> 0.3, остальные 0.
DEAL_TYPES = [
    ("Оборудование", 0),
    ("Trade-IN", 0.3),
    ("Оборудование (Л)", 0),
    ("Аттракционы", 0),
]

# Сделки: (dd, mm, contract, deal_type, revenue, cost, delivery, other, margin)
# direct_expenses = delivery + other, manager_bonus = 0, partner_share = margin * type_share
DEALS = [
    (14, 7, "", "Оборудование", 1_394_400, 1_347_286, 0, 0, 40_539),
    (1, 8, "№1", "Trade-IN", 230_500, 249_700, 0, 0, -25_775),
    (13, 8, "№10", "Trade-IN", 341_600, 347_600, 0, 0, -15_760),
    (19, 8, "№13", "Оборудование", 155_226, 133_290.56, 0, 0, 21_935.44),
    (14, 8, "№14", "Trade-IN", 23_797, 18_993.82, 0, 0, 4_124.18),
    (27, 8, "Надежда", "Оборудование", 191_920, 181_642, 1_066, 0, 10_278),
    (27, 8, "№18", "Оборудование", 296_180, 278_000, 0, 0, 18_180),
    (31, 8, "№17", "Оборудование", 362_150, 344_964.2, 2_706, 0, 14_479.8),
    (5, 9, "Надежда", "Оборудование", 96_672, 67_178, 1_558, 2_000, 25_936),
    (15, 9, "№27", "Оборудование", 12_450, 7_808, 505, 0, 4_137),
    (16, 9, "Надежда", "Оборудование", 41_320, 28_868, 1_328.4, 0, 11_123.6),
    (21, 9, "№26", "Оборудование", 119_199, 104_895, 5_516, 0, 8_788),
    (21, 9, "№28", "Оборудование", 1_664_000, 1_434_968, 34_100, 22_000, 172_932),
    (30, 9, "№31", "Оборудование", 292_744, 245_000, 11_232, 0, 36_512),
    (30, 9, "№29", "Trade-IN", 87_500, 80_000, 1_000, 0, 6_500),
    (18, 10, "Анастасия", "Trade-IN", 110_000, 58_000, 0, 8_610, 82_000),
    (21, 10, "Владимир", "Оборудование (Л)", 577_910, 463_330, 0, 17_187, 114_580),
    (22, 10, "Дарья", "Оборудование", 272_870, 185_764, 3_000, 6_307, 84_106),
    (9, 11, "Роман", "Аттракционы", 1_494_480, 1_134_558.4, 0, 0, 359_921.6),
    (17, 11, "Тимур", "Оборудование", 92_960, 82_956, 0, 0, 10_004),
    (21, 11, "№40 Владимир", "Trade-IN", 100_960, 68_000, 800, 0, 32_160),
    (22, 11, "Кирилл", "Оборудование", 42_490, 36_000, 400, 0, 6_090),
    (27, 11, "Андрей", "Оборудование", 5_800, 1_690, 400, 0, 3_710),
    (2, 12, "", "Оборудование", 1_393_962, 1_301_962, 0, 0, 92_000),
    (2, 12, "Карина", "Оборудование", 345_360, 248_400, 0, 0, 96_960),
    (11, 12, "Тимур", "Оборудование", 140_000, 120_000, 0, 0, 20_000),
]

TYPE_SHARE = {t[0]: t[1] for t in DEAL_TYPES}


def main():
    conn = get_conn()
    cur = conn.cursor()
    try:
        for name, share in DEAL_TYPES:
            cur.execute(
                "INSERT INTO deal_types (name, partner_share) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (name, share),
            )
        for row in DEALS:
            dd, mm, contract, dtype, revenue, cost, delivery, other, margin = row
            direct = delivery + other
            share = TYPE_SHARE.get(dtype, 0)
            partner_share = round(margin * share, 2)
            date_str = f"{YEAR}-{mm:02d}-{dd:02d}"
            cur.execute(
                """INSERT INTO deals (date, contract_number, deal_type, revenue, cost_price,
                   direct_expenses, manager_bonus, margin, partner_share, comment)
                   VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s)""",
                (date_str, contract or None, dtype, revenue, cost, direct, margin, partner_share, ""),
            )
        conn.commit()
        print(f"Вставлено {len(DEALS)} сделок, типы сделок обновлены.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
