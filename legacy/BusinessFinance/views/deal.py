"""Форма новой сделки."""
from datetime import datetime

import streamlit as st

from db import run_query
from logic import calculate_deal, get_deal_types


def render_deal_form():
    st.header("Новая сделка")
    st.caption("Внесите данные по сделке — маржа и доля партнёра рассчитаются автоматически.")
    deal_types = get_deal_types()
    type_names = [t["name"] for t in deal_types]
    with st.form("deal_form"):
        col1, col2 = st.columns(2)
        date = col1.date_input("Дата сделки", datetime.today())
        contract = col2.text_input("Номер договора / Клиент")
        deal_type = st.selectbox("Тип сделки", type_names)
        c1, c2, c3, c4 = st.columns(4)
        revenue = c1.number_input("Выручка", min_value=0.0, step=1000.0)
        cost = c2.number_input("Закуп (Себестоимость)", min_value=0.0, step=1000.0)
        direct_exp = c3.number_input("Прямые расх. (Доставка/Упаковка)", min_value=0.0, step=500.0)
        bonus = c4.number_input("Бонус менеджера (за сделку)", min_value=0.0, step=500.0)
        comment = st.text_area("Комментарий")
        submitted = st.form_submit_button("Сохранить сделку")
        if submitted:
            margin, partner_share = calculate_deal(deal_type, revenue, cost, direct_exp, bonus)
            run_query(
                """INSERT INTO deals (date, contract_number, deal_type, revenue, cost_price, direct_expenses,
                   manager_bonus, margin, partner_share, comment) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (str(date), contract, deal_type, revenue, cost, direct_exp, bonus, margin, partner_share, comment or ""),
            )
            st.success(f"Сделка сохранена! Маржа: {margin:,.0f}, Доля партнера: {partner_share:,.0f}")
