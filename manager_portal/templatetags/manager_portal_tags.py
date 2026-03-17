from django import template
from django.core.exceptions import ObjectDoesNotExist
from django.template import Node, TemplateSyntaxError
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from manager_portal.status_system import (
    semantic_badge_classes,
    semantic_risk_classes,
    semantic_status_for_value,
    semantic_surface_classes,
    semantic_text_classes,
)

register = template.Library()

_ALLOWED_MANAGER_TABLE_ARGS = {'table_class', 'wrapper_class', 'table_id', 'variant'}
_DEFAULT_MANAGER_TABLE_VARIANT = 'hover'
_MANAGER_TABLE_VARIANTS = {'hover', 'zebra'}


def _join_classes(*values):
    parts = []
    for value in values:
        if not value:
            continue
        parts.extend(part for part in str(value).split() if part)
    return ' '.join(parts)


def _user_profile(user):
    try:
        return user.profile
    except (AttributeError, ObjectDoesNotExist):
        return None


@register.filter(name='manager_user_label')
def manager_user_label(user):
    sentinel = object()
    cached_value = getattr(user, '_manager_user_label_cache', sentinel) if user is not None else sentinel
    if cached_value is not sentinel:
        return cached_value

    label = ''
    if user is not None:
        full_name = user.get_full_name().strip() if hasattr(user, 'get_full_name') else ''
        if full_name:
            label = full_name
        else:
            profile = _user_profile(user)
            contact_name = ''
            if profile is not None:
                contact_name = (getattr(profile, 'contact_name', '') or '').strip()
            if contact_name:
                label = contact_name
            else:
                label = (getattr(user, 'email', '') or '').strip()

        if not label:
            if hasattr(user, 'get_username'):
                label = (user.get_username() or '').strip()
            else:
                label = (getattr(user, 'username', '') or '').strip()

    if user is not None:
        setattr(user, '_manager_user_label_cache', label)
    return label


@register.filter(name='manager_semantic_badge_classes')
def manager_semantic_badge_classes(value):
    return semantic_badge_classes(value)


@register.filter(name='manager_semantic_text_classes')
def manager_semantic_text_classes(value):
    return semantic_text_classes(value)


@register.filter(name='manager_semantic_surface_classes')
def manager_semantic_surface_classes(value):
    return semantic_surface_classes(value)


@register.filter(name='manager_semantic_risk_classes')
def manager_semantic_risk_classes(value):
    return semantic_risk_classes(value)


@register.simple_tag(name='manager_semantic_status')
def manager_semantic_status(value, kind=''):
    return semantic_status_for_value(value, kind=kind)


class ManagerTableNode(Node):
    def __init__(self, nodelist, kwargs):
        self.nodelist = nodelist
        self.kwargs = kwargs

    def render(self, context):
        table_class = self._resolve(context, 'table_class')
        wrapper_class = self._resolve(context, 'wrapper_class')
        table_id = self._resolve(context, 'table_id')
        variant = self._resolve(context, 'variant') or _DEFAULT_MANAGER_TABLE_VARIANT
        if variant not in _MANAGER_TABLE_VARIANTS:
            variant = _DEFAULT_MANAGER_TABLE_VARIANT

        wrapper_classes = _join_classes('manager-table-shell', 'overflow-x-auto', wrapper_class)
        table_classes = _join_classes('manager-table', f'manager-table--{variant}', table_class)
        table_content = self.nodelist.render(context)
        return format_html(
            '<div class="{}"><table{} class="{}">{}</table></div>',
            wrapper_classes,
            format_html(' id="{}" ', table_id) if table_id else '',
            table_classes,
            mark_safe(table_content),
        )

    def _resolve(self, context, key):
        expression = self.kwargs.get(key)
        if expression is None:
            return ''
        value = expression.resolve(context)
        return '' if value is None else str(value).strip()


@register.tag(name='manager_table')
def manager_table(parser, token):
    bits = token.split_contents()
    kwargs = {}
    for bit in bits[1:]:
        if '=' not in bit:
            raise TemplateSyntaxError(
                f"'{bits[0]}' accepts only keyword arguments: table_class, wrapper_class, table_id, variant."
            )
        key, value = bit.split('=', 1)
        if key not in _ALLOWED_MANAGER_TABLE_ARGS:
            raise TemplateSyntaxError(f"Unsupported argument '{key}' for '{bits[0]}'.")
        kwargs[key] = parser.compile_filter(value)

    nodelist = parser.parse(('endmanager_table',))
    parser.delete_first_token()
    return ManagerTableNode(nodelist, kwargs)
