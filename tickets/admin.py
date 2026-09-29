from django.contrib import admin
from .models import (
    Product, StatusTransition, Ticket, TicketAssignment, TicketAttachment, TicketCategory,
    TicketComment, TicketHistory, TicketPriority, TicketReview, TicketTechnicalVerification,
    TicketVerification, WorkflowStatus,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "division", "is_active")
    list_filter = ("division", "is_active")
    search_fields = ("name", "code")


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)


@admin.register(TicketPriority)
class TicketPriorityAdmin(admin.ModelAdmin):
    list_display = ("name", "rank", "color", "is_active")


@admin.register(WorkflowStatus)
class WorkflowStatusAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "sort_order", "color", "is_active")


@admin.register(StatusTransition)
class StatusTransitionAdmin(admin.ModelAdmin):
    list_display = ("name", "from_status", "to_status", "requires_comment", "is_active")
    filter_horizontal = ("allowed_roles",)


class AssignmentInline(admin.TabularInline):
    model = TicketAssignment
    extra = 0
    readonly_fields = ("assigned_at", "ended_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("ticket_number", "title", "requesting_division", "status", "priority", "current_assignee", "created_at")
    list_filter = ("requesting_division", "status", "priority", "category")
    search_fields = ("ticket_number", "title", "description")
    readonly_fields = ("ticket_number", "created_at", "updated_at")
    inlines = (AssignmentInline,)


admin.site.register(TicketComment)
admin.site.register(TicketAttachment)
admin.site.register(TicketReview)
admin.site.register(TicketVerification)
admin.site.register(TicketTechnicalVerification)


@admin.register(TicketHistory)
class TicketHistoryAdmin(admin.ModelAdmin):
    list_display = ("ticket", "action", "actor", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("ticket__ticket_number", "description")
    readonly_fields = [field.name for field in TicketHistory._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
