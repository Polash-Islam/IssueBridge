from django.db import migrations
from django.db.models import F


PRIORITIES = [
    ("moderate", "Moderate", 1, "#3d79b7"),
    ("high", "High", 2, "#e18432"),
    ("urgent", "Urgent", 3, "#dd5850"),
]


def normalize_priorities(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    TicketPriority = apps.get_model("tickets", "TicketPriority")

    TicketPriority.objects.update(rank=10000 + F("rank"), is_active=False)
    canonical = {}
    for code, name, rank, color in PRIORITIES:
        priority = TicketPriority.objects.filter(code=code).first()
        if priority is None:
            priority = TicketPriority.objects.filter(name__iexact=name).first()
        if priority is None:
            priority = TicketPriority(code=code)
        priority.code = code
        priority.name = name
        priority.rank = rank
        priority.color = color
        priority.is_active = True
        priority.save()
        canonical[code] = priority

    for old_code in ("low", "medium"):
        Ticket.objects.filter(priority__code=old_code).update(priority=canonical["moderate"])
    Ticket.objects.filter(priority__code="critical").update(priority=canonical["urgent"])


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0004_remove_ticket_problem_identified_at"),
    ]

    operations = [
        migrations.RunPython(normalize_priorities, migrations.RunPython.noop),
    ]
