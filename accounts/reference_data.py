from core.models import Division
from .models import Role


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
ROLE_NAMES_BY_CODE = {code: name for name, code in ROLE_CODES.items()}


def seed_account_reference_data():
    divisions = {}
    for code, name in DIVISIONS:
        divisions[code], _ = Division.objects.update_or_create(
            code=code, defaults={"name": name, "is_active": True},
        )
    Division.objects.exclude(code__in=[code for code, _ in DIVISIONS]).update(is_active=False)
    # Keep the legacy code used by existing ticket data, while ensuring every
    # public registration role belongs to the selected division.
    for code, division in divisions.items():
        for name in DIVISION_ROLES[code]:
            role_code = ROLE_CODES[name]
            role, _ = Role.objects.update_or_create(
                division=division, code=role_code,
                defaults={
                    "name": name,
                    "scope": Role.Scope.DIVISION if name == "Division Head" else Role.Scope.OWN,
                    "is_system": True,
                    "is_division_director": name == "Division Head",
                },
            )
    return divisions
