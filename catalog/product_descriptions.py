import copy
import json
import logging

from django.template.loader import render_to_string
from django.utils import timezone

from .models import (
    DescriptionBlockType,
    DescriptionTemplate,
    ProductContentBlock,
    ProductDescription,
    ProductDescriptionAsset,
    ProductDescriptionBlock,
)

logger = logging.getLogger(__name__)


BLOCK_RENDERERS = {
    'hero_summary': 'catalog/partials/product_description_blocks/hero_summary.html',
    'text': 'catalog/partials/product_description_blocks/text.html',
    'image_text': 'catalog/partials/product_description_blocks/image_text.html',
    'full_image': 'catalog/partials/product_description_blocks/full_image.html',
    'feature_grid': 'catalog/partials/product_description_blocks/feature_grid.html',
    'spec_highlights': 'catalog/partials/product_description_blocks/spec_highlights.html',
    'use_cases': 'catalog/partials/product_description_blocks/use_cases.html',
    'whats_in_box': 'catalog/partials/product_description_blocks/whats_in_box.html',
    'comparison': 'catalog/partials/product_description_blocks/comparison.html',
    'video': 'catalog/partials/product_description_blocks/video.html',
    'cta_note': 'catalog/partials/product_description_blocks/cta_note.html',
}


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _text(value):
    return str(value or '').strip()


def _asset_url(asset):
    if not asset or not getattr(asset, 'image', None):
        return ''
    try:
        return asset.image.url
    except (ValueError, OSError):
        return ''


def _asset_dimensions(asset):
    if not asset or not getattr(asset, 'image', None):
        return None, None
    try:
        width = int(getattr(asset.image, 'width', 0) or 0)
        height = int(getattr(asset.image, 'height', 0) or 0)
    except (ValueError, OSError, FileNotFoundError):
        return None, None
    if width <= 0 or height <= 0:
        return None, None
    return width, height


def _asset_map(block):
    related_assets = getattr(block, 'assets', [])
    assets = list(related_assets.all() if hasattr(related_assets, 'all') else related_assets)
    return {asset.pk: asset for asset in assets if getattr(asset, 'pk', None)}


def _resolve_image(data, block=None):
    data = _as_dict(data)
    asset = None
    if block is not None:
        assets = _asset_map(block)
        asset_id = data.get('asset_id') or data.get('image_asset_id')
        if asset_id:
            try:
                asset = assets.get(int(asset_id))
            except (TypeError, ValueError):
                asset = None
        if asset is None:
            asset = next(iter(assets.values()), None)
    width, height = _asset_dimensions(asset)
    return {
        'url': _asset_url(asset) or _text(data.get('image_url')),
        'alt': _text(data.get('alt')) or _text(getattr(asset, 'alt', '')),
        'caption': _text(data.get('caption')) or _text(getattr(asset, 'caption', '')),
        'width': width,
        'height': height,
    }


def normalize_block_data(block_type_slug, data):
    """Return a compact, template-friendly representation for a block payload."""
    data = copy.deepcopy(_as_dict(data))
    if block_type_slug == 'hero_summary':
        return {
            'title': _text(data.get('title')),
            'lead': _text(data.get('lead')),
            'bullets': [_text(item) for item in _as_list(data.get('bullets')) if _text(item)][:5],
            'asset_id': data.get('asset_id') or data.get('image_asset_id'),
            'image_url': _text(data.get('image_url')),
            'alt': _text(data.get('alt')),
        }
    if block_type_slug in {'text', 'cta_note'}:
        return {
            'title': _text(data.get('title')),
            'text': _text(data.get('text')),
            'tone': _text(data.get('tone')) or 'neutral',
        }
    if block_type_slug == 'image_text':
        return {
            'title': _text(data.get('title')),
            'text': _text(data.get('text')),
            'image_position': 'right' if data.get('image_position') == 'right' else 'left',
            'asset_id': data.get('asset_id') or data.get('image_asset_id'),
            'image_url': _text(data.get('image_url')),
            'alt': _text(data.get('alt')),
            'caption': _text(data.get('caption')),
        }
    if block_type_slug == 'full_image':
        return {
            'title': _text(data.get('title')),
            'asset_id': data.get('asset_id') or data.get('image_asset_id'),
            'image_url': _text(data.get('image_url')),
            'alt': _text(data.get('alt')),
            'caption': _text(data.get('caption')),
        }
    if block_type_slug in {'feature_grid', 'use_cases'}:
        items = []
        for item in _as_list(data.get('items'))[:8]:
            item = _as_dict(item)
            title = _text(item.get('title'))
            text = _text(item.get('text'))
            if title or text:
                items.append({'icon': _text(item.get('icon')) or 'check', 'title': title, 'text': text})
        return {'title': _text(data.get('title')), 'items': items}
    if block_type_slug == 'spec_highlights':
        items = []
        for item in _as_list(data.get('items'))[:12]:
            item = _as_dict(item)
            label = _text(item.get('label') or item.get('name'))
            value = _text(item.get('value'))
            if label or value:
                items.append({'label': label, 'value': value})
        return {'title': _text(data.get('title')), 'items': items}
    if block_type_slug == 'whats_in_box':
        return {
            'title': _text(data.get('title')) or 'Комплектация',
            'items': [_text(item) for item in _as_list(data.get('items')) if _text(item)][:20],
        }
    if block_type_slug == 'comparison':
        columns = [_text(item) for item in _as_list(data.get('columns')) if _text(item)][:5]
        rows = []
        for row in _as_list(data.get('rows'))[:12]:
            row = _as_dict(row)
            label = _text(row.get('label'))
            values = [_text(item) for item in _as_list(row.get('values'))[:len(columns)]]
            if label or values:
                rows.append({'label': label, 'values': values})
        return {'title': _text(data.get('title')), 'columns': columns, 'rows': rows}
    if block_type_slug == 'video':
        return {
            'title': _text(data.get('title')),
            'rutube_url': _text(data.get('rutube_url')),
            'embed_url': _text(data.get('embed_url')),
            'caption': _text(data.get('caption')),
        }
    return data


def block_has_content(block_type_slug, data, image=None):
    if block_type_slug in {'hero_summary', 'image_text', 'full_image'} and image and image.get('url'):
        return True
    if block_type_slug in {'feature_grid', 'use_cases', 'spec_highlights'}:
        return bool(data.get('title') or data.get('items'))
    if block_type_slug == 'whats_in_box':
        return bool(data.get('items'))
    if block_type_slug == 'comparison':
        return bool(data.get('columns') and data.get('rows'))
    if block_type_slug == 'video':
        return bool(data.get('embed_url') or data.get('rutube_url'))
    return bool(data.get('title') or data.get('text') or data.get('lead') or data.get('bullets'))


def build_render_block(block):
    slug = block.block_type.slug
    template_name = BLOCK_RENDERERS.get(slug)
    if not template_name:
        logger.warning('Unknown product description block type: %s', slug)
        return None

    data = normalize_block_data(slug, block.data)
    image = _resolve_image(data, block)
    if not block_has_content(slug, data, image=image):
        return None
    return {
        'id': block.pk,
        'slot_key': block.slot_key,
        'type': slug,
        'template_name': template_name,
        'data': data,
        'image': image,
    }


def render_product_description_context(description):
    if not description:
        return None
    blocks = []
    for block in description.blocks.all():
        if not block.is_active or not block.block_type.is_active:
            continue
        render_block = build_render_block(block)
        if render_block:
            blocks.append(render_block)
    return {
        'description': description,
        'title': description.title,
        'intro': description.intro,
        'blocks': blocks,
        'has_content': bool(description.title or description.intro or blocks),
    }


def get_product_description(product):
    description = getattr(product, 'product_description', None)
    if (
        description
        and description.is_active
        and description.status == ProductDescription.Status.PUBLISHED
    ):
        context = render_product_description_context(description)
        if context and context['has_content']:
            return context
    return None


def resolve_product_description(product):
    new_description = get_product_description(product)
    legacy_blocks = list(getattr(product, 'active_content_blocks', []))
    return {
        'new': new_description,
        'legacy_blocks': legacy_blocks,
        'source': 'new' if new_description else ('legacy' if legacy_blocks else None),
    }


def build_payload_render_context(payload, product=None):
    blocks = []
    for index, raw_block in enumerate(_as_list(_as_dict(payload).get('blocks'))):
        raw_block = _as_dict(raw_block)
        slug = _text(raw_block.get('block_type') or raw_block.get('type'))
        template_name = BLOCK_RENDERERS.get(slug)
        if not template_name:
            continue
        data = normalize_block_data(slug, raw_block.get('data'))
        image = _resolve_image(data)
        if not block_has_content(slug, data, image=image):
            continue
        blocks.append({
            'id': raw_block.get('id') or index,
            'slot_key': _text(raw_block.get('slot_key')) or f'block-{index}',
            'type': slug,
            'template_name': template_name,
            'data': data,
            'image': image,
        })
    return {
        'description': None,
        'title': _text(_as_dict(payload).get('title')),
        'intro': _text(_as_dict(payload).get('intro')),
        'blocks': blocks,
        'has_content': bool(blocks or _text(_as_dict(payload).get('title')) or _text(_as_dict(payload).get('intro'))),
        'product': product,
    }


def render_description_preview(payload, product=None):
    return render_to_string(
        'catalog/partials/product_description.html',
        {'product': product, 'description_view': build_payload_render_context(payload, product=product)},
    )


def serialize_template(template):
    return serialize_template_with_start_payload(template)


def _base_constructor_payload(*, template=None, title='', intro='', status=None, is_active=False, source=None, blocks=None):
    return {
        'id': None,
        'template_id': getattr(template, 'pk', None),
        'title': title or '',
        'intro': intro or '',
        'status': status or ProductDescription.Status.DRAFT,
        'is_active': bool(is_active),
        'source': source or (ProductDescription.Source.TEMPLATE if template else ProductDescription.Source.CUSTOM),
        'blocks': blocks or [],
    }


def empty_constructor_payload():
    return _base_constructor_payload()


def serialize_template_with_start_payload(template, product=None):
    preview_image_url = ''
    if template.preview_image:
        try:
            preview_image_url = template.preview_image.url
        except (ValueError, OSError):
            preview_image_url = ''
    return {
        'id': template.pk,
        'name': template.name,
        'slug': template.slug,
        'description': template.description,
        'category': template.category,
        'preview_image_url': preview_image_url,
        'preview_data': template.preview_data or {},
        'version': template.version,
        'slots': [
            {
                'slot_key': slot.slot_key,
                'block_type': slot.block_type.slug,
                'block_type_name': slot.block_type.name,
                'label': slot.label,
                'help_text': slot.help_text,
                'sort_order': slot.sort_order,
                'is_required': slot.is_required,
                'default_data': slot.default_data or slot.block_type.default_data or {},
                'settings': slot.settings or {},
            }
            for slot in template.slots.select_related('block_type').order_by('sort_order', 'id')
        ],
        'start_payload': template_to_constructor_payload(template, product=product),
    }


def serialize_block_type(block_type):
    return {
        'id': block_type.pk,
        'slug': block_type.slug,
        'name': block_type.name,
        'description': block_type.description,
        'category': block_type.category,
        'icon': block_type.icon,
        'schema': block_type.schema or {},
        'default_data': block_type.default_data or {},
        'preview_data': block_type.preview_data or {},
        'sort_order': block_type.sort_order,
    }


def serialize_product_description(description):
    if not description:
        return empty_constructor_payload()
    return {
        'id': description.pk,
        'template_id': description.template_id,
        'title': description.title or '',
        'intro': description.intro or '',
        'status': description.status,
        'is_active': description.is_active,
        'source': description.source,
        'blocks': [
            {
                'id': block.pk,
                'client_id': f'block-{block.pk}',
                'slot_key': block.slot_key,
                'block_type': block.block_type.slug,
                'block_type_name': block.block_type.name,
                'sort_order': block.sort_order,
                'is_active': block.is_active,
                'data': block.data or {},
                'deleted': False,
            }
            for block in description.blocks.select_related('block_type').order_by('sort_order', 'id')
        ],
    }


def template_to_constructor_payload(template, product=None):
    return _base_constructor_payload(
        template=template,
        title=template.name,
        intro=getattr(product, 'description', '') or template.description or '',
        source=ProductDescription.Source.TEMPLATE,
        blocks=[
            {
                'id': None,
                'client_id': f'template-{template.pk}-{slot.slot_key}',
                'slot_key': slot.slot_key,
                'block_type': slot.block_type.slug,
                'block_type_name': slot.block_type.name,
                'sort_order': slot.sort_order,
                'is_active': True,
                'data': copy.deepcopy(slot.default_data or slot.block_type.default_data or {}),
                'deleted': False,
            }
            for slot in template.slots.select_related('block_type').order_by('sort_order', 'id')
        ],
    )


def _serialize_legacy_block(block):
    return {
        'id': block.pk,
        'block_type': block.block_type,
        'title': block.title or '',
        'text': block.text or '',
        'image_position': block.image_position or 'left',
        'caption': block.caption or '',
        'rutube_url': block.rutube_url or '',
        'sort_order': block.sort_order,
        'is_active': block.is_active,
    }


def build_admin_constructor_state(product=None):
    templates = [
        serialize_template_with_start_payload(template, product=product)
        for template in DescriptionTemplate.objects.filter(is_active=True).prefetch_related('slots__block_type').order_by('category', 'name')
    ]
    block_types = [
        serialize_block_type(block_type)
        for block_type in DescriptionBlockType.objects.filter(is_active=True).order_by('sort_order', 'name')
    ]
    description = None
    legacy_blocks = []
    if product and getattr(product, 'pk', None):
        description = getattr(product, 'product_description', None)
        legacy_blocks = [
            _serialize_legacy_block(block)
            for block in product.content_blocks.order_by('sort_order', 'id')
        ]
    return {
        'templates': templates,
        'blockTypes': block_types,
        'emptyDescription': empty_constructor_payload(),
        'description': serialize_product_description(description),
        'legacyBlocks': legacy_blocks,
    }


def parse_constructor_payload(raw_payload):
    if isinstance(raw_payload, dict):
        return raw_payload
    raw_payload = (raw_payload or '').strip()
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if 'description' in payload and 'blocks' not in payload and isinstance(payload.get('description'), dict):
        return payload['description']
    return payload


def _unique_slot_key(base_key, used_keys):
    base_key = _text(base_key).replace('_', '-').lower() or 'block'
    cleaned = ''.join(ch for ch in base_key if ch.isalnum() or ch == '-').strip('-') or 'block'
    candidate = cleaned[:80]
    counter = 2
    while candidate in used_keys:
        suffix = f'-{counter}'
        candidate = f'{cleaned[:80 - len(suffix)]}{suffix}'
        counter += 1
    used_keys.add(candidate)
    return candidate


def save_product_description_from_payload(product, payload, user=None):
    payload = parse_constructor_payload(payload)
    if not payload:
        return None

    blocks_payload = _as_list(payload.get('blocks'))
    has_non_deleted_blocks = any(not _as_dict(block).get('deleted') for block in blocks_payload)
    has_description_content = bool(
        _text(payload.get('title'))
        or _text(payload.get('intro'))
        or has_non_deleted_blocks
        or payload.get('template_id')
    )
    existing = getattr(product, 'product_description', None)
    if not has_description_content and not existing:
        return None

    template = None
    template_id = payload.get('template_id')
    if template_id:
        try:
            template = DescriptionTemplate.objects.get(pk=template_id)
        except (DescriptionTemplate.DoesNotExist, TypeError, ValueError):
            template = None

    previous_status = existing.status if existing else None
    description, _ = ProductDescription.objects.update_or_create(
        product=product,
        defaults={
            'template': template,
            'title': _text(payload.get('title')),
            'intro': _text(payload.get('intro')),
            'status': payload.get('status') if payload.get('status') in ProductDescription.Status.values else ProductDescription.Status.DRAFT,
            'is_active': bool(payload.get('is_active')),
            'source': payload.get('source') if payload.get('source') in ProductDescription.Source.values else ProductDescription.Source.CUSTOM,
        },
    )
    if description.status == ProductDescription.Status.PUBLISHED and previous_status != ProductDescription.Status.PUBLISHED:
        description.published_at = timezone.now()
        description.save(update_fields=['published_at'])
    elif description.status != ProductDescription.Status.PUBLISHED and description.published_at:
        description.published_at = None
        description.save(update_fields=['published_at'])

    existing_blocks = {block.pk: block for block in description.blocks.select_related('block_type')}
    block_types = {block_type.slug: block_type for block_type in DescriptionBlockType.objects.filter(is_active=True)}
    used_slot_keys = set()
    kept_ids = set()

    for index, raw_block in enumerate(blocks_payload):
        raw_block = _as_dict(raw_block)
        block_id = raw_block.get('id')
        try:
            block_id = int(block_id) if block_id else None
        except (TypeError, ValueError):
            block_id = None

        if raw_block.get('deleted'):
            if block_id and block_id in existing_blocks:
                existing_blocks[block_id].delete()
            continue

        block_type_slug = _text(raw_block.get('block_type'))
        block_type = block_types.get(block_type_slug)
        if not block_type:
            continue

        slot_key = _unique_slot_key(raw_block.get('slot_key') or f'{block_type_slug}-{index + 1}', used_slot_keys)
        sort_order = raw_block.get('sort_order')
        try:
            sort_order = int(sort_order)
        except (TypeError, ValueError):
            sort_order = (index + 1) * 10

        block_data = _as_dict(raw_block.get('data'))
        if block_id and block_id in existing_blocks:
            block = existing_blocks[block_id]
            block.slot_key = slot_key
            block.block_type = block_type
            block.sort_order = sort_order
            block.is_active = bool(raw_block.get('is_active', True))
            block.data = block_data
            block.save()
        else:
            block = ProductDescriptionBlock.objects.create(
                description=description,
                slot_key=slot_key,
                block_type=block_type,
                sort_order=sort_order,
                is_active=bool(raw_block.get('is_active', True)),
                data=block_data,
            )
        kept_ids.add(block.pk)

    description.blocks.exclude(pk__in=kept_ids).delete()
    return description


def apply_template_to_product(product, template, *, activate=False):
    description, _ = ProductDescription.objects.update_or_create(
        product=product,
        defaults={
            'template': template,
            'title': template.name,
            'intro': product.description or '',
            'status': ProductDescription.Status.PUBLISHED if activate else ProductDescription.Status.DRAFT,
            'is_active': activate,
            'source': ProductDescription.Source.TEMPLATE,
            'published_at': None,
        },
    )
    description.blocks.all().delete()
    block_type_by_slug = {
        block_type.slug: block_type
        for block_type in DescriptionBlockType.objects.filter(is_active=True)
    }
    for slot in template.slots.select_related('block_type').order_by('sort_order', 'id'):
        block_type = block_type_by_slug.get(slot.block_type.slug)
        if not block_type:
            continue
        ProductDescriptionBlock.objects.create(
            description=description,
            slot_key=slot.slot_key,
            block_type=block_type,
            sort_order=slot.sort_order,
            is_active=True,
            data=copy.deepcopy(slot.default_data or slot.block_type.default_data or {}),
        )
    return description


def migrate_legacy_blocks(product, *, activate=False):
    description, created = ProductDescription.objects.get_or_create(
        product=product,
        defaults={
            'title': 'Подробное описание',
            'intro': product.description or '',
            'status': ProductDescription.Status.PUBLISHED,
            'is_active': activate,
            'source': ProductDescription.Source.LEGACY,
        },
    )
    if not created:
        return description, False

    block_types = {
        block_type.slug: block_type
        for block_type in DescriptionBlockType.objects.filter(slug__in=['text', 'image_text', 'full_image', 'video'])
    }
    legacy_blocks = ProductContentBlock.objects.filter(product=product).order_by('sort_order', 'id')
    for index, legacy in enumerate(legacy_blocks):
        block_type = block_types.get(legacy.block_type)
        if not block_type:
            continue
        data = {
            'title': legacy.title or '',
            'text': legacy.text or '',
            'image_position': legacy.image_position or 'left',
            'caption': legacy.caption or '',
            'rutube_url': legacy.rutube_url or '',
            'embed_url': legacy.embed_url or '',
        }
        block = ProductDescriptionBlock.objects.create(
            description=description,
            slot_key=f'legacy-{index + 1}',
            block_type=block_type,
            sort_order=legacy.sort_order,
            is_active=legacy.is_active,
            data=data,
        )
        if legacy.image:
            ProductDescriptionAsset.objects.create(
                description=description,
                block=block,
                image=legacy.image.name,
                alt=legacy.title or product.name,
                caption=legacy.caption or '',
                role='legacy',
            )
    return description, True
