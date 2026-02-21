from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'Аккаунты'

    def ready(self):
        import sys
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return
        try:
            from .admin_roles import ensure_manager_group
            ensure_manager_group()
        except Exception:
            pass  # БД может быть ещё не готова при первом запуске
