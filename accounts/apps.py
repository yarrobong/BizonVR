from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'Аккаунты'

    def ready(self):
        pass  # Группа менеджеров создаётся при первом открытии админки пользователей (CustomUserAdmin.changelist_view)
