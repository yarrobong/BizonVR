# Как выложить приложение в интернет (дёшево, со своим доменом)

Домен у вас уже есть. Ниже варианты от почти бесплатного до ~$5–7/мес.

---

## Вариант 1: Render + Neon (почти бесплатно)

- **Render** — хостинг приложения (free tier: засыпает через 15 мин без заходов, первый заход ~30–60 сек).
- **Neon** — бесплатный PostgreSQL в облаке.
- **Свой домен** — привязывается в настройках сервиса на Render.

### Шаг 1: База данных (Neon)

1. Зайдите на [neon.tech](https://neon.tech) → Sign up (можно через GitHub).
2. Создайте проект → скопируйте **Connection string** (типа `postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`).
3. Сохраните строку — это будет `DATABASE_URL` на Render.

### Шаг 2: Код на GitHub

1. Создайте репозиторий, залейте проект (без `.env` и без папки `venv` — они в `.gitignore`).
2. В корне должны быть: `app.py`, `requirements.txt`, `Dockerfile` (уже добавлен).

### Шаг 3: Деплой на Render

1. [render.com](https://render.com) → Sign up → Dashboard.
2. **New → Web Service**.
3. Подключите репозиторий с BusinessFinance, выберите ветку (например `main`).
4. Настройки:
   - **Environment**: Docker (Render сам соберёт по `Dockerfile`).
   - **Instance type**: Free (или за $7/мес — без засыпания).
5. **Environment Variables** (обязательно):
   - `DATABASE_URL` = строка из Neon (из шага 1).
   - `COOKIE_SECRET` = придумайте длинную случайную строку (для сессий).
   - `ADMIN_INITIAL_PASSWORD` = пароль админа (или оставьте по умолчанию и смените в приложении).
6. **Create Web Service** → дождитесь сборки и запуска.
7. **Свой домен**: в карточке сервиса → **Settings → Custom Domains** → Add custom domain → введите ваш домен. Render покажет, какую CNAME-запись добавить у регистратора домена.

Итог: приложение доступно по вашему домену. На free tier — с засыпанием после 15 мин простоя.

---

## Вариант 2: Railway (~$5/мес)

- Всё в одном: приложение + PostgreSQL на Railway.
- Свой домен настраивается в пару кликов.

1. [railway.app](https://railway.app) → Login with GitHub.
2. **New Project** → **Deploy from GitHub repo** → выберите репозиторий BusinessFinance.
3. Добавьте сервис **PostgreSQL** (в том же проекте).
4. У сервиса с приложением: **Variables** → добавьте `DATABASE_URL` (Railway подставит ссылку на свою БД, если выбрать переменную из Postgres).
5. Добавьте `COOKIE_SECRET`, при необходимости `ADMIN_INITIAL_PASSWORD`.
6. **Settings** сервиса приложения: **Networking** → **Generate domain** (получите `xxx.up.railway.app`), затем **Custom domain** → введите ваш домен и настройте CNAME у регистратора.

Railway списывает по факту использования; для небольшого Streamlit + Postgres обычно выходит порядка $5/мес.

---

## Вариант 3: VPS (Hetzner ~€3.5/мес)

Полный контроль, приложение не засыпает.

1. Арендуйте VPS (например [Hetzner CX11](https://www.hetzner.com/cloud) или аналог).
2. На сервере: установите Docker и Docker Compose, склонируйте репозиторий.
3. Поднимите БД и приложение через Docker (можно расширить ваш `docker-compose.yml` вторым сервисом для Streamlit по `Dockerfile`).
4. Nginx + Let's Encrypt (certbot) для HTTPS и привязки вашего домена.

Подробные шаги для VPS можно вынести в отдельную инструкцию (напишите, если нужно).

---

## Что проверить перед деплоем

- В `.env` не должно быть секретов в репозитории — все секреты задаются в переменных окружения на Render/Railway.
- В `config.py` уже используется `os.getenv("DATABASE_URL", ...)` — подходит для облака.
- Для продакшена задайте `COOKIE_SECRET` и смените пароль админа после первого входа.

Если напишете, какой вариант выбираете (Render, Railway или VPS), могу расписать шаги под него пошагово под ваш домен.
