from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from accounts.models import Role
from tickets.models import StatusTransition, WorkflowStatus
from .seed_reference_data import STATUSES, TRANSITIONS


class Command(BaseCommand):
    help = "Add missing workflow statuses and transitions, preserving existing configuration."

    @transaction.atomic
    def handle(self, *args, **options):
        statuses = {}
        for order, (code, name, kind, color) in enumerate(STATUSES, start=1):
            statuses[code], _ = WorkflowStatus.objects.get_or_create(
                code=code,
                defaults={"name": name, "kind": kind, "color": color, "sort_order": order},
            )
        roles = {
            "intake": Role.objects.filter(code__in=["super-admin", "senior-it-consultant"]),
            "worker": Role.objects.filter(code__in=["super-admin", "officer"]),
            "requester": Role.objects.all(),
            "closer": Role.objects.filter(
                Q(code__in=["super-admin", "senior-it-consultant"]) | Q(is_division_director=True)
            ),
        }
        for source, target, group, requires_comment in TRANSITIONS:
            transition, created = StatusTransition.objects.get_or_create(
                from_status=statuses[source], to_status=statuses[target],
                defaults={
                    "name": f"{statuses[source].name} to {statuses[target].name}",
                    "requires_comment": requires_comment,
                },
            )
            if created:
                transition.allowed_roles.set(roles[group])
        self.stdout.write(self.style.SUCCESS("Missing workflow configuration added."))
