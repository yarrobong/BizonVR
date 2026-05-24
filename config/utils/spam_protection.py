import logging
import re
import time
from dataclasses import dataclass

from config.legal_consent import get_client_ip, get_user_agent

logger = logging.getLogger(__name__)

HONEYPOT_FIELDS = ('company_site', 'website', 'url')
MESSAGE_FIELDS = (
    'message',
    'comment',
    'delivery_comment',
    'premises',
    'source_path',
)
CONTACT_NAME_FIELDS = ('name', 'first_name')
EMAIL_FIELDS = ('email',)
PHONE_FIELDS = ('phone', 'contact', 'recipient_phone', 'business_phone')
BLOCK_KEYWORDS = (
    'searchregister',
    'searchregister.info',
    'searchregister.net',
    'googlesearchindex',
    'google search index',
    'online search results',
    'feature bizonvr.ru',
    'enlist bizonvr.ru',
)
SEO_WORDS = (
    'seo',
    'backlink',
    'traffic',
    'promotion',
    'marketing',
    'advertising',
    'google indexing',
    'search engine',
)
GREETING_PATTERNS = (
    ('dear sir/madam', 20, 'greeting_dear_sir_madam'),
    ('greetings', 10, 'greeting_greetings'),
)
SUSPICIOUS_EMAIL_PATTERNS = (
    (re.compile(r'^domains@', re.IGNORECASE), 35, 'email_domains_prefix'),
    (re.compile(r'search-bizonvr', re.IGNORECASE), 40, 'email_search_bizonvr'),
    (re.compile(r'(seo|domain|backlink)', re.IGNORECASE), 15, 'email_seo_like'),
)
URL_RE = re.compile(r'(https?://|www\.)', re.IGNORECASE)
ENGLISH_WORD_RE = re.compile(r'\b[a-z]{3,}\b')
VR_CONTEXT_RE = re.compile(
    r'\b(vr|quest|meta|шлем|арен|клуб|игр|аттракцион|оборудован|гарнитур|площадк|bizonvr)\b',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpamCheckResult:
    is_spam: bool
    reasons: list[str]
    score: int


def _iter_post_values(request):
    if not getattr(request, 'POST', None):
        return
    for key, values in request.POST.lists():
        for value in values:
            yield key, str(value or '').strip()


def _collect_text(request, *, fields=None):
    allowed = set(fields or [])
    parts = []
    for key, value in _iter_post_values(request):
        if not value:
            continue
        if allowed and key not in allowed:
            continue
        parts.append(value)
    return '\n'.join(parts)


def _normalize_started_at(raw_value):
    raw_value = str(raw_value or '').strip()
    if not raw_value:
        return None, 'missing'
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None, 'invalid'
    if value > 10_000_000_000:
        value /= 1000
    if value <= 0:
        return None, 'invalid'
    return value, None


def _first_present(request, field_names):
    for field_name in field_names:
        value = (request.POST.get(field_name) or '').strip()
        if value:
            return value
    return ''


def _looks_like_generic_english_seo_message(message_text):
    if not message_text:
        return False
    english_words = ENGLISH_WORD_RE.findall(message_text.lower())
    if len(english_words) < 6:
        return False
    return not VR_CONTEXT_RE.search(message_text)


def check_spam_submission(request, *, min_seconds=2, score_threshold=50):
    if not getattr(request, 'POST', None):
        return SpamCheckResult(is_spam=False, reasons=[], score=0)

    reasons = []
    score = 0
    immediate_block = False

    if getattr(request, 'limited', False):
        reasons.append('rate_limit_exceeded')
        score += 80

    for field_name in HONEYPOT_FIELDS:
        if (request.POST.get(field_name) or '').strip():
            reasons.append(f'honeypot_{field_name}')
            score += 100
            immediate_block = True

    started_at, started_at_error = _normalize_started_at(request.POST.get('form_started_at'))
    if started_at_error == 'missing':
        reasons.append('form_started_at_missing')
        score += 5
    elif started_at_error == 'invalid':
        reasons.append('form_started_at_invalid')
        score += 10
    elif (time.time() - started_at) < min_seconds:
        reasons.append('submitted_too_fast')
        score += 25

    message_text = _collect_text(request, fields=MESSAGE_FIELDS).lower()
    post_text = _collect_text(request).lower()
    email = _first_present(request, EMAIL_FIELDS)
    phone = _first_present(request, PHONE_FIELDS)

    for keyword in BLOCK_KEYWORDS:
        if keyword in post_text:
            reasons.append(f'keyword:{keyword}')
            score += 100
            immediate_block = True

    for keyword in SEO_WORDS:
        if re.search(rf'\b{re.escape(keyword)}\b', post_text):
            reasons.append(f'seo_word:{keyword}')
            score += 20

    for pattern, pattern_score, reason in GREETING_PATTERNS:
        if pattern in post_text:
            reasons.append(reason)
            score += pattern_score

    url_matches = URL_RE.findall(message_text)
    if url_matches:
        reasons.append('message_contains_link')
        score += 15
        if len(url_matches) > 1:
            reasons.append('message_contains_multiple_links')
            score += 10

    lowered_email = email.lower()
    for pattern, pattern_score, reason in SUSPICIOUS_EMAIL_PATTERNS:
        if pattern.search(lowered_email):
            reasons.append(reason)
            score += pattern_score

    if _looks_like_generic_english_seo_message(message_text):
        reasons.append('english_message_without_vr_context')
        score += 20

    if phone:
        digits = re.sub(r'\D', '', phone)
        if len(digits) < 7:
            reasons.append('phone_too_short')
            score += 8
        elif len(digits) < 10:
            reasons.append('phone_suspicious_length')
            score += 3

    is_spam = immediate_block or score >= score_threshold
    return SpamCheckResult(is_spam=is_spam, reasons=reasons, score=score)


def log_blocked_submission(request, *, source, result):
    name = _first_present(request, CONTACT_NAME_FIELDS)
    email = _first_present(request, EMAIL_FIELDS)
    phone = _first_present(request, PHONE_FIELDS)
    logger.warning(
        'Blocked spam submission',
        extra={
            'source': source,
            'reasons': result.reasons,
            'score': result.score,
            'path': request.path,
            'ip': get_client_ip(request),
            'user_agent': get_user_agent(request),
            'submitted_name': name,
            'submitted_email': email,
            'submitted_phone': phone,
        },
    )


def is_spam_request(request, min_seconds=2):
    return check_spam_submission(request, min_seconds=min_seconds).is_spam
