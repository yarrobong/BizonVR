from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class ConfigAdminConfig(AdminConfig):
    default_site = "config.admin_site.GroupedAdminSite"


class ConfigAppConfig(AppConfig):
    name = "config"

    def ready(self):
        from . import checks  # noqa: F401
