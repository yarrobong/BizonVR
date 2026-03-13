"""Конфигурация приложения."""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)
ADMIN_INITIAL_PASSWORD = os.getenv("ADMIN_INITIAL_PASSWORD", "admin")
COOKIE_SECRET = os.getenv("COOKIE_SECRET", "bf-session-secret-change-in-prod")
SESSION_EXPIRE_DAYS = int(os.getenv("SESSION_EXPIRE_DAYS", "7"))

DEAL_EXPENSE_CATEGORIES = ["Доставка", "Упаковка", "Транспортировка", "Прочее"]

MONTH_NAMES = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]

# --- OAuth 2.0 / ZenMoney ---
# Эти переменные должны быть заполнены данными, которые вы получите
# после регистрации приложения в Дзен-мани:
# - ZENMONEY_CLIENT_ID      -> consumer_key
# - ZENMONEY_CLIENT_SECRET  -> consumer_secret
# - ZENMONEY_REDIRECT_URI   -> OAuth callback point url
ZENMONEY_AUTH_URL = "https://api.zenmoney.ru/oauth2/authorize/"
ZENMONEY_TOKEN_URL = "https://api.zenmoney.ru/oauth2/token/"

ZENMONEY_CLIENT_ID = os.getenv("ZENMONEY_CLIENT_ID")
ZENMONEY_CLIENT_SECRET = os.getenv("ZENMONEY_CLIENT_SECRET")
ZENMONEY_REDIRECT_URI = os.getenv("ZENMONEY_REDIRECT_URI")

