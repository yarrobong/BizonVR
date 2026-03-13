"""Точка входа: навигация, авторизация, маршрутизация по страницам."""
import streamlit as st
from streamlit_cookies_manager import EncryptedCookieManager

from auth import (
    SESSION_COOKIE,
    create_session,
    destroy_session,
    get_user_by_token,
    verify_user,
)
from config import COOKIE_SECRET
from db import init_db
from styles import STYLES
from zenmoney import (
    exchange_code_for_token,
    generate_state,
    get_authorization_url,
    is_zenmoney_configured,
    save_tokens_for_user,
)
from views import (
    render_archive,
    render_dashboard,
    render_deal_detail,
    render_deal_form,
    render_deals_list,
    render_expenses,
    render_payouts,
    render_report,
    render_settings,
)

st.set_page_config(page_title="Учет Бизнеса", layout="wide", initial_sidebar_state="expanded")
st.markdown(STYLES, unsafe_allow_html=True)

cookies = EncryptedCookieManager(prefix="bf/", password=COOKIE_SECRET)
if not cookies.ready():
    st.info("Загрузка…")
    st.stop()

init_db()

if "user" not in st.session_state:
    st.session_state.user = None

# --- Обработка возврата из OAuth 2.0 Дзен-мани (authorization_code -> access_token) ---
# Делаем это рано, чтобы обработать коллбэк до остальной логики страницы.
query_params = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()
code = query_params.get("code")
state = query_params.get("state")
if isinstance(code, list):
    code = code[0]
if isinstance(state, list):
    state = state[0]

if code and is_zenmoney_configured():
    # Проверяем, кто у нас сейчас залогинен
    # (флоу запускается только из настроек авторизованным пользователем).
    current_user = st.session_state.get("user")
    if current_user is None:
        st.error("Получен код авторизации Дзен-мани, но пользователь не авторизован в приложении.")
    else:
        # Проверяем state, если мы его сохраняли при старте флоу
        expected_state = st.session_state.get("zenmoney_state")
        if expected_state and state and state != expected_state:
            st.error("Некорректный параметр state в ответе OAuth 2.0 Дзен-мани.")
        else:
            try:
                token_response = exchange_code_for_token(code)
                save_tokens_for_user(int(current_user["id"]), token_response)
                # Очищаем служебные значения
                st.session_state.pop("zenmoney_state", None)
                st.session_state.pop("zenmoney_start_auth", None)
                st.success("Интеграция с Дзен-мани успешно настроена (OAuth 2.0).")
            except Exception as e:  # noqa: BLE001
                st.error(f"Ошибка обмена кода авторизации Дзен-мани на токен: {e}")

if st.session_state.user is None:
    token = None
    try:
        token = cookies[SESSION_COOKIE]
    except (KeyError, TypeError):
        pass
    user = get_user_by_token(token) if token else None
    if user:
        st.session_state.user = user
        st.rerun()

if st.session_state.user is None:
    st.markdown("### Вход")
    with st.form("login_form"):
        login_user = st.text_input("Логин", autocomplete="username")
        login_pass = st.text_input("Пароль", type="password", autocomplete="current-password")
        if st.form_submit_button("Войти"):
            u = verify_user(login_user or "", login_pass or "")
            if u:
                t = create_session(u)
                cookies[SESSION_COOKIE] = t
                cookies.save()
                st.session_state.user = u
                st.rerun()
            else:
                st.error("Неверный логин или пароль.")
    st.stop()

# Если сработал флаг из настроек — запускаем OAuth 2.0 флоу с Дзен-мани
if st.session_state.user is not None and st.session_state.get("zenmoney_start_auth") and is_zenmoney_configured():
    user = st.session_state.user
    # Генерируем state и сохраняем его для проверки при коллбэке
    state_val = generate_state()
    st.session_state["zenmoney_state"] = state_val
    auth_url = get_authorization_url(state_val)
    # Мягкий редирект через JS — рабочий способ для Streamlit
    st.markdown(
        f"""
        <script>
        window.location.href = "{auth_url}";
        </script>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

user = st.session_state.user
is_admin = user["role"] == "admin"

with st.sidebar:
    st.markdown("### Учет Бизнеса")
    st.caption(f"**{user['username']}** · " + ("Админ" if is_admin else "Оператор"))
    st.divider()
    nav_items = ["Дашборд", "Сделки", "Расходы", "Выплаты", "Отчёт", "Архив"]
    if is_admin:
        nav_items.append("Настройки")
    if "nav_menu" not in st.session_state:
        st.session_state.nav_menu = "Дашборд"
    menu = st.session_state.nav_menu
    for item in nav_items:
        is_active = item == menu
        if st.button(
            item,
            key=f"nav_{item}",
            use_container_width=True,
            disabled=is_active,
        ) and not is_active:
            st.session_state.nav_menu = item
            st.rerun()
    if menu != "Сделки":
        if "deals_selected_id" in st.session_state:
            del st.session_state["deals_selected_id"]
        if "deals_adding" in st.session_state:
            del st.session_state["deals_adding"]
        if "deal_edit_field" in st.session_state:
            del st.session_state["deal_edit_field"]
        if "deal_delete_confirm" in st.session_state:
            del st.session_state["deal_delete_confirm"]
    st.divider()
    if st.button("Выйти", use_container_width=True):
        try:
            t = cookies[SESSION_COOKIE]
        except (KeyError, TypeError):
            t = None
        destroy_session(t)
        try:
            del cookies[SESSION_COOKIE]
        except (KeyError, TypeError):
            pass
        cookies.save()
        st.session_state.user = None
        st.rerun()

st.markdown("""
<div class="main-header">
<h1 style="margin:0;">Управленческий учет</h1>
<p style="color:#64748b; margin:0.25rem 0 0 0; font-size:0.95rem;">Сделки, расходы и расчёты с партнёром</p>
</div>
""", unsafe_allow_html=True)

if menu == "Сделки":
    deal_id = st.session_state.get("deals_selected_id")
    adding = st.session_state.get("deals_adding", False)
    if adding:
        col1, _ = st.columns([1, 5])
        with col1:
            if st.button("К списку сделок", key="back_from_add"):
                del st.session_state["deals_adding"]
                st.rerun()
        render_deal_form()
    elif deal_id is not None:
        render_deal_detail(deal_id)
    else:
        col1, _ = st.columns([1, 5])
        with col1:
            if st.button("Добавить сделку", key="add_deal_btn"):
                st.session_state["deals_adding"] = True
                st.rerun()
        render_deals_list()
elif menu == "Расходы":
    render_expenses()
elif menu == "Выплаты":
    render_payouts()
elif menu == "Дашборд":
    render_dashboard()
elif menu == "Настройки":
    render_settings(is_admin)
elif menu == "Отчёт":
    render_report()
elif menu == "Архив":
    render_archive()
