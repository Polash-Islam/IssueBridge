from django.conf import settings
from django.db import migrations, models


def copy_existing_route(apps, schema_editor):
    Route = apps.get_model("tickets", "TicketIntakeRoute")
    for route in Route.objects.select_related("selected_user").iterator():
        route.selected_users.add(route.selected_user)


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0006_ticketintakeroute"),
        ("accounts", "0009_merge_legacy_it_division"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketintakeroute",
            name="selected_users",
            field=models.ManyToManyField(related_name="ticket_intake_routes", to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(copy_existing_route, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="ticketintakeroute",
            name="selected_user",
        ),
    ]
