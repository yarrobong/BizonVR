from decimal import Decimal
from itertools import count

from catalog.models import CatalogSection, Category, GamePack, Product, ProductContentBlock


_section_counter = count(1)
_category_counter = count(1)
_product_counter = count(1)
_content_block_counter = count(1)
_game_pack_counter = count(1)


def _create_section(**overrides):
    index = next(_section_counter)
    defaults = {
        'name': f'Test section {index}',
        'slug': f'test-section-{index}',
    }
    defaults.update(overrides)
    return CatalogSection.objects.create(**defaults)


def create_category(**overrides):
    index = next(_category_counter)
    defaults = {
        'name': f'Test category {index}',
        'slug': f'test-category-{index}',
    }
    if overrides.get('with_section'):
        overrides = {key: value for key, value in overrides.items() if key != 'with_section'}
        defaults['section'] = _create_section()
    defaults.update(overrides)
    return Category.objects.create(**defaults)


def create_product(**overrides):
    index = next(_product_counter)
    defaults = {
        'category': create_category(),
        'name': f'Test product {index}',
        'slug': f'test-product-{index}',
        'price': Decimal('100.00'),
        'is_active': True,
    }
    defaults.update(overrides)
    return Product.objects.create(**defaults)


def create_content_block(**overrides):
    index = next(_content_block_counter)
    defaults = {
        'product': create_product(),
        'block_type': ProductContentBlock.BlockType.TEXT,
        'title': f'Block {index}',
        'text': f'Block text {index}',
        'sort_order': index,
        'is_active': True,
    }
    defaults.update(overrides)
    return ProductContentBlock.objects.create(**defaults)


def create_game_pack(**overrides):
    index = next(_game_pack_counter)
    defaults = {
        'category': create_category(),
        'name': f'Test game pack {index}',
        'slug': f'test-game-pack-{index}',
        'price': Decimal('5000.00'),
        'is_active': True,
    }
    defaults.update(overrides)
    return GamePack.objects.create(**defaults)
