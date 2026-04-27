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
git restore --source=HEAD --worktree --staged static/css/tailwind.css
sudo git pull --ff-only
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/check_single_db_contract.py
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart bizonvr
sudo systemctl reload nginx
```

## Что делает каждая команда

- `git restore --source=HEAD --worktree --staged static/css/tailwind.css` — убирает локальный diff у скомпилированного Tailwind-файла, чтобы `git pull` не упёрся в конфликт.
- `sudo git pull --ff-only` — подтягивает последние изменения из репозитория без merge-коммита.
- `.venv/bin/pip install -r requirements.txt` — обновляет Python-зависимости, если они поменялись.
- `.venv/bin/python scripts/check_single_db_contract.py` — проверяет, что проект всё ещё работает только с одной PostgreSQL БД.
- `.venv/bin/python manage.py migrate` — применяет новые миграции.
- `.venv/bin/python manage.py collectstatic --noinput` — собирает статику в `staticfiles/` из уже закоммиченных файлов репозитория.
- `sudo systemctl restart bizonvr` — перезапускает Gunicorn/Django.
- `sudo systemctl reload nginx` — перечитывает конфигурацию Nginx без полного рестарта.

`static/css/tailwind.css` хранится в репозитории и участвует в `collectstatic`, поэтому при обычном повторном деплое не нужно пересобирать Tailwind на сервере. Если CSS менялся, его нужно собрать локально перед коммитом и закоммитить вместе с остальными изменениями.

## Если менялся только Python-код

Если вы уверены, что не менялись зависимости, Tailwind и Nginx-конфиг, можно использовать короткий сценарий:

```bash
cd /opt/BizonVR
git restore --source=HEAD --worktree --staged static/css/tailwind.css
sudo git pull --ff-only
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart bizonvr
```

## Если всё же нужно пересобрать Tailwind на сервере

Это редкий сценарий. Используйте его только если вы осознанно проверяете локально незафиксированный CSS-артефакт или временно чините окружение.

```bash
cd /opt/BizonVR
npm install
npm run build:css
.venv/bin/python manage.py collectstatic --noinput
git restore --source=HEAD --worktree --staged static/css/tailwind.css
```

Последний `git restore` возвращает рабочее дерево к состоянию коммита, чтобы следующий `git pull` не падал на `static/css/tailwind.css`.

## Если `git pull` уже упёрся в `static/css/tailwind.css`

Если сервер уже успел собрать CSS и теперь `git pull` пишет `Your local changes to the following files would be overwritten by checkout: static/css/tailwind.css`, выполните:

```bash
cd /opt/BizonVR
git restore --source=HEAD --worktree --staged static/css/tailwind.css
sudo git pull --ff-only
```

Если хотите сначала сохранить текущую серверную версию файла как подстраховку, вместо `git restore` можно сделать:

```bash
git stash push -m "server tailwind before pull" -- static/css/tailwind.css
sudo git pull --ff-only
```

Не делайте потом `git stash pop` для этого файла, если ваша цель была просто подтянуть свежий код: вы вернёте старый сгенерированный CSS поверх новой версии из репозитория.

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

## Управляемые фильтры каталога

После деплоя с новой системой фильтров каталог продолжит работать по старой логике, даже если ничего не настраивать в админке. Новый управляемый режим включается только там, где вы явно создали `CategoryFilterConfig` или `SectionFilterConfig`.

### Что обязательно выполнить на сервере

После выкладки кода примените миграции:

```bash
cd /opt/BizonVR
.venv/bin/python manage.py migrate
```

Если хотите сразу развернуть управляемые фильтры, дальше используйте bootstrap-команды ниже.

### Быстрый сценарий первичной настройки

1. Создайте `CharacteristicDefinition` из текущих `ProductCharacteristic.name`.
2. Посмотрите suggested grouping для значений.
3. Подтвердите нужные alias-группы в админке.
4. Сгенерируйте config-ы для нужной категории или раздела.
5. Проверьте каталог в браузере.

### Команды для сервера

Черновой просмотр характеристик, которые будут добавлены:

```bash
cd /opt/BizonVR
.venv/bin/python manage.py bootstrap_characteristic_definitions
```

Фактическое создание `CharacteristicDefinition`:

```bash
cd /opt/BizonVR
.venv/bin/python manage.py bootstrap_characteristic_definitions --apply
```

Можно ограничить bootstrap только частью характеристик:

```bash
.venv/bin/python manage.py bootstrap_characteristic_definitions --starts-with "Ц"
.venv/bin/python manage.py bootstrap_characteristic_definitions --contains "пам"
.venv/bin/python manage.py bootstrap_characteristic_definitions --source-name "Память" --apply
```

Посмотреть suggested grouping raw values для конкретной характеристики:

```bash
.venv/bin/python manage.py suggest_characteristic_aliases --definition memory
```

Если нужен JSON-вывод для анализа:

```bash
.venv/bin/python manage.py suggest_characteristic_aliases --definition memory --format json
```

Посмотреть, какие config-ы будут созданы для категории:

```bash
.venv/bin/python manage.py bootstrap_catalog_filter_configs --category vr-shlemy
```

Создать config-ы для категории:

```bash
.venv/bin/python manage.py bootstrap_catalog_filter_configs --category vr-shlemy --apply
```

Аналогично для раздела:

```bash
.venv/bin/python manage.py bootstrap_catalog_filter_configs --section vr-attraktsiony
.venv/bin/python manage.py bootstrap_catalog_filter_configs --section vr-attraktsiony --apply
```

В `--category` и `--section` можно передавать как `slug`, так и числовой `id`.

### Как работать через Django admin

В админке появились новые разделы каталога:

- `Определения характеристик`
- `Алиасы значений характеристик`
- `Конфиги фильтров категорий`
- `Конфиги фильтров разделов`

Рекомендуемый порядок работы:

1. Откройте `Каталог -> Определения характеристик`.
2. Проверьте, что нужные характеристики созданы bootstrap-командой.
3. У каждой характеристики:
   - `source_name` должен точно совпадать с `ProductCharacteristic.name`;
   - `code` можно не заполнять вручную, он генерируется автоматически;
   - `name` — это заголовок фильтра на витрине.
4. Откройте нужную характеристику и нажмите `Подсказать алиасы`.
5. На странице preview:
   - просмотрите suggested groups;
   - при необходимости поправьте `Отображаемое значение`;
   - оставьте отмеченными только те группы, которые действительно нужно создать;
   - нажмите `Создать алиасы для выбранных групп`.
6. После этого создайте config-ы:
   - либо через команду `bootstrap_catalog_filter_configs --apply`;
   - либо через actions в списке категорий/разделов:
     - `Создать конфиги фильтров для выбранных категорий`
     - `Создать конфиги фильтров для выбранных разделов`
7. В `Конфигах фильтров` при необходимости вручную настройте:
   - `sort_order`
   - `is_quick_filter`
   - `is_visible`
   - `show_top_n`
   - `hide_single_value`

### Что именно делает нормализация значений

Suggestions и alias helper пока делают только безопасную базовую нормализацию:

- trim по краям;
- lowercase;
- схлопывание повторных пробелов;
- базовую нормализацию единиц вроде `gb`, `g b`, `гб`, `г б` в одну группу;
- аналогично для `tb` и `тб`.

Это означает, что значения вроде:

- `128 GB`
- `128Gb`
- `128 ГБ`
- `128гб`

будут предложены как одна группа. Но спорные бизнес-объединения всё равно нужно подтверждать вручную в админке.

### Как теперь работает каталог

- Если для категории есть `CategoryFilterConfig`, используется управляемый режим категории.
- Если для категории конфига нет, но у раздела есть `SectionFilterConfig`, используется управляемый режим раздела.
- Если config-ов нет, каталог работает по legacy-логике из `ProductCharacteristic`.
- Старые ссылки с параметрами вида `char_<raw source_name>` продолжают работать.
- Новые ссылки на витрине генерируются в canonical-формате `char_<code>`.

### Пример безопасного запуска на проде

```bash
cd /opt/BizonVR
.venv/bin/python manage.py migrate
.venv/bin/python manage.py bootstrap_characteristic_definitions
.venv/bin/python manage.py bootstrap_characteristic_definitions --apply
.venv/bin/python manage.py suggest_characteristic_aliases --definition memory
.venv/bin/python manage.py bootstrap_catalog_filter_configs --category vr-shlemy
.venv/bin/python manage.py bootstrap_catalog_filter_configs --category vr-shlemy --apply
```

После этого:

1. зайдите в админку;
2. откройте `Определения характеристик`;
3. у нужных definitions нажмите `Подсказать алиасы`;
4. подтвердите нужные группы;
5. откройте категорию на витрине и проверьте фильтры.

### Что проверить после настройки фильтров

Откройте в браузере:

- страницу нужной категории;
- страницу раздела, если настраивали `SectionFilterConfig`;
- переход по тегам внутри каталога;
- применение и сброс характеристик;
- поиск, сортировку и фильтр по цене вместе с `char_*`.

Проверьте руками, что:

- в фильтрах нет шумовых характеристик;
- порядок фильтров соответствует `sort_order`;
- быстрые фильтры показываются корректно;
- одинаковые значения склеились в один пункт;
- переход по тегам не сбрасывает активные `char_*` без причины.

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
