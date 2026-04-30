from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


PLACEHOLDER_MARKERS = (
    '[',
    'УКАЖИТЕ',
    'CHANGE-ME',
    'EXAMPLE.COM',
)


def _is_blank_or_placeholder(value):
    normalized = str(value or '').strip()
    if not normalized:
        return True
    upper_value = normalized.upper()
    return any(marker in upper_value for marker in PLACEHOLDER_MARKERS)


@register(Tags.security, deploy=True)
def production_launch_settings_check(app_configs, **kwargs):
    messages = []

    required_values = {
        'SITE_URL': getattr(settings, 'SITE_URL', ''),
        'DEFAULT_FROM_EMAIL': getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
        'EMAIL_HOST': getattr(settings, 'EMAIL_HOST', ''),
        'EMAIL_HOST_USER': getattr(settings, 'EMAIL_HOST_USER', ''),
        'EMAIL_HOST_PASSWORD': getattr(settings, 'EMAIL_HOST_PASSWORD', ''),
        'LEGAL_OPERATOR_FULL_NAME': getattr(settings, 'LEGAL_OPERATOR_FULL_NAME', ''),
        'LEGAL_OPERATOR_INN': getattr(settings, 'LEGAL_OPERATOR_INN', ''),
        'LEGAL_OPERATOR_OGRN': getattr(settings, 'LEGAL_OPERATOR_OGRN', ''),
        'LEGAL_OPERATOR_LEGAL_ADDRESS': getattr(settings, 'LEGAL_OPERATOR_LEGAL_ADDRESS', ''),
        'LEGAL_OPERATOR_POSTAL_ADDRESS': getattr(settings, 'LEGAL_OPERATOR_POSTAL_ADDRESS', ''),
        'LEGAL_OPERATOR_PD_EMAIL': getattr(settings, 'LEGAL_OPERATOR_PD_EMAIL', ''),
    }
    missing = [name for name, value in required_values.items() if _is_blank_or_placeholder(value)]
    if missing:
        messages.append(Error(
            'Production launch settings contain empty or placeholder values.',
            hint='Fill these environment variables before restart: ' + ', '.join(sorted(missing)),
            id='config.E001',
        ))

    site_url = str(getattr(settings, 'SITE_URL', '') or '')
    if site_url and not site_url.startswith('https://'):
        messages.append(Error(
            'SITE_URL must use HTTPS in production.',
            hint='Set SITE_URL=https://bizonvr.ru in the production .env.',
            id='config.E002',
        ))

    default_from = str(getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '').lower()
    if 'no-reply@bizonvr.ru' in default_from:
        messages.append(Warning(
            'DEFAULT_FROM_EMAIL still uses the generic no-reply@bizonvr.ru sender.',
            hint='Set DEFAULT_FROM_EMAIL to the real corporate mailbox after SMTP is configured.',
            id='config.W001',
        ))

    if getattr(settings, 'EMAIL_USE_TLS', False) and getattr(settings, 'EMAIL_USE_SSL', False):
        messages.append(Error(
            'EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled.',
            hint='Use STARTTLS on port 587 or SSL on port 465, not both.',
            id='config.E003',
        ))

    return messages
