"""Бизнес-логика: сделки, расходы, справочники."""
import pandas as pd
from psycopg2 import IntegrityError

from db import get_conn, run_query, run_query_one


def get_deal_types():
    rows = run_query("SELECT id, name, partner_share FROM deal_types ORDER BY id", fetch=True)
    return [{"id": r[0], "name": r[1], "partner_share": float(r[2])} for r in rows]


def get_our_categories():
    rows = run_query("SELECT id, name FROM our_expense_categories ORDER BY name", fetch=True)
    return [r[1] for r in rows]


def get_partner_categories():
    rows = run_query("SELECT id, name FROM partner_expense_categories ORDER BY name", fetch=True)
    return [r[1] for r in rows]


def get_partner_share_for_deal_type(deal_type_name):
    row = run_query_one("SELECT partner_share FROM deal_types WHERE name = %s", (deal_type_name,))
    return float(row[0]) if row else 0


def delete_deal(deal_id: int) -> None:
    """Удалить сделку. Расходы по сделке отвязываются (deal_id = NULL), не удаляются."""
    run_query("UPDATE expenses SET deal_id = NULL WHERE deal_id = %s", (deal_id,))
    run_query("DELETE FROM deals WHERE id = %s", (deal_id,))


def sync_deal_types_from_df(edited_df, original_df):
    """
    Синхронизировать deal_types с отредактированным DataFrame.
    edited_df / original_df: колонки id, name, partner_share_pct (0–100).
    Возвращает (ok: bool, error_message: str | None).
    """
    edited = edited_df.dropna(how="all")
    original = original_df
    orig_ids = set(original["id"].dropna().astype(int).tolist())
    edited_ids = set(edited["id"].dropna().astype(int).tolist())
    deleted_ids = orig_ids - edited_ids

    def pct_to_share(x):
        v = float(x) if pd.notna(x) else 0
        return round(max(0, min(100, v)) / 100, 4)

    try:
        for id_ in deleted_ids:
            run_query("DELETE FROM deal_types WHERE id = %s", (id_,))

        id_to_orig_name = original.set_index("id")["name"].to_dict()
        for _, row in edited.iterrows():
            id_val = row.get("id")
            name = (row.get("name") or "").strip()
            if not name:
                continue
            share = pct_to_share(row.get("partner_share_pct"))
            if pd.isna(id_val) or int(id_val) not in orig_ids:
                run_query("INSERT INTO deal_types (name, partner_share) VALUES (%s, %s)", (name, share))
            else:
                id_val = int(id_val)
                old_name = id_to_orig_name.get(id_val)
                run_query(
                    "UPDATE deal_types SET name = %s, partner_share = %s WHERE id = %s",
                    (name, share, id_val),
                )
                if old_name and old_name != name:
                    run_query("UPDATE deals SET deal_type = %s WHERE deal_type = %s", (name, old_name))
        return True, None
    except IntegrityError as e:
        return False, "Такое название типа уже есть или нарушено ограничение."


def get_deals_list():
    rows = run_query(
        "SELECT id, date, contract_number, deal_type, revenue, margin FROM deals ORDER BY date DESC, id DESC",
        fetch=True,
    )
    return [{"id": r[0], "date": r[1], "contract": r[2], "deal_type": r[3], "revenue": r[4], "margin": r[5]} for r in rows]


def get_deal_by_id(deal_id):
    row = run_query_one(
        """SELECT id, date, contract_number, deal_type, revenue, cost_price, direct_expenses,
                  manager_bonus, margin, partner_share, comment FROM deals WHERE id = %s""",
        (deal_id,),
    )
    if not row:
        return None
    return {
        "id": row[0], "date": row[1], "contract": row[2], "deal_type": row[3],
        "revenue": row[4], "cost_price": row[5], "direct_expenses": row[6],
        "manager_bonus": row[7], "margin": row[8], "partner_share": row[9], "comment": row[10],
    }


def get_expenses_for_deal(deal_id):
    conn = get_conn()
    try:
        return pd.read_sql_query(
            "SELECT id, date, category, amount, who_paid, comment FROM expenses WHERE deal_id = %s ORDER BY date, id",
            conn,
            params=(deal_id,),
        )
    finally:
        conn.close()


def get_expense_totals_by_deal():
    rows = run_query(
        "SELECT deal_id, SUM(amount) FROM expenses WHERE deal_id IS NOT NULL GROUP BY deal_id",
        fetch=True,
    )
    return {r[0]: float(r[1]) for r in rows}


def compute_partner_profit_by_direction(deals_df: pd.DataFrame, total_opex: float) -> tuple[pd.DataFrame, float]:
    """Расчёт прибыли партнёра по направлениям (группам с одинаковой долей партнёра).

    Направления с одинаковой долей партнёра объединяются. Чистая прибыль (total_margin − total_opex)
    распределяется по группам пропорционально (маржа × доля партнёра), а не пропорционально марже.
    Тогда OPEX по направлению = маржа − выделенная чистая прибыль (расходы не пропорциональны марже).
    Доля партнёра = чистая_прибыль × partner_share группы.

    Возвращает (таблица по группам направлений, итоговая прибыль партнёра).
    """
    if deals_df is None or deals_df.empty or "deal_type" not in deals_df.columns or "margin" not in deals_df.columns:
        return pd.DataFrame(), 0.0
    types = get_deal_types()
    name_to_share = {t["name"]: float(t["partner_share"]) for t in types}
    margin_col = pd.to_numeric(deals_df["margin"], errors="coerce").fillna(0)
    df = deals_df.assign(_margin=margin_col, _share=deals_df["deal_type"].map(lambda n: name_to_share.get(n, 0.0)))
    # Группируем по доле партнёра
    by_share = df.groupby("_share", as_index=False).agg(
        margin=("_margin", "sum"),
        deal_types=("deal_type", lambda s: " + ".join(sorted(s.unique().astype(str)))),
    )
    by_share = by_share.rename(columns={"deal_types": "deal_type"})
    by_share["partner_share_pct"] = by_share["_share"]
    by_share = by_share.drop(columns=["_share"])
    total_margin = float(by_share["margin"].sum())
    total_net = total_margin - total_opex
    if total_margin <= 0:
        by_share["opex_allocated"] = 0.0
        by_share["net_profit"] = by_share["margin"]
        by_share["partner_profit"] = (by_share["net_profit"] * by_share["partner_share_pct"]).round(2)
        return by_share, 0.0
    # Чистая прибыль распределяется пропорционально (маржа × доля партнёра), не пропорционально марже
    weight = by_share["margin"] * by_share["partner_share_pct"]
    weight_sum = float(weight.sum())
    if weight_sum <= 0:
        by_share["net_profit"] = total_net * (by_share["margin"] / total_margin)
    else:
        by_share["net_profit"] = (total_net * weight / weight_sum).round(2)
    by_share["opex_allocated"] = (by_share["margin"] - by_share["net_profit"]).round(2)
    by_share["partner_profit"] = (by_share["net_profit"] * by_share["partner_share_pct"]).round(2)
    artem_total = float(by_share["partner_profit"].sum())
    return by_share, artem_total


def get_operational_expenses(expense_side: str | None = None) -> pd.DataFrame:
    """OPEX: расходы не привязанные к сделке (deal_id IS NULL).

    expense_side:
      - None: все
      - "ours": наши
      - "partner": партнёра
    """
    conn = get_conn()
    try:
        if expense_side in ("ours", "partner"):
            return pd.read_sql_query(
                """
                SELECT id, date, category, amount, who_paid, comment, expense_side
                FROM expenses
                WHERE deal_id IS NULL AND expense_side = %s
                ORDER BY date DESC, id DESC
                """,
                conn,
                params=(expense_side,),
            )
        return pd.read_sql_query(
            """
            SELECT id, date, category, amount, who_paid, comment, expense_side
            FROM expenses
            WHERE deal_id IS NULL
            ORDER BY date DESC, id DESC
            """,
            conn,
        )
    finally:
        conn.close()


def get_expense_by_id(expense_id: int) -> dict | None:
    row = run_query_one(
        "SELECT id, expense_side, date, category, amount, who_paid, comment, deal_id FROM expenses WHERE id = %s",
        (expense_id,),
    )
    if not row:
        return None
    return {
        "id": row[0],
        "expense_side": row[1],
        "date": row[2],
        "category": row[3],
        "amount": row[4],
        "who_paid": row[5],
        "comment": row[6],
        "deal_id": row[7],
    }


def update_expense(
    expense_id: int,
    *,
    date=None,
    category=None,
    amount=None,
    comment=None,
) -> None:
    """Обновить поля расхода (для OPEX/расходов по сделке)."""
    updates: list[str] = []
    params: list[object] = []
    if date is not None:
        updates.append("date = %s")
        params.append(str(date) if hasattr(date, "isoformat") else date)
    if category is not None:
        updates.append("category = %s")
        params.append(category)
    if amount is not None:
        updates.append("amount = %s")
        params.append(float(amount))
    if comment is not None:
        updates.append("comment = %s")
        params.append(comment or "")

    if not updates:
        return
    params.append(expense_id)
    run_query(f"UPDATE expenses SET {', '.join(updates)} WHERE id = %s", tuple(params))


def delete_expense(expense_id: int) -> None:
    run_query("DELETE FROM expenses WHERE id = %s", (expense_id,))


def calculate_deal(deal_type_name, revenue, cost, direct_exp, bonus):
    margin = revenue - cost - direct_exp - bonus
    share = get_partner_share_for_deal_type(deal_type_name)
    return margin, margin * share


def update_deal(
    deal_id: int,
    *,
    contract_number=None,
    deal_type=None,
    date=None,
    comment=None,
    revenue=None,
    cost_price=None,
    direct_expenses=None,
):
    """Обновить поля сделки. При смене типа — пересчёт partner_share.
    При смене revenue/cost_price/direct_expenses — пересчёт margin и partner_share."""
    deal = get_deal_by_id(deal_id)
    if not deal:
        return
    updates, params = [], []
    if contract_number is not None:
        updates.append("contract_number = %s")
        params.append(contract_number or "")
    if deal_type is not None:
        updates.append("deal_type = %s")
        params.append(deal_type)
    if date is not None:
        updates.append("date = %s")
        params.append(str(date) if hasattr(date, "isoformat") else date)
    if comment is not None:
        updates.append("comment = %s")
        params.append(comment or "")

    rev = float(revenue) if revenue is not None else (float(deal["revenue"]) if deal.get("revenue") is not None else 0)
    cost = float(cost_price) if cost_price is not None else (float(deal["cost_price"]) if deal.get("cost_price") is not None else 0)
    direct = float(direct_expenses) if direct_expenses is not None else (float(deal["direct_expenses"]) if deal.get("direct_expenses") is not None else 0)
    bonus = float(deal["manager_bonus"] or 0)

    if revenue is not None:
        updates.append("revenue = %s")
        params.append(rev)
    if cost_price is not None:
        updates.append("cost_price = %s")
        params.append(cost)
    if direct_expenses is not None:
        updates.append("direct_expenses = %s")
        params.append(direct)

    dtype = deal_type if deal_type is not None else (deal.get("deal_type") or "")
    if deal_type is not None or revenue is not None or cost_price is not None or direct_expenses is not None:
        margin = round(rev - cost - direct - bonus, 2)
        share = get_partner_share_for_deal_type(dtype) if dtype else 0
        new_ps = round(margin * share, 2)
        updates.append("margin = %s")
        params.append(margin)
        updates.append("partner_share = %s")
        params.append(new_ps)

    if not updates:
        return
    params.append(deal_id)
    q = f"UPDATE deals SET {', '.join(updates)} WHERE id = %s"
    run_query(q, tuple(params))
