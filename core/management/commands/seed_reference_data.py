from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from communications.models import MeetingType
from accounts.models import Role
from tickets.models import (
    StatusTransition, TicketCategory, TicketPriority, WorkflowStatus,
)


CATEGORY_NAMES = [
    "Bug / Software Error", "UI / Design Issue", "Data Change", "Data Error",
    "New Feature Request", "Existing Feature Modification", "Access / Permission Issue",
    "Performance Issue", "Report Issue", "Documentation Issue", "General Support",
    "Meeting / Discussion Request", "Other",
]

PRIORITIES = [
    ("moderate", "Moderate", 1, "#3d79b7"),
    ("high", "High", 2, "#e18432"),
    ("urgent", "Urgent", 3, "#dd5850"),
]

STATUSES = [
    ("new", "New", "OPEN", "#4f7fa9"),
    ("under-review", "Under Review", "ACTIVE", "#7161b7"),
    ("need-more-information", "Need More Information", "WAITING", "#c0842f"),
    ("validated", "Validated", "OPEN", "#31836b"),
    ("invalid", "Invalid", "CLOSED", "#7a8590"),
    ("assigned", "Assigned", "ACTIVE", "#327bb8"),
    ("in-progress", "In Progress", "ACTIVE", "#286fb4"),
    ("blocked", "Blocked", "WAITING", "#ca4d4d"),
    ("waiting-for-requester", "Waiting for Requester", "WAITING", "#c17c2b"),
    ("waiting-for-meeting", "Waiting for Meeting", "WAITING", "#9c6bb6"),
    ("ready-for-it-verification", "Ready for IT Verification", "WAITING", "#4868c7"),
    ("ready-for-verification", "Ready for Verification", "WAITING", "#7656d8"),
    ("verification-failed", "Verification Failed", "ACTIVE", "#d15151"),
    ("reopened", "Reopened", "ACTIVE", "#d05d52"),
    ("completed", "Completed", "RESOLVED", "#21835f"),
    ("closed", "Closed", "CLOSED", "#526575"),
    ("cancelled", "Cancelled", "CLOSED", "#7d8790"),
]

MEETING_TYPES = [
    ("it-division", "IT + Division Meeting"),
    ("one-to-one", "One-to-One Discussion"),
    ("technical", "Technical Discussion"),
    ("requirement", "Requirement Discussion"),
    ("demonstration", "Demonstration"),
    ("other", "Other"),
]

TRANSITIONS = [
    ("new", "under-review", "intake", False),
    ("under-review", "validated", "intake", False),
    ("under-review", "invalid", "intake", True),
    ("under-review", "need-more-information", "intake", True),
    ("under-review", "completed", "intake", True),
    ("need-more-information", "under-review", "requester", True),
    ("validated", "assigned", "intake", False),
    ("assigned", "in-progress", "worker", False),
    ("in-progress", "blocked", "worker", True),
    ("blocked", "in-progress", "worker", True),
    ("in-progress", "waiting-for-requester", "worker", True),
    ("waiting-for-requester", "in-progress", "worker", True),
    ("in-progress", "waiting-for-meeting", "worker", True),
    ("waiting-for-meeting", "in-progress", "worker", True),
    ("in-progress", "ready-for-it-verification", "worker", True),
    ("ready-for-it-verification", "ready-for-verification", "intake", False),
    ("ready-for-it-verification", "in-progress", "intake", True),
    ("ready-for-verification", "completed", "requester", False),
    ("ready-for-verification", "verification-failed", "requester", True),
    ("verification-failed", "reopened", "requester", False),
    ("reopened", "in-progress", "worker", False),
    ("completed", "closed", "closer", False),
]


class Command(BaseCommand):
    help = "Insert or refresh code-defined reference data without changing divisions or roles."

    @transaction.atomic
    def handle(self, *args, **options):
        for name in CATEGORY_NAMES:
            code = name.lower().replace(" / ", "-").replace(" ", "-")
            TicketCategory.objects.update_or_create(
                code=code, defaults={"name": name, "is_active": True},
            )

        # Move every rank out of the canonical range before assigning defaults.
        TicketPriority.objects.update(rank=10000 + F("rank"))
        for code, name, rank, color in PRIORITIES:
            priority = (
                TicketPriority.objects.filter(code=code).first()
                or TicketPriority.objects.filter(name__iexact=name).first()
            )
            if priority is None:
                priority = TicketPriority(code=code)
            priority.code = code
            priority.name = name
            priority.rank = rank
            priority.color = color
            priority.is_active = True
            priority.save()

        default_codes = {code for code, *_ in PRIORITIES}
        TicketPriority.objects.exclude(code__in=default_codes).update(is_active=False)

        for order, (code, name, kind, color) in enumerate(STATUSES, start=1):
            WorkflowStatus.objects.update_or_create(
                code=code,
                defaults={
                    "name": name, "kind": kind, "color": color,
                    "sort_order": order, "is_active": True,
                },
            )

        roles = {
            "intake": Role.objects.filter(code__in=["super-admin", "senior-it-consultant"]),
            "worker": Role.objects.filter(code__in=["super-admin", "officer"]),
            "requester": Role.objects.all(),
            "closer": Role.objects.filter(
                code__in=["super-admin", "senior-it-consultant"],
            ) | Role.objects.filter(is_division_director=True),
        }
        statuses = {item.code: item for item in WorkflowStatus.objects.all()}
        for source, target, role_group, requires_comment in TRANSITIONS:
            transition, _ = StatusTransition.objects.update_or_create(
                from_status=statuses[source],
                to_status=statuses[target],
                defaults={
                    "name": f"{statuses[source].name} to {statuses[target].name}",
                    "requires_comment": requires_comment,
                    "is_active": True,
                },
            )
            transition.allowed_roles.set(roles[role_group])

        for code, name in MEETING_TYPES:
            MeetingType.objects.update_or_create(
                code=code, defaults={"name": name, "is_active": True},
            )

        self.stdout.write(self.style.SUCCESS("Reference data is ready."))
