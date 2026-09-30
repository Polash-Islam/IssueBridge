from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User
from core.models import Division
from communications.models import Meeting, MeetingHistory, MeetingParticipant, MeetingSequence, MeetingType, Notification
from tickets.models import (
    Product, StatusTransition, Ticket, TicketAssignment, TicketCategory, TicketComment,
    TicketHistory, TicketNumberSequence, TicketPriority, WorkflowStatus,
)


class Command(BaseCommand):
    help = "Create FRC configuration. Demo users/data are created only with --with-demo-data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-demo-data", action="store_true",
            help="Also create fictional users, tickets, meetings, and notifications for local demonstrations.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        divisions = {}
        for code, name in [("APR", "Audit Practice Review"), ("FRM", "Financial Reporting Monitoring"), ("ENF", "Enforcement"), ("IT", "Information Technology")]:
            divisions[code], _ = Division.objects.update_or_create(code=code, defaults={"name": name, "is_active": True})

        role_specs = [
            ("super-admin", "Super Admin", "GLOBAL"), ("director", "Director", "DIVISION"),
            ("senior-it-consultant", "Senior IT Consultant", "GLOBAL"),
            ("senior-officer", "Senior Officer / Consultant", "DIVISION"),
            ("officer", "Officer", "OWN"), ("general-user", "General User", "OWN"),
        ]
        roles = {}
        for code, name, scope in role_specs:
            roles[code], _ = Role.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "scope": scope,
                    "is_system": True,
                    "is_division_director": code == "director",
                },
            )

        category_names = [
            "Bug / Software Error", "UI / Design Issue", "Data Change", "Data Error", "New Feature Request",
            "Existing Feature Modification", "Access / Permission Issue", "Performance Issue", "Report Issue",
            "Documentation Issue", "General Support", "Meeting / Discussion Request", "Other",
        ]
        categories = {}
        for name in category_names:
            code = name.lower().replace(" / ", "-").replace(" ", "-")
            categories[name], _ = TicketCategory.objects.update_or_create(code=code, defaults={"name": name, "is_active": True})

        for rank, (code, name, color) in enumerate([
            ("low", "Low", "#5f8e73"), ("medium", "Medium", "#3d79b7"), ("high", "High", "#e18432"),
            ("urgent", "Urgent", "#dd5850"), ("critical", "Critical", "#a93445"),
        ], start=1):
            TicketPriority.objects.update_or_create(code=code, defaults={"name": name, "rank": rank, "color": color, "is_active": True})

        status_specs = [
            ("new", "New", "OPEN", "#4f7fa9"), ("under-review", "Under Review", "ACTIVE", "#7161b7"),
            ("need-more-information", "Need More Information", "WAITING", "#c0842f"),
            ("validated", "Validated", "OPEN", "#31836b"), ("invalid", "Invalid", "CLOSED", "#7a8590"),
            ("assigned", "Assigned", "ACTIVE", "#327bb8"), ("in-progress", "In Progress", "ACTIVE", "#286fb4"),
            ("blocked", "Blocked", "WAITING", "#ca4d4d"), ("waiting-for-requester", "Waiting for Requester", "WAITING", "#c17c2b"),
            ("waiting-for-meeting", "Waiting for Meeting", "WAITING", "#9c6bb6"),
            ("ready-for-it-verification", "Ready for IT Verification", "WAITING", "#4868c7"),
            ("ready-for-verification", "Ready for Verification", "WAITING", "#7656d8"),
            ("verification-failed", "Verification Failed", "ACTIVE", "#d15151"),
            ("reopened", "Reopened", "ACTIVE", "#d05d52"), ("completed", "Completed", "RESOLVED", "#21835f"),
            ("closed", "Closed", "CLOSED", "#526575"), ("cancelled", "Cancelled", "CLOSED", "#7d8790"),
        ]
        statuses = {}
        for order, (code, name, kind, color) in enumerate(status_specs, start=1):
            statuses[code], _ = WorkflowStatus.objects.update_or_create(code=code, defaults={"name": name, "kind": kind, "color": color, "sort_order": order, "is_active": True})

        all_roles = list(roles.values())
        intake_roles = [roles["super-admin"], roles["senior-it-consultant"]]
        worker_roles = [roles["super-admin"], roles["officer"]]
        requester_roles = all_roles
        transitions = [
            ("new", "under-review", intake_roles, False),
            ("under-review", "validated", intake_roles, False), ("under-review", "invalid", intake_roles, True),
            ("under-review", "need-more-information", intake_roles, True), ("under-review", "completed", intake_roles, True),
            ("need-more-information", "under-review", requester_roles, True),
            ("validated", "assigned", intake_roles, False), ("assigned", "in-progress", worker_roles, False),
            ("in-progress", "blocked", worker_roles, True), ("blocked", "in-progress", worker_roles, True),
            ("in-progress", "waiting-for-requester", worker_roles, True), ("waiting-for-requester", "in-progress", worker_roles, True),
            ("in-progress", "waiting-for-meeting", worker_roles, True), ("waiting-for-meeting", "in-progress", worker_roles, True),
            ("in-progress", "ready-for-it-verification", worker_roles, True),
            ("ready-for-it-verification", "ready-for-verification", intake_roles, False),
            ("ready-for-it-verification", "in-progress", intake_roles, True),
            ("ready-for-verification", "completed", requester_roles, False),
            ("ready-for-verification", "verification-failed", requester_roles, True),
            ("verification-failed", "reopened", requester_roles, False), ("reopened", "in-progress", worker_roles, False),
            ("completed", "closed", [roles["super-admin"], roles["director"], roles["senior-it-consultant"]], False),
        ]
        for source, target, allowed, requires_comment in transitions:
            transition, _ = StatusTransition.objects.update_or_create(
                from_status=statuses[source], to_status=statuses[target],
                defaults={"name": f"{statuses[source].name} to {statuses[target].name}", "requires_comment": requires_comment, "is_active": True},
            )
            transition.allowed_roles.set(allowed)
        # Retire the former shortcut so requester verification can never bypass
        # the Senior IT Consultant's technical check on existing installations.
        StatusTransition.objects.filter(
            from_status=statuses["in-progress"], to_status=statuses["ready-for-verification"],
        ).update(is_active=False)

        product_specs = [("APR", "APR Software", "apr-software"), ("APR", "Other APR System", "other-apr-system"), ("FRM", "FRM Software", "frm-software"), ("FRM", "Other FRM System", "other-frm-system"), ("ENF", "Enforcement Systems", "enforcement-systems"), ("IT", "Internal IT Services", "internal-it-services")]
        products = {}
        for division_code, name, code in product_specs:
            products[code], _ = Product.objects.update_or_create(code=code, defaults={"name": name, "division": divisions[division_code], "is_active": True})

        if not options["with_demo_data"]:
            self.stdout.write(self.style.SUCCESS("FRC configuration is ready. No demo users or sample records were created."))
            self.stdout.write("Use --with-demo-data only in an isolated local demo database.")
            return

        users = {}
        user_specs = [
            ("admin@frc.gov.bd", "System", "Administrator", "IT", "super-admin", "System Administrator", "DEMO-1001", True),
            ("it.director@frc.gov.bd", "Sharmeen", "Ahmed", "IT", "director", "Executive Director", "DEMO-1007", False),
            ("consultant@frc.gov.bd", "Nadia", "Rahman", "IT", "senior-it-consultant", "Senior IT Consultant", "DEMO-1002", False),
            ("it.officer@frc.gov.bd", "Arif", "Hasan", "IT", "officer", "IT Officer", "DEMO-1003", False),
            ("apr.officer@frc.gov.bd", "Farhana", "Islam", "APR", "officer", "Assistant Director", "DEMO-1004", False),
            ("apr.director@frc.gov.bd", "Mahmud", "Karim", "APR", "director", "Executive Director", "DEMO-1005", False),
            ("frm.officer@frc.gov.bd", "Tania", "Sultana", "FRM", "general-user", "Senior Officer", "DEMO-1006", False),
        ]
        for email, first, last, division, role, designation, employee_id, superuser in user_specs:
            user, created = User.objects.get_or_create(username=email, defaults={"email": email})
            user.email = email; user.first_name = first; user.last_name = last; user.division = divisions[division]
            user.role = roles[role]; user.designation = designation
            if created or not user.employee_id:
                user.employee_id = employee_id
            user.is_staff = superuser; user.is_superuser = superuser; user.is_active = True
            if created or not user.has_usable_password():
                user.set_password("FrcDemo2026!")
            user.save()
            users[email] = user

        users["consultant@frc.gov.bd"].supervisor = users["it.director@frc.gov.bd"]
        users["consultant@frc.gov.bd"].save(update_fields=["supervisor"])
        users["it.officer@frc.gov.bd"].supervisor = users["consultant@frc.gov.bd"]
        users["it.officer@frc.gov.bd"].save(update_fields=["supervisor"])
        users["apr.officer@frc.gov.bd"].supervisor = users["apr.director@frc.gov.bd"]
        users["apr.officer@frc.gov.bd"].save(update_fields=["supervisor"])

        meeting_types = {}
        for name, code in [
            ("IT + Division Meeting", "it-division"), ("One-to-One Discussion", "one-to-one"),
            ("Technical Discussion", "technical"), ("Requirement Discussion", "requirement"),
            ("Demonstration", "demonstration"), ("Other", "other"),
        ]:
            meeting_types[code], _ = MeetingType.objects.update_or_create(code=code, defaults={"name": name, "is_active": True})

        if not Ticket.objects.exists():
            demo_tickets = [
                ("APR", "APR Software — audit report PDF upload fails", "PDF files above 8 MB fail during final submission. The page returns a generic validation error.", "apr-software", "Bug / Software Error", "high", "in-progress", "it.officer@frc.gov.bd", 2),
                ("FRM", "Quarterly report totals do not match", "The summary total differs from the underlying schedule for Q3 submissions.", "frm-software", "Report Issue", "critical", "under-review", None, 1),
                ("APR", "Add reviewer name to exported report", "Please include the assigned reviewer name in the final PDF export.", "apr-software", "Existing Feature Modification", "medium", "ready-for-it-verification", "it.officer@frc.gov.bd", -1),
                ("ENF", "New user access for case register", "A newly joined officer requires access to the enforcement case register.", "enforcement-systems", "Access / Permission Issue", "medium", "new", None, 5),
            ]
            year = timezone.localdate().year
            for index, (division_code, title, description, product_code, category, priority, status, assignee_email, due_days) in enumerate(demo_tickets, start=1):
                division = divisions[division_code]
                sequence, _ = TicketNumberSequence.objects.get_or_create(division=division, year=year)
                sequence.last_number += 1; sequence.save(update_fields=["last_number"])
                requester = users["apr.officer@frc.gov.bd"] if division_code in {"APR", "ENF"} else users["frm.officer@frc.gov.bd"]
                assignee = users.get(assignee_email)
                ticket = Ticket.objects.create(
                    ticket_number=f"{division.code}-{year}-{sequence.last_number:04d}", title=title, description=description,
                    expected_behavior="The operation should complete successfully and show the correct result.", actual_behavior=description,
                    requester=requester, identified_by=requester, requesting_division=division, product=products[product_code],
                    category=categories[category], priority=TicketPriority.objects.get(code=priority), status=statuses[status],
                    current_assignee=assignee, reviewed_by=users["consultant@frc.gov.bd"] if status != "new" else None,
                    problem_identified_at=timezone.now() - timedelta(days=index), deadline=timezone.now() + timedelta(days=due_days),
                )
                ticket.watchers.add(requester)
                TicketHistory.objects.create(ticket=ticket, actor=requester, action="TICKET_CREATED", description=f"Ticket created by {requester.full_name}")
                if assignee:
                    TicketAssignment.objects.create(ticket=ticket, assigned_to=assignee, assigned_by=users["consultant@frc.gov.bd"], task_description="Investigate the reported issue, implement a safe fix, and provide evidence for verification.", technical_instructions="Review application logs, reproduce in staging, and test the complete workflow.", deadline=ticket.deadline)
                    TicketHistory.objects.create(ticket=ticket, actor=users["consultant@frc.gov.bd"], action="TICKET_ASSIGNED", description=f"Assigned to {assignee.full_name}")
                TicketComment.objects.create(ticket=ticket, author=requester, body="Please let me know if you need any additional information.", visibility="PUBLIC")

        if not Meeting.objects.exists():
            year = timezone.localdate().year
            meetings = [
                Meeting.objects.create(
                    reference=f"MTG-{year}-0001", title="APR upload validation review",
                    reason="Confirm the remaining file-size requirements and deployment plan.",
                    description="Review the reproduced issue, agree the accepted upload limit, and confirm verification steps.",
                    meeting_type=meeting_types["technical"], requested_by=users["consultant@frc.gov.bd"], organizer=users["consultant@frc.gov.bd"],
                    ticket=Ticket.objects.filter(requesting_division__code="APR").first(),
                    scheduled_start=timezone.now() + timedelta(days=1, hours=2), scheduled_end=timezone.now() + timedelta(days=1, hours=3),
                    location_link="Conference Room 2", status=Meeting.Status.ACCEPTED,
                ),
                Meeting.objects.create(
                    reference=f"MTG-{year}-0002", title="FRM quarterly totals requirement discussion",
                    reason="Walk through calculation rules before the technical investigation continues.",
                    description="FRM will demonstrate the expected schedule and provide two sample submissions.",
                    meeting_type=meeting_types["requirement"], requested_by=users["frm.officer@frc.gov.bd"], organizer=users["frm.officer@frc.gov.bd"],
                    ticket=Ticket.objects.filter(requesting_division__code="FRM").first(),
                    scheduled_start=timezone.now() + timedelta(days=3), scheduled_end=timezone.now() + timedelta(days=3, hours=1),
                    location_link="Microsoft Teams", status=Meeting.Status.REQUESTED,
                ),
            ]
            for meeting in meetings:
                participant_users = [meeting.requested_by, users["consultant@frc.gov.bd"], users["it.officer@frc.gov.bd"]]
                for participant in {user.pk: user for user in participant_users}.values():
                    MeetingParticipant.objects.create(
                        meeting=meeting, user=participant,
                        response=MeetingParticipant.Response.ACCEPTED if participant == meeting.requested_by else MeetingParticipant.Response.PENDING,
                        responded_at=timezone.now() if participant == meeting.requested_by else None,
                    )
                MeetingHistory.objects.create(meeting=meeting, actor=meeting.requested_by, action="REQUESTED", description=f"Meeting requested by {meeting.requested_by.full_name}")
            MeetingSequence.objects.update_or_create(year=year, defaults={"last_number": 2})

        sample_ticket = Ticket.objects.filter(current_assignee=users["it.officer@frc.gov.bd"]).first()
        if sample_ticket:
            Notification.objects.get_or_create(
                recipient=users["it.officer@frc.gov.bd"], kind=Notification.Kind.ASSIGNED,
                verb=f"assigned {sample_ticket.ticket_number} to you", ticket=sample_ticket,
                defaults={"actor": users["consultant@frc.gov.bd"]},
            )
        intake_ticket = Ticket.objects.filter(status__code="new").first()
        if intake_ticket:
            Notification.objects.get_or_create(
                recipient=users["consultant@frc.gov.bd"], kind=Notification.Kind.TICKET_CREATED,
                verb=f"created {intake_ticket.ticket_number}", ticket=intake_ticket,
                defaults={"actor": intake_ticket.requester},
            )
        sample_meeting = Meeting.objects.first()
        if sample_meeting:
            Notification.objects.get_or_create(
                recipient=users["it.officer@frc.gov.bd"], kind=Notification.Kind.MEETING,
                verb=f"invited you to {sample_meeting.title}", meeting=sample_meeting,
                defaults={"actor": sample_meeting.requested_by},
            )

        self.stdout.write(self.style.SUCCESS("FRC configuration and demo data are ready."))
        self.stdout.write("Demo password for seeded accounts: FrcDemo2026!")
