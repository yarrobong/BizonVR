# BizonVR Agent Guide

## Назначение проекта
- BizonVR — Django-магазин VR-оборудования и VR-аттракционов.
- Основной стек: Django 6, PostgreSQL, Tailwind CSS, серверные Django templates, немного JS, WhiteNoise.
- Основные бизнес-потоки: каталог -> корзина -> заказ -> оплата по СБП, банковской карте или через менеджера для юрлиц.
- Вторичные потоки: вход по SMS-коду, избранное, шаринг корзины, заявки с лендингов и страницы контактов.

## Быстрый старт для агента
- Сначала прочитай [README.md](/Users/Yaroslav/Documents/dev/BizonVR/README.md), [config/settings.py](/Users/Yaroslav/Documents/dev/BizonVR/config/settings.py) и [config/urls.py](/Users/Yaroslav/Documents/dev/BizonVR/config/urls.py).
- Для доменной модели смотри [catalog/models.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/models.py), [orders/models.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/models.py), [payments/models.py](/Users/Yaroslav/Documents/dev/BizonVR/payments/models.py), [accounts/models.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/models.py).
- Для пользовательского сценария "что происходит при запросе" начинай с `urls.py`, затем переходи в `views/`, потом в `forms.py`, `services.py`, `models.py`, шаблоны.
- Для проверки ожидаемого поведения читай тесты: [catalog/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/tests.py), [orders/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/tests.py), [accounts/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/tests.py).

## Структура репозитория
- [config/](/Users/Yaroslav/Documents/dev/BizonVR/config) — настройки проекта, корневые URL, статические и legal views.
- [catalog/](/Users/Yaroslav/Documents/dev/BizonVR/catalog) — основной каталог, остатки, корзина, избранное, рекомендации.
- [orders/](/Users/Yaroslav/Documents/dev/BizonVR/orders) — checkout, заказы, промокоды, legacy purchase requests.
- [payments/](/Users/Yaroslav/Documents/dev/BizonVR/payments) — инструкции по оплате заказа, платёжные данные и webhook-процессинг.
- [accounts/](/Users/Yaroslav/Documents/dev/BizonVR/accounts) — вход по SMS, профиль, баланс, сохранённые адреса.
- [manager_portal/](/Users/Yaroslav/Documents/dev/BizonVR/manager_portal) — внутренний портал, финансы, логистика, договоры и import-команды для legacy-источников.
- [legacy/](/Users/Yaroslav/Documents/dev/BizonVR/legacy) — архивные источники данных; не активный runtime и не source of truth.
- [templates/](/Users/Yaroslav/Documents/dev/BizonVR/templates) — все серверные шаблоны.
- [static/](/Users/Yaroslav/Documents/dev/BizonVR/static) — исходные статические файлы, которые редактируют вручную.
- [staticfiles/](/Users/Yaroslav/Documents/dev/BizonVR/staticfiles) — результат `collectstatic`, generated output; руками не редактировать, если задача не про артефакт сборки.
- [media/](/Users/Yaroslav/Documents/dev/BizonVR/media) — пользовательские и маркетинговые медиа; `media/products` не считать исходным кодом.
- [docs/](/Users/Yaroslav/Documents/dev/BizonVR/docs) — локальные поясняющие документы по данным и инфраструктуре.
- [deploy/](/Users/Yaroslav/Documents/dev/BizonVR/deploy) — Nginx и cloud-init для сервера.

## Приложения и source of truth

### catalog
- Главные сущности: `CatalogSection`, `Category`, `Product`, `ProductVariant`, `ProductImage`, `ProductCharacteristic`, `ProductBundle`, `City`, `PickupPoint`, `ProductStock`, `CartItem`, `CartShare`, `Favorite`, `Service`, `ContactRequest`, `CallbackRequest`.
- Корзина и избранное работают по двум режимам:
- Анонимный пользователь: состояние хранится в сессии.
- Авторизованный пользователь: состояние хранится в БД.
- Ключевой файл для этого поведения: [catalog/cart_services.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/cart_services.py).
- Остатки товара живут только в `ProductStock`. Товар не привязан к городу напрямую; наличие по городу считается как сумма по `PickupPoint` этого города.
- Публичный статус наличия вычисляется в [catalog/stock.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/stock.py).

### orders
- Главные сущности: `Order`, `OrderItem`, `PromoCode`, `PurchaseRequest`.
- Checkout для авторизованного пользователя собирает строки заказа из корзины, валидирует остатки и создаёт `Order` + `OrderItem`.
- Если включён `TEST_ORDER_NO_PAYMENT`, заказ сразу создаётся со статусом `paid`.
- Side effects оплаты живут в [orders/services.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/services.py):
- `apply_partner_bonus_for_order(order)` начисляет партнёрский бонус.
- `decrease_stock_for_order(order)` списывает остатки.

### payments
- Главная сущность: `Payment`.
- Публичные способы оплаты: СБП, банковская карта, для юридических лиц — через менеджера.
- Создание платежа: [payments/views/checkout.py](/Users/Yaroslav/Documents/dev/BizonVR/payments/views/checkout.py) + [payments/services.py](/Users/Yaroslav/Documents/dev/BizonVR/payments/services.py).
- Вебхук: [payments/views/webhook.py](/Users/Yaroslav/Documents/dev/BizonVR/payments/views/webhook.py).
- При `payment_status=finished` вебхук переводит заказ в `paid`, после чего запускает бонусы и списание остатков.

### accounts
- Вход без пароля, по SMS-коду.
- Пользователь Django создаётся с `username=<нормализованный телефон>`.
- Профиль пользователя и его контактные данные хранятся в `Profile`.
- Сохранённые адреса checkout хранятся в `SavedAddress`.
- Генерация и проверка SMS-кода: [accounts/services.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/services.py).
- В dev-режиме без `SMS_API_KEY` код не отправляется провайдером, а логируется в консоль.

## URL-карта
- `/` -> [config/views/home.py](/Users/Yaroslav/Documents/dev/BizonVR/config/views/home.py)
- `/catalog/` -> [catalog/views/products.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/products.py)
- `/catalog/cart/*` -> [catalog/views/cart.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/cart.py), [catalog/views/cart_mutations.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/cart_mutations.py), [catalog/views/cart_share.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/cart_share.py)
- `/catalog/favorites/` -> [catalog/views/favorites.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/favorites.py)
- `/orders/checkout/` -> [orders/views/checkout.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/views/checkout.py)
- `/payments/order/<id>/create/` -> [payments/views/checkout.py](/Users/Yaroslav/Documents/dev/BizonVR/payments/views/checkout.py)
- `/accounts/*` -> [accounts/views/auth.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/views/auth.py), [accounts/views/profile.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/views/profile.py), [accounts/views/registration.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/views/registration.py)

## Шаблоны и фронтенд
- Это преимущественно серверный рендеринг, не SPA и не DRF.
- Главный layout: [templates/base.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/base.html).
- Общие partials шапки и футера: [templates/layout/](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout).
- Каталог и карточки товара: [templates/catalog/](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog).
- Исходный CSS редактируется в [static/](/Users/Yaroslav/Documents/dev/BizonVR/static), Tailwind собирается из [static_src/input.css](/Users/Yaroslav/Documents/dev/BizonVR/static_src/input.css).
- Админские кастомизации лежат в [static/admin/](/Users/Yaroslav/Documents/dev/BizonVR/static/admin), а не в `staticfiles/admin`.

## Критичные соглашения
- Не редактируй `staticfiles/`, если задача не требует именно пересобранных артефактов. Обычно правят `static/` и затем запускают `collectstatic`.
- Не считай `tech.md` источником правды по текущей архитектуре: это старое ТЗ, часть структуры там уже не совпадает с репозиторием.
- Активный runtime только один: Django BizonVR. Активная БД только одна: PostgreSQL из `DATABASES["default"]`.
- Источник истины по данным каталога — PostgreSQL, а не локальные JSON/fixture-файлы.
- `legacy/` не является source of truth. Данные оттуда можно только импортировать через `manager_portal` management commands, не подключая отдельные Django DB aliases.
- Корневой `db.sqlite3` и любые новые persistent SQLite-файлы вне `legacy/` запрещены. Для проверки есть `make check-single-db`.
- Города, точки выдачи и остатки подробно описаны в [docs/CITIES_AND_PRODUCTS.md](/Users/Yaroslav/Documents/dev/BizonVR/docs/CITIES_AND_PRODUCTS.md).
- Во многих формах и сущностях обязательны поля legal consent. См. [config/legal_consent.py](/Users/Yaroslav/Documents/dev/BizonVR/config/legal_consent.py).
- В проекте может быть грязное рабочее дерево. Не откатывай чужие изменения без явного запроса.

## Команды разработки
- Локально:
```bash
make install-local
make migrate-local
make run-local
```
- Полезные команды:
```bash
make migrate
make load-data-clear
make superuser-local
make shell
make collectstatic
make check-single-db
npm run build:css
```

## Деплой и окружение
- Локальный запуск обычно использует PostgreSQL на `localhost:5432`.
- Продакшен рассчитан на `venv` + Gunicorn + systemd + Nginx.
- `legacy/` в продакшене не запускается как отдельный сервис и не добавляет новые БД в runtime.
- Переменные окружения смотри в [.env.example](/Users/Yaroslav/Documents/dev/BizonVR/.env.example).
- Документ по деплою: [DEPLOY.md](/Users/Yaroslav/Documents/dev/BizonVR/DEPLOY.md).

## Где искать по типовым задачам
- Пропала логика каталога или фильтров: [catalog/views/products.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/products.py), [templates/catalog/product_list.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/product_list.html), [templates/catalog/_filters_main.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/_filters_main.html).
- Неправильно считается корзина: [catalog/cart_services.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/cart_services.py), [catalog/views/cart.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/cart.py), [catalog/views/cart_mutations.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/cart_mutations.py).
- Проблема с остатками: [catalog/models.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/models.py), [catalog/views/common.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/common.py), [orders/services.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/services.py).
- Проблема с checkout: [orders/forms.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/forms.py), [orders/views/checkout.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/views/checkout.py).
- Платёж не меняет заказ: [payments/views/webhook.py](/Users/Yaroslav/Documents/dev/BizonVR/payments/views/webhook.py), [payments/services.py](/Users/Yaroslav/Documents/dev/BizonVR/payments/services.py), [orders/services.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/services.py).
- Проблемы с входом: [accounts/forms.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/forms.py), [accounts/views/auth.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/views/auth.py), [accounts/services.py](/Users/Yaroslav/Documents/dev/BizonVR/accounts/services.py).
- Непонятно, откуда данные в шапке: [catalog/context_processors.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/context_processors.py).

## Тесты
- Самое широкое покрытие сейчас в [catalog/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/tests.py).
- Перед серьёзными правками запускай хотя бы:
```bash
make test
# или напрямую:
DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python manage.py test config catalog orders accounts payments manager_portal --keepdb --noinput
```
- Для быстрой проверки менеджерского контура используй:
```bash
make test-manager-smoke
```
- Если тесты не проходят, сначала проверь `.env`, подключение к PostgreSQL и наличие миграций.
