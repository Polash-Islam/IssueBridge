from django.conf import settings
from django.db import models
from django.utils import timezone
from django.urls import reverse

from .validators import validate_attachment


class Product(models.Model):
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=60, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["division__code", "name"]
        constraints = [models.UniqueConstraint(fields=["division", "name"], name="unique_product_per_division")]

    def __str__(self):
        return self.name


class TicketCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=60, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "ticket categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TicketPriority(models.Model):
    name = models.CharField(max_length=40, unique=True)
    code = models.SlugField(max_length=30, unique=True)
    rank = models.PositiveSmallIntegerField(unique=True)
    color = models.CharField(max_length=7, default="#64748b")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-rank"]
        verbose_name_plural = "ticket priorities"

    def __str__(self):
        return self.name


class WorkflowStatus(models.Model):
    class Kind(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACTIVE = "ACTIVE", "Active"
        WAITING = "WAITING", "Waiting"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    name = models.CharField(max_length=80, unique=True)
    code = models.SlugField(max_length=50, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OPEN)
    color = models.CharField(max_length=7, default="#64748b")
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "workflow statuses"

    def __str__(self):
        return self.name


class StatusTransition(models.Model):
    name = models.CharField(max_length=100)
    from_status = models.ForeignKey(WorkflowStatus, on_delete=models.CASCADE, related_name="transitions_from")
    to_status = models.ForeignKey(WorkflowStatus, on_delete=models.CASCADE, related_name="transitions_to")
    allowed_roles = models.ManyToManyField("accounts.Role", blank=True, related_name="status_transitions")
    requires_comment = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["from_status__sort_order", "to_status__sort_order"]
        constraints = [models.UniqueConstraint(fields=["from_status", "to_status"], name="unique_status_transition")]

    def __str__(self):
        return f"{self.from_status} → {self.to_status}"


class TicketNumberSequence(models.Model):
    division = models.ForeignKey("core.Division", on_delete=models.CASCADE)
    year = models.PositiveSmallIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["division", "year"], name="unique_ticket_sequence")]


class Ticket(models.Model):
    ticket_number = models.CharField(max_length=30, unique=True, db_index=True)
    title = models.CharField(max_length=220)
    description = models.TextField()
    expected_behavior = models.TextField(blank=True)
    actual_behavior = models.TextField(blank=True)
    additional_notes = models.TextField(blank=True)
    module_page = models.CharField(max_length=180, blank=True)
    browser_device = models.CharField(max_length=255, blank=True)

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets")
    identified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="identified_tickets")
    requesting_division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="tickets")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="tickets")
    category = models.ForeignKey(TicketCategory, on_delete=models.PROTECT, related_name="tickets")
    priority = models.ForeignKey(TicketPriority, on_delete=models.PROTECT, related_name="tickets")
    status = models.ForeignKey(WorkflowStatus, on_delete=models.PROTECT, related_name="tickets")
    current_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_tickets"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_tickets"
    )
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="subtasks")
    related_tickets = models.ManyToManyField("self", blank=True, symmetrical=True)
    watchers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="watched_tickets")

    problem_identified_at = models.DateTimeField()
    deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["requesting_division", "status"]),
            models.Index(fields=["current_assignee", "status"]),
            models.Index(fields=["product", "category"]),
        ]

    @property
    def is_overdue(self):
        return bool(self.deadline and self.deadline < timezone.now() and self.status.kind not in {"RESOLVED", "CLOSED"})

    @property
    def due_label(self):
        if not self.deadline:
            return "No deadline"
        delta = self.deadline - timezone.now()
        total = int(delta.total_seconds())
        if total < 0:
            days = abs(total) // 86400
            return f"Overdue by {max(days, 1)}d"
        if total < 86400:
            return f"{max(total // 3600, 1)}h remaining"
        return f"{total // 86400}d remaining"

    def __str__(self):
        return f"{self.ticket_number} — {self.title}"

    def get_absolute_url(self):
        return reverse("ticket_detail", args=[self.ticket_number])


class TicketAssignment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="assignments")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_assignments")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="made_assignments")
    task_description = models.TextField()
    technical_instructions = models.TextField(blank=True)
    expected_output = models.TextField(blank=True)
    additional_notes = models.TextField(blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [models.Index(fields=["assigned_to", "is_active"])]


class TicketComment(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Requester visible"
        INTERNAL = "INTERNAL", "Internal IT only"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_comments")
    body = models.TextField()
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


def attachment_path(instance, filename):
    return f"tickets/{instance.ticket.ticket_number}/{timezone.now():%Y/%m}/{filename}"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(TicketComment, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments")
    file = models.FileField(upload_to=attachment_path, validators=[validate_attachment])
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_attachments")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    @property
    def is_image(self):
        return self.content_type.startswith("image/")


class TicketReview(models.Model):
    class Decision(models.TextChoices):
        VALID = "VALID", "Valid problem"
        INVALID = "INVALID", "Invalid problem"
        NEED_INFO = "NEED_INFO", "Need more information"
        DUPLICATE = "DUPLICATE", "Duplicate"
        RESOLVED = "RESOLVED", "Already resolved"
        NOT_IT = "NOT_IT", "Not an IT issue"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_reviews")
    decision = models.CharField(max_length=20, choices=Decision.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TicketVerification(models.Model):
    class Decision(models.TextChoices):
        VERIFIED = "VERIFIED", "Problem resolved"
        FAILED = "FAILED", "Problem still exists"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="verifications")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_verifications")
    decision = models.CharField(max_length=10, choices=Decision.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TicketTechnicalVerification(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Technical work approved"
        RETURNED = "RETURNED", "Returned to responsible person"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="technical_verifications")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="technical_ticket_verifications")
    decision = models.CharField(max_length=10, choices=Decision.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TicketHistory(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ticket_history_events")
    action = models.CharField(max_length=80, db_index=True)
    description = models.CharField(max_length=500)
    previous_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "ticket history"
