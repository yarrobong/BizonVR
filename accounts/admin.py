from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from .models import Profile, PhoneVerificationCode

User = get_user_model()


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('phone', 'user')
    search_fields = ('phone', 'user__username')


@admin.register(PhoneVerificationCode)
class PhoneVerificationCodeAdmin(admin.ModelAdmin):
    list_display = ('phone', 'code', 'created_at')
    list_filter = ('created_at',)
