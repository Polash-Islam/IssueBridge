# IssueBridge · FRC Internal Management Portal

A professional Django/PostgreSQL service workspace for the Financial Reporting Council.
The implemented release includes authentication, scoped user management, role-aware
dashboards, ticket intake, IT review, assignment, guarded workflow transitions, requester
verification, public and internal comments, attachments, and immutable history. It also
includes a drag-and-drop Kanban board, meeting workflows, in-app notifications, a combined
deadline/meeting calendar, and permission-scoped reports with CSV, Excel, and PDF exports.

The system design, ERD, permission matrix, lifecycle, page structure, and UI structure are
documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Local setup (PostgreSQL)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres
```

The application loads `.env` automatically. Then run:

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
python manage.py runserver
```

`seed_demo` creates only divisions, roles, products, statuses, and workflow configuration; it does not create users or sample records. For an isolated development database only, run:

```bash
python manage.py seed_demo --with-demo-data
```

The optional fictional accounts include:

- `admin@frc.gov.bd`
- `it.director@frc.gov.bd`
- `consultant@frc.gov.bd`
- `it.officer@frc.gov.bd`
- `apr.officer@frc.gov.bd`
- `apr.director@frc.gov.bd`
- `frm.officer@frc.gov.bd`

For isolated local demo data only, their password is `FrcDemo2026!`. Change all credentials before
using the project outside a local development environment.

## Implemented modules

- Ticket service desk with configurable workflow and human-friendly IDs
- Two-stage resolution approval: Senior IT technical verification, then requester confirmation
- Hierarchical account management, user profiles, self-service profile/password edits, and profile photos
- Public Officer registration with division-Director approval and a one-day pending-account expiry
- Kanban board that uses the same guarded workflow service as ticket detail actions
- Meeting requests, participants, responses, rescheduling, completion, and history
- Notification center for ticket, assignment, comment, verification, and meeting events
- Operational calendar combining ticket deadlines and meetings
- Attention counters in the sidebar for assignments, verification, meetings, and notifications
- Filterable all-status reports with division, product, category, workload, SLA indicators, and exports

## Test

Tests can run without provisioning PostgreSQL by enabling the explicit test fallback:

```bash
USE_SQLITE=1 python manage.py test
```

PostgreSQL remains the default application database.

## Pending-account cleanup

Pending Officer registrations are removed on the first request after their one-day approval
window expires. In production, also schedule the following command every few minutes so expiry
does not depend on site traffic:

```bash
python manage.py purge_expired_accounts
```

Directors can approve only Officer requests for their own division. Senior IT Consultants and
the IT Division Director have organization-wide ticket visibility; other Directors are scoped to
their division, while Officers see their division's board plus work explicitly assigned to or
requested by them. Officer dashboards intentionally show only personal activity and deadlines.

## Production checklist

- Set a strong `SECRET_KEY` and `DEBUG=0`.
- Set exact `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and secure-cookie settings.
- Use private object storage in production; application downloads already enforce object-level access.
- Run behind TLS and a reverse proxy; configure backups and PostgreSQL connection limits.
- Replace demo credentials and add organizational SSO/MFA before rollout.
