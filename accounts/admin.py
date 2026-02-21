from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.contrib import messages

from .models import CommercialProposalContact, Profile, PhoneVerificationCode
from .admin_roles import MANAGER_GROUP_NAME, user_has_manager_role, set_user_manager_role

User = get_user_model()


class CommercialProposalContactInline(admin.StackedInline):
    model = CommercialProposalContact
    extra = 0
    max_num = 1
    can_delete = True
    verbose_name_plural = 'Телефон и email для КП (отображаются в документе как «Телефон для связи»)'
    fields = ('phone', 'email', 'updated_at')
    readonly_fields = ('updated_at',)


# Переопределяем админку пользователей: показываем роль менеджера и даём действия.
class CustomUserAdmin(BaseUserAdmin):
    list_display = BaseUserAdmin.list_display + ('is_manager_display',)
    list_filter = BaseUserAdmin.list_filter + ('groups',)
    inlines = (CommercialProposalContactInline,)

    @admin.display(boolean=True, description='Менеджер')
    def is_manager_display(self, obj):
        return user_has_manager_role(obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if request.user.is_superuser:
            actions['make_manager'] = (
                self._make_manager_action,
                'make_manager',
                'Сделать менеджером (ограниченный доступ к админке)',
            )
            actions['remove_manager'] = (
                self._remove_manager_action,
                'remove_manager',
                'Убрать роль менеджера',
            )
        return actions

    @admin.action(description='Сделать менеджером')
    def _make_manager_action(self, request, queryset):
        for user in queryset:
            set_user_manager_role(user, True)
        self.message_user(
            request,
            f'Роль менеджера назначена: {queryset.count()} пользователей.',
            messages.SUCCESS,
        )

    @admin.action(description='Убрать роль менеджера')
    def _remove_manager_action(self, request, queryset):
        done = sum(1 for user in queryset if set_user_manager_role(user, False))
        self.message_user(request, f'Роль менеджера снята: {done} пользователей.', messages.SUCCESS)


# Регистрируем свою админку пользователя (с группой «Менеджеры админ-панели» и действиями).
try:
    admin.site.unregister(User)
except Exception:
    pass
admin.site.register(User, CustomUserAdmin)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('phone', 'contact_name', 'privacy_agreed_at', 'user')
    search_fields = ('phone', 'contact_name', 'user__username')


@admin.register(PhoneVerificationCode)
class PhoneVerificationCodeAdmin(admin.ModelAdmin):
    list_display = ('phone', 'code', 'created_at')
    list_filter = ('created_at',)
