from datetime import timedelta
from io import BytesIO
import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from tickets.access import visible_tickets_for
from tickets.models import TicketPriority, WorkflowStatus
from core.models import Division


@login_required
def dashboard(request):
    tickets = visible_tickets_for(request.user)
    full_dashboard = request.user.is_super_admin or request.user.is_director or request.user.is_senior_it
    dashboard_tickets = tickets if full_dashboard else tickets.filter(
        Q(requester=request.user) | Q(current_assignee=request.user)
    ).distinct()
    now = timezone.now()
    open_tickets = dashboard_tickets.exclude(status__kind__in=["RESOLVED", "CLOSED"])
    metrics = {
        "total": dashboard_tickets.count(),
        "open": open_tickets.count(),
        "in_progress": dashboard_tickets.filter(status__code="in-progress").count(),
        "verification": dashboard_tickets.filter(status__code__in=["ready-for-it-verification", "ready-for-verification"]).count(),
        "overdue": open_tickets.filter(deadline__lt=now).count(),
        "completed": dashboard_tickets.filter(status__kind__in=["RESOLVED", "CLOSED"]).count(),
    }
    division_counts = list(
        tickets.values("requesting_division__name", "requesting_division__code")
        .annotate(total=Count("id"), open=Count("id", filter=~Q(status__kind__in=["RESOLVED", "CLOSED"])))
        .order_by("requesting_division__code")
    )
    max_division = max([row["total"] for row in division_counts], default=1)
    for row in division_counts:
        row["percent"] = round(row["total"] / max_division * 100)
    priority_counts = list(tickets.values("priority__name", "priority__color").annotate(total=Count("id")).order_by("-priority__rank"))
    context = {
        "metrics": metrics,
        "full_dashboard": full_dashboard,
        "division_counts": division_counts,
        "priority_counts": priority_counts,
        "recent_tickets": dashboard_tickets[:7],
        "due_soon": open_tickets.filter(deadline__gte=now, deadline__lte=now + timedelta(days=7)).order_by("deadline")[:5],
        "my_tasks": open_tickets.filter(current_assignee=request.user).order_by("deadline")[:5],
        "my_requests": dashboard_tickets.filter(requester=request.user).order_by("-created_at")[:5],
    }
    return render(request, "dashboard/dashboard.html", context)


def _report_queryset(request):
    tickets = visible_tickets_for(request.user)
    division = request.GET.get("division", "")
    status = request.GET.get("status", "")
    priority = request.GET.get("priority", "")
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    if division:
        tickets = tickets.filter(requesting_division__code=division)
    if status:
        tickets = tickets.filter(status__code=status)
    if priority:
        tickets = tickets.filter(priority__code=priority)
    if start:
        tickets = tickets.filter(created_at__date__gte=start)
    if end:
        tickets = tickets.filter(created_at__date__lte=end)
    return tickets


@login_required
def reports(request):
    tickets = _report_queryset(request)
    now = timezone.now()
    resolved = tickets.filter(status__kind__in=["RESOLVED", "CLOSED"])
    durations = [
        (completed_at - created_at).total_seconds() / 3600
        for created_at, completed_at in resolved.values_list("created_at", "completed_at") if completed_at
    ]
    groups = {
        "status_data": list(tickets.values("status__name", "status__color", "status__kind").annotate(total=Count("id")).order_by("status__sort_order")),
        "division_data": list(tickets.values("requesting_division__code", "requesting_division__name").annotate(total=Count("id")).order_by("-total")),
        "products": list(tickets.values("product__name").annotate(total=Count("id")).order_by("-total")[:8]),
        "categories": list(tickets.values("category__name").annotate(total=Count("id")).order_by("-total")[:8]),
        "officers": list(tickets.exclude(current_assignee=None).values("current_assignee__first_name", "current_assignee__last_name").annotate(total=Count("id"), open=Count("id", filter=~Q(status__kind__in=["RESOLVED", "CLOSED"]))).order_by("-open", "-total")[:8]),
    }
    max_group = max([row["total"] for row in groups["division_data"] + groups["products"] + groups["categories"]], default=1)
    for collection in (groups["division_data"], groups["products"], groups["categories"]):
        for row in collection:
            row["percent"] = round(row["total"] / max_group * 100)
    context = {
        "metrics": {
            "total": tickets.count(), "open": tickets.exclude(status__kind__in=["RESOLVED", "CLOSED"]).count(),
            "resolved": resolved.count(), "overdue": tickets.filter(deadline__lt=now).exclude(status__kind__in=["RESOLVED", "CLOSED"]).count(),
            "reopened": tickets.filter(status__code="reopened").count(),
            "avg_hours": round(sum(durations) / len(durations), 1) if durations else 0,
        },
        **groups,
        "recent": tickets.order_by("-created_at")[:10],
        "division_options": Division.objects.filter(is_active=True), "statuses": WorkflowStatus.objects.filter(is_active=True),
        "priorities": TicketPriority.objects.filter(is_active=True), "filters": request.GET,
    }
    return render(request, "dashboard/reports.html", context)


def _report_rows(tickets):
    yield ["Ticket ID", "Title", "Division", "Product", "Category", "Priority", "Status", "Requester", "Assignee", "Created", "Deadline", "Completed"]
    for ticket in tickets.select_related("requesting_division", "product", "category", "priority", "status", "requester", "current_assignee"):
        yield [
            ticket.ticket_number, ticket.title, ticket.requesting_division.code, ticket.product.name,
            ticket.category.name, ticket.priority.name, ticket.status.name, ticket.requester.full_name,
            ticket.current_assignee.full_name if ticket.current_assignee else "",
            timezone.localtime(ticket.created_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(ticket.deadline).strftime("%Y-%m-%d %H:%M") if ticket.deadline else "",
            timezone.localtime(ticket.completed_at).strftime("%Y-%m-%d %H:%M") if ticket.completed_at else "",
        ]


@login_required
def report_export(request, format):
    tickets = _report_queryset(request).order_by("-created_at")
    rows = list(_report_rows(tickets))
    filename = f"frc-ticket-report-{timezone.localdate().isoformat()}"
    if format == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        writer = csv.writer(response)
        writer.writerows(rows)
        return response
    if format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Ticket Report"
        for row in rows:
            sheet.append(row)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="173D5F")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            letter = column[0].column_letter
            sheet.column_dimensions[letter].width = min(max(len(str(cell.value or "")) for cell in column) + 2, 45)
        output = BytesIO()
        workbook.save(output)
        response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
        return response
    if format == "pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        output = BytesIO()
        document = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=10 * mm, leftMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
        styles = getSampleStyleSheet()
        compact_rows = [rows[0][:8]] + [[Paragraph(str(value), styles["BodyText"]) for value in row[:8]] for row in rows[1:]]
        table = Table(compact_rows, repeatRows=1, colWidths=[25*mm, 58*mm, 18*mm, 35*mm, 35*mm, 19*mm, 27*mm, 31*mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173D5F")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#D9E1E8")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
        ]))
        document.build([Paragraph("FRC Ticket Report", styles["Title"]), Paragraph(f"Generated {timezone.localtime():%d %B %Y, %I:%M %p}", styles["Normal"]), Spacer(1, 5*mm), table])
        response = HttpResponse(output.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
        return response
    return HttpResponse("Unsupported export format", status=400)
