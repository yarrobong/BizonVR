# Аудит фильтров каталога

Актуально для текущего рабочего дерева BizonVR на 2026-04-02.

Важно: этот аудит описывает текущее состояние фильтров в репозитории. В старых заметках и предыдущих версиях документа могли фигурировать отдельные preset-модели, setup wizard, audit dashboard, snapshot-таблицы и связанные команды, но в текущем коде этого слоя уже нет.

## Коротко

Сейчас фильтры каталога работают в трёх слоях:

1. Базовый runtime-фильтр в [catalog/filtering.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/filtering.py)
2. Управляемая конфигурация через `FilterConfig`
3. Операционные helpers через bootstrap-команды и admin-страницы для алиасов и конфигов

Главная идея такая:

- каталог по-прежнему умеет жить без управляемых конфигов;
- при наличии конфигов он использует managed-режим;
- если managed-конфиг формально есть, но не даёт ни одной видимой группы, каталог откатывается в `legacy`;
- raw-данные по-прежнему живут в `ProductCharacteristic`, а поверх них работают definitions, source aliases, value aliases и scope-конфиги.

## Где живёт логика

- Вход в каталог: [catalog/views/products.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/products.py)
- Основной runtime service: [catalog/filtering.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/filtering.py)
- Bootstrap и suggestion-логика: [catalog/filter_bootstrap.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/filter_bootstrap.py)
- Нормализация raw values: [catalog/characteristic_normalization.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/characteristic_normalization.py)
- Работа с source names: [catalog/characteristic_sources.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/characteristic_sources.py)
- Генерация canonical code: [catalog/characteristic_codes.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/characteristic_codes.py)
- Typed sorting значений: [catalog/filter_presets.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/filter_presets.py)
- Admin для definitions, alias helpers и config-ов: [catalog/admin/filters.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/admin/filters.py)
- Admin для category/section bootstrap: [catalog/admin/taxonomy.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/admin/taxonomy.py)
- Модели managed-фильтров: [catalog/models.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/models.py)
- Поведенческие тесты: [catalog/tests.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/tests.py)

## Какие параметры понимает каталог

Runtime каталог сейчас понимает:

- `section`
- `category`
- `tag`
- `price_min`
- `price_max`
- `q`
- `sort`
- `char_*`

`char_*` работает в двух форматах:

- legacy-формат: `char_<raw source_name>`
- canonical-формат: `char_<definition.code>`

Примеры:

- `char_Память=128 GB`
- `char_memory=128 gb`

Если в запросе одновременно есть legacy и canonical ключи для одной и той же definition, приоритет у canonical-параметра по `code`.

Важные ограничения runtime:

- разные характеристики соединяются через `AND`;
- мультивыбора внутри одной характеристики нет;
- фильтрация по характеристикам работает только по `ProductCharacteristic`;
- `ProductVariantCharacteristic` в каталоговых фильтрах не участвует.

## Как каталог определяет scope и режим

Runtime идёт так:

1. [catalog/views/products.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/views/products.py) создаёт `CatalogFilterService`.
2. Сервис определяет:
   - `current_category_slug`
   - `current_section_slug`
   - `selected_category`
   - `selected_section`
   - `effective_section_slug`
3. Потом выбирает filter mode:
   - сначала category-level config;
   - если его нет, section-level config;
   - если и его нет, `legacy`.

Точный приоритет:

1. `FilterConfig` с заполненным `category`
2. `FilterConfig` с заполненным `section`
3. `legacy fallback`

Дополнительная safety net:

- если category/section config есть, но из него не удалось построить ни одной видимой группы, сервис возвращается в `legacy`.

Это важно, потому что managed-конфиг не может “сломать” выдачу только фактом своего существования.

## Реальные сущности и их роль

### `CharacteristicDefinition`

Это центральный справочник фильтруемых характеристик.

Ключевые поля:

- `code` — canonical key для URL и query params;
- `name` — заголовок фильтра в UI;
- `source_name` — основной raw `ProductCharacteristic.name`;
- `sorting_mode` — режим typed sorting для значений;
- `is_filterable`
- `sort_order`
- `is_active`

Как сейчас работает `code`:

- если поле пустое, код генерируется автоматически из `source_name`;
- используется собственная транслитерация + `slugify`;
- при конфликте добавляется suffix: `memory`, `memory-2`, `memory-3`.

### `CharacteristicSourceAlias`

Это слой, который позволяет одной definition покрывать несколько raw source names.

Пример:

- основной `source_name`: `Память`
- source alias: `Объем памяти`
- source alias: `Встроенная память`

После этого runtime считает их одной и той же фильтруемой характеристикой.

Практическое следствие:

- модель больше не ограничена жёстко правилом “одна definition = ровно один raw source name”;
- корректнее говорить так: “одна definition имеет один primary source name и произвольное число активных source aliases”.

### `CharacteristicValueAlias`

Это слой нормализации raw values внутри одной definition.

Основные поля:

- `raw_value`
- `normalized_value`
- `display_value`
- `sort_order`
- `is_active`

Смысл:

- `raw_value` — как значение реально лежит в БД;
- `normalized_value` — каноническое значение для фильтрации;
- `display_value` — как показывать вариант пользователю;
- `sort_order` — ручной приоритет порядка значений.

### `FilterConfig`

Это единая модель managed-конфига для категории или раздела.

Ключевые поля:

- `category` или `section`
- `characteristic_definition`
- `is_visible`
- `is_quick_filter`
- `sort_order`
- `is_expanded_by_default`
- `show_top_n`
- `hide_single_value`

Ограничение модели:

- ровно одно из полей `category` / `section` должно быть заполнено.

## Как сейчас работают `char_*`

Runtime разбирает все GET-параметры в порядке следования.

Дальше происходит такой пайплайн:

1. Все `char_*` собираются в список.
2. Если ключ совпадает с `definition.code`, это canonical hit.
3. Если ключ совпадает с `definition.source_name` или активным `source alias`, это source hit.
4. Если совпадения нет, параметр остаётся raw fallback-фильтром.
5. Для одной definition выигрывает canonical hit.
6. Для source hit и canonical hit selected value дополнительно нормализуется через `CharacteristicValueAlias`.

Что это даёт на практике:

- старые ссылки не ломаются;
- новые ссылки идут через `char_<code>`;
- source aliases тоже поддерживаются в URL;
- при снятии фильтра runtime умеет удалить сразу все относящиеся к definition query keys, а не только один конкретный ключ.

## Из каких данных строятся фильтры

Источник данных по-прежнему один:

- `ProductCharacteristic.name`
- `ProductCharacteristic.value`

Но между raw данными и UI теперь есть несколько слоёв:

1. `CharacteristicDefinition`
2. `CharacteristicSourceAlias`
3. `CharacteristicValueAlias`
4. `FilterConfig`

Typed sorting значений при этом задаётся не отдельной моделью preset-ов, а полем `CharacteristicDefinition.sorting_mode` и утилитой [catalog/filter_presets.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/filter_presets.py).

## Как работает `legacy` режим

Если для текущего scope нет валидного managed-конфига, каталог строит фильтры автоматически:

- берёт `ProductCharacteristic` только по текущей выборке товаров;
- группирует по raw `name`;
- для каждой характеристики строит raw values;
- скрывает характеристики, у которых только одно значение;
- сортирует по алфавиту.

Особенности:

- alias-слой тут не участвует;
- `quick_characteristic_filters` в legacy-режиме просто берутся как первые две группы.

Это безопасный fallback, но он не умеет чистить шум так же хорошо, как managed-режим.

## Как работает managed режим

Если есть category или section config, сервис берёт только разрешённые definitions из config-а.

Для каждой definition runtime делает следующее:

1. Строит scoped queryset товаров с учётом остальных активных фильтров.
2. Для конкретной definition исключает из подсчёта её собственный активный `char_*`, чтобы правильно показать все доступные варианты.
3. Читает `ProductCharacteristic` по всем source names definition:
   - primary `source_name`
   - все активные `source aliases`
4. Каждое raw value прогоняет через alias mapping.
5. Одинаковые `normalized_value` склеивает в один bucket.
6. `count` считает по distinct products после склейки.
7. `display_value` берёт из alias-а, если он задан.
8. Порядок значений строит по:
   - `CharacteristicValueAlias.sort_order`
   - потом typed sort key из `sorting_mode`
   - потом по label.

Группа скрывается, если:

- вариантов нет;
- вариант ровно один и в config стоит `hide_single_value=True`.

Группа получает UI-настройки из config-а:

- `is_quick_filter`
- `is_expanded_by_default`
- `show_top_n`

Также сервис вычисляет:

- `show_as_list`
- `initial_visible_count`
- `has_more_values`
- `all_url` для сброса конкретной группы.

## Нормализация значений сейчас

Текущая автоматическая нормализация довольно консервативна.

Из [catalog/characteristic_normalization.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/characteristic_normalization.py):

- схлопываются лишние пробелы;
- значение lower-case-ится для `normalized_key`;
- нормализуются обозначения `GB/ГБ`;
- нормализуются обозначения `TB/ТБ`;
- извлекается `number + unit` для safe merge key.

Что это реально означает:

- `128 GB`
- `128Gb`
- `128 ГБ`
- `128гб`

могут попасть в одну suggestion group.

Что ещё важно:

- `safe_merge_key` используется для safe auto-apply;
- спорные смысловые синонимы автоматически не склеиваются;
- существующие alias-ы не перетираются автоматически.

## Source alias suggestions

Suggestion-логика умеет подсказывать не только value alias-ы, но и source alias-ы.

Для этого учитываются:

- similarity score по токенам source name;
- overlap нормализованных значений между definition и кандидатом;
- coverage по товарам в scope.

Это закрывает проблему, когда в данных одновременно живут похожие source names:

- `Память`
- `Объем памяти`
- `Встроенная память`

Теперь это можно не плодить в отдельные definitions, а свести в одну definition через `CharacteristicSourceAlias`.

## Typed sorting значений

Старая версия документа описывала только алфавитную сортировку. Сейчас это уже не так.

В managed-режиме порядок вариантов зависит от `CharacteristicDefinition.sorting_mode`.

Поддерживаются как минимум:

- `alpha`
- `numeric_unit`
- `screen_size`
- `boolean`
- `resolution`

Если `sorting_mode` не задан явно, остаётся узкий fallback по содержимому:

- numeric + unit;
- диагональ;
- boolean.

Поэтому значения вроде:

- `64 ГБ`
- `128 ГБ`
- `256 ГБ`

могут сортироваться численно даже без ручного `sort_order`.

## Quick filters

Quick filters сейчас задаются только явно через `FilterConfig.is_quick_filter`.

В `legacy`-режиме быстрыми фильтрами остаются первые две автоматически собранные группы.

## Что автоматизировано сейчас

### 1. Bootstrap definitions

Команда:

```bash
.venv/bin/python manage.py bootstrap_characteristic_definitions
.venv/bin/python manage.py bootstrap_characteristic_definitions --apply
```

Что делает:

- читает distinct `ProductCharacteristic.name`;
- проверяет покрытие не только по `CharacteristicDefinition.source_name`, но и по `CharacteristicSourceAlias`;
- создаёт только отсутствующие definitions;
- не дублирует уже покрытые source names;
- генерирует `code` автоматически.

Поддерживаются фильтры:

```bash
.venv/bin/python manage.py bootstrap_characteristic_definitions --starts-with "Ц"
.venv/bin/python manage.py bootstrap_characteristic_definitions --contains "пам"
.venv/bin/python manage.py bootstrap_characteristic_definitions --source-name "Память" --apply
```

### 2. Suggested value aliases

CLI:

```bash
.venv/bin/python manage.py suggest_characteristic_aliases --definition memory
.venv/bin/python manage.py suggest_characteristic_aliases --definition memory --format json
.venv/bin/python manage.py suggest_characteristic_aliases --definition memory --auto-apply-safe
```

Admin helper:

- открыть `CharacteristicDefinition`;
- перейти в `Предложения алиасов значений`;
- посмотреть grouping;
- применить выбранные группы;
- или нажать safe auto-apply.

Статусы suggestion group:

- `safe_auto_applicable`
- `blocked_by_existing_alias`
- `conflicting_group`
- `manual_review_required`

### 3. Suggested source aliases

Admin helper:

- открыть `CharacteristicDefinition`;
- перейти в `Предложения source aliases`;
- отметить raw source names;
- создать `CharacteristicSourceAlias`.

Это особенно полезно, когда definition уже есть, но каталог продолжает получать похожие raw source names.

### 4. Bootstrap category/section configs

Команда:

```bash
.venv/bin/python manage.py bootstrap_catalog_filter_configs --category vr-shlemy
.venv/bin/python manage.py bootstrap_catalog_filter_configs --category vr-shlemy --apply

.venv/bin/python manage.py bootstrap_catalog_filter_configs --section vr-attraktsiony
.venv/bin/python manage.py bootstrap_catalog_filter_configs --section vr-attraktsiony --apply
```

Что делает:

- ищет definitions, которые реально встречаются в scope;
- учитывает source aliases;
- создаёт только отсутствующие config-ы;
- не перетирает существующие настройки.

Дефолты:

- `sort_order = definition.sort_order`
- `hide_single_value = True`
- `is_quick_filter = False`
- `is_visible = definition.is_filterable and definition.is_active`
- `is_expanded_by_default = False`
- `show_top_n = NULL`

## Что можно делать прямо из admin

Сейчас без консоли доступны такие сценарии:

### У `CharacteristicDefinition`

- открыть предложения alias-ов значений;
- открыть предложения source aliases.

### У `Category`

- action `Автозаполнить фильтры для выбранных категорий`;
- вручную настроить `FilterConfig` через inline.

### У `CatalogSection`

- action `Автозаполнить фильтры для выбранных разделов`;
- вручную настроить `FilterConfig` через inline.

## Что в старой версии аудита уже устарело

Ниже список важных поправок к предыдущему описанию:

### 1. Отдельных `CategoryFilterConfig` и `SectionFilterConfig` больше нет

Сейчас используется единая модель `FilterConfig`, которая привязывается либо к `category`, либо к `section`.

### 2. `CharacteristicPreset` больше нет

Typed sorting остался, но управляется полем `CharacteristicDefinition.sorting_mode` и утилитой [catalog/filter_presets.py](/Users/Yaroslav/Documents/dev/BizonVR/catalog/filter_presets.py), а не отдельной моделью preset-ов.

### 3. Нет snapshot-моделей аудита

В текущем коде отсутствуют `CatalogFilterSourceSnapshot` и `CatalogFilterValueSnapshot`.

### 4. Нет setup wizard

Подготовка фильтров делается через bootstrap-команды, admin actions и helper-страницы алиасов.

### 5. Нет audit dashboard

У `CharacteristicDefinition` сейчас есть helper-страницы для alias suggestions и source alias suggestions, но отдельного dashboard-а в коде нет.

### 6. Удалены связанные команды

В текущем репозитории нет команд:

- `bootstrap_characteristic_presets`
- `sync_catalog_filter_audit`

## Реальные ограничения текущей реализации

Несмотря на сильный прогресс, ограничения всё ещё есть.

### 1. Мультивыбор внутри одной характеристики не сделан

Сейчас всё ещё single-select per definition.

### 2. Runtime-фильтрация идёт только по `ProductCharacteristic`

`ProductVariantCharacteristic` не участвует.

### 3. Нормализация остаётся консервативной

Автоматика хорошо справляется с:

- пробелами;
- регистром;
- `GB/ГБ`;
- `TB/ТБ`;
- некоторыми типовыми numeric/unit сценариями.

Но она не решает за бизнес:

- смысловые синонимы;
- спорные merge-группы;
- конфликтные обозначения;
- маркетинговые варианты одного и того же значения.

### 4. Quick filters не становятся автоматическими

Их нужно явно выставлять в `FilterConfig`, если нужен управляемый набор быстрых фильтров.

### 5. Managed mode всё ещё зависит от качества config-а

Да, safety net есть, но плохая структура definitions / aliases / configs всё равно даст шумный или слабый UI.

### 6. Runtime-источник истины всё ещё raw catalog data

Definitions и aliases не создают отдельное materialized представление. Они только интерпретируют текущий `ProductCharacteristic`.

## Рекомендуемый рабочий сценарий сейчас

Самый прагматичный flow на текущем этапе:

1. Выполнить миграции.
2. Выполнить bootstrap definitions:
   ```bash
   .venv/bin/python manage.py bootstrap_characteristic_definitions --apply
   ```
3. Для приоритетной category или section создать missing configs:
   ```bash
   .venv/bin/python manage.py bootstrap_catalog_filter_configs --category <slug> --apply
   ```
4. В admin у нужных definitions проверить:
   - value alias suggestions
   - source alias suggestions
5. Вручную проверить:
   - `name`
   - `code`
   - `source_name`
   - `sorting_mode`
   - `sort_order`
   - `is_quick_filter`
   - `is_visible`
6. Проверить каталог в браузере.

## Что рекомендую не делать

- Не переводить весь каталог в managed mode одним массовым движением без выборочной проверки по category.
- Не auto-apply-ить спорные alias groups без review.
- Не плодить новые definitions для каждого похожего raw source name, если их можно покрыть `CharacteristicSourceAlias`.

## Итог

На текущий момент система фильтров уже не просто “полуавтоматическая”:

- `legacy fallback` сохранён;
- managed runtime работает через definitions, source aliases, value aliases и scope config-ы;
- старые ссылки `char_<raw source_name>` продолжают работать;
- новые canonical-ссылки идут через `char_<code>`;
- value normalization и safe auto-apply уже работают;
- source aliases уже поддерживаются;
- typed sorting уже работает;
- подготовка managed-фильтров делается через bootstrap-команды и admin helpers.

Главное, что пока остаётся ручным, это бизнесовые решения:

- что действительно склеивать;
- что делать quick filter;
- что скрывать;
- в каком порядке показывать;
- где managed mode уже готов, а где лучше остаться на fallback.
