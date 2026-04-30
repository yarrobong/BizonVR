import re
import time


SPAM_WORDS = (
    'seo',
    'backlink',
    'traffic',
    'promotion',
    'marketing',
    'advertising',
    'casino',
    'crypto',
    'loan',
    'viagra',
    'dating',
    'escort',
)
LINK_MARKERS = ('http://', 'https://', 'www.')


def _build_post_text(request):
    parts = []
    for _, values in request.POST.lists():
        for value in values:
            if value:
                parts.append(str(value))
    return '\n'.join(parts).lower()


def is_spam_request(request, min_seconds=2):
    if not getattr(request, 'POST', None):
        return False

    if (request.POST.get('website') or '').strip():
        return True
    if (request.POST.get('company_site') or '').strip():
        return True

    started_at_raw = (request.POST.get('form_started_at') or '').strip()
    if started_at_raw:
        try:
            started_at = int(float(started_at_raw))
        except (TypeError, ValueError):
            started_at = None
        if started_at is not None and (time.time() - started_at) < min_seconds:
            return True

    post_text = _build_post_text(request)
    if sum(post_text.count(marker) for marker in LINK_MARKERS) >= 2:
        return True

    return any(re.search(rf'\b{re.escape(word)}\b', post_text) for word in SPAM_WORDS)
