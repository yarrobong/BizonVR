from .settings import *  # noqa: F401,F403

DEBUG = True

# В тестах отключаем manifest-хеши статики, чтобы шаблоны не падали на Missing staticfiles manifest entry.
STORAGES['staticfiles'] = {
    'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
}
