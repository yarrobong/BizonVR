# Полный отчёт по проекту BizonVR

**Дата:** 4 февраля 2025  
**Версия:** 1.0

---

## 1. Общая информация

| Параметр | Значение |
|----------|----------|
| **Название** | BizonVR |
| **Тип** | Интернет-магазин VR-оборудования и аттракционов |
| **Язык** | Русский |
| **Репозиторий** | https://github.com/yarrobong/BizonVR.git |

### Технологический стек

| Компонент | Технология |
|-----------|------------|
| Backend | Django 6.0.1, Python 3.12 |
| База данных | PostgreSQL 16 |
| Frontend | Tailwind CSS 3.4, HTMX 1.9, Alpine.js 3.x |
| Иконки | Lucide Icons |
| WSGI | Gunicorn |
| Статика | WhiteNoise |
| Инфраструктура | Docker, Nginx |
| Платежи | NowPayments (крипто) |
| SMS | SMS.ru (опционально) |

---

## 2. Структура проекта

```
portal-shop-clone/
├── config/                 # Настройки Django
│   ├── settings.py
│   ├── urls.py
│   ├── views.py            # Главная, serve_media
│   └── wsgi.py
├── accounts/               # Пользователи, вход по SMS
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   ├── services.py
│   ├── urls.py
│   └── admin.py
├── catalog/                # Каталог, корзина, избранное
│   ├── models.py
│   ├── views.py
│   ├── context_processors.py
│   ├── templatetags/
│   ├── urls.py
│   └── admin.py
├── orders/                 # Заказы
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   ├── services.py
│   ├── urls.py
│   └── admin.py
├── payments/               # NowPayments
│   ├── models.py
│   ├── views.py
│   ├── services.py
│   ├── urls.py
│   └── admin.py
├── templates/
├── static/
├── static_src/
├── media/
├── deploy/
├── manage.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── entrypoint.sh
├── package.json
├── tailwind.config.js
├── .env.example
└── Makefile
```

---

## 3. Модели данных

### 3.1 Catalog (catalog/models.py)

| Модель | Поля | Описание |
|--------|------|----------|
| **CatalogSection** | name, slug, order | Раздел каталога в меню |
| **Category** | section (FK), name, slug | Категория товаров |
| **Product** | category (FK), name, slug, description, price, image, is_active | Товар |
| **ProductCharacteristic** | product (FK), name, value | Характеристика товара |
| **City** | name, slug, order | Город с точками выдачи |
| **PickupPoint** | city (FK), name, address, order | Точка выдачи |
| **ProductStock** | product (FK), pickup_point (FK), quantity | Остаток в точке |
| **Favorite** | user (FK), product (FK) | Избранное |

### 3.2 Accounts (accounts/models.py)

| Модель | Поля | Описание |
|--------|------|----------|
| **Profile** | user (OneToOne), phone, balance | Профиль пользователя |
| **BalanceTransaction** | user, kind, amount, order (nullable) | Операция по балансу |
| **PhoneVerificationCode** | phone, code, created_at | Код подтверждения SMS |

Типы операций баланса: `topup`, `order_payment`, `promo_bonus`.

### 3.3 Orders (orders/models.py)

| Модель | Поля | Описание |
|--------|------|----------|
| **PromoCode** | code, discount_amount, partner_bonus, partner_user | Промокод |
| **Order** | user (nullable), status, total, promo_code, delivery_type, city, pickup_point, контакты | Заказ |
| **OrderItem** | order (FK), product (FK), quantity, price | Позиция заказа |

Статусы Order: `new`, `paid`, `shipping`, `done`, `cancelled`.  
Доставка: `courier`, `pickup`, `post`.

### 3.4 Payments (payments/models.py)

| Модель | Поля | Описание |
|--------|------|----------|
| **Payment** | order (FK), external_id, price_amount, pay_amount, pay_address, pay_url, status | Платёж NowPayments |

Статусы: `pending`, `waiting`, `confirming`, `sent`, `finished`, `failed`, `refunded`, `expired`.

---

## 4. Маршрутизация (URL)

### Главные

| URL | View | Описание |
|-----|------|----------|
| `/` | home_view | Главная страница |
| `/admin/` | Django Admin | Админка |

### Accounts

| URL | View | Описание |
|-----|------|----------|
| `/accounts/login/` | login_view | Ввод телефона |
| `/accounts/send-code/` | send_code_view | Отправка SMS (POST) |
| `/accounts/verify/` | verify_code_view | Ввод кода, вход |
| `/accounts/logout/` | logout_view | Выход |
| `/accounts/profile/` | profile_view | Личный кабинет |
| `/accounts/profile/balance/` | balance_history_view | История баланса |

### Catalog

| URL | View | Описание |
|-----|------|----------|
| `/catalog/` | ProductListView | Список товаров |
| `/catalog/product/<slug>/` | ProductDetailView | Страница товара |
| `/catalog/cart/` | cart_page_view | Страница корзины |
| `/catalog/cart/partial/` | cart_partial | HTMX-фрагмент корзины |
| `/catalog/cart/add/<id>/` | add_to_cart_view | Добавить в корзину (POST) |
| `/catalog/cart/update/` | cart_update_view | Обновить корзину (POST) |
| `/catalog/set-city/` | set_city_view | Выбор города (POST) |
| `/catalog/favorites/` | favorite_list_view | Избранное |
| `/catalog/favorite/<id>/` | toggle_favorite_view | Переключить избранное (POST) |

### Orders

| URL | View | Описание |
|-----|------|----------|
| `/orders/` | order_list_view | Мои заказы |
| `/orders/checkout/` | checkout_view | Оформление заказа |
| `/orders/created/<id>/` | order_created_view | Заказ оформлен (гость) |
| `/orders/<pk>/` | order_detail_view | Детали заказа |
| `/orders/guest/` | order_guest_lookup_view | Поиск заказа (гость) |
| `/orders/guest/<id>/` | order_guest_view | Просмотр заказа (гость) |

### Payments

| URL | View | Описание |
|-----|------|----------|
| `/payments/order/<id>/create/` | create_payment_view | Создать платёж NowPayments |
| `/payments/order/<id>/wait/` | payment_wait_view | Ожидание оплаты |
| `/payments/webhook/` | webhook_view | IPN callback NowPayments (POST) |

---

## 5. Бизнес-логика

### 5.1 Корзина

- Хранение: `request.session['cart_items']` — список dict с `product_id`, `name`, `price`, `quantity`, `subtotal`, `image_url`
- При выбранном городе количество ограничивается остатком в городе
- HTMX: добавление/обновление возвращает фрагмент и событие `cart-updated` для счётчика

### 5.2 Вход по SMS

1. Пользователь вводит телефон → POST `/accounts/send-code/`
2. Генерируется 6-значный код, сохраняется в БД, отправляется SMS (SMS.ru или лог в dev)
3. Пользователь вводит код → POST `/accounts/verify/`
4. Проверка кода (TTL 10 мин) → создание User (username=телефон) и Profile → вход

Ограничения: cooldown 60 сек по IP, rate limit на проверку кода (5 попыток / 15 мин).

### 5.3 Оформление заказа

1. Валидация корзины и остатков по городу/точке выдачи
2. Создание Order и OrderItem с актуальными ценами из БД
3. Применение промокода (скидка)
4. Очистка корзины
5. **TEST_ORDER_NO_PAYMENT=True**: Order сразу `paid`, бонус партнёру, списание остатков
6. **Иначе**: редирект на страницу оплаты NowPayments

### 5.4 Платежи NowPayments

1. POST `/payments/order/<id>/create/` → запрос к API NowPayments
2. Создание Payment, редирект на `pay_url`
3. Webhook `/payments/webhook/` при смене статуса
4. При `finished`: Order → `paid`, бонус партнёру, списание остатков

### 5.5 Промокоды и партнёры

- Промокод даёт скидку покупателю и бонус партнёру
- Бонус начисляется при переходе Order в статус `paid` (webhook или тестовый режим)
- Идемпотентность: `partner_bonus_applied`, `stock_decreased`

---

## 6. Конфигурация

### 6.1 Переменные окружения (.env)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| SECRET_KEY | Ключ Django | — |
| DEBUG | Режим отладки | True |
| ALLOWED_HOSTS | Разрешённые хосты | localhost,127.0.0.1 |
| CSRF_TRUSTED_ORIGINS | Доверенные origins | — |
| DB_ENGINE | Движок БД | postgresql |
| DB_NAME | Имя БД | bizon |
| DB_USER | Пользователь БД | postgres |
| DB_PASSWORD | Пароль БД | — |
| DB_HOST | Хост БД | localhost |
| DB_PORT | Порт БД | 5434 (dev) / 5432 (Docker) |
| DATABASE_URL | URL БД (приоритет над DB_*) | — |
| SMS_API_KEY | Ключ SMS.ru | — |
| SMS_PROVIDER | Провайдер SMS | smsru |
| NOWPAYMENTS_API_KEY | API-ключ NowPayments | — |
| NOWPAYMENTS_IPN_SECRET | Секрет IPN | — |
| SITE_URL | URL сайта | http://localhost:8000 |
| TEST_ORDER_NO_PAYMENT | Тест без оплаты | 1 |
| USE_HTTPS | Редирект на HTTPS | 0 |
| SERVE_MEDIA | Раздача медиа при DEBUG=False | — |
| GUNICORN_WORKERS | Число воркеров | 2 |

### 6.2 Настройки Django (config/settings.py)

- **SMS_COOLDOWN_SECONDS**: 60
- **SMS_CODE_TTL_MINUTES**: 10
- **LOGIN_URL**: /accounts/login/
- **LOGIN_REDIRECT_URL**: /accounts/profile/
- **LANGUAGE_CODE**: ru-ru
- **CACHES**: LocMemCache (для django-ratelimit)
- **WhiteNoise** для статики
- **Безопасность** (при DEBUG=False): SSL redirect, HSTS, secure cookies (если USE_HTTPS)

---

## 7. Инфраструктура

### 7.1 Docker

**docker-compose.yml** (dev):
- **db**: PostgreSQL 16, порт 5434
- **web**: Django + Gunicorn, volume с кодом

**docker-compose.prod.yml** (prod):
- **db**: PostgreSQL 16, без внешнего порта
- **web**: образ без монтирования кода, volumes для staticfiles и media, порт 127.0.0.1:8000

### 7.2 Dockerfile

- Base: python:3.12-slim
- Установка Node.js 20 для Tailwind
- `pip install -r requirements.txt`
- `npm run build:css` при сборке
- Entrypoint: миграции → collectstatic → Gunicorn

### 7.3 Entrypoint (entrypoint.sh)

1. `python manage.py migrate --noinput`
2. Сборка Tailwind (если нет файла)
3. `python manage.py collectstatic --noinput`
4. `gunicorn --bind 0.0.0.0:8000 --workers $GUNICORN_WORKERS config.wsgi:application`

### 7.4 Makefile

| Команда | Описание |
|---------|----------|
| make up | Поднять prod-контейнеры |
| make down | Остановить контейнеры |
| make ps | Статус контейнеров |
| make logs | Логи web |
| make build | Пересборка и up |
| make migrate | Миграции |
| make superuser | Создать суперпользователя |
| make collectstatic | Собрать статику |
| make dev-up | Только dev (без prod) |

---

## 8. Деплой

### 8.1 Cloud-init (deploy/cloud-init.yml)

При создании VPS: Docker, Nginx, Certbot, таймзона Europe/Moscow.

### 8.2 Nginx (deploy/nginx.conf.example)

- Редирект HTTP → HTTPS
- SSL (Let's Encrypt)
- Проксирование на 127.0.0.1:8000
- Опционально: раздача /static/ и /media/ через Nginx

### 8.3 Чек-лист деплоя

- [ ] Репозиторий в `/opt/BizonVR`
- [ ] `.env` с SECRET_KEY, ALLOWED_HOSTS, DB_*
- [ ] DEBUG=False, USE_HTTPS=true
- [ ] docker compose up -d
- [ ] Nginx + SSL (certbot)
- [ ] createsuperuser

---

## 9. Зависимости

### Python (requirements.txt)

```
asgiref==3.11.0
dj-database-url==2.1.0
django-ratelimit==4.1.0
Django==6.0.1
gunicorn==23.0.0
whitenoise==6.8.2
pillow==12.1.0
psycopg2-binary==2.9.11
python-decouple==3.8
requests>=2.28.0
sqlparse==0.5.5
```

### Node (package.json)

- tailwindcss ^3.4.1
- Скрипт: `npm run build:css` → Tailwind build

---

## 10. Безопасность

| Мера | Реализация |
|------|------------|
| CSRF | django.middleware.csrf.CsrfViewMiddleware |
| Rate limit | django-ratelimit: SMS 60/мин, checkout 15/мин, add_to_cart 60/мин |
| IPN подпись | HMAC-SHA512 в payments.services.verify_ipn_signature |
| Редирект | _safe_redirect_url — только внутренние пути |
| HTTPS | SECURE_SSL_REDIRECT, HSTS при USE_HTTPS |
| Cookies | SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE в prod |

---

## 11. Шаблоны

| Шаблон | Описание |
|--------|----------|
| base.html | Базовый: шапка, меню каталога, модалка корзины, футер |
| home.html | Главная: hero-слайдер, товары, категории |
| accounts/login.html | Ввод телефона |
| accounts/verify_code.html | Ввод кода |
| accounts/profile.html | Личный кабинет |
| accounts/balance_history.html | История баланса |
| catalog/product_list.html | Список товаров |
| catalog/product_detail.html | Страница товара |
| catalog/cart.html | Корзина |
| catalog/favorite_list.html | Избранное |
| catalog/partials/cart_content.html | HTMX-фрагмент корзины |
| orders/checkout.html | Оформление заказа |
| orders/order_created.html | Заказ оформлен (гость) |
| orders/order_detail.html | Детали заказа |
| orders/order_list.html | Список заказов |
| orders/order_guest_lookup.html | Поиск заказа (гость) |
| orders/order_guest_verify.html | Верификация телефона (гость) |
| payments/create_payment.html | Создание платежа |
| payments/payment_wait.html | Ожидание оплаты |

---

## 12. Связанные документы

- **tech.md** — техническое задание
- **DEVELOPMENT_PLAN.md** — план разработки по фазам
- **DEPLOY.md** — инструкция по деплою
- **OZON_INTEGRATION.md** — интеграция с Ozon (если есть)
- **upgrade.md** — доработки

---

*Отчёт сформирован автоматически на основе анализа кодовой базы.*
