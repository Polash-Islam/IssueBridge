from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import AccountApprovalRequest, Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "scope", "is_system")
    search_fields = ("name", "code")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("FRC profile", {"fields": ("employee_id", "mobile", "designation", "division", "role", "profile_photo", "joining_date", "supervisor", "created_by")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("FRC profile", {"fields": ("email", "employee_id", "division", "role")}),)
    list_display = ("username", "email", "first_name", "last_name", "division", "role", "is_active")
    list_filter = ("division", "role", "is_active")


@admin.register(AccountApprovalRequest)
class AccountApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "division", "status", "requested_at", "expires_at", "reviewed_by")
    list_filter = ("status", "division")
    search_fields = ("user__email", "user__first_name", "user__last_name")
