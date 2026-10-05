from datetime import datetime, timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tickets.models import Ticket
from .access import visible_meetings_for
from .models import Meeting, MeetingParticipant, MeetingType, Notification


class NotificationListTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="notification-reader", email="reader@example.com")
        self.other_user = User.objects.create_user(username="other-reader", email="other@example.com")
        self.client.force_login(self.user)
        self.url = reverse("notification_list")

    def create_notification(self, timestamp, **kwargs):
        notification = Notification.objects.create(
            recipient=kwargs.pop("recipient", self.user), kind=Notification.Kind.COMMENT,
            verb="Test update", **kwargs,
        )
        Notification.objects.filter(pk=notification.pk).update(
            created_at=timezone.make_aware(datetime.fromisoformat(timestamp)),
        )
        return notification

    def test_pagination_includes_notifications_beyond_old_limit(self):
        Notification.objects.bulk_create([
            Notification(recipient=self.user, kind=Notification.Kind.COMMENT, verb=f"Update {number}")
            for number in range(105)
        ])
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["notifications"]), 20)
        self.assertEqual(response.context["page_obj"].paginator.count, 105)
        response = self.client.get(self.url, {"page": 6})
        self.assertEqual(len(response.context["notifications"]), 5)
        self.assertContains(response, "Page 6 of 6")

    def test_date_range_is_inclusive_in_local_timezone_and_respects_scope(self):
        start = self.create_notification("2026-10-01T00:00:00")
        end = self.create_notification("2026-10-02T23:59:59")
        self.create_notification("2026-09-30T23:59:59")
        self.create_notification("2026-10-03T00:00:00")
        self.create_notification("2026-10-01T12:00:00", is_read=True)
        self.create_notification("2026-10-01T12:00:00", recipient=self.other_user)
        response = self.client.get(self.url, {
            "scope": "unread", "start_date": "2026-10-01", "end_date": "2026-10-02",
        })
        self.assertEqual([item.pk for item in response.context["notifications"]], [end.pk, start.pk])

    def test_page_and_scope_links_keep_date_filters(self):
        for number in range(21):
            self.create_notification("2026-10-01T12:00:00")
        response = self.client.get(self.url, {
            "scope": "unread", "start_date": "2026-10-01", "end_date": "2026-10-01",
        })
        self.assertContains(response, 'scope=unread&amp;start_date=2026-10-01&amp;end_date=2026-10-01&amp;page=2')
        self.assertContains(response, '?scope=all&amp;start_date=2026-10-01&amp;end_date=2026-10-01"')

    def test_invalid_dates_show_validation_errors(self):
        for filters in [
            {"start_date": "bad-date"},
            {"start_date": "2026-10-04", "end_date": "2026-10-01"},
        ]:
            with self.subTest(filters=filters):
                response = self.client.get(self.url, filters)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["filter_form"].errors)
                self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_invalid_page_and_one_sided_date_filter(self):
        self.create_notification("2026-10-01T12:00:00")
        self.create_notification("2026-10-03T12:00:00")
        for filters in [
            {"start_date": "2026-10-02", "page": "bad-page"},
            {"end_date": "2026-10-02", "page": "999"},
        ]:
            with self.subTest(filters=filters):
                response = self.client.get(self.url, filters)
                self.assertEqual(response.context["page_obj"].number, 1)
                self.assertEqual(response.context["page_obj"].paginator.count, 1)


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
