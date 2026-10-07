from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def pdf_report_rows(tickets):
    yield ["Title", "Division", "Sent by", "Assigned to", "Created", "Updated", "Deadline", "Status", "Days overdue"]
    for ticket in tickets:
        yield [
            ticket.title, ticket.requesting_division.name, ticket.requester.full_name,
            ticket.current_assignee.full_name if ticket.current_assignee else "Unassigned",
            timezone.localtime(ticket.created_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(ticket.updated_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(ticket.deadline).strftime("%Y-%m-%d %H:%M") if ticket.deadline else "No deadline",
            ticket.status.name, ticket.overdue_days,
        ]


def build_ticket_pdf(tickets):
    output = BytesIO()
    page_size = landscape(A4)
    document = SimpleDocTemplate(output, pagesize=page_size, leftMargin=7*mm, rightMargin=7*mm,
                                 topMargin=27*mm, bottomMargin=18*mm)
    body = ParagraphStyle("ReportCell", fontName="Helvetica", fontSize=8, leading=11)
    header = ParagraphStyle("ReportHeader", parent=body, fontName="Helvetica-Bold")
    title = ParagraphStyle("ReportTitle", fontName="Helvetica-Bold", fontSize=14, leading=18, alignment=1)
    rows = list(pdf_report_rows(tickets))
    table_rows = [[Paragraph(escape(str(value)).replace("\n", "<br/>"), header if index == 0 else body)
                   for value in row] for index, row in enumerate(rows)]
    if len(rows) == 1:
        table_rows.append([Paragraph("No tickets match the selected filters.", body)] + [""] * (len(rows[0]) - 1))
    table = Table(table_rows, repeatRows=1, colWidths=[58*mm, 28*mm, 33*mm, 33*mm, 27*mm, 27*mm, 27*mm, 30*mm, 20*mm],
                  minRowHeights=[12*mm] * len(table_rows), splitByRow=1, splitInRow=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9EDF1")),
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#606060")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    if len(rows) == 1:
        commands.append(("SPAN", (0, 1), (-1, 1)))
    table.setStyle(TableStyle(commands))

    def page_frame(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawCentredString(page_size[0]/2, page_size[1]-12*mm, "Financial Reporting Council (FRC)")
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(page_size[0]/2, page_size[1]-18*mm, "Finance Division, Ministry of Finance")
        canvas.setStrokeColor(colors.HexColor("#606060"))
        canvas.line(7*mm, 14*mm, page_size[0]-7*mm, 14*mm)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(7*mm, 10*mm, "Financial Reporting Council (FRC) | Official Ticket Status Report")
        canvas.drawRightString(page_size[0]-7*mm, 10*mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build([Paragraph("Ticket Status Report", title), Spacer(1, 3*mm),
                    Paragraph(f"Report Date: {timezone.localdate():%d %B %Y}", body), Spacer(1, 5*mm), table],
                   onFirstPage=page_frame, onLaterPages=page_frame)
    return output.getvalue()
