# Управление играми и игровыми паками

## Игры для VR-клубов

1. Создайте или откройте товар-игру в админ-панели.
2. Добавьте запись `B2B-метаданные игры`.
3. Заполните совместимость, жанры, минимальное и максимальное количество игроков, возраст, сценарий, PCVR/Standalone/Multiplayer и короткий B2B-комментарий.
4. Включите `Показывать в конструкторе` и задайте `Порядок`.

Игры с активными B2B-метаданными появляются на `/catalog/vr-club-games/` и участвуют в фильтрах.

## Игровые паки

В админ-панели `Игровые паки` настраиваются:

- название, slug и описание;
- изображение;
- цена, скидка и цена под заказ;
- категория каталога;
- формат пака: для клуба, дома, арены, детей или вечеринки;
- тариф для VR-клубов;
- совместимость со шлемами через поле `Устройства`;
- жанры, возраст, количество игроков и игровых мест;
- коммерческий тезис и краткое описание состава;
- состав игр через inline `Позиции игрового пака`;
- включённые услуги через inline `Услуги игрового пака`;
- порядок сортировки;
- активность и показ в разделе VR-клубов.

Чтобы пак появился в блоке VR club games, включите `Активен` и `Показывать в разделе VR-клубов`.

## Корзина и заявки

Готовый GamePack добавляется в корзину как одна цифровая позиция с сохранённым снимком состава. В конструкторе пользователь может выбрать игры и услуги, после чего в корзину добавляется индивидуальный игровой комплект и выбранные услуги.

## Admin checklist

Use this checklist when a game pack must appear correctly on the public site:

1. Create or update the game products first.
2. For every VR-club game product, add `ProductGameMetadata`, set compatibility, genres, player counts, age rating, club format, PCVR/Standalone/Multiplayer flags, `is_active`, and `sort_order`.
3. Create the `GamePack` with category, name, slug, description, image, price/request-price mode, active state, and sort order.
4. Fill `package_format`, `vr_club_tariff`, devices, genres, players count, play places count, commercial pitch, and included summary.
5. Add game rows through `GamePackEntryInline`; use `product` when the game exists in catalog and `unresolved_title` only as a temporary placeholder.
6. Add included services through `GamePackServiceEntryInline` if the pack contains setup, support, installation, or other service items.
7. Enable `show_on_vr_club_page` only for packs that should be visible in the VR club games section.
8. Open `/catalog/vr-club-games/`, verify cards, filters, pack composition, prices/request state, cart action, and lead form behavior.

Do not hardcode pack content in templates if the same data can be maintained through Django admin.
