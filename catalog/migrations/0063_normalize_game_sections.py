from django.db import migrations


LEGACY_SECTION_SLUG = 'vr-games-and-packs'
DIGITAL_SECTION_SLUG = 'cifrovye-tovary'
DIGITAL_SECTION_NAME = 'Цифровые товары'
BUSINESS_SECTION_SLUG = 'resheniya-dlya-vr-biznesa'

GAME_CATEGORY_SLUGS = ('mr-vr-games', 'vr-games')
PACK_CATEGORY_SLUGS = ('vr-zone-packs', 'game-packs')
CANONICAL_CATEGORY_NAMES = {
    'mr-vr-games': 'MR / VR Игры',
    'vr-zone-packs': 'Паки для VR-зон',
}


def normalize_game_sections(apps, schema_editor):
    CatalogSection = apps.get_model('catalog', 'CatalogSection')
    Category = apps.get_model('catalog', 'Category')

    has_relevant_structure = (
        CatalogSection.objects.filter(slug=LEGACY_SECTION_SLUG).exists()
        or Category.objects.filter(slug__in=GAME_CATEGORY_SLUGS + PACK_CATEGORY_SLUGS).exists()
    )
    business_section = CatalogSection.objects.filter(slug=BUSINESS_SECTION_SLUG).first()
    if business_section is None:
        if not has_relevant_structure:
            return
        raise RuntimeError("Required catalog section 'resheniya-dlya-vr-biznesa' was not found.")

    legacy_section = CatalogSection.objects.filter(slug=LEGACY_SECTION_SLUG).first()
    digital_section = CatalogSection.objects.filter(slug=DIGITAL_SECTION_SLUG).first()

    if legacy_section is not None and digital_section is None:
        legacy_section.slug = DIGITAL_SECTION_SLUG
        legacy_section.name = DIGITAL_SECTION_NAME
        legacy_section.save(update_fields=['slug', 'name'])
        digital_section = legacy_section
    elif digital_section is not None and digital_section.name != DIGITAL_SECTION_NAME:
        digital_section.name = DIGITAL_SECTION_NAME
        digital_section.save(update_fields=['name'])

    if digital_section is None:
        return

    Category.objects.filter(slug__in=GAME_CATEGORY_SLUGS).exclude(section=digital_section).update(section=digital_section)
    Category.objects.filter(slug__in=PACK_CATEGORY_SLUGS).exclude(section=business_section).update(section=business_section)

    for slug, canonical_name in CANONICAL_CATEGORY_NAMES.items():
        Category.objects.filter(slug=slug).exclude(name=canonical_name).update(name=canonical_name)

    legacy_section = CatalogSection.objects.filter(slug=LEGACY_SECTION_SLUG).first()
    if legacy_section is not None and not Category.objects.filter(section=legacy_section).exists():
        legacy_section.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0062_gamepack_mirror_product_and_platforms'),
    ]

    operations = [
        migrations.RunPython(normalize_game_sections, migrations.RunPython.noop),
    ]
