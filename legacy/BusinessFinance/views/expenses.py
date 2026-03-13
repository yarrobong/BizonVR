"""Операционные расходы: наши и партнёра. Список блоков + карточка расхода (как в сделках)."""
from datetime import datetime

import streamlit as st

from db import run_query
from logic import (
    delete_expense,
    get_expense_by_id,
    get_operational_expenses,
    get_our_categories,
    get_partner_categories,
    update_expense,
)


def _fmt_rub(x) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _side_label(side: str | None) -> str:
    return {"ours": "Наши", "partner": "Партнёр"}.get(side or "", "—")


def _side_chip_html(side: str | None) -> str:
    if side == "ours":
        return "<span class='expense-chip expense-chip-ours'>Наши</span>"
    if side == "partner":
        return "<span class='expense-chip expense-chip-partner'>Партнёр</span>"
    return "<span class='expense-chip'>—</span>"


def _edit_row_expense(label: str, field: str, expense: dict, expense_id: int, cats: list):
    """Клик по значению → правка на месте (дата, категория, сумма, комментарий)."""
    editing = st.session_state.get("expense_edit_field") == field
    bid = expense_id
    display_map = {
        "date": str(expense.get("date") or ""),
        "category": (expense.get("category") or "").strip() or "—",
        "amount": _fmt_rub(expense.get("amount")),
        "comment": (expense.get("comment") or "").strip() or "—",
    }
    display = display_map.get(field, "—")

    lab_col, val_col = st.columns([1, 2])
    with lab_col:
        st.markdown(f"**{label}**")
    with val_col:
        if editing:
            if field == "date":
                d = expense.get("date")
                v = st.date_input(
                    "",
                    value=d if d and hasattr(d, "year") else datetime.today(),
                    key=f"exp_ei_d_{bid}",
                    label_visibility="collapsed",
                )
            elif field == "category":
                idx = cats.index(expense["category"]) if expense.get("category") in cats else 0
                v = st.selectbox("", cats, index=idx, key=f"exp_ei_c_{bid}", label_visibility="collapsed")
            elif field == "amount":
                v = st.number_input(
                    "",
                    min_value=0.0,
                    step=100.0,
                    value=float(expense.get("amount") or 0),
                    key=f"exp_ei_a_{bid}",
                    label_visibility="collapsed",
                )
            else:  # comment
                v = st.text_input(
                    "",
                    value=expense.get("comment") or "",
                    key=f"exp_ei_m_{bid}",
                    label_visibility="collapsed",
                )
            s, c = st.columns(2)
            with s:
                if st.button("Сохранить", key=f"exp_save_{field}_{bid}"):
                    if field == "date":
                        update_expense(expense_id, date=v)
                    elif field == "category":
                        update_expense(expense_id, category=v)
                    elif field == "amount":
                        update_expense(expense_id, amount=v)
                    elif field == "comment":
                        update_expense(expense_id, comment=v)
                    if "expense_edit_field" in st.session_state:
                        del st.session_state["expense_edit_field"]
                    st.rerun()
            with c:
                if st.button("Отмена", key=f"exp_cancel_{field}_{bid}"):
                    if "expense_edit_field" in st.session_state:
                        del st.session_state["expense_edit_field"]
                    st.rerun()
        else:
            if st.button(display, key=f"exp_edit_{field}_{bid}"):
                st.session_state["expense_edit_field"] = field
                st.rerun()


def render_expense_detail(expense_id: int):
    """Карточка расхода: кнопки назад/удалить, поля с кликом для редактирования."""
    expense = get_expense_by_id(expense_id)
    if not expense:
        for k in ("expenses_selected_id", "expense_edit_field", "expense_delete_confirm_id"):
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()
        return

    st.subheader("Подробности расхода")
    back_col, del_col, _ = st.columns([1, 1, 4])
    with back_col:
        if st.button("← К списку расходов", key="back_expenses"):
            for k in ("expenses_selected_id", "expense_edit_field", "expense_delete_confirm_id"):
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
    with del_col:
        confirm = st.session_state.get("expense_delete_confirm_id") == expense_id
        if not confirm:
            if st.button("🗑 Удалить расход", key="delete_expense_btn", type="secondary"):
                st.session_state["expense_delete_confirm_id"] = expense_id
                st.rerun()
        else:
            if st.button("Да, удалить", key="exp_delete_confirm"):
                delete_expense(expense_id)
                for k in ("expenses_selected_id", "expense_edit_field", "expense_delete_confirm_id"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.success("Расход удалён.")
                st.rerun()
            if st.button("Отмена", key="exp_delete_cancel"):
                del st.session_state["expense_delete_confirm_id"]
                st.rerun()

    st.caption("Щёлкните по значению, чтобы изменить.")
    st.divider()

    side = expense.get("expense_side")
    cats = get_our_categories() if side == "ours" else get_partner_categories()

    c1, c2 = st.columns(2)
    with c1:
        _edit_row_expense("Дата:", "date", expense, expense_id, cats)
        _edit_row_expense("Категория:", "category", expense, expense_id, cats)
    with c2:
        _edit_row_expense("Сумма, ₽:", "amount", expense, expense_id, cats)
        _edit_row_expense("Комментарий:", "comment", expense, expense_id, cats)

    st.caption(f"Чей расход: **{_side_label(side)}** (менять нельзя для OPEX).")


def render_expenses():
    st.header("Операционные расходы (OPEX)")
    st.caption(
        "Все операционные расходы (без привязки к сделке). "
        "Нажмите «Подробнее» на блоке, чтобы открыть и редактировать расход."
    )

    view = st.radio(
        "Показать",
        ["Все расходы", "Наши расходы", "Расходы партнёра"],
        horizontal=True,
        key="expenses_view",
    )
    side_filter = None
    if view == "Наши расходы":
        side_filter = "ours"
    elif view == "Расходы партнёра":
        side_filter = "partner"

    selected_id = st.session_state.get("expenses_selected_id")

    if selected_id is not None:
        render_expense_detail(selected_id)
        st.divider()

    st.subheader("Список расходов" if selected_id is None else "Другие расходы")
    df = get_operational_expenses(side_filter)
    if df is None or df.empty:
        st.info("Пока нет расходов по выбранному фильтру.")
    else:
        for _, r in df.iterrows():
            eid = int(r["id"])
            date_s = str(r["date"])
            cat_s = (r["category"] or "").strip() or "—"
            amt_s = _fmt_rub(r["amount"])
            side = r.get("expense_side")
            side_lbl = _side_label(side)
            cmt = (r["comment"] or "").strip()
            info_line = f"**{date_s}** · **{cat_s}** · **{amt_s}** · {side_lbl}"
            if cmt:
                info_line += f" · {cmt[:40]}{'…' if len(cmt) > 40 else ''}"

            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(info_line)
                    if cmt and len(cmt) > 40:
                        st.caption(cmt)
                with col2:
                    if st.button("Подробнее", key=f"exp_btn_{eid}"):
                        st.session_state["expenses_selected_id"] = eid
                        for k in ("expense_edit_field", "expense_delete_confirm_id"):
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

    st.divider()
    st.subheader("Добавить расход")

    if side_filter in ("ours", "partner"):
        add_side = side_filter
    else:
        who = st.radio("Кому записать?", ["Наши", "Партнёр"], horizontal=True, key="exp_add_side")
        add_side = "ours" if who == "Наши" else "partner"

    add_cats = get_our_categories() if add_side == "ours" else get_partner_categories()
    who_paid = "Я (Из кассы бизнеса/свои)" if add_side == "ours" else "Партнер (Свои деньги)"

    with st.form("expense_add_form"):
        d = st.date_input("Дата", datetime.today(), key="exp_add_date")
        cat = st.selectbox("Категория", add_cats, key="exp_add_cat")
        amt = st.number_input("Сумма, ₽", min_value=0.0, step=100.0, key="exp_add_amt")
        cmt = st.text_input("Комментарий (необяз.)", key="exp_add_cmt")
        if st.form_submit_button("Добавить расход"):
            run_query(
                """INSERT INTO expenses (expense_side, date, category, amount, who_paid,
                   partner_expense_share, comment, deal_id) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)""",
                (add_side, str(d), cat, amt, who_paid, 0, cmt or ""),
            )
            st.success(f"Расход добавлен: {cat} — {_fmt_rub(amt)}")
            st.rerun()
