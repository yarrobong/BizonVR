"""Отчёт за месяц в формате Excel: сделки, расходы, выплаты — подробная детализация."""
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from config import MONTH_NAMES
from db import get_conn
from logic import compute_partner_profit_by_direction


def _excel_bytes_for_month(year: int, month: int) -> bytes:
    """Сформировать подробный Excel-файл за выбранный месяц. Возвращает bytes."""
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"

    conn = get_conn()
    deals = pd.read_sql_query(
        "SELECT * FROM deals WHERE date >= %s AND date < %s ORDER BY date, id",
        conn,
        params=(start_date, end_date),
    )
    expenses = pd.read_sql_query(
        "SELECT * FROM expenses WHERE date >= %s AND date < %s ORDER BY date, id",
        conn,
        params=(start_date, end_date),
    )
    payouts = pd.read_sql_query(
        "SELECT * FROM payouts WHERE date >= %s AND date < %s ORDER BY date, id",
        conn,
        params=(start_date, end_date),
    )
    # Расходы по сделкам с данными сделки (для периода по дате расхода)
    by_deal_join = pd.read_sql_query(
        """SELECT e.id AS exp_id, e.deal_id, e.date AS exp_date, e.category, e.amount, e.who_paid, e.comment AS exp_comment,
                  d.date AS deal_date, d.contract_number AS deal_contract, d.deal_type, d.revenue AS deal_revenue,
                  d.cost_price, d.direct_expenses, d.manager_bonus, d.margin AS deal_margin, d.partner_share AS deal_partner_share, d.comment AS deal_comment
           FROM expenses e
           JOIN deals d ON e.deal_id = d.id
           WHERE e.date >= %s AND e.date < %s AND e.deal_id IS NOT NULL
           ORDER BY d.date, d.id, e.date, e.id""",
        conn,
        params=(start_date, end_date),
    )
    conn.close()

    # —— Сводка подробная ——
    n_deals = len(deals)
    total_revenue = deals["revenue"].sum() if not deals.empty else 0
    total_cost = deals["cost_price"].sum() if not deals.empty else 0
    total_direct = deals["direct_expenses"].sum() if not deals.empty else 0
    total_bonus = deals["manager_bonus"].sum() if not deals.empty else 0
    total_margin = deals["margin"].sum() if not deals.empty else 0

    # OPEX: только операционные расходы (deal_id IS NULL); распределение по направлениям пропорционально марже
    exp_opex = expenses[expenses["deal_id"].isna()] if not expenses.empty and "deal_id" in expenses.columns else pd.DataFrame()
    ours = exp_opex[exp_opex["expense_side"] == "ours"] if not exp_opex.empty and "expense_side" in exp_opex.columns else pd.DataFrame()
    partner_exp = exp_opex[exp_opex["expense_side"] == "partner"] if not exp_opex.empty and "expense_side" in exp_opex.columns else pd.DataFrame()
    if ours.empty and not exp_opex.empty:
        ours = exp_opex[exp_opex["who_paid"].astype(str).str.contains("касс|свои", case=False, na=False)]
    if partner_exp.empty and not exp_opex.empty:
        partner_exp = exp_opex[exp_opex["who_paid"].astype(str).str.contains("Партнер", case=False, na=False)]

    total_ours_opex = ours["amount"].sum() if not ours.empty else 0
    total_partner_exp = partner_exp["amount"].sum() if not partner_exp.empty else 0
    total_opex_both = total_ours_opex + total_partner_exp
    by_direction_df, partner_profit = compute_partner_profit_by_direction(deals, total_opex_both)

    by_deal = expenses[expenses["deal_id"].notna()] if not expenses.empty and "deal_id" in expenses.columns else pd.DataFrame()
    total_exp_by_deal = by_deal["amount"].sum() if not by_deal.empty else 0
    already_paid = payouts["amount"].sum() if not payouts.empty else 0
    # Расходы партнёра уже в общем OPEX при расчёте чистой прибыли — возврат не добавляем
    final_payout = partner_profit - already_paid
    n_payouts = len(payouts)
    n_expenses = len(expenses)

    summary_rows = [
        ("Количество сделок", n_deals, ""),
        ("Выручка всего", total_revenue, "₽"),
        ("Себестоимость всего", total_cost, "₽"),
        ("Прямые расходы всего", total_direct, "₽"),
        ("Бонусы менеджерам всего", total_bonus, "₽"),
        ("Маржа всего", total_margin, "₽"),
        ("Доля партнёра в прибыли", partner_profit, "₽"),
        ("", None, ""),
        ("Количество расходов", n_expenses, ""),
        ("Наши расходы (OPEX)", total_ours_opex, "₽"),
        ("Расходы партнёра (оплатил сам)", total_partner_exp, "₽"),
        ("Расходы по сделкам (привязанные)", total_exp_by_deal, "₽"),
        ("", None, ""),
        ("Выплат партнёру", n_payouts, ""),
        ("Уже выплачено", already_paid, "₽"),
        ("Итого к выдаче / долг партнёра", final_payout, "₽"),
    ]
    summary_df = pd.DataFrame(
        [(r[0], r[1] if r[1] is not None else "", r[2]) for r in summary_rows],
        columns=["Показатель", "Значение", "Ед."],
    )

    # —— Сделки: все поля ——
    deals_ru = deals.rename(columns={
        "id": "ID",
        "date": "Дата",
        "contract_number": "Договор / Клиент",
        "deal_type": "Тип сделки",
        "revenue": "Выручка",
        "cost_price": "Себестоимость",
        "direct_expenses": "Прямые расходы",
        "manager_bonus": "Бонус менеджера",
        "margin": "Маржа",
        "partner_share": "Доля партнёра",
        "comment": "Комментарий",
    })

    # —— Расходы по сделкам подробно (с данными сделки) ——
    if not by_deal_join.empty:
        by_deal_det = by_deal_join.rename(columns={
            "exp_id": "ID расхода",
            "deal_id": "ID сделки",
            "deal_date": "Дата сделки",
            "deal_contract": "Договор / Клиент",
            "deal_type": "Тип сделки",
            "deal_revenue": "Выручка сделки",
            "cost_price": "Себестоимость",
            "direct_expenses": "Прямые расходы",
            "manager_bonus": "Бонус менеджера",
            "deal_margin": "Маржа сделки",
            "deal_partner_share": "Доля партнёра по сделке",
            "deal_comment": "Комментарий сделки",
            "exp_date": "Дата расхода",
            "category": "Категория расхода",
            "amount": "Сумма расхода",
            "who_paid": "Кто оплатил",
            "exp_comment": "Комментарий расхода",
        })
        # Порядок колонок для удобства
        col_order = [
            "ID сделки", "Дата сделки", "Договор / Клиент", "Тип сделки",
            "Выручка сделки", "Себестоимость", "Прямые расходы", "Бонус менеджера", "Маржа сделки", "Доля партнёра по сделке", "Комментарий сделки",
            "ID расхода", "Дата расхода", "Категория расхода", "Сумма расхода", "Кто оплатил", "Комментарий расхода",
        ]
        by_deal_det = by_deal_det[[c for c in col_order if c in by_deal_det.columns]]
    else:
        by_deal_det = pd.DataFrame(columns=[
            "ID сделки", "Дата сделки", "Договор / Клиент", "Тип сделки",
            "ID расхода", "Дата расхода", "Категория расхода", "Сумма расхода", "Кто оплатил", "Комментарий расхода",
        ])

    # —— Развёрнуто: каждая сделка × каждый её расход (или сделка без расходов) ——
    expand_rows = []
    for _, d in deals.iterrows():
        did = d["id"]
        dexp = by_deal_join[by_deal_join["deal_id"] == did] if not by_deal_join.empty else pd.DataFrame()
        if dexp.empty:
            expand_rows.append({
                "ID сделки": did,
                "Дата сделки": d["date"],
                "Договор / Клиент": d["contract_number"],
                "Тип сделки": d["deal_type"],
                "Выручка": d["revenue"],
                "Себестоимость": d["cost_price"],
                "Прямые расходы": d["direct_expenses"],
                "Бонус менеджера": d["manager_bonus"],
                "Маржа": d["margin"],
                "Доля партнёра": d["partner_share"],
                "Комментарий сделки": d["comment"],
                "ID расхода": None,
                "Дата расхода": None,
                "Категория расхода": None,
                "Сумма расхода": None,
                "Кто оплатил расход": None,
                "Комментарий расхода": None,
            })
        else:
            for _, ex in dexp.iterrows():
                expand_rows.append({
                    "ID сделки": did,
                    "Дата сделки": d["date"],
                    "Договор / Клиент": d["contract_number"],
                    "Тип сделки": d["deal_type"],
                    "Выручка": d["revenue"],
                    "Себестоимость": d["cost_price"],
                    "Прямые расходы": d["direct_expenses"],
                    "Бонус менеджера": d["manager_bonus"],
                    "Маржа": d["margin"],
                    "Доля партнёра": d["partner_share"],
                    "Комментарий сделки": d["comment"],
                    "ID расхода": ex["exp_id"],
                    "Дата расхода": ex["exp_date"],
                    "Категория расхода": ex["category"],
                    "Сумма расхода": ex["amount"],
                    "Кто оплатил расход": ex["who_paid"],
                    "Комментарий расхода": ex["exp_comment"],
                })
    expand_df = pd.DataFrame(expand_rows)

    # —— Наши расходы: все колонки ——
    ours_cols = {"id": "ID", "expense_side": "Сторона", "date": "Дата", "category": "Категория", "amount": "Сумма",
                 "who_paid": "Кто оплатил", "partner_expense_share": "Доля партн. в расх.", "comment": "Комментарий", "deal_id": "ID сделки"}
    ours_ru = ours.rename(columns={k: v for k, v in ours_cols.items() if k in ours.columns}) if not ours.empty else pd.DataFrame(columns=list(ours_cols.values()))
    partner_ru = partner_exp.rename(columns={k: v for k, v in ours_cols.items() if k in partner_exp.columns}) if not partner_exp.empty else pd.DataFrame(columns=list(ours_cols.values()))

    # —— Все расходы: полная таблица + привязка к сделке ——
    exp_ru = expenses.copy()
    deal_map = deals.set_index("id")["contract_number"].to_dict() if not deals.empty else {}
    if not expenses.empty and "deal_id" in expenses.columns:
        exp_ru["Договор по сделке"] = exp_ru["deal_id"].map(lambda x: deal_map.get(int(x), "—") if pd.notna(x) else "—")
    exp_ru = exp_ru.rename(columns={
        "id": "ID",
        "expense_side": "Сторона",
        "date": "Дата",
        "category": "Категория",
        "amount": "Сумма",
        "who_paid": "Кто оплатил",
        "partner_expense_share": "Доля партнёра в расх.",
        "comment": "Комментарий",
        "deal_id": "ID сделки",
    })
    if "Договор по сделке" not in exp_ru.columns and not exp_ru.empty:
        exp_ru["Договор по сделке"] = "—"

    payouts_ru = payouts.rename(columns={"id": "ID", "date": "Дата", "amount": "Сумма", "comment": "Комментарий"})

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        summary_df.to_excel(w, sheet_name="Сводка подробная", index=False)
        deals_ru.to_excel(w, sheet_name="Сделки (все поля)", index=False)
        expand_df.to_excel(w, sheet_name="Сделки и расходы по сделкам (развёрнуто)", index=False)
        by_deal_det.to_excel(w, sheet_name="Расходы по сделкам (подробно)", index=False)
        if not ours_ru.empty:
            ours_ru.to_excel(w, sheet_name="Наши расходы", index=False)
        else:
            pd.DataFrame(columns=list(ours_cols.values())).to_excel(w, sheet_name="Наши расходы", index=False)
        if not partner_ru.empty:
            partner_ru.to_excel(w, sheet_name="Расходы партнёра", index=False)
        else:
            pd.DataFrame(columns=list(ours_cols.values())).to_excel(w, sheet_name="Расходы партнёра", index=False)
        exp_ru.to_excel(w, sheet_name="Все расходы (подробно)", index=False)
        payouts_ru.to_excel(w, sheet_name="Выплаты", index=False)

    buf.seek(0)
    return buf.getvalue()


def render_report():
    st.header("Отчёт за месяц (Excel)")
    st.caption("Скачайте полный отчёт по сделкам, расходам и выплатам за выбранный месяц.")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        month = st.selectbox(
            "Месяц",
            range(1, 13),
            index=datetime.today().month - 1,
            format_func=lambda x: MONTH_NAMES[x - 1].capitalize(),
            key="report_month",
        )
    with col2:
        year = st.number_input("Год", value=datetime.today().year, min_value=2020, max_value=2030, key="report_year")

    month_name = MONTH_NAMES[month - 1].capitalize()
    filename = f"otchet_{year}_{month:02d}_{month_name}.xlsx"

    if st.button("Сформировать и скачать Excel", type="primary"):
        with st.spinner("Формирую отчёт…"):
            data = _excel_bytes_for_month(year, month)
        st.session_state["report_download_data"] = data
        st.session_state["report_download_filename"] = filename
        st.session_state["report_download_month"] = (year, month)
        st.rerun()

    # Показываем кнопку скачивания, если отчёт уже сформирован для этого месяца
    prev = st.session_state.get("report_download_month")
    if prev == (year, month) and st.session_state.get("report_download_data"):
        st.download_button(
            label="Скачать отчёт",
            data=st.session_state["report_download_data"],
            file_name=st.session_state.get("report_download_filename", filename),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_report",
        )
        st.success(f"Отчёт за {month_name} {year} готов. Нажмите «Скачать отчёт» выше.")
