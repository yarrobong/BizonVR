# BizonVR — управление Docker (prod: docker-compose + docker-compose.prod)
# Использование: make up, make ps, make logs и т.д. (из корня проекта)

COMPOSE_FILES = -f docker-compose.yml -f docker-compose.prod.yml
COMPOSE = docker compose $(COMPOSE_FILES)

.PHONY: up down ps logs restart build pull migrate shell superuser collectstatic

# Поднять контейнеры (prod)
up:
	$(COMPOSE) up -d

# Остановить и удалить контейнеры
down:
	$(COMPOSE) down

# Статус контейнеров
ps:
	$(COMPOSE) ps

# Логи web (последние 100 строк)
logs:
	$(COMPOSE) logs web --tail 100

# Логи web в реальном времени
logs-f:
	$(COMPOSE) logs -f web

# Перезапустить web
restart:
	$(COMPOSE) restart web

# Собрать образ и поднять (после изменений кода)
build:
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

# Обновление: git pull + пересборка + up
pull:
	git pull
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

# Миграции Django
migrate:
	$(COMPOSE) exec web python manage.py migrate

# Django shell
shell:
	$(COMPOSE) exec web python manage.py shell

# Создать суперпользователя
superuser:
	$(COMPOSE) exec web python manage.py createsuperuser

# Собрать статику
collectstatic:
	$(COMPOSE) exec web python manage.py collectstatic --noinput

# Пересоздать web (после смены .env)
recreate-web:
	$(COMPOSE) up -d --force-recreate web

# Только dev (локально, без prod-файла)
dev-up:
	docker compose -f docker-compose.yml up -d

dev-down:
	docker compose -f docker-compose.yml down

dev-ps:
	docker compose -f docker-compose.yml ps
