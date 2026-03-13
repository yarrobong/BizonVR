"""Фиксация выплат партнёру."""
from datetime import datetime

import streamlit as st

from db import run_query


def render_payouts():
    st.header("Фиксация выплат")
    st.caption("Отметьте фактически переведённые партнёру суммы — они учитываются в итоге месяца.")
    with st.form("payout_form"):
        date = st.date_input("Дата выплаты", datetime.today())
        amount = st.number_input("Сумма переведенная партнеру", min_value=0.0, step=1000.0)
        comment = st.text_input("Комментарий")
        submitted = st.form_submit_button("Зафиксировать выплату")
        if submitted:
            run_query("INSERT INTO payouts (date, amount, comment) VALUES (%s, %s, %s)", (str(date), amount, comment or ""))
            st.success("Выплата сохранена")
