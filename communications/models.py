from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class MeetingType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MeetingSequence(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)


class Meeting(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        ACCEPTED = "ACCEPTED", "Accepted"
        PROPOSED = "PROPOSED", "New time proposed"
        RESCHEDULED = "RESCHEDULED", "Rescheduled"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    reference = models.CharField(max_length=30, unique=True, db_index=True)
    title = models.CharField(max_length=180)
    reason = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    meeting_type = models.ForeignKey(MeetingType, on_delete=models.PROTECT, related_name="meetings")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_meetings")
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="organized_meetings")
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, through="MeetingParticipant", related_name="meetings")
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="meetings")
    scheduled_start = models.DateTimeField(db_index=True)
    scheduled_end = models.DateTimeField()
    proposed_start = models.DateTimeField(null=True, blank=True)
    location_link = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_start"]
        indexes = [models.Index(fields=["status", "scheduled_start"])]

    @property
    def is_past(self):
        return self.scheduled_end < timezone.now()

    def __str__(self):
        return f"{self.reference} — {self.title}"


class MeetingParticipant(models.Model):
    class Response(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="participant_records")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meeting_participations")
    response = models.CharField(max_length=10, choices=Response.choices, default=Response.PENDING)
    is_required = models.BooleanField(default=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["meeting", "user"], name="unique_meeting_participant")]


class MeetingHistory(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=50)
    description = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "meeting history"


class Notification(models.Model):
    class Kind(models.TextChoices):
        TICKET_CREATED = "TICKET_CREATED", "New ticket"
        ASSIGNED = "ASSIGNED", "Ticket assigned"
        COMMENT = "COMMENT", "New comment"
        STATUS = "STATUS", "Status changed"
        MENTION = "MENTION", "Mention"
        DEADLINE = "DEADLINE", "Deadline"
        MEETING = "MEETING", "Meeting"
        VERIFICATION = "VERIFICATION", "Verification"
        REOPENED = "REOPENED", "Ticket reopened"
        ACCOUNT_APPROVAL = "ACCOUNT_APPROVAL", "Account approval"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="triggered_notifications")
    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    verb = models.CharField(max_length=255)
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    approval_request = models.ForeignKey(
        "accounts.AccountApprovalRequest", on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"])]

    @property
    def target_url(self):
        if self.ticket_id:
            return reverse("ticket_detail", args=[self.ticket.ticket_number])
        if self.meeting_id:
            return reverse("meeting_detail", args=[self.meeting.reference])
        if self.approval_request_id:
            return reverse("account_approval_list")
        return reverse("notification_list")
