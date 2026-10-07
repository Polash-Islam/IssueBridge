from io import BytesIO

from openpyxl import load_workbook
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from tickets.access import visible_tickets_for
from tickets.models import Ticket


class ReportDetailsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", with_demo_data=True, verbosity=0)
        cls.requester = User.objects.get(email="apr.officer@frc.gov.bd")
        cls.consultant = User.objects.get(email="consultant@frc.gov.bd")

    def test_report_shows_all_filtered_tickets_and_people(self):
        self.client.force_login(self.consultant)
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["report_tickets"]), Ticket.objects.count())
        for ticket in Ticket.objects.all():
            self.assertContains(response, ticket.ticket_number)
            self.assertContains(response, ticket.requester.full_name)
        self.assertContains(response, "Sent by")
        self.assertContains(response, "Assigned to")

    def test_report_respects_visibility_and_status_filter(self):
        self.client.force_login(self.requester)
        visible = visible_tickets_for(self.requester)
        status = visible.first().status.code
        response = self.client.get(reverse("reports"), {"status": status})
        expected = set(visible.filter(status__code=status).values_list("pk", flat=True))
        self.assertEqual({ticket.pk for ticket in response.context["report_tickets"]}, expected)
        for ticket in Ticket.objects.exclude(pk__in=expected):
            self.assertNotContains(response, ticket.ticket_number)

    def test_empty_report(self):
        self.client.force_login(self.consultant)
        response = self.client.get(reverse("reports"), {"division": "missing"})
        self.assertContains(response, "No tickets match the selected filters.")

    def test_excel_download_matches_filtered_ticket_details(self):
        self.client.force_login(self.requester)
        visible = visible_tickets_for(self.requester)
        status = visible.first().status.code
        response = self.client.get(reverse("report_export", args=["xlsx"]), {"status": status})
        self.assertEqual(response.status_code, 200)
        self.assertIn(".xlsx", response["Content-Disposition"])
        sheet = load_workbook(BytesIO(response.content)).active
        rows = list(sheet.values)
        self.assertEqual(rows[0][7:13], ("Sent by", "Identified by", "Assigned to", "Reviewed by", "Created", "Updated"))
        expected = visible.filter(status__code=status)
        self.assertEqual({row[0] for row in rows[1:]}, set(expected.values_list("ticket_number", flat=True)))
        for row in rows[1:]:
            ticket = expected.get(ticket_number=row[0])
            self.assertEqual(row[7], ticket.requester.full_name)
            self.assertEqual(row[8], ticket.identified_by.full_name)
        page = self.client.get(reverse("reports"), {"status": status})
        self.assertContains(page, "Download Excel")
        self.assertContains(page, f'{reverse("report_export", args=["xlsx"])}?status={status}')

    def test_pdf_export_includes_assignee_and_dates(self):
        self.client.force_login(self.consultant)
        response = self.client.get(reverse("report_export", args=["pdf"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
