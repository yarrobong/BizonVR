from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


PLACEHOLDER_MARKERS = (
    '[',
    'УКАЖИТЕ',
    'CHANGE-ME',
    'EXAMPLE.COM',
    'YOUR-SECRET-KEY-HERE',
    'DJANGO-INSECURE',
)


def _is_blank_or_placeholder(value):
    if isinstance(value, (list, tuple, set)):
        values = [str(item or '').strip() for item in value if str(item or '').strip()]
        if not values:
            return True
        return all(_is_blank_or_placeholder(item) for item in values)
    normalized = str(value or '').strip()
    if not normalized:
        return True
    upper_value = normalized.upper()
    return any(marker in upper_value for marker in PLACEHOLDER_MARKERS)


@register(Tags.security, deploy=True)
def production_launch_settings_check(app_configs, **kwargs):
    messages = []
    production_mode = not getattr(settings, 'DEBUG', True)
    require_https_site_url = bool(getattr(settings, 'USE_HTTPS', False)) or production_mode

    if production_mode:
        if not getattr(settings, 'USE_HTTPS', False):
            messages.append(Error(
                'USE_HTTPS must be enabled in production.',
                hint='Set USE_HTTPS=True before starting with DEBUG=False.',
                id='config.E006',
            ))
        required_values = {
            'SITE_URL': getattr(settings, 'SITE_URL', ''),
            'SECRET_KEY': getattr(settings, 'SECRET_KEY', ''),
            'DEFAULT_FROM_EMAIL': getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
            'EMAIL_HOST': getattr(settings, 'EMAIL_HOST', ''),
            'EMAIL_HOST_USER': getattr(settings, 'EMAIL_HOST_USER', ''),
            'EMAIL_HOST_PASSWORD': getattr(settings, 'EMAIL_HOST_PASSWORD', ''),
            'LEGAL_OPERATOR_FULL_NAME': getattr(settings, 'LEGAL_OPERATOR_FULL_NAME', ''),
            'LEGAL_OPERATOR_INN': getattr(settings, 'LEGAL_OPERATOR_INN', ''),
            'LEGAL_OPERATOR_OGRN': getattr(settings, 'LEGAL_OPERATOR_OGRN', ''),
            'LEGAL_OPERATOR_PD_EMAIL': getattr(settings, 'LEGAL_OPERATOR_PD_EMAIL', ''),
        }
        missing = [name for name, value in required_values.items() if _is_blank_or_placeholder(value)]
        if not getattr(settings, 'ALLOWED_HOSTS_WAS_SET', bool(getattr(settings, 'ALLOWED_HOSTS', []))):
            missing.append('ALLOWED_HOSTS')
        if not getattr(settings, 'EMAIL_PORT_WAS_SET', False):
            missing.append('EMAIL_PORT')
        if missing:
            messages.append(Error(
                'Production launch settings contain empty or placeholder values.',
                hint='Fill these environment variables before restart: ' + ', '.join(sorted(missing)),
                id='config.E001',
            ))

    site_url = str(getattr(settings, 'SITE_URL', '') or '')
    if require_https_site_url and not site_url.startswith('https://'):
        messages.append(Error(
            'SITE_URL must use HTTPS when DEBUG=False or USE_HTTPS=True.',
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

    email_port_error = str(getattr(settings, 'EMAIL_PORT_CONFIG_ERROR', '') or '').strip()
    email_port = getattr(settings, 'EMAIL_PORT', None)
    if email_port_error:
        messages.append(Error(
            'EMAIL_PORT must be a number.',
            hint='Set EMAIL_PORT to an integer SMTP port such as 587 or 465.',
            id='config.E004',
        ))
    elif email_port is None or not isinstance(email_port, int) or email_port <= 0:
        messages.append(Error(
            'EMAIL_PORT must be a positive integer.',
            hint='Set EMAIL_PORT to an integer SMTP port such as 587 or 465.',
            id='config.E005',
        ))

    return messages
