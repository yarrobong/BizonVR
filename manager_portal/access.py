from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


FINANCE_OPERATOR_GROUP = 'manager_portal_finance_operator'
FINANCE_ADMIN_GROUP = 'manager_portal_finance_admin'
FINANCE_GROUP_NAMES = {FINANCE_OPERATOR_GROUP, FINANCE_ADMIN_GROUP}


def has_manager_portal_access(user):
    return bool(user.is_authenticated and user.is_staff)


def has_finance_portal_access(user):
    if not user.is_authenticated:
        return False
    return bool(user.is_staff or user.groups.filter(name__in=FINANCE_GROUP_NAMES).exists())


def has_finance_admin_access(user):
    if not user.is_authenticated:
        return False
    return bool(user.is_staff or user.groups.filter(name=FINANCE_ADMIN_GROUP).exists())


def has_any_manager_portal_access(user):
    return bool(has_manager_portal_access(user) or has_finance_portal_access(user))


def staff_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not has_manager_portal_access(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped


def finance_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not has_finance_portal_access(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped


def finance_admin_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not has_finance_admin_access(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return _wrapped
