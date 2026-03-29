# Повторный деплой на сервер

Инструкция для случаев, когда BizonVR уже один раз развернут на сервере и нужно выкатить очередное обновление.

Предполагается, что:

- проект уже лежит в `/opt/BizonVR`;
- `.env` уже создан и заполнен;
- systemd-сервис `bizonvr` уже настроен;
- Nginx и HTTPS уже работают.

Активный runtime по-прежнему один: Django BizonVR. Рабочая БД только одна: PostgreSQL из `DATABASES["default"]`.

## Когда использовать

Этот сценарий подходит, если:

- вы уже делали первый деплой по [DEPLOY.md](/Users/Yaroslav/Documents/dev/BizonVR/DEPLOY.md);
- нужно подтянуть новый код из репозитория;
- нужно применить миграции, пересобрать статику и перезапустить приложение.

## Базовый сценарий обновления

Подключитесь к серверу и выполните:

```bash
cd /opt/BizonVR
sudo git pull
.venv/bin/pip install -r requirements.txt
npm install
npm run build:css
.venv/bin/python scripts/check_single_db_contract.py
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart bizonvr
sudo systemctl reload nginx
```

## Что делает каждая команда

- `sudo git pull` — подтягивает последние изменения из репозитория.
- `.venv/bin/pip install -r requirements.txt` — обновляет Python-зависимости, если они поменялись.
- `npm install` — подтягивает frontend-зависимости, если они изменились.
- `npm run build:css` — пересобирает Tailwind/CSS.
- `.venv/bin/python scripts/check_single_db_contract.py` — проверяет, что проект всё ещё работает только с одной PostgreSQL БД.
- `.venv/bin/python manage.py migrate` — применяет новые миграции.
- `.venv/bin/python manage.py collectstatic --noinput` — собирает статику в `staticfiles/`.
- `sudo systemctl restart bizonvr` — перезапускает Gunicorn/Django.
- `sudo systemctl reload nginx` — перечитывает конфигурацию Nginx без полного рестарта.

## Если менялся только Python-код

Если вы уверены, что не менялись зависимости, Tailwind и Nginx-конфиг, можно использовать короткий сценарий:

```bash
cd /opt/BizonVR
sudo git pull
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart bizonvr
```

## Если менялся `.env`

После правок в `.env` достаточно перечитать сервис:

```bash
cd /opt/BizonVR
sudo systemctl restart bizonvr
```

Если поменялись домены, HTTPS или проксирование, дополнительно проверьте и перезагрузите Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Если вы добавляете редирект со старого домена `bizon-business.ru`, порядок такой:

1. Убедитесь, что DNS записей `bizon-business.ru` и `www.bizon-business.ru` смотрят на текущий IP сервера с BizonVR.
2. Обновите `/etc/nginx/sites-available/bizonvr` по примеру из [deploy/nginx.conf.example](/Users/Yaroslav/Documents/dev/BizonVR/deploy/nginx.conf.example), где старый домен уходит в `301` на главную страницу `https://bizonvr.ru/`.
3. Выпустите или перевыпустите сертификаты:

```bash
sudo certbot --nginx -d bizonvr.ru -d www.bizonvr.ru
sudo certbot --nginx -d bizon-business.ru -d www.bizon-business.ru
```

Старый домен не нужно добавлять в Django `ALLOWED_HOSTS`, если редирект делает сам Nginx и запросы не доходят до Gunicorn.

## Проверка после деплоя

После обновления стоит проверить:

```bash
sudo systemctl status bizonvr --no-pager
sudo nginx -t
curl -I https://bizonvr.ru
```

Если меняли редирект старого домена, дополнительно проверьте:

```bash
curl -I http://bizon-business.ru/
curl -I https://bizon-business.ru/
curl -I "http://bizon-business.ru/catalog/?page=2"
curl -I http://www.bizon-business.ru/
curl -I https://www.bizon-business.ru/
```

Дополнительно полезно открыть в браузере:

- главную страницу;
- каталог;
- админку;
- корзину;
- checkout;
- страницу заказа или оплаты, если меняли checkout/payments.

## Если что-то пошло не так

Смотреть последние логи приложения:

```bash
sudo journalctl -u bizonvr -n 200 --no-pager
```

Смотреть логи в реальном времени:

```bash
sudo journalctl -u bizonvr -f
```

Проверить, что миграции не забыты:

```bash
.venv/bin/python manage.py showmigrations
```

Проверить, что Django вообще стартует:

```bash
.venv/bin/python manage.py check --deploy
```

## Короткий чек-лист

- [ ] Код подтянут через `git pull`
- [ ] Зависимости обновлены, если менялись `requirements.txt` или `package-lock.json`
- [ ] CSS пересобран, если менялись файлы в `static/` или `static_src/`
- [ ] `scripts/check_single_db_contract.py` проходит без ошибок
- [ ] Миграции применены
- [ ] `collectstatic` выполнен
- [ ] `bizonvr` успешно перезапущен
- [ ] `nginx -t` проходит без ошибок
- [ ] `bizon-business.ru` и `www.bizon-business.ru` отдают `301` на `https://bizonvr.ru/`, если старый домен подключался
- [ ] Сайт открывается и ключевые страницы работают
