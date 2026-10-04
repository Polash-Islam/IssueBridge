from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0003_alter_tickettechnicalverification_decision"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="ticket",
            name="problem_identified_at",
        ),
    ]
