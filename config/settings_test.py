from .settings import *  # noqa: F401,F403

DEBUG = True
ENABLE_ALFATRACK = False
SITE_URL = 'http://testserver'

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
EMAIL_HOST = 'localhost'
EMAIL_PORT = 25
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
EMAIL_USE_TLS = False
EMAIL_USE_SSL = False
EMAIL_TIMEOUT = 1

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'bizonvr-tests',
    }
}

# В тестах не нужен collectstatic: используем finders-based static storage.
STORAGES['staticfiles'] = {
    'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
}
STORAGES['default'] = {
    'BACKEND': 'django.core.files.storage.FileSystemStorage',
}

# WhiteNoise в тестах только шумит предупреждениями про отсутствующий STATIC_ROOT.
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE
    if middleware != 'whitenoise.middleware.WhiteNoiseMiddleware'
]

MEDIA_ROOT = BASE_DIR / '.test-media'
STATIC_ROOT = BASE_DIR / '.test-static'
WHITENOISE_MAX_AGE = 0

CDEK_WIDGET_API_BASE = 'https://cdek.invalid/v2'
CDEK_WIDGET_ACCOUNT = 'test-cdek-account'
CDEK_WIDGET_PASSWORD = 'test-cdek-password'

EXOLVE_API_KEY = ''
EXOLVE_SENDER = ''
EXOLVE_API_BASE = 'https://sms.invalid/messaging/v1'
TURNSTILE_SITE_KEY = ''
TURNSTILE_SECRET_KEY = ''
TURNSTILE_VERIFY_URL = 'https://turnstile.invalid/siteverify'
PAYMENT_GATEWAY_API_KEY = ''
PAYMENT_GATEWAY_IPN_SECRET = 'test-ipn-secret'
PAYMENT_GATEWAY_API_BASE = 'https://payments.invalid/v1'
DOCUFLOW_BACKEND_URL = 'http://docuflow.invalid'
CRM_LEADS_EMAIL = ''
