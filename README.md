# BizonVR

## Запуск без Docker

Нужен установленный **PostgreSQL** (например `brew install postgresql@16` и `brew services start postgresql@16`).

1. Создайте базу и настройте окружение:
   ```bash
   createdb bizon
   cp .env.example .env
   # В .env укажите DB_HOST=localhost, DB_PORT=5432 (или 5434, если постгрес на другом порту)
   ```

2. Установка и запуск:
   ```bash
   make install-local   # venv, зависимости, tailwind (один раз)
   make migrate-local   # миграции
   make run-local       # сервер на http://127.0.0.1:8000
   ```

3. По желанию: тестовые данные и админ:
   ```bash
   make load-data-clear-local   # каталог (города, товары)
   make superuser-local         # создать суперпользователя для /admin/
   ```

## Docker (локально)

```bash
make dev      # или просто make — запуск на http://localhost:8000
make up       # продакшен-режим (порт из .env PORT, по умолчанию 8001)
make migrate  # миграции
make load-data-clear   # тестовые данные (с очисткой)
make superuser         # создать админа
make logs              # логи
```

Подробнее: [DEPLOY.md](DEPLOY.md)
