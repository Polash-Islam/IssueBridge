from django.db import migrations, models
from django.db.models import Q


def configure_director_and_officer_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(
        Q(code="director")
        | Q(name__istartswith="ED ")
        | Q(name__iexact="Division Chief")
    ).update(is_division_director=True)
    Role.objects.get_or_create(
        code="officer",
        defaults={
            "name": "Officer",
            "scope": "OWN",
            "is_system": True,
            "is_division_director": False,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_accountapprovalrequest")]

    operations = [
        migrations.AddField(
            model_name="role",
            name="is_division_director",
            field=models.BooleanField(
                default=False,
                help_text="Users with this role act as the head/director of their assigned division.",
            ),
        ),
        migrations.RunPython(configure_director_and_officer_roles, migrations.RunPython.noop),
    ]
