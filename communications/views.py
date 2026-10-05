import calendar as calendar_module
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from tickets.access import visible_tickets_for
from .access import visible_meetings_for
from .forms import MeetingActionForm, MeetingForm, NotificationFilterForm
from .models import Meeting, MeetingHistory, MeetingParticipant, Notification
from .services import create_meeting, notify_users, record_meeting_action


@login_required
def meeting_list(request):
    meetings = visible_meetings_for(request.user)
    status = request.GET.get("status", "")
    scope = request.GET.get("scope", "upcoming")
    q = request.GET.get("q", "").strip()
    if q:
        meetings = meetings.filter(Q(reference__icontains=q) | Q(title__icontains=q) | Q(reason__icontains=q))
    if status:
        meetings = meetings.filter(status=status)
    if scope == "upcoming":
        meetings = meetings.filter(scheduled_end__gte=timezone.now()).exclude(status__in=[Meeting.Status.COMPLETED, Meeting.Status.CANCELLED])
    elif scope == "mine":
        meetings = meetings.filter(Q(requested_by=request.user) | Q(organizer=request.user)).distinct()
    elif scope == "past":
        meetings = meetings.filter(Q(scheduled_end__lt=timezone.now()) | Q(status__in=[Meeting.Status.COMPLETED, Meeting.Status.CANCELLED]))
    return render(request, "communications/meeting_list.html", {
        "meetings": meetings, "status_choices": Meeting.Status.choices,
        "selected_status": status, "scope": scope, "q": q,
    })


@login_required
def meeting_create(request):
    form = MeetingForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        meeting = create_meeting(form=form, user=request.user)
        messages.success(request, f"{meeting.reference} was requested and participants were notified.")
        return redirect("meeting_detail", reference=meeting.reference)
    return render(request, "communications/meeting_form.html", {"form": form})


@login_required
def meeting_detail(request, reference):
    meeting = get_object_or_404(visible_meetings_for(request.user), reference=reference)
    participant = meeting.participant_records.filter(user=request.user).first()
    can_manage = request.user.is_super_admin or request.user.is_senior_it or request.user.is_director or meeting.organizer_id == request.user.id
    return render(request, "communications/meeting_detail.html", {
        "meeting": meeting, "participant": participant, "can_manage": can_manage,
        "action_form": MeetingActionForm(participant=bool(participant), can_manage=can_manage),
    })


@login_required
def meeting_action(request, reference):
    if request.method != "POST":
        raise Http404
    meeting = get_object_or_404(visible_meetings_for(request.user), reference=reference)
    participant = meeting.participant_records.filter(user=request.user).first()
    can_manage = request.user.is_super_admin or request.user.is_senior_it or request.user.is_director or meeting.organizer_id == request.user.id
    form = MeetingActionForm(request.POST, participant=bool(participant), can_manage=can_manage)
    if not form.is_valid():
        messages.error(request, " ".join(message for errors in form.errors.values() for message in errors))
        return redirect("meeting_detail", reference=reference)
    action = form.cleaned_data["action"]
    proposed = form.cleaned_data.get("proposed_start")
    note = form.cleaned_data.get("note", "").strip()
    if action in {"accept", "decline", "propose"} and not participant:
        raise PermissionDenied
    if action in {"reschedule", "complete", "cancel"} and not can_manage:
        raise PermissionDenied

    if action == "accept":
        participant.response = MeetingParticipant.Response.ACCEPTED
        participant.responded_at = timezone.now()
        participant.save(update_fields=["response", "responded_at"])
        meeting.status = Meeting.Status.ACCEPTED
        description = f"{request.user.full_name} accepted the meeting"
    elif action == "decline":
        participant.response = MeetingParticipant.Response.DECLINED
        participant.responded_at = timezone.now()
        participant.save(update_fields=["response", "responded_at"])
        description = f"{request.user.full_name} declined: {note}"
    elif action == "propose":
        meeting.proposed_start = proposed
        meeting.status = Meeting.Status.PROPOSED
        description = f"{request.user.full_name} proposed {timezone.localtime(proposed):%d %b %Y, %I:%M %p}"
    elif action == "reschedule":
        duration = meeting.scheduled_end - meeting.scheduled_start
        meeting.scheduled_start = proposed
        meeting.scheduled_end = proposed + duration
        meeting.proposed_start = None
        meeting.status = Meeting.Status.RESCHEDULED
        description = f"Meeting rescheduled to {timezone.localtime(proposed):%d %b %Y, %I:%M %p}"
    elif action == "complete":
        meeting.status = Meeting.Status.COMPLETED
        meeting.completed_at = timezone.now()
        description = f"Meeting marked completed by {request.user.full_name}"
    else:
        meeting.status = Meeting.Status.CANCELLED
        description = f"Meeting cancelled by {request.user.full_name}: {note}"
    meeting.save()
    record_meeting_action(meeting, request.user, action.upper(), description)
    users = [record.user for record in meeting.participant_records.select_related("user")]
    notify_users(users, kind=Notification.Kind.MEETING, verb=description, actor=request.user, meeting=meeting)
    messages.success(request, description + ".")
    return redirect("meeting_detail", reference=reference)


@login_required
def notification_list(request):
    notifications = request.user.notifications.select_related("actor", "ticket", "meeting", "approval_request")
    scope = "unread" if request.GET.get("scope") == "unread" else "all"
    if scope == "unread":
        notifications = notifications.filter(is_read=False)
    filter_form = NotificationFilterForm(request.GET)
    if filter_form.is_valid():
        start_date = filter_form.cleaned_data.get("start_date")
        end_date = filter_form.cleaned_data.get("end_date")
        if start_date:
            notifications = notifications.filter(created_at__date__gte=start_date)
        if end_date:
            notifications = notifications.filter(created_at__date__lte=end_date)
    else:
        notifications = notifications.none()
    page_obj = Paginator(notifications.order_by("-created_at", "-pk"), 20).get_page(request.GET.get("page"))
    return render(request, "communications/notification_list.html", {
        "notifications": page_obj, "page_obj": page_obj, "scope": scope, "filter_form": filter_form,
    })


@login_required
def notification_open(request, pk):
    notification = get_object_or_404(
        request.user.notifications.select_related("ticket", "meeting", "approval_request"), pk=pk,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    return redirect(notification.target_url)


@login_required
def notifications_read_all(request):
    if request.method != "POST":
        raise Http404
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    messages.success(request, "All notifications marked as read.")
    return redirect("notification_list")


@login_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        year, month = today.year, today.month
    first = date(year, month, 1)
    last = date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    start_dt = timezone.make_aware(datetime.combine(first, time.min))
    end_dt = timezone.make_aware(datetime.combine(last + timedelta(days=1), time.min))
    tickets = visible_tickets_for(request.user).filter(deadline__gte=start_dt, deadline__lt=end_dt)
    meetings = visible_meetings_for(request.user).filter(scheduled_start__gte=start_dt, scheduled_start__lt=end_dt)
    events = defaultdict(list)
    for ticket in tickets:
        local = timezone.localtime(ticket.deadline)
        events[local.day].append({"kind": "deadline", "time": local.strftime("%I:%M %p"), "title": ticket.title, "url": ticket.get_absolute_url() if hasattr(ticket, "get_absolute_url") else f"/tickets/{ticket.ticket_number}/", "code": ticket.ticket_number})
    for meeting in meetings:
        local = timezone.localtime(meeting.scheduled_start)
        events[local.day].append({"kind": "meeting", "time": local.strftime("%I:%M %p"), "title": meeting.title, "url": f"/workspace/meetings/{meeting.reference}/", "code": meeting.reference})
    weeks = []
    for week in calendar_module.Calendar(firstweekday=6).monthdayscalendar(year, month):
        weeks.append([{"day": day, "events": events.get(day, []), "is_today": day == today.day and month == today.month and year == today.year} for day in week])
    previous = first - timedelta(days=1)
    next_month = last + timedelta(days=1)
    return render(request, "communications/calendar.html", {
        "weeks": weeks, "month_name": first.strftime("%B"), "year": year, "month": month,
        "previous": previous, "next": next_month, "today": today,
        "weekdays": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    })
