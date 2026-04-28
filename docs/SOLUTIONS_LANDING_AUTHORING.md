# Solutions Landing Workflow

`/solutions/` — это standalone SEO-лендинги BizonVR, которые верстаются вручную и публикуются только через кодовую базу.

## Как добавить новую страницу

1. Создать папку `solutions/<slug>/`.
2. Положить туда минимум `index.html`.
3. При необходимости добавить `styles.css`, `script.js`, `assets/**`.
4. Добавить запись в [config/solution_landings.py](/Users/Yaroslav/Documents/dev/BizonVR/config/solution_landings.py).
5. Добавить smoke-тесты в [config/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/config/tests.py), если страница вводит новый паттерн или новые ассеты.

## Обязательные HTML-конвенции

- Уникальные `title` и `meta description`.
- Canonical вида `https://bizonvr.ru/solutions/<slug>/`.
- Standalone-страница не использует `base.html`.
- Разрешены только явные ссылки на каталог, товары, `/contacts/`, Telegram, WhatsApp и телефон.
- Ассеты подключаются относительными путями внутри текущей папки.
- Нельзя использовать пути вида `../...`.
- Для лидогенерации использовать `GET` на `/contacts/` с `site_context` и `site_comment`.

## Публикация

- `is_published=True` делает страницу доступной публично.
- `include_in_hub=True` выводит её в `/solutions/`.
- `include_in_sitemap=True` добавляет её в `sitemap.xml`.

Админка для `/solutions/` не создаётся: source of truth всегда остаётся в репозитории.
