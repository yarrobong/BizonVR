"""Настройки (админ): типы сделок, категории, пользователи, интеграции."""
import pandas as pd
import streamlit as st
from psycopg2 import IntegrityError

from auth import hash_password
from db import get_conn, run_query
from logic import (
    get_deal_types,
    get_our_categories,
    get_partner_categories,
    sync_deal_types_from_df,
)
from zenmoney import delete_tokens_for_user, get_tokens_for_user, is_zenmoney_configured


def render_settings(is_admin: bool):
    if not is_admin:
        st.error("Доступ только для администратора.")
        return
    st.header("Настройки")
    st.caption("Изменения применяются только к новым сделкам и новым расходам; старые данные не меняются.")

    with st.expander("Типы сделок и доля партнёра", expanded=True):
        deal_types = get_deal_types()
        df = pd.DataFrame([
            {"id": t["id"], "name": t["name"], "partner_share_pct": round(t["partner_share"] * 100, 1)}
            for t in deal_types
        ])
        if df.empty:
            df = pd.DataFrame(columns=["id", "name", "partner_share_pct"])
            df["id"] = df["id"].astype("Int64")
            df["partner_share_pct"] = df["partner_share_pct"].astype("float64")
        original = df.copy()
        st.caption("Редактируйте названия и доли в таблице, добавляйте и удаляйте строки. Затем нажмите «Сохранить».")
        edited = st.data_editor(
            df,
            key="deal_types_editor",
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_order=["name", "partner_share_pct"],
            column_config={
                "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
                "name": st.column_config.TextColumn("Тип сделки", width="medium"),
                "partner_share_pct": st.column_config.NumberColumn(
                    "Доля партнёра (%)",
                    min_value=0.0,
                    max_value=100.0,
                    step=0.5,
                    format="%.1f",
                    width="small",
                ),
            },
        )
        if st.button("Сохранить типы сделок", key="save_deal_types"):
            if edited is None or edited.empty:
                if not original.empty:
                    st.warning("Не удаляйте все типы.")
                else:
                    st.info("Добавьте хотя бы одну строку.")
            else:
                ok, err = sync_deal_types_from_df(edited, original)
                if ok:
                    st.success("Сохранено.")
                    st.rerun()
                else:
                    st.error(err or "Ошибка сохранения.")

    with st.expander("Наши категории расходов"):
        our_cats = get_our_categories()
        st.write(", ".join(our_cats) if our_cats else "—")
        with st.form("add_our_cat"):
            a = st.text_input("Новая категория")
            if st.form_submit_button("Добавить"):
                if (a or "").strip():
                    try:
                        run_query("INSERT INTO our_expense_categories (name) VALUES (%s)", (a.strip(),))
                        st.success("Добавлено.")
                        st.rerun()
                    except IntegrityError:
                        st.error("Такая категория уже есть.")
                else:
                    st.error("Введите название.")
        if our_cats:
            with st.form("del_our_cat"):
                d = st.selectbox("Удалить", our_cats, key="del_our")
                if st.form_submit_button("Удалить"):
                    run_query("DELETE FROM our_expense_categories WHERE name = %s", (d,))
                    st.rerun()

    with st.expander("Категории расходов партнёра"):
        partner_cats = get_partner_categories()
        st.write(", ".join(partner_cats) if partner_cats else "—")
        with st.form("add_partner_cat"):
            a = st.text_input("Новая категория", key="ap")
            if st.form_submit_button("Добавить"):
                if (a or "").strip():
                    try:
                        run_query("INSERT INTO partner_expense_categories (name) VALUES (%s)", (a.strip(),))
                        st.success("Добавлено.")
                        st.rerun()
                    except IntegrityError:
                        st.error("Такая категория уже есть.")
                else:
                    st.error("Введите название.")
        if partner_cats:
            with st.form("del_partner_cat"):
                d = st.selectbox("Удалить", partner_cats, key="del_partner")
                if st.form_submit_button("Удалить"):
                    run_query("DELETE FROM partner_expense_categories WHERE name = %s", (d,))
                    st.rerun()

    with st.expander("Пользователи"):
        conn = get_conn()
        users_df = pd.read_sql("SELECT id, username, role FROM users ORDER BY id", conn)
        conn.close()
        st.dataframe(users_df.rename(columns={"id": "ID", "username": "Логин", "role": "Роль"}), use_container_width=True, hide_index=True)
        with st.form("add_user"):
            st.subheader("Добавить пользователя")
            un = st.text_input("Логин", autocomplete="username")
            pw = st.text_input("Пароль", type="password", autocomplete="new-password")
            role = st.selectbox("Роль", ["operator", "admin"])
            if st.form_submit_button("Добавить"):
                if (un or "").strip() and pw:
                    try:
                        run_query("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)", (un.strip(), hash_password(pw), role))
                        st.success("Пользователь добавлен.")
                        st.rerun()
                    except IntegrityError:
                        st.error("Пользователь с таким логином уже есть.")
                else:
                    st.error("Укажите логин и пароль.")
        usernames = list(users_df["username"])
        if usernames:
            with st.form("chg_pw"):
                st.subheader("Сменить пароль")
                u = st.selectbox("Пользователь", usernames, key="chg_user")
                new_pw = st.text_input("Новый пароль", type="password", key="new_pw", autocomplete="new-password")
                if st.form_submit_button("Сменить"):
                    if new_pw:
                        run_query("UPDATE users SET password_hash = %s WHERE username = %s", (hash_password(new_pw), u))
                        st.success("Пароль изменён.")
                        st.rerun()
                    else:
                        st.error("Введите новый пароль.")

    with st.expander("Интеграция с Дзен-мани (OAuth 2.0)"):
        st.caption(
            "Подключение к Дзен-мани выполняется по стандартному протоколу **OAuth 2.0 Authorization Code**. "
            "После регистрации приложения в Дзен-мани укажите в переменных окружения "
            "`ZENMONEY_CLIENT_ID`, `ZENMONEY_CLIENT_SECRET` и `ZENMONEY_REDIRECT_URI`."
        )

        if not is_zenmoney_configured():
            st.warning(
                "ZenMoney OAuth2 ещё не сконфигурирован. "
                "Заполните `ZENMONEY_CLIENT_ID`, `ZENMONEY_CLIENT_SECRET` и `ZENMONEY_REDIRECT_URI` "
                "в `.env` перед регистрацией приложения в Дзен-мани."
            )
            return

        current_user = getattr(st.session_state, "user", None)
        if not current_user:
            st.info("Авторизуйтесь в приложении, чтобы настроить интеграцию Дзен-мани.")
            return

        user_id = int(current_user["id"])
        tokens = get_tokens_for_user(user_id)

        if tokens:
            st.success("Дзен-мани уже подключён для этого пользователя.")
            with st.expander("Технические детали", expanded=False):
                st.write(
                    f"- Тип токена: `{tokens.get('token_type')}`\n"
                    f"- Истекает: `{tokens.get('expires_at')}`\n"
                )
            if st.button("Отключить интеграцию Дзен-мани"):
                delete_tokens_for_user(user_id)
                st.success("Интеграция отключена, токены удалены.")
                st.rerun()
        else:
            st.info(
                "Дзен-мани ещё не подключён. Для подключения запустите OAuth 2.0 авторизацию."
            )
            if st.button("Подключить Дзен-мани"):
                # Флаг, который будет обработан в app.py для старта OAuth-флоу
                st.session_state["zenmoney_start_auth"] = True
                st.rerun()
