from __future__ import annotations

from .models import GamePack, GamePackItem, Product, ProductCharacteristic


_UNSET = object()


def build_game_pack_mirror_items(game_pack: GamePack) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []

    for entry in game_pack.entries.select_related('product').order_by('sort_order', 'id'):
        items.append({
            'title': entry.product.name if entry.product_id else (entry.unresolved_title or 'Unresolved entry'),
            'platform': entry.platform,
            'note': entry.note,
        })

    for entry in game_pack.service_entries.select_related('service').order_by('sort_order', 'id'):
        items.append({
            'title': entry.display_title,
            'platform': entry.platform,
            'note': entry.note,
        })

    return items


def sync_game_pack_mirror(
    game_pack: GamePack,
    *,
    sku: str | None = None,
    allow_create: bool = False,
    mirror_image_name: str | None | object = _UNSET,
    product_characteristics: dict[str, str] | None = None,
) -> Product | None:
    product = game_pack.mirror_product

    if product is None and sku:
        product = Product.objects.filter(sku=sku).order_by('pk').first()

    if product is None and not allow_create:
        return None

    if product is None:
        product = Product()

    product.category = game_pack.category
    product.name = game_pack.name
    product.description = game_pack.description
    product.product_kind = Product.PRODUCT_KIND_GAME_PACK
    product.price = game_pack.price
    product.discount_percent = game_pack.discount_percent
    product.price_on_request = game_pack.price_on_request
    product.is_active = game_pack.is_active
    product.allow_order_on_request = game_pack.allow_order_on_request
    product.avito_url = ''
    product.ozon_url = ''
    product.wildberries_url = ''
    product.option_label = ''
    if sku is not None:
        product.sku = sku
    if mirror_image_name is not _UNSET:
        product.image = mirror_image_name or ''
    product.save()

    if game_pack.mirror_product_id != product.pk:
        GamePack.objects.filter(pk=game_pack.pk).update(mirror_product=product)
        game_pack.mirror_product = product

    product.tags.set(game_pack.tags.all())

    if product_characteristics is not None:
        product.characteristics.all().delete()
        ProductCharacteristic.objects.bulk_create(
            [
                ProductCharacteristic(product=product, name=name, value=value)
                for name, value in product_characteristics.items()
            ]
        )

    mirror_items = build_game_pack_mirror_items(game_pack)
    GamePackItem.objects.filter(product=product).delete()
    GamePackItem.objects.bulk_create(
        [
            GamePackItem(
                product=product,
                title=item['title'],
                platform=item.get('platform', ''),
                note=item.get('note', ''),
                sort_order=index,
            )
            for index, item in enumerate(mirror_items, start=1)
        ]
    )

    return product
