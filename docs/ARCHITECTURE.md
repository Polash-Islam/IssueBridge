# IssueBridge · FRC Internal Management Portal Architecture

## 1. System architecture

The first release is a modular Django application backed by PostgreSQL.

```text
Browser
  -> Django templates + small progressive JavaScript helpers
  -> View / form layer (validation, request/response)
  -> Domain services (workflow, assignment, audit, notifications)
  -> Django ORM
  -> PostgreSQL
```

Modules are separated by responsibility:

- `accounts`: custom users, configurable roles, designations, division membership.
- `core`: divisions and shared presentation/context utilities.
- `tickets`: products, categories, priorities, configurable statuses and transitions,
  tickets, assignments, comments, attachments, and immutable history.
- `communications`: meetings, participants, meeting history, and in-app notifications.
- `dashboard`: role-aware operational summaries.

Business transitions belong in `tickets.services`, not in templates or model signals.
That makes rules testable and leaves a clean seam for a future REST API, Celery jobs,
email/SMS delivery, and AI classification services.

PostgreSQL is the default runtime database. SQLite can be enabled only with
`USE_SQLITE=1` for isolated local tests and CI bootstrapping.

## 2. Database / ERD

```text
Division 1---* User *---1 Role
Division 1---* Product

Division 1---* Ticket *---1 Product
User     1---* Ticket (requester)
Category 1---* Ticket
Priority 1---* Ticket
WorkflowStatus 1---* Ticket

WorkflowStatus 1---* StatusTransition *---1 WorkflowStatus
Role *---* StatusTransition (roles permitted to perform it)

Ticket 1---* TicketAssignment *---1 User
Ticket 1---* TicketComment *---1 User
Ticket 1---* TicketAttachment *---1 User
Ticket 1---* TicketHistory *---1 User
Ticket *---* User (watchers)
```

Important integrity rules:

- Human ticket IDs are generated from a locked per-division/year sequence, such as
  `APR-2026-0001`.
- A product belongs to one division.
- Ticket status is a foreign key to configurable workflow data.
- Assignments keep start/end timestamps, so reassignment never destroys history.
- Each material mutation writes a `TicketHistory` row in the same transaction.
- Normal users cannot update or delete history records through the application.
- Indexed fields cover ticket number, requester division, status, assignee, deadline,
  created time, and search/filter dimensions.

## 3. Role and permission matrix

| Capability | Super Admin | Director | Senior IT Consultant | Officer | General User |
|---|---:|---:|---:|---:|---:|
| View all tickets | Yes | Division scope | Yes (IT intake) | Assigned/participating | Own/division-visible |
| Create ticket | Yes | Yes | Yes | Yes | Yes |
| Review IT intake | Yes | No | Yes | No | No |
| Assign/reassign IT work | Yes | No | Yes | No | No |
| Update work status | Yes | Limited | Yes | Assigned tickets | Limited |
| Add public comments | Yes | Yes | Yes | Yes | Yes |
| Add internal IT comments | Yes | No | Yes | IT officers only | No |
| Manage users | All | Own division | No | No | No |
| Manage configuration | Yes | No | No | No | No |
| View audit/history | All | Division scope | IT scope | Accessible tickets | Accessible tickets |

Object-level checks are applied before ticket retrieval. Knowing a URL or ticket ID is
not sufficient to access a restricted ticket.

## 4. Ticket lifecycle

```text
NEW -> UNDER REVIEW
  -> NEED MORE INFORMATION -> UNDER REVIEW
  -> INVALID
  -> VALIDATED -> ASSIGNED -> IN PROGRESS
                           -> BLOCKED -> IN PROGRESS
                           -> WAITING FOR REQUESTER -> IN PROGRESS
                           -> WAITING FOR MEETING -> IN PROGRESS
                           -> READY FOR VERIFICATION
                                -> COMPLETED -> CLOSED
                                -> VERIFICATION FAILED -> REOPENED -> IN PROGRESS
```

The path is stored as configuration (`WorkflowStatus` + `StatusTransition`). Services
also enforce guards: assignment is required before work starts, a rejection requires a
reason, and only the requester/division verifier can confirm resolution. Drag-and-drop
clients added in Phase 2 will call the same guarded service.

## 5. Main page structure

- Sign in
- Dashboard (role-aware metrics, workload, recent activity)
- Tickets
  - All accessible tickets
  - My tickets
  - Assigned to me
  - Create ticket
  - Ticket workspace/detail
- Users (admin/director scope)
- Divisions and configuration (admin)
- Kanban board with server-validated drag-and-drop transitions
- Meetings, notifications, and operational calendar
- Reports and CSV/XLSX/PDF exports

The ticket workspace keeps the description, expected/actual behavior, comments,
attachments, and timeline in the main column, with ownership, priority, product,
status, dates, assignment, and workflow actions in a concise sidebar.

## 6. UI component structure

The UI uses reusable Django partials and one local design system stylesheet:

- application shell (sidebar, header, account menu)
- metric cards and mini charts
- status/priority badges
- filter/search toolbar
- ticket table and compact ticket cards
- form fields and upload drop zone
- comment composer with public/internal visibility
- immutable activity timeline
- empty states, flash messages, validation errors, and confirmation prompts

Server rendering keeps Phase 1 simple and secure. Small JavaScript modules add sidebar
behavior, file previews, and dismissible notices without making core flows dependent on
JavaScript.

one more thing this project can host on local like vercel or netlify etc.
