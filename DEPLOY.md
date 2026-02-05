# Деплой на сервер

Пошаговая подготовка и выкладка проекта на продакшен (Docker + Nginx).

**В документе явно указано, что делать локально (на своей машине) и что — на сервере.**

---

## Требования на сервере

- Docker и Docker Compose (v2)
- Nginx (для HTTPS и раздачи статики/медиа)
- Домен bizonvr.ru, направленный на IP сервера

### Cloud-init при создании сервера

Перед первым деплоем можно один раз подготовить сервер через **Cloud-init**: при создании VPS в панели облака (Hetzner, Yandex Cloud, DigitalOcean, Selectel и т.д.) в поле **User data** / **Cloud-init** / **Скрипт инициализации** вставьте содержимое файла **`deploy/cloud-init.yml`** из репозитория.

Это установит при первом запуске сервера:

- обновление пакетов;
- Docker и Docker Compose (официальный скрипт);
- Nginx;
- Certbot (Let's Encrypt);
- таймзону Europe/Moscow.

После загрузки сервера подключайтесь по SSH и выполняйте шаги из раздела «На сервере» ниже (клонирование репозитория, `.env`, `docker compose up`). Файл `deploy/cloud-init.yml` можно скопировать из репозитория или из этой папки после клонирования.

---

# Локально (на своей машине)

## 1. Подготовка репозитория

Убедитесь, что код запушен в GitHub:

```bash
git add .
git commit -m "Prepare for deploy"
git push origin main
```

Репозиторий: https://github.com/yarrobong/BizonVR.git

## 2. (Опционально) Сгенерировать SECRET_KEY для сервера

Скопируйте вывод команды — вставите в `.env` на сервере:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 3. При обновлении деплоя — только push

После изменений в коде:

```bash
git add .
git commit -m "Update"
git push origin main
```

Дальше на сервере выполните шаги из раздела «Обновление деплоя» ниже.

---

# На сервере

Подключитесь по SSH к серверу и выполняйте команды ниже там.

## 1. Первый раз: клонирование и каталог

```bash
cd /opt
sudo git clone https://github.com/yarrobong/BizonVR.git
cd BizonVR
```

## 2. Создание .env (один раз, не коммитить)

```bash
cp .env.example .env
nano .env
```

**Обязательные переменные для продакшена:**

```env
SECRET_KEY=0TN7p13vbV1M6rywLTNSbguOWrAN_Qpwcd61FVALevMdkwk4t9mSvWzVHr7OPKFmf5M
DEBUG=False
ALLOWED_HOSTS=bizonvr.ru,www.bizonvr.ru
CSRF_TRUSTED_ORIGINS=https://bizonvr.ru,https://www.bizonvr.ru
USE_HTTPS=true
SITE_URL=https://bizonvr.ru

DB_ENGINE=django.db.backends.postgresql
DB_NAME=bizon
DB_USER=postgres
DB_PASSWORD=надёжный-пароль-для-бд
DB_HOST=db
DB_PORT=5432

GUNICORN_WORKERS=2
PORT=8000
```

По необходимости: `SMS_API_KEY`, `NOWPAYMENTS_API_KEY`, `NOWPAYMENTS_IPN_SECRET`.

Сгенерировать SECRET_KEY прямо на сервере (если не сделали локально):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

## 3. Запуск приложения (Docker)

Сборка и запуск в режиме продакшена:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Проверка:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -I http://127.0.0.1:8000/
```

Создание суперпользователя (один раз):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Миграции выполняются автоматически при старте контейнера (entrypoint).

## 4. Nginx

Установка (если ещё нет):

```bash
sudo apt install nginx
```

Скопировать пример конфигурации (уже подставлен домен bizonvr.ru):

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/bizonvr
sudo ln -s /etc/nginx/sites-available/bizonvr /etc/nginx/sites-enabled/
```

Если нужны правки (пути к сертификатам после certbot):

- `ssl_certificate` / `ssl_certificate_key` — после certbot будут в `/etc/letsencrypt/live/bizonvr.ru/`

Минимальный вариант Nginx (всё через Gunicorn, статика через WhiteNoise):

```nginx
server {
    listen 80;
    server_name bizonvr.ru www.bizonvr.ru;
    return 301 https://$server_name$request_uri;
}
server {
    listen 443 ssl http2;
    server_name bizonvr.ru www.bizonvr.ru;
    ssl_certificate     /etc/letsencrypt/live/bizonvr.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bizonvr.ru/privkey.pem;
    client_max_body_size 20M;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Проверка и перезагрузка Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5. SSL (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d bizonvr.ru -d www.bizonvr.ru
```

Certbot сам подставит пути к сертификатам в Nginx.

---

## Обновление деплоя (на сервере)

После того как вы сделали `git push` локально:

```bash
cd /opt/BizonVR
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Миграции выполняются при старте контейнера.

---

## Чек-лист (на сервере)

- [ ] Репозиторий склонирован в `/opt/BizonVR`
- [ ] `.env` создан, `SECRET_KEY` и `ALLOWED_HOSTS` заданы
- [ ] `DEBUG=False`, `USE_HTTPS=true`, `CSRF_TRUSTED_ORIGINS` указаны
- [ ] Контейнеры подняты, приложение отвечает на `http://127.0.0.1:8000`
- [ ] Nginx проксирует на 127.0.0.1:8000, передаёт `X-Forwarded-Proto: https`
- [ ] SSL включён (HTTPS открывается без ошибок)
- [ ] Выполнено `createsuperuser`, вход в админку работает
- [ ] Проверены: вход по телефону, каталог, корзина, оформление заказа

---

## Без Docker (systemd + Gunicorn) — на сервере

Если разворачиваете без Docker:

1. Установите Python 3.12, PostgreSQL, создайте БД и пользователя.
2. Создайте venv, установите зависимости из `requirements.txt`.
3. Выполните миграции и `collectstatic`.
4. Запустите Gunicorn через systemd (unit с `ExecStart=gunicorn --bind 127.0.0.1:8000 ... config.wsgi:application`).
5. Nginx настроить так же, как выше, проксировать на `127.0.0.1:8000`.
