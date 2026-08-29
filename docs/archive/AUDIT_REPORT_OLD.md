# BizonVR Audit Report

Аудит выполнен без правок кода. `manager_portal` не анализировался глубоко; отмечены только публичные зависимости, которые могут влиять на сайт.

Проверки:
- `manage.py check` - проходит.
- `scripts/check_single_db_contract.py` - проходит.
- `npm run build:css` - не проходит в текущем Windows-окружении: `tailwindcss is not recognized`.
- `manage.py test config catalog orders accounts payments --keepdb --noinput` - не проходит: 452 теста, 15 failures, 20 errors.

## Critical issues

1. Checkout публичного сайта зависит от внутреннего контура.
   - В `orders/views/checkout.py` после создания заказа вызывается `manager_portal.services.ensure_website_order_workflow(order)`.
   - Если сервис менеджерского контура сломается, публичное оформление заказа может упасть уже после создания `Order`/`OrderItem`.
   - Это критично для продаж: внешний checkout не должен зависеть от доступности внутреннего портала без изоляции ошибок.

2. Тесты публичного контура сейчас красные.
   - Падает `test-shop`: 15 failures и 20 errors.
   - Ошибки затрагивают корзину, рекомендации, фильтры, контент-блоки товара, responsive media, YML feed, public media cache headers.
   - Часть ошибок выглядит окруженческой: тесты не могут писать в `%TEMP%` (`PermissionError: [WinError 5] Отказано в доступе` при создании `products/` в temp dir).
   - Но failures в корзине и рекомендациях выглядят как реальные регрессии поведения или устаревшие ожидания тестов.

3. CSS-сборка не воспроизводится в текущем Windows-окружении.
   - `npm run build:css` падает, хотя `node_modules/tailwindcss` есть.
   - В `node_modules/.bin` лежат Unix-style shims без `.cmd`, поэтому `npx tailwindcss` не находится.
   - Это блокирует нормальную пересборку `static/css/tailwind.css` на этой машине.

4. Публичный checkout фактически сведен к CDEK PVZ и оплате через менеджера.
   - `CheckoutForm` принудительно возвращает `delivery_type = CDEK_PVZ`, `payment_method = manager_contact`, очищает `comment` и `delivery_comment`.
   - Если `CDEK_WIDGET_ACCOUNT`/`CDEK_WIDGET_PASSWORD` не заданы и у пользователя нет сохраненного адреса, checkout показывает ошибочный блок про недоступную карту, а не альтернативный способ оставить заявку.
   - Для продаж это риск потери заявок.

5. В корне лежит `.env` с локальными настройками.
   - Файл игнорируется `.gitignore`, но сам факт его присутствия в рабочей директории требует аккуратности при архивах, деплое и передаче проекта.

## Major improvements

1. Разделить публичный checkout и внутренние side effects.
   - Обернуть создание workflow для внутреннего портала в безопасный сервис с логированием и retry-планом.
   - Публичный заказ должен завершаться успешно даже если внутренний workflow временно недоступен.

2. Привести checkout к реальному обещанию сайта.
   - В документации и моделях есть СБП, карта, юрлица, разные типы доставки.
   - В UI и форме сейчас публично остается в основном "менеджер + CDEK PVZ".
   - Нужно либо вернуть варианты оплаты/доставки, либо явно позиционировать сайт как "заявка, менеджер подтвердит".

3. Починить корзину и связанные тесты.
   - Падают тесты `CartTest`: add/update/clear/session order/share/stock status/buy now.
   - Эти сценарии напрямую влияют на каталог -> корзина -> заказ.

4. Довести рекомендации и карточки до стабильного поведения.
   - Падают `ProductRecommendationsTest`.
   - В одном выводе теста видно, что карточки рекомендаций могут показывать "Цена не указана" и placeholder изображения, что ухудшает доверие и конверсию.

5. Уточнить стратегию медиа.
   - Есть `media/game_packs` с множеством однотипных SVG-дубликатов.
   - После тестового прогона появились новые untracked SVG в `media/game_packs`.
   - Нужен регламент: что является пользовательским медиа, что seed/generated, что можно пересоздавать.

6. Упростить публичные лендинги.
   - В `config/urls.py` подключены standalone-директории: `invest/`, `invest-2/`, `invest-2-new/`, `conference-attractions/`, `solutions/<slug>/`.
   - Это нормально как архив/маркетинг, но сейчас они лежат рядом с runtime-кодом и создают шум.
   - Для production стоит решить, какие лендинги действительно публичные.

## Minor improvements

1. Исправить опечатки в именах документов:
   - `chechoutupdate.md` -> вероятно `checkout_update.md`.
   - `docs/prodile.md` -> вероятно `profile.md` или удалить после подтверждения.
   - `create-discriptions-tz.md` -> вероятно `create-descriptions-tz.md`.

2. Почистить `.gitignore`.
   - В конце файла есть поврежденная строка с NUL-символами вокруг `media/cache/`.

3. Уточнить Windows-команды разработки.
   - `Makefile` использует `.venv/bin/python`, `.venv/bin/pip`, что подходит Unix/macOS, но не PowerShell/Windows.
   - В текущем окружении рабочая команда: `.venv\Scripts\python.exe ...`.

4. Проверить настройки времени.
   - `TIME_ZONE = 'UTC'`, при этом бизнес-настройки manager workflow используют `Asia/Yekaterinburg`.
   - Для публичных писем, заказов и админских дат стоит явно договориться, какая зона показывается пользователю.

5. Не показывать пользователю технические заглушки.
   - В пустых состояниях игр/паков есть сообщения вида "Добавьте ProductGameMetadata в админке".
   - Это полезно администратору, но публичному пользователю лучше показывать нейтральный CTA.

## Game packs and games section

1. Раздел `/catalog/vr-club-games/` выглядит как MVP, а не готовый коммерческий раздел.
   - Много CSS и контента находится прямо в шаблоне `templates/catalog/vr_club_games.html`.
   - Нет визуальных карточек с обложками игр в списке конструктора, хотя медиа для игр есть в `solutions/vr-dlya-kluba/img/...` и `static/images/compact-vr-v3/...`.
   - Фильтрация по `devices`/`genres` сделана через `icontains` по строкам, что хрупко для списков значений.

2. Конструктор индивидуального пака добавляет custom pack и отдельно добавляет выбранные услуги как service lines.
   - Это может быть правильно, но в корзине нужно явно объяснять, что является паком, а что отдельной услугой, чтобы не выглядело как дубль.

3. Ценообразование custom pack неочевидно.
   - `add_vr_club_custom_pack_to_cart_view` собирает кастомный пак, но итоговая цена может быть 0 или зависеть от service lines.
   - Для B2B-продаж лучше показывать "расчет менеджером" или предварительный диапазон.

4. GamePack и ProductGameMetadata настраиваются через админку.
   - Это хорошо, но нужны обязательные поля/валидации для публичного качества: обложка, коммерческий pitch, состав, совместимость, игроки, возраст, услуги.

## Header/navigation issues

1. Мобильная шапка не является полноценной навигацией.
   - `templates/layout/_header_mobile.html` показывает в основном поиск.
   - Основная мобильная навигация вынесена в нижний dock в `base.html`.
   - Нет явного мобильного меню со ссылками `Аренда`, `Услуги`, `Контакты`, `VR club games`, `Solutions`.

2. Desktop header частично хардкодит контакты.
   - В одном месте используются `site_avito_url`, но Telegram и телефон в шаблоне прописаны напрямую.
   - При изменении настроек в `.env` часть шапки может остаться старой.

3. Каталог-оверлей и sticky header имеют высокий `z-index` и сложную Alpine-логику.
   - Нужна ручная проверка на мобильных/планшетах: не перекрывает ли он модалки, CDEK, cookie-banner, mini-cart.

4. Навигация не ведет напрямую в games section.
   - `/catalog/vr-club-games/` есть, но в основной шапке ссылки на него не видно.

## Admin configurability

Через админку уже можно настраивать:
- разделы, категории, товары, варианты, фото, видео, характеристики;
- остатки, города, точки выдачи;
- bundles, game packs, game metadata, services;
- контент-блоки и шаблоны описаний;
- заявки, заказы, промокоды, платежи, контакты.

Желательно вынести в админку или отдельную site settings-модель:

1. Основные пункты шапки и футера.
   - Сейчас часть через env, часть прямо в шаблонах.

2. Способы доставки и оплаты для публичного checkout.
   - Сейчас публичный checkout жестко сведен к CDEK PVZ и менеджеру.

3. Тексты hero/CTA на главной, услугах, аренде, VR club games.
   - Сейчас большая часть маркетингового текста живет в templates.

4. Публичные лендинги.
   - Нужен реестр "показывать/скрывать", SEO-метаданные, canonical, порядок в навигации.

5. Empty states и пользовательские тексты ошибок.
   - Не стоит показывать публичному пользователю технические инструкции для админки.

6. Настройки game packs quality gate.
   - Например: не публиковать пак без цены/изображения/состава/описания.

## Documentation cleanup

Документы, которые выглядят актуальными source of truth:
- `README.md`
- `DEPLOY.md`
- `.env.example`
- `docs/CITIES_AND_PRODUCTS.md`
- `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md`
- `docs/SOLUTIONS_LANDING_AUTHORING.md`
- `docs/DEV_CHEATSHEET.md`

Документы, которые нужно пересмотреть/объединить:
- `DEPLOY_UPDATE.md` - вероятно объединить с `DEPLOY.md`.
- `docs/project_work_description.md` - очень большой файл, лучше разбить или архивировать как отчет.
- `docs/CHECKOUT_USER_REPORT.md` - сверить с текущим checkout.
- `docs/CATALOG_FILTERS_AUDIT.md` и `docs/CATALOG_FILTER_PERFORMANCE_PLAN.md` - объединить в один актуальный документ по фильтрам.
- `docs/FRONTEND_PERFORMANCE_PLAN.md` - оставить как план или превратить в чеклист с выполненными пунктами.
- `docs/SEO_PRESENTATION_LANDING_PLAN.md` - сверить с текущими лендингами.

Документы, подозрительные на устаревание/архив:
- `tech.md` - уже отмечен как старое ТЗ, не source of truth.
- `chechoutupdate.md` - опечатка и выглядит как временный отчет.
- `create-discriptions-tz.md` - опечатка и похоже на старое ТЗ.
- `docs/prodile.md` - опечатка, очень большой размер, нужно подтвердить назначение.
- `docs/MANAGER_PORTAL.md`, `docs/MANAGER_SIMPLIFICATION.md` - не трогать в рамках публичного аудита, но держать отдельно от публичной документации.

## Possible unused files

Без удаления, только список для проверки:

- `staticfiles/` - generated output `collectstatic`, не редактировать вручную.
- `node_modules/` - локальные зависимости, не должны быть source of truth.
- `.codex-runserver.err.log`, `.codex-runserver.out.log` - локальные логи.
- `logs/` - локальные runtime-логи.
- `invest (sponsor) 2/` - standalone landing, проверить нужен ли в production.
- `invest_2/` - второй standalone investment landing, проверить дублирование с `invest (sponsor) 2/`.
- `Конференция (Аттракционы)/` - standalone landing с тяжелыми видео, проверить нужен ли как публичный route.
- `solutions/vr-dlya-kluba/` - standalone solution assets, частично пересекается с `/catalog/vr-club-games/`.
- `launchers/*.command`, `launchers/*.applescript` - macOS launchers в Windows-рабочем дереве.
- `media/_data` - назначение неочевидно.
- `media/game_packs/club-starvr-pack-*.svg` - много дубликатов с суффиксами; часть появилась после тестового прогона.
- `static/images/compact-vr-v3` и `solutions/vr-dlya-kluba/img` - похожие наборы игровых медиа, нужна карта использования.
- `static/js/manager_portal.js`, `static/css/manager_portal*.css` - не анализировались; публичному сайту не должны мешать.
- `legacy/` - архивные источники, не runtime; не удалять без отдельной процедуры.
- `db.sqlite3` в корне отсутствует; `legacy/db.sqlite3` допустим как архив.

Untracked после аудита/тестов:
- `media/game_packs/club-starvr-pack-all-in_4HYOZqn.svg`
- `media/game_packs/club-starvr-pack-all-in_N8JUyFH.svg`
- `media/game_packs/club-starvr-pack-all-in_UcrsmSM.svg`
- `media/game_packs/club-starvr-pack-all-in_qhhAqeS.svg`
- `media/game_packs/club-starvr-pack-base_2zR0YCP.svg`
- `media/game_packs/club-starvr-pack-base_4vwG6jo.svg`
- `media/game_packs/club-starvr-pack-base_7IZTjP2.svg`
- `media/game_packs/club-starvr-pack-base_RoHl2VN.svg`
- `media/game_packs/club-starvr-pack-universal_QjfikSD.svg`
- `media/game_packs/club-starvr-pack-universal_T7PYU5B.svg`
- `media/game_packs/club-starvr-pack-universal_rDVMn12.svg`
- `media/game_packs/club-starvr-pack-universal_tT6F4QV.svg`

## Safe implementation plan

## 2026-05-09 VR club games implementation

Выполнено для публичного сайта:
- Обновлены модели `GamePack` и `ProductGameMetadata`: добавлен формат пака, порядок сортировки, расширены сценарии игр для дома, детей и вечеринки.
- Обновлена админка игровых паков и B2B-метаданных игр: поля сгруппированы по смыслу, добавлены фильтры, быстрые правки активности/порядка и autocomplete для состава.
- Переписан публичный раздел `/catalog/vr-club-games/`: исправлены битые русские строки, добавлены карточки паков и игр, фильтры, CTA, изображения, мобильная адаптация и пустые состояния.
- Обновлена карточка игрового пака в каталоге: формат, совместимость, игроки, состав игр и услуги выводятся из админских данных.
- Публичная сортировка GamePack теперь учитывает `sort_order`.
- Добавлена документация администратора: `docs/VR_CLUB_GAMES_ADMIN.md`.

Manager portal не изменялся.

Этап 1. Стабилизировать проверки.
- Починить Windows CSS build или документировать WSL/Linux-only workflow.
- Исправить `.gitignore` NUL-хвост.
- Разобрать failures/errors `test-shop`.
- Отдельно решить temp/media permissions в тестах.

Этап 2. Защитить продажи.
- Изолировать публичный checkout от ошибок manager workflow.
- Добавить fallback-заявку, если CDEK widget не настроен или недоступен.
- Проверить корзину, buy-now, cart share, session/db sync по тестам и вручную.

Этап 3. Привести checkout к продуктовой политике.
- Решить: онлайн-оплата возвращается или сайт работает как заявочный checkout.
- Если возвращается - восстановить СБП/карта/юрлица в UI, тестах и документации.
- Если нет - удалить/переименовать legacy payment promises из публичной документации.

Этап 4. Довести игры и game packs.
- Добавить ссылку на `/catalog/vr-club-games/` в навигацию.
- Вынести inline CSS в `static/`.
- Добавить изображения/обложки, понятные цены, quality gate в админке.
- Нормализовать фильтры игр: structured choices вместо `icontains` по строкам.

Этап 5. Навигация и UX.
- Сделать полноценное мобильное меню или явно расширить bottom dock.
- Унифицировать телефон/Telegram/Avito через settings/admin.
- Проверить z-index и модалки на desktop/mobile.

Этап 6. Документы и файлы.
- Утвердить список актуальных docs.
- Архивировать старые отчеты после подтверждения владельцем.
- Разобрать standalone лендинги и медиа-дубли.
- Не удалять `legacy/`, `staticfiles/`, `media/` без отдельного решения.
