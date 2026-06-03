UTM_FIELDS = (
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term',
)
SESSION_KEY = 'site_marketing_context'


def _clean(value, *, limit=500):
    return str(value or '').strip()[:limit]


def persist_marketing_context(request):
    session = getattr(request, 'session', None)
    if session is None:
        return

    existing = dict(session.get(SESSION_KEY) or {})
    updated = False

    for field_name in UTM_FIELDS:
        value = _clean(request.GET.get(field_name), limit=255)
        if value:
            if existing.get(field_name) != value:
                existing[field_name] = value
                updated = True

    current_url = ''
    if hasattr(request, 'build_absolute_uri'):
        current_url = _clean(request.build_absolute_uri(request.get_full_path()))
    if current_url and not existing.get('first_page_url'):
        existing['first_page_url'] = current_url
        updated = True
    if current_url and existing.get('last_page_url') != current_url:
        existing['last_page_url'] = current_url
        updated = True

    referer = _clean(request.META.get('HTTP_REFERER'))
    if referer and existing.get('latest_referer') != referer:
        existing['latest_referer'] = referer
        updated = True

    if updated:
        session[SESSION_KEY] = existing


def get_marketing_context(request):
    session = getattr(request, 'session', None)
    if session is None:
        return {}
    stored = session.get(SESSION_KEY)
    return dict(stored) if isinstance(stored, dict) else {}
