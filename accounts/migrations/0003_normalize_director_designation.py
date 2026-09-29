from django.db import migrations


def normalize_director_designations(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role__code="director").update(designation="Executive Director")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_user_supervisor")]

    operations = [migrations.RunPython(normalize_director_designations, migrations.RunPython.noop)]
