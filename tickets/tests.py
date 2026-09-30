from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from communications.models import Notification
from .access import visible_tickets_for
from .models import (
    Product, Ticket, TicketAttachment, TicketCategory, TicketPriority, TicketReview,
    TicketTechnicalVerification, TicketVerification, WorkflowStatus,
)
from .services import assign_ticket, review_ticket, technical_verify_ticket, transition_ticket, verify_ticket


class TicketWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", with_demo_data=True, verbosity=0)
        cls.requester = User.objects.get(email="apr.officer@frc.gov.bd")
        cls.consultant = User.objects.get(email="consultant@frc.gov.bd")
        cls.it_officer = User.objects.get(email="it.officer@frc.gov.bd")

    def test_division_user_cannot_discover_other_division_ticket(self):
        frm_ticket = Ticket.objects.filter(requesting_division__code="FRM").first()
        self.assertFalse(visible_tickets_for(self.requester).filter(pk=frm_ticket.pk).exists())
        self.client.force_login(self.requester)
        response = self.client.get(reverse("ticket_detail", args=[frm_ticket.ticket_number]))
        self.assertEqual(response.status_code, 404)

    def test_it_user_can_view_cross_division_intake(self):
        self.assertEqual(visible_tickets_for(self.consultant).count(), Ticket.objects.count())

    def test_it_officer_sees_own_division_or_assigned_work_not_every_ticket(self):
        visible = visible_tickets_for(self.it_officer)
        self.assertTrue(visible.filter(current_assignee=self.it_officer).exists())
        self.assertFalse(visible.filter(requesting_division__code="FRM", current_assignee=None).exists())

    def test_it_director_can_view_all_division_tickets(self):
        it_director = User.objects.get(email="it.director@frc.gov.bd")
        self.assertEqual(visible_tickets_for(it_director).count(), Ticket.objects.count())

    def test_review_and_assignment_follow_configured_workflow(self):
        ticket = Ticket.objects.get(status__code="new")
        review_ticket(ticket=ticket, actor=self.consultant, decision=TicketReview.Decision.VALID, reason="Confirmed")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "validated")
        self.assertEqual(ticket.reviewed_by, self.consultant)

        assignment = assign_ticket(
            ticket=ticket, actor=self.consultant, assigned_to=self.it_officer,
            task_description="Investigate and resolve", technical_instructions="Reproduce in staging",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "assigned")
        self.assertEqual(ticket.current_assignee, self.it_officer)
        self.assertTrue(assignment.is_active)
        self.assertTrue(ticket.history.filter(action="TICKET_ASSIGNED").exists())

    def test_requester_can_reject_verification_with_reason(self):
        ticket = Ticket.objects.get(status__code="ready-for-it-verification")
        technical_verify_ticket(
            ticket=ticket, actor=self.consultant,
            decision=TicketTechnicalVerification.Decision.APPROVED,
            reason="Technical tests passed.",
        )
        verify_ticket(
            ticket=ticket, actor=ticket.requester, decision=TicketVerification.Decision.FAILED,
            reason="The exported total is still incorrect.",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "reopened")
        self.assertTrue(ticket.verifications.filter(decision="FAILED").exists())

    def test_assigned_officer_can_mark_ready_for_verification(self):
        ticket = Ticket.objects.get(status__code="in-progress")
        target = WorkflowStatus.objects.get(code="ready-for-it-verification")
        transition_ticket(ticket=ticket, to_status=target, actor=self.it_officer, comment="Fix deployed and tested.")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, target)

    def test_senior_it_approval_is_required_before_requester_verification(self):
        ticket = Ticket.objects.get(status__code="in-progress")
        transition_ticket(
            ticket=ticket, to_status=WorkflowStatus.objects.get(code="ready-for-it-verification"),
            actor=self.it_officer, comment="Fix deployed with test evidence.",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "ready-for-it-verification")
        with self.assertRaises(PermissionDenied):
            verify_ticket(
                ticket=ticket, actor=ticket.requester,
                decision=TicketVerification.Decision.VERIFIED, reason="Trying too early.",
            )
        technical_verify_ticket(
            ticket=ticket, actor=self.consultant,
            decision=TicketTechnicalVerification.Decision.APPROVED,
            reason="Reviewed logs and regression results.",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "ready-for-verification")
        verify_ticket(
            ticket=ticket, actor=ticket.requester,
            decision=TicketVerification.Decision.VERIFIED, reason="Confirmed fixed.",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "completed")


class PageSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", with_demo_data=True, verbosity=0)
        cls.user = User.objects.get(email="consultant@frc.gov.bd")

    def setUp(self):
        self.client.force_login(self.user)

    def test_core_pages_render(self):
        for url in [reverse("dashboard"), reverse("ticket_list"), reverse("ticket_create")]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_ticket_comment_author_label_handles_missing_division(self):
        ticket = Ticket.objects.first()
        author = User.objects.create_user(
            username="comment-author", email="comment-author@example.com",
            first_name="Comment", last_name="Author",
        )
        ticket.comments.create(author=author, body="Comment from an optional profile.")
        division = self.user.division
        for designation, author_division, expected in [
            ("", None, ""),
            ("Support specialist", None, "Support specialist"),
            ("", division, division.code),
            ("Support specialist", division, "Support specialist"),
        ]:
            with self.subTest(designation=designation, division=author_division):
                author.designation = designation
                author.division = author_division
                author.save(update_fields=["designation", "division"])
                response = self.client.get(ticket.get_absolute_url())
                self.assertContains(
                    response,
                    f"<strong>Comment Author</strong><span>{expected}</span>",
                    html=True,
                )

    def test_dashboard_is_full_for_senior_it_and_focused_for_officer(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Division workload")
        officer = User.objects.get(email="it.officer@frc.gov.bd")
        self.client.force_login(officer)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Division workload")
        self.assertContains(response, "My recent activity")

    def _ticket_payload(self, *, requester, title, requested_for=None, assign_to=None, product=None):
        payload = {
            "title": title,
            "description": "A sufficiently detailed issue description for workflow testing.",
            "requesting_division": requester.division_id,
            "product": (product or Product.objects.filter(division=requester.division, is_active=True).first()).pk,
            "category": TicketCategory.objects.filter(is_active=True).first().pk,
            "priority": TicketPriority.objects.filter(is_active=True).first().pk,
            "problem_identified_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        }
        if requested_for:
            payload["requested_for"] = requested_for.pk
        if assign_to:
            payload["assign_to"] = assign_to.pk
        return payload

    def test_senior_it_can_create_ticket_for_any_active_user(self):
        frm_user = User.objects.get(email="frm.officer@frc.gov.bd")
        response = self.client.get(reverse("ticket_create"))
        self.assertContains(response, "Requester / ticket owner")
        self.assertContains(response, "Assign work to")
        self.assertContains(response, frm_user.email)

        response = self.client.post(
            reverse("ticket_create"),
            self._ticket_payload(
                requester=frm_user, requested_for=frm_user, assign_to=frm_user,
                title="Ticket submitted for FRM requester",
            ),
        )
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(title="Ticket submitted for FRM requester")
        self.assertEqual(ticket.requester, frm_user)
        self.assertEqual(ticket.identified_by, self.user)
        self.assertEqual(ticket.current_assignee, frm_user)
        self.assertEqual(ticket.status.code, "assigned")
        self.assertTrue(ticket.watchers.filter(pk=frm_user.pk).exists())
        self.assertTrue(Notification.objects.filter(recipient=frm_user, ticket=ticket).exists())

        transition_ticket(
            ticket=ticket, to_status=WorkflowStatus.objects.get(code="in-progress"),
            actor=frm_user,
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "in-progress")

    def test_senior_it_can_route_cross_division_product_to_any_user(self):
        requester = User.objects.get(email="consultant@frc.gov.bd")
        assignee = User.objects.get(email="frm.officer@frc.gov.bd")
        apr_product = Product.objects.filter(division__code="APR", is_active=True).first()
        response = self.client.post(
            reverse("ticket_create"),
            self._ticket_payload(
                requester=requester, requested_for=requester, assign_to=assignee,
                product=apr_product, title="Cross-division APR product task",
            ),
        )
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(title="Cross-division APR product task")
        self.assertEqual(ticket.requesting_division.code, "IT")
        self.assertEqual(ticket.product.division.code, "APR")
        self.assertEqual(ticket.current_assignee, assignee)

    def test_other_it_users_can_only_create_ticket_for_themselves(self):
        it_officer = User.objects.get(email="it.officer@frc.gov.bd")
        frm_user = User.objects.get(email="frm.officer@frc.gov.bd")
        self.client.force_login(it_officer)
        response = self.client.get(reverse("ticket_create"))
        self.assertNotContains(response, "Requester / ticket owner")

        response = self.client.post(
            reverse("ticket_create"),
            self._ticket_payload(
                requester=it_officer, requested_for=frm_user,
                title="Officer self-service ticket",
            ),
        )
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(title="Officer self-service ticket")
        self.assertEqual(ticket.requester, it_officer)
        self.assertEqual(ticket.identified_by, it_officer)

    def test_ticket_workspace_renders(self):
        ticket = Ticket.objects.first()
        response = self.client.get(reverse("ticket_detail", args=[ticket.ticket_number]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ticket.title)
        self.assertContains(response, "Activity history")

    def test_attachment_download_enforces_ticket_visibility(self):
        ticket = Ticket.objects.filter(requesting_division__code="APR").first()
        attachment = TicketAttachment.objects.create(
            ticket=ticket, uploaded_by=ticket.requester, original_name="evidence.pdf",
            content_type="application/pdf", file_size=12,
            file=SimpleUploadedFile("evidence.pdf", b"test evidence", content_type="application/pdf"),
        )
        response = self.client.get(reverse("attachment_download", args=[attachment.pk]))
        self.assertEqual(response.status_code, 200)

        frm_user = User.objects.get(email="frm.officer@frc.gov.bd")
        self.client.force_login(frm_user)
        response = self.client.get(reverse("attachment_download", args=[attachment.pk]))
        self.assertEqual(response.status_code, 404)

    def test_verification_cannot_be_bypassed_by_generic_transition_endpoint(self):
        ticket = Ticket.objects.get(status__code="ready-for-it-verification")
        self.client.force_login(ticket.requester)
        completed = WorkflowStatus.objects.get(code="completed")
        response = self.client.post(reverse("ticket_transition", args=[ticket.ticket_number]), {"to_status": completed.pk})
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "ready-for-it-verification")
        self.assertFalse(ticket.verifications.exists())
