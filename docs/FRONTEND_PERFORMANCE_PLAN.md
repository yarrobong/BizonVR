# Frontend Performance Plan

План собран по итогам аудита причин лагов на слабых ПК. Цель: сначала снять самый дорогой вес и лишние глобальные загрузки, затем убрать CPU-нагрузку и фоновый шум от frontend-рантайма и трекеров.

## Приоритет страниц

1. `compact-vr` — самая проблемная страница, здесь максимальный выигрыш.
2. `catalog` — самый массовый пользовательский сценарий, высокий ROI.
3. `product` — следующий по важности.
4. `home` — полезно, но не первый кандидат.

## Общий порядок работ

1. Изображения и lazy-loading.
2. Убрать глобальный `checkout_cdek_widget.js` и сократить глобальные third-party.
3. Исправить `Lucide` и глобальный `MutationObserver`.
4. Причесать `scroll` и `resize` handlers.
5. Отдельно дочистить `compact-vr`.

## PR 1

Цель: быстро снять основной вес и самые дорогие лишние загрузки без изменения UX-логики.

### 1. Изображения каталога и карточек

Статус: `done` (2026-05-04)

Файлы:

- [templates/catalog/_product_card.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/_product_card.html:1)
- [templates/catalog/product_detail.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/product_detail.html:575)
- [templates/catalog/bundle_detail.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/bundle_detail.html:135)
- [templates/catalog/_product_card_recommend.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/_product_card_recommend.html:1)

Что менять:

- перестать подставлять оригинальный `image.url` как единственный `src`;
- добавить производные размеры для карточек, галереи и bundle detail;
- подключить `srcset` и `sizes`;
- оставить `loading="eager"` только для главного hero-image на PDP, остальное `lazy`.

Сделано:

- добавлен локальный responsive-image cache на Pillow без новой внешней зависимости: [catalog/image_utils.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/image_utils.py:1);
- добавлены template filters `image_variant_url` и `image_srcset` в [catalog/templatetags/catalog_tags.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/templatetags/catalog_tags.py:1);
- карточки каталога и рекомендации переведены с оригиналов на уменьшенные `src` + `srcset/sizes`;
- PDP теперь сериализует responsive-версии для hero, thumbnails и variant swatches, чтобы Alpine не возвращал страницу к оригиналам;
- bundle detail hero-image тоже переведён на responsive-источники;
- добавлены тесты на генерацию cached variants и наличие `srcset` в PDP.

### 2. Видео на PDP и в контент-блоках

Статус: `done` (2026-05-04)

Файлы:

- [templates/catalog/product_detail.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/product_detail.html:552)
- [templates/catalog/partials/product_description_blocks/video.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/partials/product_description_blocks/video.html:1)
- [templates/catalog/partials/content_blocks/video.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/partials/content_blocks/video.html:1)

Что менять:

- не рендерить тяжёлый `iframe` сразу;
- сначала выводить `poster`/preview и кнопку `play`;
- подставлять `iframe src` только по клику или хотя бы использовать `loading="lazy"`.

Сделано:

- PDP-галерея теперь сначала показывает poster-экран для видео и создаёт `iframe` только после клика по `play`;
- при переключении с видео на другое медиа `iframe` выгружается обратно, чтобы не оставлять лишний embed активным в фоне;
- для контент-блоков добавлен общий lazy-video partial с preview-shell и отложенной установкой `src`;
- на всех embed-видео добавлен `loading="lazy"` как дополнительная страховка;
- добавлены проверки в тестах на lazy video markup для PDP и контент-блоков.

### 3. Убрать глобальный checkout-only JS

Статус: `done` (2026-05-04)

Файлы:

- [templates/layout/_head_assets.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_head_assets.html:21)
- [templates/orders/checkout.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/orders/checkout.html:1)

Что менять:

- убрать глобальное подключение `static/js/orders/checkout_cdek_widget.js`;
- подключать его только на checkout, когда виджет реально включён.

Сделано:

- глобальное подключение `checkout_cdek_widget.js` удалено из [templates/layout/_head_assets.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_head_assets.html:21);
- checkout теперь подключает `checkout_cdek_widget.js` только через `extra_head` и только при `show_cdek_widget` в [templates/orders/checkout.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/orders/checkout.html:6);
- добавлены проверки в [orders/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/orders/tests.py:160), что пустой checkout больше не тянет этот JS глобально, а checkout с активным CDEK-виджетом его рендерит.

### 4. Первый проход по `compact-vr`

Статус: `done` (2026-05-04)

Файлы:

- [templates/compact_vr.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/compact_vr.html:7)
- [static/images/compact-vr-v3](/Users/Yaroslav/Documents/dev/BizonVR/static/images/compact-vr-v3)
- [static/css/compact-vr-v3.css](/Users/Yaroslav/Documents/dev/BizonVR/static/css/compact-vr-v3.css:1)

Что менять:

- всем изображениям добавить `loading="lazy"`, `decoding="async"`, `width/height`;
- первые 1-2 hero assets оставить `eager`, всё остальное `lazy`;
- пережать самые тяжёлые картинки;
- если возможно, заменить `PNG`/`JFIF` на `webp`.

Сделано:

- добавлен кешируемый template tag `static_image_dimension_attrs` в [catalog/templatetags/catalog_tags.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/templatetags/catalog_tags.py:257), чтобы `compact-vr` получал корректные `width/height` из локальной static-стории без ручного хардкода;
- все bitmap-изображения в [templates/compact_vr.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/compact_vr.html:125) получили `width/height`, `loading="lazy"` и `decoding="async"`;
- для страницы не оставлял `eager`-изображения: в текущем `compact-vr` нет above-the-fold bitmap hero, поэтому безопаснее лениво грузить все изображения;
- самые тяжёлые `PNG`/`JFIF` assets переведены в `webp`: `1.png`, `katvrplayer.png`, `Pavlov VR/1.png`, `Bow Bots/1.png`, `Gorilla Tag/1.png`, `Green Hell VR/1.png`, `Arizona Sunshine 2/1.jfif`, `Solo/assassins-creed-nexus-vr.png`;
- добавлен тест рендера `compact-vr` на `webp` и lazy-image markup в [config/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/config/tests.py:295).

### Ожидаемый результат PR 1

- самый заметный выигрыш на `compact-vr`, `catalog`, `product`;
- меньше сетевого веса;
- лучше `LCP` и меньше лагов при скролле.

## PR 2

Цель: убрать лишнюю CPU-нагрузку и глобальные побочные эффекты.

### 1. `Lucide` и глобальный observer

Статус: `done` (2026-05-04)

Файлы:

- [static/js/layout/base.js](/Users/Yaroslav/Documents/dev/BizonVR/static/js/layout/base.js:247)
- [templates/layout/_head_assets.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_head_assets.html:28)

Что менять:

- убрать глобальный `MutationObserver` по всему `document.body`;
- инициализировать иконки только в `swap-target` после `HTMX`;
- по возможности постепенно заменить `data-lucide` на inline `SVG` в самых массовых частях: `header`, `footer`, `catalog cards`.

Сделано:

- удалён глобальный `MutationObserver` из [static/js/layout/base.js](/Users/Yaroslav/Documents/dev/BizonVR/static/js/layout/base.js:1), который раньше слушал весь `document.body` ради новых `data-lucide`-узлов;
- `Lucide` теперь продолжает инициализироваться на первой загрузке страницы и адресно доинициализируется только по `htmx:afterSwap` внутри конкретного `swap-target`, без фонового наблюдателя за всем DOM;
- fallback для `afterSwap` оставлен безопасным: если `HTMX` не передал target, инициализация откатывается к `document`.
- добавлен reusable template tag `{% lucide_icon %}` в [catalog/templatetags/catalog_tags.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/templatetags/catalog_tags.py:1) для server-rendered inline `SVG` с поддержкой обычных и Alpine-атрибутов;
- на inline `SVG` переведены самые частые иконки в [templates/layout/_header_desktop.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_header_desktop.html:1), [templates/layout/_header_mobile.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_header_mobile.html:1), [templates/layout/_footer.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_footer.html:1), [templates/catalog/_product_card.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/_product_card.html:1) и [templates/catalog/_bundle_card.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/_bundle_card.html:1);
- у карточек каталога убран дополнительный `lucide.createIcons()` из image `onerror`, потому что placeholder-иконки больше не требуют клиентской доинициализации.

### 2. `scroll`/`resize` cleanup

Статус: `done` (2026-05-04)

Файлы:

- [templates/base.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/base.html:59)
- [templates/layout/_header_mobile.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_header_mobile.html:3)
- [templates/home.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/home.html:8)
- [templates/catalog/product_detail.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/product_detail.html:25)
- [static/js/compact-vr-v3.js](/Users/Yaroslav/Documents/dev/BizonVR/static/js/compact-vr-v3.js:172)

Что менять:

- сократить число параллельных `scroll`-listeners;
- где можно, перевести логику показа/скрытия на `IntersectionObserver`;
- не пересчитывать `layout` на каждом `scroll`, если достаточно события crossing threshold.

Сделано:

- в [static/js/layout/base.js](/Users/Yaroslav/Documents/dev/BizonVR/static/js/layout/base.js:1) добавлены общие helper’ы `observePageThreshold`, `observeElementViewportState` и `observeElementSize`, чтобы страницы не плодили собственные `scroll`/`resize`-слушатели для простых threshold-сценариев;
- sticky header в [templates/base.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/base.html:32) больше не держит два `scroll.window`-обработчика: показ теперь идёт через shared threshold observer на отметке `180px`;
- мобильный fixed-search в [templates/layout/_header_mobile.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_header_mobile.html:3) и [templates/home.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/home.html:8) переведён со `scroll + requestAnimationFrame` на `observePageThreshold(100, ...)`;
- mobile header на [templates/catalog/product_detail.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/product_detail.html:5) и [templates/catalog/bundle_detail.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/bundle_detail.html:5) больше не слушает `scroll/resize`: заполнение шапки теперь переключается через `IntersectionObserver` относительно `.main-image-wrapper`;
- в [static/js/compact-vr-v3.js](/Users/Yaroslav/Documents/dev/BizonVR/static/js/compact-vr-v3.js:1) убран глобальный `window.scroll` для пересчёта offsets; `compact-vr` теперь реагирует на `layout-scroll-threshold`, resize/mutation/visibility события шапки и дедуплицирует пересчёты через один `requestAnimationFrame`;
- в PDP синхронизация mobile dock offset больше не вешает отдельный глобальный `resize`-listener, а опирается на `ResizeObserver` у самой dock-ноды;
- добавлены регрессионные проверки в [config/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/config/tests.py:295) и [catalog/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/tests.py:602), что новые observer-based хелперы присутствуют в markup/runtime, а старые inline `scroll`-слушатели убраны.

### 3. Убрать дублирование JS каталога

Статус: `done` (2026-05-04)

Файлы:

- [templates/catalog/product_list.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/product_list.html:9)
- [static/js/layout/base.js](/Users/Yaroslav/Documents/dev/BizonVR/static/js/layout/base.js:14)

Что менять:

- оставить одну реализацию `catalogProductList()`;
- `page-specific` script грузить через `defer` или встроить в единый entrypoint;
- исключить повторную инициализацию одинаковой логики.

Сделано:

- убрано отдельное подключение `static/js/catalog/product_list.js` из [templates/catalog/product_list.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/catalog/product_list.html:9), потому что `catalogProductList()` уже живёт в общем entrypoint [static/js/layout/base.js](/Users/Yaroslav/Documents/dev/BizonVR/static/js/layout/base.js:189);
- удалён больше неиспользуемый дублирующий файл `static/js/catalog/product_list.js`, чтобы в репозитории осталась единственная реализация поведения фильтров каталога;
- добавлены регрессионные проверки, что каталог больше не рендерит второй page-specific script и продолжает работать через общий layout runtime.

### 4. Трекеры и аналитика

Статус: `done` (2026-05-04)

Файлы:

- [templates/base.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/base.html:11)
- [templates/manager_portal/base.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/manager_portal/base.html:8)
- [templates/layout/_alfatrack.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_alfatrack.html:22)
- [templates/layout/_yandex_metrika.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_yandex_metrika.html:45)
- [templates/layout/_calltouch.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_calltouch.html:23)

Что менять:

- не тянуть public trackers в `manager portal`;
- `AlfaTrack` грузить как fallback, а не запускать оба mirror сразу;
- проверить, нужен ли `webvisor` на всех страницах, а не только на части funnel.

Сделано:

- из [templates/manager_portal/base.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/manager_portal/base.html:1) убраны публичные tracker partials; дополнительно для manager-контура отключён helper `js/layout/metrika.js`, чтобы служебные страницы не несли лишний публичный tracking runtime;
- [templates/layout/_alfatrack.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_alfatrack.html:1) больше не грузит оба mirror параллельно: сначала пробует основной `cloud.emailtracking.ru`, а второй URL использует только как `onerror` fallback;
- в [templates/layout/_yandex_metrika.html](/Users/Yaroslav/Documents/dev/BizonVR/templates/layout/_yandex_metrika.html:1) `webvisor` оставлен только для продуктовых и маркетинговых страниц воронки (`/`, `catalog`, `orders`, `solutions`, `contacts`, лендинги), а на error-страницах и прочих служебных маршрутах отключается.

### Ожидаемый результат PR 2

- меньше лагов на слабых ПК при скролле и `HTMX`-навигации;
- более предсказуемый `CPU`-профиль;
- меньше фонового шума от сторонних скриптов.

## Рекомендуемый порядок внутри реализации

1. PR 1: `checkout_cdek_widget.js` scope.
2. PR 1: медиа каталога и PDP.
3. PR 1: `compact-vr` изображения.
4. PR 1: lazy video.
5. PR 2: `Lucide` observer.
6. PR 2: `scroll` handlers.
7. PR 2: tracker cleanup.
8. PR 2: dedupe catalog JS.

## Рабочая стратегия

- Первый PR держать максимально безопасным: без изменения бизнес-логики, только `asset loading` и `rendering`.
- Второй PR делать более архитектурным, потому что там выше риск побочных эффектов в `HTMX`/`Alpine`.
