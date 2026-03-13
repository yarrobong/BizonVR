"""Список сделок и карточка сделки с расходами."""
from datetime import datetime

import streamlit as st

from config import DEAL_EXPENSE_CATEGORIES
from db import run_query
from logic import (
    delete_deal,
    get_deal_by_id,
    get_deals_list,
    get_expense_totals_by_deal,
    get_expenses_for_deal,
    get_deal_types,
    update_deal,
)


def render_deals_list():
    st.header("Сделки")
    st.caption("Все сделки. Нажмите «Подробнее», чтобы открыть сделку и добавить расходы.")
    deals_list = get_deals_list()
    if not deals_list:
        st.info("Нет сделок. Нажмите «Добавить сделку» выше.")
        return
    totals = get_expense_totals_by_deal()
    for d in deals_list:
        exp_total = totals.get(d["id"], 0)
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{d['date']}** · **{d['contract']}**")
                info = f"{d['deal_type']} · Выручка **{d['revenue']:,.0f}** ₽ · Маржа **{d['margin']:,.0f}** ₽"
                if exp_total > 0:
                    info += f" · Расходы по сделке **{exp_total:,.0f}** ₽"
                st.caption(info)
            with col2:
                if st.button("Подробнее", key=f"deal_btn_{d['id']}"):
                    st.session_state.deals_selected_id = d["id"]
                    st.rerun()


def _fmt_num(x):
    if x is None:
        return "—"
    try:
        return f"{float(x):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _edit_row(label: str, field: str, deal: dict, deal_id: int, type_names: list):
    """Клик по значению → правка на месте (договор, тип, дата, комментарий, суммы)."""
    editing = st.session_state.get("deal_edit_field") == field
    bid = deal_id
    display_map = {
        "contract": (deal.get("contract") or "").strip() or "—",
        "deal_type": deal.get("deal_type") or "—",
        "date": str(deal.get("date") or ""),
        "comment": (deal.get("comment") or "").strip() or "—",
        "revenue": _fmt_num(deal.get("revenue")),
        "cost_price": _fmt_num(deal.get("cost_price")),
        "direct_expenses": _fmt_num(deal.get("direct_expenses")),
    }
    display = display_map.get(field, "—")

    lab_col, val_col = st.columns([1, 2])
    with lab_col:
        st.markdown(f"**{label}**")
    with val_col:
        if editing:
            if field == "contract":
                v = st.text_input("", value=deal.get("contract") or "", key=f"ei_c_{bid}", label_visibility="collapsed")
            elif field == "deal_type":
                if not type_names:
                    type_names = [deal.get("deal_type") or "—"]
                idx = type_names.index(deal["deal_type"]) if deal.get("deal_type") in type_names else 0
                v = st.selectbox("", type_names, index=idx, key=f"ei_t_{bid}", label_visibility="collapsed")
            elif field == "date":
                d = deal.get("date")
                if d and hasattr(d, "year"):
                    v = st.date_input("", value=d, key=f"ei_d_{bid}", label_visibility="collapsed")
                else:
                    v = st.date_input("", value=datetime.today(), key=f"ei_d_{bid}", label_visibility="collapsed")
            elif field == "comment":
                v = st.text_input("", value=deal.get("comment") or "", key=f"ei_m_{bid}", label_visibility="collapsed")
            elif field == "revenue":
                v = st.number_input("", min_value=0.0, step=1000.0, value=float(deal.get("revenue") or 0), key=f"ei_r_{bid}", label_visibility="collapsed")
            elif field == "cost_price":
                v = st.number_input("", min_value=0.0, step=1000.0, value=float(deal.get("cost_price") or 0), key=f"ei_cost_{bid}", label_visibility="collapsed")
            else:  # direct_expenses
                v = st.number_input("", min_value=0.0, step=500.0, value=float(deal.get("direct_expenses") or 0), key=f"ei_dir_{bid}", label_visibility="collapsed")
            save_k, cancel_k = f"save_{field}_{bid}", f"cancel_{field}_{bid}"
            s, c = st.columns(2)
            with s:
                if st.button("Сохранить", key=save_k):
                    if field == "contract":
                        update_deal(deal_id, contract_number=v)
                    elif field == "deal_type":
                        update_deal(deal_id, deal_type=v)
                    elif field == "date":
                        update_deal(deal_id, date=v)
                    elif field == "comment":
                        update_deal(deal_id, comment=v)
                    elif field == "revenue":
                        update_deal(deal_id, revenue=v)
                    elif field == "cost_price":
                        update_deal(deal_id, cost_price=v)
                    elif field == "direct_expenses":
                        update_deal(deal_id, direct_expenses=v)
                    if "deal_edit_field" in st.session_state:
                        del st.session_state["deal_edit_field"]
                    st.rerun()
            with c:
                if st.button("Отмена", key=cancel_k):
                    if "deal_edit_field" in st.session_state:
                        del st.session_state["deal_edit_field"]
                    st.rerun()
        else:
            if st.button(display, key=f"edit_{field}_{bid}"):
                st.session_state["deal_edit_field"] = field
                st.rerun()


def render_deal_detail(deal_id: int):
    deal = get_deal_by_id(deal_id)
    if not deal:
        if "deals_selected_id" in st.session_state:
            del st.session_state["deals_selected_id"]
        if "deal_edit_field" in st.session_state:
            del st.session_state["deal_edit_field"]
        st.rerun()
        return
    st.subheader("Подробности сделки")
    back_col, del_col, _ = st.columns([1, 1, 4])
    with back_col:
        if st.button("← К списку сделок", key="back_deals"):
            for k in ("deals_selected_id", "deal_edit_field", "deal_delete_confirm"):
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
    with del_col:
        confirm = st.session_state.get("deal_delete_confirm") == deal_id
        if not confirm:
            if st.button("🗑 Удалить сделку", key="delete_deal_btn", type="secondary"):
                st.session_state["deal_delete_confirm"] = deal_id
                st.rerun()
        else:
            if st.button("Да, удалить", key="delete_deal_confirm"):
                delete_deal(deal_id)
                for k in ("deals_selected_id", "deal_edit_field", "deal_delete_confirm"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.success("Сделка удалена.")
                st.rerun()
            if st.button("Отмена", key="delete_deal_cancel"):
                del st.session_state["deal_delete_confirm"]
                st.rerun()
    st.caption("Щёлкните по значению, чтобы изменить.")
    st.divider()
    type_names = [t["name"] for t in get_deal_types()]
    c1, c2, c3 = st.columns(3)
    with c1:
        _edit_row("Выручка:", "revenue", deal, deal_id, type_names)
        _edit_row("Закуп (себестоимость):", "cost_price", deal, deal_id, type_names)
        _edit_row("Прямые расх. (доставка/упаковка):", "direct_expenses", deal, deal_id, type_names)
        st.write("**Маржа:**", _fmt_num(deal.get("margin")))
    with c2:
        _edit_row("Договор / клиент:", "contract", deal, deal_id, type_names)
        _edit_row("Тип:", "deal_type", deal, deal_id, type_names)
        st.write("**Доля партнёра:**", _fmt_num(deal.get("partner_share")))
    with c3:
        _edit_row("Дата:", "date", deal, deal_id, type_names)
        _edit_row("Комментарий:", "comment", deal, deal_id, type_names)
    st.divider()
    st.subheader("Расходы по сделке")
    exp_df = get_expenses_for_deal(deal_id)
    if exp_df.empty:
        st.caption("Пока нет расходов. Добавьте ниже.")
    else:
        st.dataframe(exp_df, use_container_width=True, hide_index=True)
        st.caption(f"Итого по сделке: {exp_df['amount'].sum():,.0f} ₽")
    with st.expander("Добавить расход к сделке", expanded=True):
        with st.form("deal_expense_form"):
            de_date = st.date_input("Дата", datetime.today(), key="de_date")
            de_cat = st.selectbox("Наименование", DEAL_EXPENSE_CATEGORIES, key="de_cat")
            de_amount = st.number_input("Сумма, ₽", min_value=0.0, step=100.0, key="de_amt")
            de_who = st.radio("Кто оплатил?", ["Я (из кассы)", "Партнер (свои)"], key="de_who")
            de_cmt = st.text_input("Комментарий", key="de_cmt")
            if st.form_submit_button("Добавить расход"):
                who_paid = "Я (Из кассы бизнеса/свои)" if "Я" in de_who else "Партнер (Свои деньги)"
                run_query(
                    """INSERT INTO expenses (expense_side, date, category, amount, who_paid,
                       partner_expense_share, comment, deal_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    ("ours" if "Я" in de_who else "partner", str(de_date), de_cat, de_amount, who_paid, 0, de_cmt or "", deal_id),
                )
                st.success(f"Расход добавлен: {de_cat} — {de_amount:,.0f} ₽")
                st.rerun()
