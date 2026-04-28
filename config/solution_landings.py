from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True, slots=True)
class SolutionLanding:
    """Source of truth for standalone SEO landings under /solutions/."""

    slug: str
    directory: str
    title: str
    description: str
    is_published: bool
    include_in_hub: bool = True
    include_in_sitemap: bool = True
    preview_image: str = ''
    order: int = 0

    @property
    def root_dir(self) -> Path:
        return settings.BASE_DIR / 'solutions' / self.directory


SOLUTION_LANDINGS: tuple[SolutionLanding, ...] = (
    SolutionLanding(
        slug='vr-dlya-kluba',
        directory='vr-dlya-kluba',
        title='VR для клуба',
        description='Подбор VR-шлемов, аксессуаров и игрового контента для клубов, арен и коммерческих VR-зон.',
        is_published=True,
        preview_image='img/pico-4-ultra.webp',
        order=10,
    ),
)


def get_solution_landing(slug: str, *, include_unpublished: bool = False) -> SolutionLanding | None:
    for landing in SOLUTION_LANDINGS:
        if landing.slug != slug:
            continue
        if landing.is_published or include_unpublished:
            return landing
        return None
    return None


def get_solution_landings(
    *,
    published_only: bool = True,
    include_in_hub: bool | None = None,
    include_in_sitemap: bool | None = None,
) -> list[SolutionLanding]:
    items = []
    for landing in SOLUTION_LANDINGS:
        if published_only and not landing.is_published:
            continue
        if include_in_hub is not None and landing.include_in_hub != include_in_hub:
            continue
        if include_in_sitemap is not None and landing.include_in_sitemap != include_in_sitemap:
            continue
        items.append(landing)
    return sorted(items, key=lambda item: (item.order, item.title.lower(), item.slug))
