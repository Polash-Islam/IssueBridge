from django.db import migrations


DIVISIONS = [
    ("SS", "Standard Setting Division"),
    ("FRM", "Financial Report Monitoring Division"),
    ("APR", "Audit Practice Review Division"),
    ("IT", "Administration, Accounts and Information Technology Division"),
    ("ENF", "Enforcement Division"),
]

DIVISION_ROLES = {
    "SS": ["Division Head", "Executive Officer", "Assistant Director", "Standard Setting Officer", "Administrative Officer", "Intern"],
    "FRM": ["Division Head", "Executive Officer", "Assistant Director", "Administrative Officer", "Intern"],
    "APR": ["Division Head", "Executive Officer", "Assistant Director", "Audit Practice Officer", "Administrative Officer", "Intern"],
    "IT": ["Division Head", "Executive Officer", "Assistant Director", "IT Consultant", "Junior IT Consultant", "Administrative Officer", "Intern"],
    "ENF": ["Division Head", "Executive Officer", "Assistant Director", "Administrative Officer", "Intern"],
}

ROLE_CODES = {
    "Division Head": "director",
    "Executive Officer": "executive-officer",
    "Assistant Director": "assistant-director",
    "Standard Setting Officer": "standard-setting-officer",
    "Audit Practice Officer": "audit-practice-officer",
    "Administrative Officer": "administrative-officer",
    "Intern": "intern",
    "IT Consultant": "senior-it-consultant",
    "Junior IT Consultant": "junior-it-consultant",
}


def seed_registration_data(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    Role = apps.get_model("accounts", "Role")

    divisions = {}
    for code, name in DIVISIONS:
        division, _ = Division.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_active": True},
        )
        divisions[code] = division

    Division.objects.exclude(code__in=[code for code, _ in DIVISIONS]).update(is_active=False)

    for division_code, role_names in DIVISION_ROLES.items():
        division = divisions[division_code]
        for role_name in role_names:
            Role.objects.update_or_create(
                division=division,
                code=ROLE_CODES[role_name],
                defaults={
                    "name": role_name,
                    "scope": "DIVISION" if role_name == "Division Head" else "OWN",
                    "is_system": True,
                    "is_division_director": role_name == "Division Head",
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_alter_role_code_alter_role_name_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_registration_data, migrations.RunPython.noop),
    ]
