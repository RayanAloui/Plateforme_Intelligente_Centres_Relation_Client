from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User


@admin.register(User)
class PlatformUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "is_active", "last_login")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Plateforme", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Plateforme", {"fields": ("role", "first_name", "last_name")}),)
