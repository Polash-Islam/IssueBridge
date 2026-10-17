from django.db import migrations


LEGACY_IT_NAME = "administration, accounts and information technology"


def merge_legacy_it_division(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    legacy = next(
        (
            division
            for division in Division.objects.all()
            if " ".join(division.name.casefold().split()).removesuffix(" division")
            == LEGACY_IT_NAME
            and division.code != "IT"
        ),
        None,
    )
    if legacy is None:
        return

    canonical = Division.objects.filter(code="IT").first()
    if canonical is None:
        legacy.code = "IT"
        legacy.name = "Administration, Accounts and Information Technology Division"
        legacy.is_active = True
        legacy.save(update_fields=["code", "name", "is_active"])
        return
    if canonical.pk == legacy.pk:
        return

    # Move every division relationship except Role. Legacy role rows can stay
    # attached to the inactive division; user accounts and operational data
    # must point at the canonical IT division. Map each user's old role to an
    # equivalent role in IT, creating that role if this install used a local
    # role such as the generic "Officer" role.
    Role = apps.get_model("accounts", "Role")
    User = apps.get_model("accounts", "User")
    for role in Role.objects.filter(division=legacy):
        replacement, _ = Role.objects.get_or_create(
            division=canonical,
            code=role.code,
            defaults={
                "name": role.name,
                "description": role.description,
                "scope": role.scope,
                "is_system": role.is_system,
                "is_division_director": role.is_division_director,
            },
        )
        User.objects.filter(division=legacy, role=role).update(role=replacement)

    for model in apps.get_models():
        if model._meta.label_lower == "accounts.role":
            continue
        for field in model._meta.fields:
            remote = getattr(field, "remote_field", None)
            if remote and remote.model._meta.label_lower == "core.division":
                model.objects.filter(**{field.attname: legacy.pk}).update(
                    **{field.attname: canonical.pk}
                )

    legacy.is_active = False
    legacy.save(update_fields=["is_active"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_seed_registration_divisions"),
        ("tickets", "0006_ticketintakeroute"),
    ]

    operations = [
        migrations.RunPython(merge_legacy_it_division, migrations.RunPython.noop),
    ]
