from django.contrib.auth.models import Group, Permission
from django.db.models import Q

MANAGER_GROUP_NAME = 'Менеджеры админ-панели'

# Ограниченный набор возможностей менеджера в админке.
MANAGER_PERMISSIONS = (
    ('orders', 'view_order'),
    ('orders', 'change_order'),
    ('orders', 'view_orderitem'),
    ('orders', 'view_purchaserequest'),
    ('orders', 'change_purchaserequest'),
    ('orders', 'view_promocode'),
    ('payments', 'view_payment'),
    ('catalog', 'view_contactrequest'),
    ('catalog', 'view_callbackrequest'),
    ('catalog', 'view_product'),  # просмотр товаров и формирование коммерческого предложения
    ('accounts', 'view_profile'),
)


def ensure_manager_group() -> Group:
    """Создаёт (или обновляет) группу менеджеров с фиксированными правами."""
    group, _ = Group.objects.get_or_create(name=MANAGER_GROUP_NAME)
    permission_filter = Q()
    for app_label, codename in MANAGER_PERMISSIONS:
        permission_filter |= Q(content_type__app_label=app_label, codename=codename)
    permissions = Permission.objects.filter(permission_filter)
    group.permissions.set(permissions)
    return group


def user_has_manager_role(user) -> bool:
    return user.groups.filter(name=MANAGER_GROUP_NAME).exists()


def set_user_manager_role(user, enabled: bool) -> bool:
    """Включает/выключает роль менеджера. Возвращает True, если что-то изменилось."""
    manager_group = ensure_manager_group()
    changed = False

    if enabled:
        update_fields = []
        if not user.is_staff:
            user.is_staff = True
            update_fields.append('is_staff')
        if user.is_superuser:
            user.is_superuser = False
            update_fields.append('is_superuser')
        if update_fields:
            user.save(update_fields=update_fields)
            changed = True

        if not user.groups.filter(pk=manager_group.pk).exists():
            user.groups.add(manager_group)
            changed = True
        return changed

    if user.groups.filter(pk=manager_group.pk).exists():
        user.groups.remove(manager_group)
        changed = True
    return changed
