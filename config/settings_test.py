from .settings import *  # noqa: F401,F403

DEBUG = True

# В тестах не нужен collectstatic: используем finders-based static storage.
STORAGES['staticfiles'] = {
    'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
}

# WhiteNoise в тестах только шумит предупреждениями про отсутствующий STATIC_ROOT.
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE
    if middleware != 'whitenoise.middleware.WhiteNoiseMiddleware'
]
