"""Архив: сделки, расходы, выплаты."""
import pandas as pd
import streamlit as st

from db import get_conn


def render_archive():
    st.header("Архив операций")
    st.caption("Полная база: сделки, расходы и выплаты.")
    conn = get_conn()
    try:
        with st.expander("Сделки", expanded=True):
            st.dataframe(pd.read_sql("SELECT * FROM deals", conn), use_container_width=True, hide_index=True)
        exp_all = pd.read_sql(
            """SELECT e.id, e.deal_id, e.expense_side, e.date, e.category, e.amount, e.who_paid, e.comment,
                      d.contract_number AS deal_contract
               FROM expenses e LEFT JOIN deals d ON e.deal_id = d.id ORDER BY e.date DESC, e.id DESC""",
            conn,
        )
        if not exp_all.empty and "expense_side" in exp_all.columns:
            _df = exp_all.rename(columns={"deal_contract": "Сделка"})
            _df["Сделка"] = _df["Сделка"].fillna("—")
            _cols = ["date", "category", "amount", "who_paid", "Сделка", "comment"]
            _disp = _df[[c for c in _cols if c in _df.columns]]
            with st.expander("Наши расходы"):
                st.dataframe(_disp[_df["expense_side"] == "ours"], use_container_width=True, hide_index=True)
            with st.expander("Расходы партнёра"):
                st.dataframe(_disp[_df["expense_side"] == "partner"], use_container_width=True, hide_index=True)
        else:
            with st.expander("Расходы"):
                st.dataframe(exp_all, use_container_width=True, hide_index=True)
        with st.expander("Выплаты"):
            st.dataframe(pd.read_sql("SELECT * FROM payouts", conn), use_container_width=True, hide_index=True)
    finally:
        conn.close()
