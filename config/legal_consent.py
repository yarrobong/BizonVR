from django.utils import timezone

from .legal_docs import LEGAL_BUNDLE_VERSION


def get_client_ip(request):
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if xff:
        return xff.split(',')[0].strip()
    return (request.META.get('REMOTE_ADDR') or '').strip()


def get_user_agent(request):
    return (request.META.get('HTTP_USER_AGENT') or '')[:512]


def get_legal_bundle_version():
    return LEGAL_BUNDLE_VERSION


def build_legal_acceptance_payload(request):
    return {
        'legal_accepted_at': timezone.now(),
        'legal_docs_version': get_legal_bundle_version(),
        'legal_acceptance_ip': get_client_ip(request) or None,
        'legal_acceptance_user_agent': get_user_agent(request),
    }
