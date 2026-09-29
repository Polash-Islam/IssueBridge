from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tickets.models import Ticket
from .access import visible_meetings_for
from .models import Meeting, MeetingParticipant, MeetingType, Notification


class CollaborationModuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", with_demo_data=True, verbosity=0)
        cls.consultant = User.objects.get(email="consultant@frc.gov.bd")
        cls.it_officer = User.objects.get(email="it.officer@frc.gov.bd")
        cls.apr_officer = User.objects.get(email="apr.officer@frc.gov.bd")
        cls.frm_officer = User.objects.get(email="frm.officer@frc.gov.bd")

    def test_module_pages_render(self):
        self.client.force_login(self.consultant)
        urls = [reverse("meeting_list"), reverse("meeting_create"), reverse("notification_list"), reverse("calendar")]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_non_participant_cannot_view_restricted_meeting(self):
        meeting = Meeting.objects.filter(requested_by=self.frm_officer).first()
        self.assertFalse(visible_meetings_for(self.apr_officer).filter(pk=meeting.pk).exists())
        self.client.force_login(self.apr_officer)
        self.assertEqual(self.client.get(reverse("meeting_detail", args=[meeting.reference])).status_code, 404)

    def test_user_can_request_meeting_and_participants_are_notified(self):
        self.client.force_login(self.apr_officer)
        start = timezone.localtime() + timedelta(days=5)
        response = self.client.post(reverse("meeting_create"), {
            "title": "APR verification discussion", "meeting_type": MeetingType.objects.first().pk,
            "reason": "Agree verification evidence", "description": "Walk through the test plan.",
            "scheduled_start": start.strftime("%Y-%m-%dT%H:%M"),
            "scheduled_end": (start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "participants": [self.consultant.pk, self.it_officer.pk],
            "ticket": Ticket.objects.filter(requesting_division__code="APR").first().pk,
            "location_link": "Conference Room 1",
        })
        self.assertEqual(response.status_code, 302)
        meeting = Meeting.objects.get(title="APR verification discussion")
        self.assertEqual(meeting.participant_records.count(), 3)
        self.assertTrue(Notification.objects.filter(recipient=self.consultant, meeting=meeting).exists())

    def test_participant_can_accept_meeting(self):
        meeting = Meeting.objects.filter(participant_records__user=self.it_officer).first()
        self.client.force_login(self.it_officer)
        response = self.client.post(reverse("meeting_action", args=[meeting.reference]), {"action": "accept"})
        self.assertEqual(response.status_code, 302)
        record = MeetingParticipant.objects.get(meeting=meeting, user=self.it_officer)
        self.assertEqual(record.response, MeetingParticipant.Response.ACCEPTED)

    def test_opening_notification_marks_it_read(self):
        notification = Notification.objects.filter(recipient=self.it_officer).first()
        self.client.force_login(self.it_officer)
        response = self.client.get(reverse("notification_open", args=[notification.pk]))
        self.assertEqual(response.status_code, 302)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)


class KanbanAndReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", with_demo_data=True, verbosity=0)
        cls.consultant = User.objects.get(email="consultant@frc.gov.bd")
        cls.it_officer = User.objects.get(email="it.officer@frc.gov.bd")

    def test_kanban_page_and_guarded_move(self):
        self.client.force_login(self.it_officer)
        self.assertEqual(self.client.get(reverse("kanban")).status_code, 200)
        ticket = Ticket.objects.get(status__code="in-progress")
        response = self.client.post(reverse("kanban_move"), {
            "ticket": ticket.ticket_number, "to_status": "blocked", "comment": "Waiting for vendor response.",
        })
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.code, "blocked")

    def test_report_page_and_exports(self):
        self.client.force_login(self.consultant)
        report_response = self.client.get(reverse("reports"))
        self.assertEqual(report_response.status_code, 200)
        self.assertContains(report_response, "All ticket statuses")
        expected = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf"}
        for format, content_type in expected.items():
            with self.subTest(format=format):
                response = self.client.get(reverse("report_export", args=[format]))
                self.assertEqual(response.status_code, 200)
                self.assertIn(content_type, response["Content-Type"])
        csv_response = self.client.get(reverse("report_export", args=["csv"]))
        csv_text = csv_response.content.decode()
        for status_name in Ticket.objects.values_list("status__name", flat=True).distinct():
            self.assertIn(status_name, csv_text)
