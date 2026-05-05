from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


RESPONSIVE_CARD_WIDTHS = (320, 480, 640)
RESPONSIVE_RECOMMENDATION_WIDTHS = (240, 320, 480)
RESPONSIVE_GALLERY_WIDTHS = (120, 240, 360)
RESPONSIVE_HERO_WIDTHS = (640, 960, 1280, 1600)
RESPONSIVE_VARIANT_WIDTHS = (80, 120, 160)

_RESIZED_CACHE_DIR = Path('cache') / 'responsive'
_JPEG_EXTENSIONS = {'.jpg', '.jpeg'}
_PNG_EXTENSIONS = {'.png'}
_WEBP_EXTENSIONS = {'.webp'}


@dataclass(frozen=True)
class ResponsiveImageCandidate:
    url: str
    width: int
    height: int


def get_image_dimensions(image_field):
    try:
        if not image_field:
            return None, None
        width = int(getattr(image_field, 'width', 0) or 0)
        height = int(getattr(image_field, 'height', 0) or 0)
    except (TypeError, ValueError, OSError, FileNotFoundError):
        return None, None
    if width <= 0 or height <= 0:
        return None, None
    return width, height


def build_responsive_image_data(image_field, *, widths, default_width=None, request=None, sizes=''):
    candidates = get_responsive_image_candidates(image_field, widths)
    if not candidates:
        return {}

    if default_width is None:
        default_width = max(int(candidate.width) for candidate in candidates)

    default_candidate = _pick_default_candidate(candidates, default_width)
    original_width, original_height = get_image_dimensions(image_field)

    def _resolve_url(url):
        if request is None or not url or url.startswith(('http://', 'https://')):
            return url
        return request.build_absolute_uri(url)

    return {
        'src': _resolve_url(default_candidate.url),
        'srcset': ', '.join(
            f'{_resolve_url(candidate.url)} {candidate.width}w'
            for candidate in candidates
        ),
        'sizes': sizes,
        'width': original_width,
        'height': original_height,
    }


def get_responsive_image_candidates(image_field, widths):
    original_url = _safe_image_url(image_field)
    original_width, original_height = get_image_dimensions(image_field)
    if not original_url or original_width is None or original_height is None:
        return []

    normalized_widths = sorted({int(width) for width in widths if int(width) > 0})
    if not normalized_widths:
        return [ResponsiveImageCandidate(original_url, original_width, original_height)]

    candidates = []
    for width in normalized_widths:
        if width >= original_width:
            if not any(candidate.width == original_width for candidate in candidates):
                candidates.append(ResponsiveImageCandidate(original_url, original_width, original_height))
            continue
        resized_candidate = _build_resized_candidate(
            image_field=image_field,
            original_width=original_width,
            original_height=original_height,
            target_width=width,
            original_url=original_url,
        )
        if resized_candidate is None:
            continue
        if any(candidate.width == resized_candidate.width for candidate in candidates):
            continue
        candidates.append(resized_candidate)

    if not any(candidate.width == original_width for candidate in candidates):
        candidates.append(ResponsiveImageCandidate(original_url, original_width, original_height))
    return sorted(candidates, key=lambda candidate: candidate.width)


def _pick_default_candidate(candidates, default_width):
    for candidate in candidates:
        if candidate.width >= default_width:
            return candidate
    return candidates[-1]


def _safe_image_url(image_field):
    try:
        return image_field.url if image_field else ''
    except (ValueError, AttributeError, OSError):
        return ''


def _build_resized_candidate(*, image_field, original_width, original_height, target_width, original_url):
    source_path = _safe_image_path(image_field)
    if not source_path:
        return None

    target_height = max(1, round(original_height * (target_width / original_width)))
    output_extension, output_format = _resolve_output_format(source_path)
    signature = sha1(
        f'{image_field.name}:{source_path.stat().st_mtime_ns}:{target_width}:{target_height}:{output_extension}'.encode('utf-8')
    ).hexdigest()
    relative_path = _RESIZED_CACHE_DIR / signature[:2] / f'{signature}-{target_width}w{output_extension}'
    absolute_path = Path(settings.MEDIA_ROOT) / relative_path

    if not absolute_path.exists():
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        if not _generate_resized_image(
            source_path=source_path,
            output_path=absolute_path,
            target_width=target_width,
            target_height=target_height,
            output_format=output_format,
        ):
            return None

    return ResponsiveImageCandidate(
        url=_build_media_url(relative_path),
        width=target_width,
        height=target_height,
    )


def _safe_image_path(image_field):
    try:
        if not image_field:
            return None
        return Path(image_field.path)
    except (NotImplementedError, ValueError, AttributeError, OSError):
        return None


def _resolve_output_format(source_path):
    extension = source_path.suffix.lower()
    if extension in _JPEG_EXTENSIONS:
        return '.jpg', 'JPEG'
    if extension in _PNG_EXTENSIONS:
        return '.png', 'PNG'
    if extension in _WEBP_EXTENSIONS:
        return '.webp', 'WEBP'
    return extension or '.jpg', 'JPEG'


def _build_media_url(relative_path):
    return f"{settings.MEDIA_URL.rstrip('/')}/{relative_path.as_posix()}"


def _generate_resized_image(*, source_path, output_path, target_width, target_height, output_format):
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            if getattr(image, 'is_animated', False):
                return False
            resized_image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
            save_kwargs = _build_save_kwargs(output_format)
            if output_format == 'JPEG' and resized_image.mode not in {'RGB', 'L'}:
                resized_image = resized_image.convert('RGB')
            resized_image.save(output_path, format=output_format, **save_kwargs)
    except (FileNotFoundError, OSError, UnidentifiedImageError, ValueError):
        return False
    return True


def _build_save_kwargs(output_format):
    if output_format == 'JPEG':
        return {
            'optimize': True,
            'progressive': True,
            'quality': 82,
        }
    if output_format == 'PNG':
        return {
            'optimize': True,
        }
    if output_format == 'WEBP':
        return {
            'quality': 82,
            'method': 6,
        }
    return {}
