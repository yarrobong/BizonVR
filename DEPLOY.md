# Деплой на сервер

Пошаговая подготовка и выкладка проекта на продакшен через `venv`, Gunicorn, systemd и Nginx.

Активный runtime в продакшене только один: Django BizonVR. Единственная рабочая БД проекта — PostgreSQL из `DATABASES["default"]`. Каталог `legacy` не деплоится как отдельный сервис и используется только как архив источников для импорт-команд.

## Требования на сервере

- Python 3.12+ и `python3-venv`
- PostgreSQL
- Nginx
- Certbot
- Домен `bizonvr.ru`, направленный на IP сервера
- Если нужен редирект со старого домена, `bizon-business.ru` и `www.bizon-business.ru` тоже должны указывать на этот же сервер

### Cloud-init при создании сервера

Перед первым деплоем можно подготовить VPS через `deploy/cloud-init.yml`. Файл устанавливает Python, PostgreSQL, Nginx и Certbot, затем включает нужные сервисы.

## Локально

Перед выкладкой убедитесь, что изменения запушены:

```bash
git add .
git commit -m "Update deploy"
git push origin main
```

При необходимости сгенерируйте новый `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

## На сервере

### 1. Клонирование репозитория

```bash
cd /opt
sudo git clone https://github.com/yarrobong/BizonVR.git
cd BizonVR
```

### 2. База данных PostgreSQL

Если БД и пользователь ещё не созданы:

```bash
sudo -u postgres psql <<'SQL'
CREATE USER bizon WITH PASSWORD 'change-me';
CREATE DATABASE bizon OWNER bizon;
SQL
```

### 3. `.env`

```bash
cp .env.example .env
nano .env
```

Минимум для продакшена:

```env
SECRET_KEY=replace-me
DEBUG=False
ALLOWED_HOSTS=bizonvr.ru,www.bizonvr.ru
CSRF_TRUSTED_ORIGINS=https://bizonvr.ru,https://www.bizonvr.ru
USE_HTTPS=True
SITE_URL=https://bizonvr.ru

DB_NAME=bizon
DB_USER=bizon
DB_PASSWORD=change-me
DB_HOST=127.0.0.1
DB_PORT=5432

PORT=8000
GUNICORN_WORKERS=2
```

Для публичного сценария обязательно настройте корпоративную почту через `EMAIL_*` и `DEFAULT_FROM_EMAIL`. `EXOLVE_*` и `PAYMENT_GATEWAY_*` остаются legacy-настройками и не нужны для checkout без онлайн-оплаты.

### 4. Виртуальное окружение и зависимости

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install
npm run build:css
```

### 5. Проверка single-db контракта

```bash
make check-single-db
```

### 6. Миграции и статика

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
```

Создание суперпользователя:

```bash
.venv/bin/python manage.py createsuperuser
```

### 7. Gunicorn через systemd

Создайте unit `/etc/systemd/system/bizonvr.service`:

```ini
[Unit]
Description=BizonVR Gunicorn
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/BizonVR
EnvironmentFile=/opt/BizonVR/.env
ExecStart=/bin/sh -c '/opt/BizonVR/.venv/bin/gunicorn --workers ${GUNICORN_WORKERS:-2} --bind 127.0.0.1:${PORT:-8000} config.wsgi:application'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Если сервис запускается от `www-data`, заранее выставьте права:

```bash
sudo chown -R www-data:www-data /opt/BizonVR
```

Запуск и проверка:

```bash
sudo systemctl daemon-reload
sudo systemctl enable bizonvr
sudo systemctl start bizonvr
sudo systemctl status bizonvr
curl -I http://127.0.0.1:8000/
```

### 8. Nginx

Если переносите трафик со старого домена, сначала направьте DNS записей `bizon-business.ru` и `www.bizon-business.ru` на тот же IP, что и `bizonvr.ru`. Без этого Nginx не сможет отдать редирект, потому что запросы просто не попадут на сервер.

Скопируйте пример конфига:

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/bizonvr
sudo ln -s /etc/nginx/sites-available/bizonvr /etc/nginx/sites-enabled/bizonvr
sudo rm -f /etc/nginx/sites-enabled/default
```

Проверьте, что `proxy_pass` указывает на `127.0.0.1:8000`, а `alias` для `/static/` и `/media/` ссылаются на:

- `/opt/BizonVR/staticfiles/`
- `/opt/BizonVR/media/`

В примере `deploy/nginx.conf.example` уже есть отдельные `server` blocks для:

- основного сайта `bizonvr.ru`;
- постоянного `301`-редиректа с `bizon-business.ru` и `www.bizon-business.ru` на главную страницу `https://bizonvr.ru/`.

Старый домен не нужно добавлять в `ALLOWED_HOSTS`, если редирект выполняется через `return 301` на уровне Nginx и трафик не проксируется в Django.

Затем:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 9. HTTPS

```bash
sudo certbot --nginx -d bizonvr.ru -d www.bizonvr.ru
sudo certbot --nginx -d bizon-business.ru -d www.bizon-business.ru
```

Сертификат для старого домена нужен тоже: без него `https://bizon-business.ru` не сможет корректно открыть TLS-соединение и дойти до редиректа.

## Обновление деплоя

Для повторных выкладок см. отдельную инструкцию: [DEPLOY_UPDATE.md](/Users/Yaroslav/Documents/dev/BizonVR/DEPLOY_UPDATE.md).

После `git push` локально:

```bash
cd /opt/BizonVR
git restore --source=HEAD --worktree --staged static/css/tailwind.css
sudo git pull --ff-only
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/check_single_db_contract.py
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart bizonvr
sudo systemctl reload nginx
```

При повторном деплое не нужно пересобирать `static/css/tailwind.css` на сервере: этот файл уже хранится в репозитории и должен приезжать через `git pull`. Если вы всё же вручную запускали `npm run build:css` на сервере, перед следующим `git pull` верните файл к состоянию коммита:

```bash
git restore --source=HEAD --worktree --staged static/css/tailwind.css
```

Если вместе с обновлением вы включали редирект со старого домена, после `nginx reload` проверьте:

```bash
curl -I http://bizon-business.ru/
curl -I https://bizon-business.ru/
curl -I "http://bizon-business.ru/catalog/?page=2"
curl -I http://www.bizon-business.ru/
curl -I https://www.bizon-business.ru/
curl -I https://bizonvr.ru/
```

## Медиафайлы

- `media/hero/` хранит фоновые изображения hero-блока и может лежать в git.
- `media/products/` содержит пользовательские загрузки из админки и в git не хранится.

Рекомендуемый бэкап:

```bash
tar -czvf media-backup-$(date +%Y%m%d).tar.gz -C /opt/BizonVR media/
```

## Частые проблемы

**Cross-Origin-Opener-Policy ignored**: предупреждение при HTTP. Для продакшена нужен HTTPS.

**`favicon.ico` 404**: проверьте, что выполнен `collectstatic`.

**500 на странице товара**: проверьте `sudo journalctl -u bizonvr -n 200` и наличие файлов в `media/`.

## Чек-лист

- [ ] Репозиторий расположен в `/opt/BizonVR`
- [ ] `.env` заполнен и не закоммичен
- [ ] PostgreSQL доступен по параметрам из `.env`
- [ ] `make check-single-db` проходит без ошибок
- [ ] Выполнены `migrate` и `collectstatic`
- [ ] Gunicorn отвечает на `127.0.0.1:8000`
- [ ] Nginx проксирует трафик на Gunicorn
- [ ] HTTPS выпущен и работает
- [ ] `http://bizon-business.ru`, `https://bizon-business.ru` и `www`-вариант отдают `301` на `https://bizonvr.ru/`, если старый домен подключён
- [ ] Админка, каталог, корзина и checkout открываются без ошибок
- [ ] Никакие архивные директории из `legacy` не запускаются как отдельные сервисы
