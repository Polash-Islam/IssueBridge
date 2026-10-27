from django.db import migrations


def rename_status(apps, schema_editor):
    WorkflowStatus = apps.get_model("tickets", "WorkflowStatus")
    WorkflowStatus.objects.filter(code="verification-failed").update(name="Problem Still Exists")

    # Older code immediately changed a failed requester verification to
    # In Progress. Restore that visible failure state when that automatic
    # transition is still the ticket's latest status change.
    Ticket = apps.get_model("tickets", "Ticket")
    TicketHistory = apps.get_model("tickets", "TicketHistory")
    TicketVerification = apps.get_model("tickets", "TicketVerification")
    failed_status = WorkflowStatus.objects.filter(code="verification-failed").first()
    in_progress = WorkflowStatus.objects.filter(code="in-progress").first()
    if not failed_status or not in_progress:
        return
    tickets = Ticket.objects.filter(status=in_progress).iterator()
    for ticket in tickets:
        last_status_event = TicketHistory.objects.filter(
            ticket=ticket, action="STATUS_CHANGED",
        ).order_by("-created_at", "-pk").first()
        if not last_status_event:
            continue
        if (
            last_status_event.previous_value.get("status") != "Verification Failed"
            or last_status_event.new_value.get("status") != "In Progress"
            or last_status_event.actor_id != ticket.requester_id
        ):
            continue
        if TicketVerification.objects.filter(
            ticket=ticket, verified_by_id=ticket.requester_id, decision="FAILED",
        ).exists():
            Ticket.objects.filter(pk=ticket.pk).update(status=failed_status)


def restore_status_name(apps, schema_editor):
    WorkflowStatus = apps.get_model("tickets", "WorkflowStatus")
    WorkflowStatus.objects.filter(code="verification-failed").update(name="Verification Failed")


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0007_ticketintakeroute_two_users"),
    ]

    operations = [
        migrations.RunPython(rename_status, restore_status_name),
    ]
