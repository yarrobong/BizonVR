"""Дашборд: финансовый обзор за выбранный период."""
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import get_conn
from logic import compute_partner_profit_by_direction

# Короткие названия месяцев для фильтра слева направо
MONTH_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]


def render_dashboard():
    st.header("Финансовый обзор")

    # Строка фильтров: слева — год, справа — месяцы кнопками + «Все»
    # dash_month: 1–12 = месяц, 0 = весь год
    if "dash_month" not in st.session_state:
        st.session_state.dash_month = datetime.today().month
    row_filter = st.columns([1, 4])
    with row_filter[0]:
        selected_year = st.number_input(
            "Год",
            value=datetime.today().year,
            min_value=2020,
            max_value=2030,
            key="dash_year",
        )
    with row_filter[1]:
        st.caption("Месяц")
        # Два ряда кнопок: первый — месяцы 1–7, второй — 8–12 + «Все»
        month_row1 = st.columns(7)
        month_row2 = st.columns(6)  # 5 месяцев + Все
        for i, col in enumerate(month_row1):
            m = i + 1
            label = MONTH_SHORT[i]
            is_selected = st.session_state.dash_month == m
            with col:
                if st.button(
                    label,
                    key=f"dash_m{m}",
                    type="primary" if is_selected else "secondary",
                    use_container_width=True,
                ) and not is_selected:
                    st.session_state.dash_month = m
                    st.rerun()
        for i, col in enumerate(month_row2):
            if i < 5:
                m = i + 8
                label = MONTH_SHORT[i + 7]
            else:
                m = 0
                label = "Все"
            is_selected = st.session_state.dash_month == m
            with col:
                if st.button(
                    label,
                    key=f"dash_m{m}" if m > 0 else "dash_m_all",
                    type="primary" if is_selected else "secondary",
                    use_container_width=True,
                ) and not is_selected:
                    st.session_state.dash_month = m
                    st.rerun()
        selected_month = st.session_state.dash_month

    if selected_month == 0:
        start_date = f"{selected_year}-01-01"
        end_date = f"{selected_year + 1}-01-01"
    else:
        start_date = f"{selected_year}-{selected_month:02d}-01"
        end_date = f"{selected_year + 1}-01-01" if selected_month == 12 else f"{selected_year}-{selected_month + 1:02d}-01"

    conn = get_conn()
    deals_data = pd.read_sql_query(
        "SELECT * FROM deals WHERE date >= %s AND date < %s ORDER BY date, id",
        conn,
        params=(start_date, end_date),
    )
    exp_data = pd.read_sql_query(
        "SELECT * FROM expenses WHERE date >= %s AND date < %s",
        conn,
        params=(start_date, end_date),
    )
    payout_data = pd.read_sql_query(
        "SELECT * FROM payouts WHERE date >= %s AND date < %s",
        conn,
        params=(start_date, end_date),
    )
    conn.close()

    def _sum_num(df, col, default=0.0):
        """Сумма колонки с приведением к float (учёт Decimal, NULL, нечисловых)."""
        if df is None or df.empty or col not in df.columns:
            return float(default)
        return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

    # Финансовые величины за период (явно в float для корректного отображения)
    turnover = _sum_num(deals_data, "revenue")
    cost_of_goods = _sum_num(deals_data, "cost_price")
    company_profit = _sum_num(deals_data, "margin")  # прибыль компании (маржа)

    # OPEX: только операционные расходы (не привязанные к сделке) для расчёта 50/50
    if not exp_data.empty and "deal_id" in exp_data.columns:
        exp_opex = exp_data.loc[exp_data["deal_id"].isna()]
    else:
        exp_opex = pd.DataFrame()

    if not exp_opex.empty and "expense_side" in exp_opex.columns:
        opex_ours = exp_opex.loc[exp_opex["expense_side"] == "ours"]
        opex_partner = exp_opex.loc[exp_opex["expense_side"] == "partner"]
        total_opex = _sum_num(opex_ours, "amount")
        partner_paid_physically = _sum_num(opex_partner, "amount")
    else:
        total_opex = _sum_num(exp_opex, "amount")
        if not exp_opex.empty and "who_paid" in exp_opex.columns:
            partner_paid_physically = _sum_num(
                exp_opex[exp_opex["who_paid"] == "Партнер (Свои деньги)"], "amount"
            )
        else:
            partner_paid_physically = 0.0

    total_opex_both = total_opex + partner_paid_physically  # наши + его OPEX
    # Чистая прибыль распределяется по направлениям пропорционально (маржа × доля партнёра); OPEX по направлению = маржа − выделенная чистая прибыль (не пропорционально марже)
    by_direction_df, artem_profit = compute_partner_profit_by_direction(deals_data, total_opex_both)
    already_paid = _sum_num(payout_data, "amount")

    # Для метрики "наши операционные расходы" и net_profit — все наши расходы за период (в т.ч. по сделкам)
    if not exp_data.empty and "expense_side" in exp_data.columns:
        ours_all = exp_data.loc[exp_data["expense_side"] == "ours"]
        total_opex_display = _sum_num(ours_all, "amount")
    else:
        total_opex_display = _sum_num(exp_data, "amount")
    net_profit = company_profit - total_opex_display  # чистая прибыль компании

    # К выдаче = доля Артёма по направлениям − уже выплачено. Расходы партнёра уже в общем OPEX при расчёте чистой прибыли — возврат не добавляем (двойной учёт).
    final_payout = artem_profit - already_paid

    # Блок: финансовый обзор — метрики в три ряда (3 + 2 + 2)
    st.markdown("#### Финансовый обзор за период")
    row1 = st.columns(3)
    row1[0].metric("Оборот за период", f"{turnover:,.0f} ₽", help="Сумма выручки по сделкам")
    row1[1].metric("Закупка товара", f"{cost_of_goods:,.0f} ₽", help="Себестоимость товара")
    row1[2].metric("Прибыль компании", f"{company_profit:,.0f} ₽", help="Маржа: выручка − закуп − прямые расходы − бонусы")
    row2 = st.columns(2)
    row2[0].metric("Чистая прибыль компании", f"{net_profit:,.0f} ₽", help="Прибыль компании минус наши операционные расходы")
    row2[1].metric("Прибыль лидген бюро (Артёма)", f"{artem_profit:,.0f} ₽", help="Сумма долей по направлениям: OPEX распределён по марже, от чистой прибыли по каждому типу — доля партнёра (0/30/50%)")
    row3 = st.columns(2)
    row3[0].metric("Расходы наши", f"{total_opex:,.0f} ₽", help="Операционные расходы (OPEX) за период")
    row3[1].metric("Расходы партнёра", f"{partner_paid_physically:,.0f} ₽", help="Операционные расходы, оплаченные партнёром")

    # Графики: слева — динамика доходов/расходов, справа — типы сделок (круговая диаграмма)
    st.markdown("#### Динамика и структура")
    chart_col, pie_col = st.columns([2, 1])

    with chart_col:
        # Динамика доходов и расходов по датам за период
        dates = pd.date_range(start=start_date, end=pd.Timestamp(end_date) - timedelta(days=1), freq="D")
        if not deals_data.empty and "date" in deals_data.columns and "revenue" in deals_data.columns:
            rev = pd.to_numeric(deals_data["revenue"], errors="coerce").fillna(0)
            income_by_date = deals_data.assign(_rev=rev).groupby("date")["_rev"].sum()
        else:
            income_by_date = pd.Series(dtype=float)
        if not exp_data.empty and "date" in exp_data.columns and "amount" in exp_data.columns:
            amt = pd.to_numeric(exp_data["amount"], errors="coerce").fillna(0)
            exp_by_date = exp_data.assign(_amt=amt).groupby("date")["_amt"].sum()
        else:
            exp_by_date = pd.Series(dtype=float)
        income_map = {pd.Timestamp(k).date() if hasattr(k, "date") else k: float(v) for k, v in income_by_date.items()} if len(income_by_date) else {}
        exp_map = {pd.Timestamp(k).date() if hasattr(k, "date") else k: float(v) for k, v in exp_by_date.items()} if len(exp_by_date) else {}
        df_dates = pd.DataFrame(index=dates)
        df_dates["Доходы"] = [income_map.get(d.date(), 0.0) for d in df_dates.index]
        df_dates["Расходы"] = [exp_map.get(d.date(), 0.0) for d in df_dates.index]
        if float(df_dates["Доходы"].sum()) > 0 or float(df_dates["Расходы"].sum()) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_dates.index, y=df_dates["Доходы"], name="Доходы", marker_color="#2ecc71"))
            fig.add_trace(go.Bar(x=df_dates.index, y=df_dates["Расходы"], name="Расходы", marker_color="#e74c3c"))
            fig.update_layout(title="Динамика доходов и расходов за период", xaxis_title="Дата", yaxis_title="₽", legend=dict(orientation="h"), margin=dict(l=40, r=20, t=40, b=40), height=320, barmode="group")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Нет данных по доходам и расходам за выбранный период.")

    with pie_col:
        # Круговая диаграмма: доля типов сделок по выручке
        if not deals_data.empty and "deal_type" in deals_data.columns and "revenue" in deals_data.columns:
            rev = pd.to_numeric(deals_data["revenue"], errors="coerce").fillna(0)
            type_revenue = deals_data.assign(_rev=rev).groupby("deal_type")["_rev"].sum()
            if float(type_revenue.sum()) > 0:
                fig_pie = go.Figure(data=[go.Pie(labels=type_revenue.index.tolist(), values=type_revenue.astype(float).tolist(), hole=0.5, textinfo="label+percent", textposition="outside")])
                fig_pie.update_layout(title="Типы сделок (% выручки)", margin=dict(l=20, r=20, t=40, b=20), height=320, showlegend=False)
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.caption("Нет выручки по сделкам за период.")
        else:
            st.caption("Нет сделок за выбранный период.")

    st.divider()
    st.subheader("Расчёт с партнёром (Артём)")
    st.markdown("""
    Ниже пошаговый расчёт: общая чистая прибыль (маржа − OPEX) распределяется по направлениям **пропорционально (маржа × доля партнёра)** — расходы по направлениям тогда не пропорциональны марже; доля Артёма = чистая прибыль × % по типу (0/30/50%).
    Расходы уже учтены в чистой прибыли (включая расходы партнёра). К выдаче = сумма долей Артёма − уже выплачено (возврат его расходов не добавляем — они уже в OPEX).
    """)

    # —— 1. Исходные данные ——
    st.markdown("##### 1. Исходные данные за период")
    st.markdown(f"""
    | Показатель | Значение |
    |------------|----------|
    | Прибыль компании (маржа по сделкам) | **{company_profit:,.2f} ₽** |
    | Операционные расходы — наши | {total_opex:,.2f} ₽ |
    | Операционные расходы — партнёр (оплатил сам) | {partner_paid_physically:,.2f} ₽ |
    | **OPEX всего** | **{total_opex_both:,.2f} ₽** |
    """)
    st.caption("Операционные расходы — только те, что не привязаны к конкретной сделке (общие расходы периода).")

    # —— 2. Распределение OPEX по направлениям ——
    st.markdown("##### 2. Распределение чистой прибыли и OPEX по направлениям")
    st.markdown("Чистая прибыль (маржа всего − OPEX всего) распределяется по группам **пропорционально (маржа × доля партнёра)**. OPEX по направлению = маржа направления − выделенная ему чистая прибыль (поэтому расходы **не** пропорциональны марже).")
    if by_direction_df.empty:
        st.caption("Нет сделок за период — распределение OPEX по направлениям не применимо.")
    if not by_direction_df.empty and company_profit > 0:
        weight_sum = float((by_direction_df["margin"] * by_direction_df["partner_share_pct"]).sum())
        rows_opex = []
        for _, row in by_direction_df.iterrows():
            m = float(row["margin"])
            w = m * float(row["partner_share_pct"])
            weight_pct = (w / weight_sum * 100) if weight_sum else 0
            net_val = float(row["net_profit"])
            opex = float(row["opex_allocated"])
            rows_opex.append(f"| {row['deal_type']} | {m:,.2f} ₽ | {w:,.2f} | {weight_pct:.2f}% | {net_val:,.2f} ₽ | {opex:,.2f} ₽ |")
        net_total = float(by_direction_df["net_profit"].sum())
        table_opex = "\n".join([
            "| Направление | Маржа | Вес (маржа×доля) | Доля в распределении | Чистая прибыль | OPEX на направление |",
            "|-------------|-------|-----------------|----------------------|-----------------|---------------------|",
            *rows_opex,
            f"| **Итого** | **{company_profit:,.2f} ₽** | | 100% | **{net_total:,.2f} ₽** | **{total_opex_both:,.2f} ₽** |",
        ])
        st.markdown(table_opex)

    # —— 3. Чистая прибыль по направлениям ——
    st.markdown("##### 3. Чистая прибыль по направлениям")
    st.markdown("Итог: по каждому направлению **маржа − OPEX на направление** = чистая прибыль (OPEX рассчитан из распределения чистой прибыли по весу).")
    if not by_direction_df.empty:
        rows_net = []
        for _, row in by_direction_df.iterrows():
            m, o, n = float(row["margin"]), float(row["opex_allocated"]), float(row["net_profit"])
            rows_net.append(f"| {row['deal_type']} | {m:,.2f} ₽ | − {o:,.2f} ₽ | **{n:,.2f} ₽** |")
        net_total = float(by_direction_df["net_profit"].sum())
        table_net = "\n".join([
            "| Направление | Маржа | − OPEX на направление | = Чистая прибыль |",
            "|-------------|-------|------------------------|------------------|",
            *rows_net,
            f"| **Итого** | **{company_profit:,.2f} ₽** | − **{total_opex_both:,.2f} ₽** | **{net_total:,.2f} ₽** |",
        ])
        st.markdown(table_net)
        st.caption(f"Проверка: {company_profit:,.2f} − {total_opex_both:,.2f} = {net_total:,.2f} ₽.")

    # —— 4. Доля Артёма по направлениям ——
    st.markdown("##### 4. Доля Артёма по направлениям")
    st.markdown("По каждому типу сделок задана доля партнёра (0%, 30%, 50% и т.д.). Прибыль Артёма по направлению = чистая прибыль × доля.")
    if not by_direction_df.empty:
        rows_artem = []
        for _, row in by_direction_df.iterrows():
            n = float(row["net_profit"])
            pct = float(row["partner_share_pct"]) * 100
            pp = float(row["partner_profit"])
            rows_artem.append(f"| {row['deal_type']} | {n:,.2f} ₽ | {pct:.0f}% | **{pp:,.2f} ₽** |")
        table_artem = "\n".join([
            "| Направление | Чистая прибыль | Доля партнёра | Прибыль Артёма |",
            "|-------------|----------------|---------------|----------------|",
            *rows_artem,
            f"| **Итого прибыль Артёма** | | | **{artem_profit:,.2f} ₽** |",
        ])
        st.markdown(table_artem)

    # —— 5. Итого к выдаче ——
    st.markdown("##### 5. Расчёт к выдаче")
    st.markdown("Чистая прибыль рассчитана с учётом всех OPEX (включая расходы партнёра). Доля Артёма уже отражает это. К выдаче = прибыль Артёма − уже выплачено (возврат его расходов не добавляем — двойной учёт).")
    st.markdown(f"""
    | Шаг | Описание | Сумма |
    |:---:|----------|------:|
    | 1 | Прибыль Артёма по направлениям (все расходы уже учтены в чистой прибыли) | **+{artem_profit:,.2f} ₽** |
    | 2 | Уже выплачено Артёму за период | **−{already_paid:,.2f} ₽** |
    | | **Итого к выдаче** | **{final_payout:,.2f} ₽** |
    """)

    if final_payout > 0:
        cls, text = "final-result-box", f"Итого к выдаче Артёму: {final_payout:,.2f} ₽"
    else:
        cls, text = "final-result-box final-result-negative", f"Артём должен бизнесу: {abs(final_payout):,.2f} ₽"
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)

    st.markdown("#### Детализация")
    with st.expander("Сделки за месяц"):
        st.dataframe(deals_data, use_container_width=True, hide_index=True)
    if not exp_data.empty and "expense_side" in exp_data.columns:
        with st.expander("Наши расходы за месяц"):
            st.dataframe(
                exp_data[exp_data["expense_side"] == "ours"][["date", "category", "amount", "comment"]],
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Расходы партнёра за месяц"):
            st.dataframe(
                exp_data[exp_data["expense_side"] == "partner"][["date", "category", "amount", "comment"]],
                use_container_width=True,
                hide_index=True,
            )
    else:
        with st.expander("Расходы за месяц"):
            st.dataframe(exp_data, use_container_width=True, hide_index=True)
