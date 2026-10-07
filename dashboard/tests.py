from io import BytesIO
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

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
        self.assertEqual(rows[0], ("Ticket ID", "Title", "Division", "Status", "Sent by", "Assigned to", "Created", "Updated", "Deadline", "Completed"))
        expected = visible.filter(status__code=status)
        self.assertEqual({row[0] for row in rows[1:]}, set(expected.values_list("ticket_number", flat=True)))
        for row in rows[1:]:
            ticket = expected.get(ticket_number=row[0])
            self.assertEqual(row[4], ticket.requester.full_name)
            self.assertEqual(row[5], ticket.current_assignee.full_name if ticket.current_assignee else "Unassigned")
        page = self.client.get(reverse("reports"), {"status": status})
        self.assertContains(page, "Download PDF")
        self.assertContains(page, f'{reverse("report_export", args=["pdf"])}?status={status}')

    def test_pdf_columns_match_portrait_report_with_status_instead_of_completed(self):
        from .report_pdf import pdf_report_rows
        tickets = list(Ticket.objects.select_related("requester", "current_assignee", "status"))
        rows = list(pdf_report_rows(tickets))
        self.assertEqual(rows[0], ["Title", "Sent by", "Assigned to", "Created", "Updated", "Deadline", "Status"])
        for ticket, row in zip(tickets, rows[1:]):
            self.assertEqual(row[0], ticket.title)
            self.assertNotIn(ticket.ticket_number, row)
            self.assertEqual(row[-1], ticket.status.name)

    def test_pdf_export_includes_assignee_and_dates(self):
        self.client.force_login(self.consultant)
        response = self.client.get(reverse("report_export", args=["pdf"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_excel_is_formatted_for_portrait_printing(self):
        self.client.force_login(self.consultant)
        ticket = Ticket.objects.first()
        ticket.title = "Detailed ticket description " * 8
        ticket.save(update_fields=["title"])
        response = self.client.get(reverse("report_export", args=["xlsx"]))
        sheet = load_workbook(BytesIO(response.content)).active
        self.assertEqual(sheet.page_setup.orientation, "portrait")
        self.assertEqual(str(sheet.page_setup.paperSize), sheet.PAPERSIZE_A4)
        self.assertEqual(sheet.page_setup.fitToWidth, 1)
        self.assertEqual(sheet.page_setup.fitToHeight, 0)
        self.assertTrue(sheet.sheet_properties.pageSetUpPr.fitToPage)
        self.assertEqual(sheet.print_title_rows, "$1:$1")
        self.assertTrue(sheet.print_area)
        self.assertLessEqual(max(d.width for d in sheet.column_dimensions.values()), 18)
        for row in sheet.iter_rows(min_row=2):
            self.assertTrue(all(c.alignment.wrap_text for c in row))
            self.assertGreaterEqual(sheet.row_dimensions[row[0].row].height, 60)
            if row[0].value == ticket.ticket_number:
                self.assertEqual(row[1].value, ticket.title)
                self.assertGreater(sheet.row_dimensions[row[0].row].height, 60)

    def test_each_filter_and_combination_updates_report_and_excel(self):
        self.client.force_login(self.consultant)
        tickets = list(Ticket.objects.select_related("requesting_division", "status", "priority"))
        target = tickets[0]
        dhaka = ZoneInfo("Asia/Dhaka")
        for index, ticket in enumerate(tickets):
            created = datetime(2026, 9, 10 + index, 12, tzinfo=dhaka)
            Ticket.objects.filter(pk=ticket.pk).update(created_at=created)
            ticket.created_at = created
        cases = [
            {}, {"division": target.requesting_division.code},
            {"status": target.status.code}, {"priority": target.priority.code},
            {"start": "2026-09-11"}, {"end": "2026-09-12"},
            {"start": "2026-09-10", "end": "2026-09-10"},
            {"division": target.requesting_division.code, "status": target.status.code,
             "priority": target.priority.code, "start": "2026-09-10", "end": "2026-09-10"},
            {"start": "2027-01-01"},
        ]
        for filters in cases:
            with self.subTest(filters=filters):
                expected = [t for t in tickets if
                    (not filters.get("division") or t.requesting_division.code == filters["division"]) and
                    (not filters.get("status") or t.status.code == filters["status"]) and
                    (not filters.get("priority") or t.priority.code == filters["priority"]) and
                    (not filters.get("start") or t.created_at.date().isoformat() >= filters["start"]) and
                    (not filters.get("end") or t.created_at.date().isoformat() <= filters["end"])]
                response = self.client.get(reverse("reports"), filters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual({t.pk for t in response.context["report_tickets"]}, {t.pk for t in expected})
                self.assertEqual(response.context["metrics"]["total"], len(expected))
                self.assertEqual({r["status__name"]: r["total"] for r in response.context["status_data"]}, Counter(t.status.name for t in expected))
                assigned = Counter(t.current_assignee_id for t in expected if t.current_assignee_id)
                opened = Counter(t.current_assignee_id for t in expected if t.current_assignee_id and t.status.kind not in {"RESOLVED", "CLOSED"})
                self.assertEqual({r["current_assignee_id"]: r["total"] for r in response.context["officers"]}, assigned)
                self.assertEqual({r["current_assignee_id"]: r["open"] for r in response.context["officers"]}, {pk: opened[pk] for pk in assigned})
                for key, value in filters.items():
                    self.assertEqual(response.context["filters"][key], value)
                export = self.client.get(reverse("report_export", args=["xlsx"]), filters)
                self.assertEqual(export.status_code, 200)
                rows = list(load_workbook(BytesIO(export.content)).active.values)
                self.assertEqual({r[0] for r in rows[1:]}, {t.ticket_number for t in expected})

    def test_date_filter_uses_dhaka_day_boundaries(self):
        self.client.force_login(self.consultant)
        tickets = list(Ticket.objects.all()[:3])
        dhaka = ZoneInfo("Asia/Dhaka")
        moments = [datetime(2026, 9, 9, 23, 59, tzinfo=dhaka),
                   datetime(2026, 9, 10, 0, 0, tzinfo=dhaka),
                   datetime(2026, 9, 10, 23, 59, tzinfo=dhaka)]
        for ticket, moment in zip(tickets, moments):
            Ticket.objects.filter(pk=ticket.pk).update(created_at=moment)
        response = self.client.get(reverse("reports"), {"start": "2026-09-10", "end": "2026-09-10"})
        self.assertEqual({t.pk for t in response.context["report_tickets"]}, {t.pk for t in tickets[1:]})

    def test_invalid_dates_show_validation_error(self):
        self.client.force_login(self.consultant)
        for filters in [{"start": "invalid"}, {"end": "2026-02-30"},
                        {"start": "2026-09-12", "end": "2026-09-10"}]:
            with self.subTest(filters=filters):
                response = self.client.get(reverse("reports"), filters)
                self.assertContains(response, "Please enter valid From and To dates", status_code=400)
                export = self.client.get(reverse("report_export", args=["xlsx"]), filters)
                self.assertEqual(export.status_code, 400)
