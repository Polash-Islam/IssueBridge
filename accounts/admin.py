from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils.html import format_html
from .models import AccountApprovalRequest, Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "division", "code", "scope", "is_division_director", "is_system", "edit_link")
    list_filter = ("division", "scope", "is_division_director", "is_system")
    search_fields = ("name", "code", "division__name", "division__code")
    list_select_related = ("division",)
    prepopulated_fields = {"code": ("name",)}
    fieldsets = (
        (None, {"fields": ("name", "division", "code", "description")}),
        ("Access settings", {"fields": ("scope", "is_division_director", "permissions", "is_system")}),
    )
    filter_horizontal = ("permissions",)

    @admin.display(description="Edit")
    def edit_link(self, obj):
        url = reverse("admin:accounts_role_change", args=[obj.pk], current_app=self.admin_site.name)
        return format_html('<a class="button" href="{}">Edit</a>', url)


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
