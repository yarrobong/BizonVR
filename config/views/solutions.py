from django.urls import reverse

from ..solution_landings import get_solution_landings


def build_solution_hub_cards():
    cards = []
    for landing in get_solution_landings(include_in_hub=True):
        preview_url = ''
        if landing.preview_image:
            preview_url = reverse(
                'solution_landing_asset',
                kwargs={'slug': landing.slug, 'path': landing.preview_image},
            )
        cards.append({
            'slug': landing.slug,
            'title': landing.title,
            'description': landing.description,
            'url': reverse('solution_landing', kwargs={'slug': landing.slug}),
            'preview_url': preview_url,
        })
    return cards
