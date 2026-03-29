# BizonVR — Шпаргалка разработчика

## Доступы и пароли

### База данных (локально)
| Параметр | Значение |
|----------|----------|
| Хост     | `localhost:5432` |
| БД       | `BizonVR` |
| Юзер     | `postgres` |
| Пароль   | `Ispector228!` |

### База данных (продакшен)
| Параметр | Значение |
|----------|----------|
| Хост     | `127.0.0.1:5432` |
| БД       | `bizon` |
| Юзер     | `bizon` |
| Пароль   | см. `.env` на сервере (`DB_PASSWORD`) |

> **Важно:** имя БД в продакшене — только нижний регистр (`bizon`), иначе ошибка "database does not exist"

### Сервер
- Путь к проекту: `/opt/BizonVR`
- Systemd-сервис: `bizonvr`
- Gunicorn слушает: `127.0.0.1:8000`

---

## Локальная разработка

### Первый запуск (один раз)
```bash
createdb bizon          # создать БД в postgres
cp .env.example .env    # скопировать конфиг
make install-local      # venv + pip install + npm install
make migrate-local      # применить миграции
make superuser-local    # создать суперпользователя
make run-local          # запустить сервер
```

### Ежедневные команды
```bash
make run-local          # запустить dev-сервер (http://localhost:8000)
make migrate-local      # применить новые миграции
make shell              # Django shell
```

---

## Тесты
```bash
make test               # все тесты
make test-shop          # без manager_portal
make test-manager       # только manager_portal
make test-manager-smoke # быстрые smoke-тесты
```

---

## Данные
```bash
make load-data-local          # загрузить тестовый каталог
make load-data-clear-local    # загрузить каталог с очисткой
make seed-manager-test-deal   # создать тестовую сделку в менеджерском портале
make clear-manager-data       # очистить данные менеджерского портала
make clear-cache              # очистить кэш каталога
```

---

## Продакшен — сервис

### Статус / старт / стоп / рестарт
```bash
sudo systemctl status bizonvr
sudo systemctl start bizonvr
sudo systemctl stop bizonvr
sudo systemctl restart bizonvr
```

### Логи приложения (Gunicorn)
```bash
sudo journalctl -u bizonvr -f              # в реальном времени
sudo journalctl -u bizonvr -n 200          # последние 200 строк
sudo journalctl -u bizonvr --since "1 hour ago"
```

---

## Продакшен — Nginx

### Управление
```bash
sudo nginx -t                   # проверить конфиг
sudo systemctl reload nginx     # перезагрузить конфиг (без даунтайма)
sudo systemctl restart nginx    # перезапустить
sudo systemctl status nginx
```

### Логи Nginx
```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Конфиг
```bash
sudo nano /etc/nginx/sites-available/bizonvr
```

---

## Продакшен — PostgreSQL

### Подключиться к БД
```bash
sudo -u postgres psql -d bizon
```

### Основные команды psql
```sql
\dt                    -- список таблиц
\l                     -- список БД
\q                     -- выйти
SELECT version();      -- версия postgres
```

### Создать БД и юзера (если с нуля)
```bash
sudo -u postgres psql <<'SQL'
CREATE USER bizon WITH PASSWORD 'change-me';
CREATE DATABASE bizon OWNER bizon;
SQL
```

### Бэкап / восстановление
```bash
# Бэкап
pg_dump -U bizon bizon > backup-$(date +%Y%m%d).sql

# Восстановление
psql -U bizon bizon < backup-20240101.sql
```

---

## Продакшен — деплой обновлений

```bash
cd /opt/BizonVR
sudo git pull
.venv/bin/pip install -r requirements.txt
npm install && npm run build:css
.venv/bin/python scripts/check_single_db_contract.py
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart bizonvr
sudo systemctl reload nginx
```

---

## HTTPS / Certbot

```bash
# Выпустить/обновить сертификат
sudo certbot --nginx -d bizonvr.ru -d www.bizonvr.ru

# Проверить автообновление
sudo certbot renew --dry-run
```

---

## Полезные мелочи

### Генерация нового SECRET_KEY
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

### Проверить что сервер отвечает
```bash
curl -I http://127.0.0.1:8000/
```

### Собрать статику вручную
```bash
.venv/bin/python manage.py collectstatic --noinput
# или
make collectstatic
```

### Проверка single-db контракта
```bash
make check-single-db
```

### Права на файлы (если запускается от www-data)
```bash
sudo chown -R www-data:www-data /opt/BizonVR
```

### Бэкап медиафайлов
```bash
tar -czvf media-backup-$(date +%Y%m%d).tar.gz -C /opt/BizonVR media/
```

---

## Стек

| Компонент | Версия / Описание |
|-----------|-------------------|
| Django    | 6.0.1 |
| Python    | 3.12+ |
| БД        | PostgreSQL (одна, `default`) |
| Сервер    | Gunicorn + Nginx + systemd |
| CSS       | Tailwind (build: `npm run build:css`) |
| Кэш       | Redis (опционально) или LocMemCache |
| Статика   | WhiteNoise |
| PDF       | WeasyPrint |
