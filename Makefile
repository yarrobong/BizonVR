# BizonVR — управление Docker
# Локальная разработка: make dev
# Продакшен (сервер): make up

COMPOSE_BASE = docker compose -f docker-compose.yml
COMPOSE_PROD = docker compose -f docker-compose.yml -f docker-compose.prod.yml

.PHONY: dev up down ps logs logs-f restart build migrate load-data load-data-clear shell superuser collectstatic
.PHONY: install-local run-local migrate-local load-data-local load-data-clear-local superuser-local

# ========== Локально без Docker (нужен установленный PostgreSQL) ==========
# Однократно: создайте БД (createdb bizon), скопируйте .env.example в .env, укажите DB_HOST=localhost DB_PORT=5432
# make install-local   # venv + зависимости + tailwind
# make migrate-local  # миграции
# make run-local      # сервер на http://127.0.0.1:8000
PY = .venv/bin/python
PIP = .venv/bin/pip

install-local:
	python3 -m venv .venv
	$(PIP) install -r requirements.txt
	npm install

migrate-local:
	$(PY) manage.py migrate

run-local:
	@[ -f static/css/tailwind.css ] || (npm run build:css || true)
	$(PY) manage.py runserver

load-data-local:
	$(PY) manage.py load_catalog_data

load-data-clear-local:
	$(PY) manage.py load_catalog_data --clear

superuser-local:
	$(PY) manage.py createsuperuser

# ========== Локальная разработка в Docker (код монтируется, порт 8000) ==========
# make или make dev — запуск для разработки
dev:
	$(COMPOSE_BASE) up -d

# Алиас: make = make dev
.DEFAULT_GOAL := dev

dev-down:
	$(COMPOSE_BASE) down

dev-ps:
	$(COMPOSE_BASE) ps

# ========== Продакшен (образ, порт из .env PORT, по умолчанию 8001) ==========
up:
	$(COMPOSE_PROD) up -d

down:
	$(COMPOSE_PROD) down

ps:
	$(COMPOSE_PROD) ps

logs:
	$(COMPOSE_PROD) logs web --tail 100

logs-f:
	$(COMPOSE_PROD) logs -f web

restart:
	$(COMPOSE_PROD) restart web

build:
	$(COMPOSE_PROD) build --no-cache
	$(COMPOSE_PROD) up -d

pull:
	git pull
	$(COMPOSE_PROD) build --no-cache
	$(COMPOSE_PROD) up -d

# ========== Django (работает с dev или prod — тот же проект) ==========
migrate:
	$(COMPOSE_BASE) exec web python manage.py migrate

# Миграции и данные в контейнере prod (когда запущен make up / make restart)
migrate-prod:
	$(COMPOSE_PROD) exec web python manage.py migrate
load-data-prod:
	$(COMPOSE_PROD) exec web python manage.py load_catalog_data
shell-prod:
	$(COMPOSE_PROD) exec web python manage.py shell

# Сбросить кэш каталога (города/разделы), чтобы на сайте отобразились города из БД
clear-cache-prod:
	$(COMPOSE_PROD) exec web python manage.py clear_catalog_cache

load-data:
	$(COMPOSE_BASE) exec web python manage.py load_catalog_data

load-data-clear:
	$(COMPOSE_BASE) exec web python manage.py load_catalog_data --clear

shell:
	$(COMPOSE_BASE) exec web python manage.py shell

superuser:
	$(COMPOSE_BASE) exec web python manage.py createsuperuser

collectstatic:
	$(COMPOSE_BASE) exec web python manage.py collectstatic --noinput

recreate-web:
	$(COMPOSE_PROD) up -d --force-recreate web
