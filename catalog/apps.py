from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'catalog'
    verbose_name = 'Каталог'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from . import signals  # noqa: F401
        from .cart_services import (
            merge_session_cart_into_user,
            merge_session_compare_into_user,
            merge_session_favorites_into_user,
        )

        def _merge_cart_and_favorites(sender, request, user, **kwargs):
            request.user = user
            merge_session_cart_into_user(request)
            merge_session_favorites_into_user(request)
            merge_session_compare_into_user(request)

        user_logged_in.connect(
            _merge_cart_and_favorites,
            dispatch_uid='catalog.merge_session_state_on_login',
            weak=False,
        )
