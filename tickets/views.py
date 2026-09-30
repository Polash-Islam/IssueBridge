from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.http import FileResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .access import (
    can_assign_ticket, can_review_ticket, can_technical_verify_ticket, can_verify_ticket,
    can_view_internal_comments, visible_tickets_for,
)
from .forms import (
    AssignmentForm, CommentForm, ReviewForm, TechnicalVerificationForm, TicketCreateForm,
    TransitionForm, VerificationForm,
)
from .models import StatusTransition, TicketAttachment, TicketPriority, WorkflowStatus
from .services import (
    assign_ticket, create_ticket, record_history, review_ticket, technical_verify_ticket,
    transition_ticket, verify_ticket,
)


def _ticket_or_404(user, number):
    return get_object_or_404(visible_tickets_for(user), ticket_number=number)


def _error_message(exc):
    if hasattr(exc, "messages"):
        return " ".join(exc.messages)
    return str(exc)


@login_required
def ticket_list(request):
    tickets = visible_tickets_for(request.user)
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    priority = request.GET.get("priority", "")
    scope = request.GET.get("scope", "")
    if q:
        tickets = tickets.filter(
            Q(ticket_number__icontains=q) | Q(title__icontains=q) | Q(description__icontains=q)
            | Q(requester__first_name__icontains=q) | Q(requester__last_name__icontains=q)
            | Q(product__name__icontains=q)
        )
    if status:
        tickets = tickets.filter(status__code=status)
    if priority:
        tickets = tickets.filter(priority__code=priority)
    if scope == "mine":
        tickets = tickets.filter(requester=request.user)
    elif scope == "assigned":
        tickets = tickets.filter(current_assignee=request.user)
    elif scope == "verification":
        verification_filter = Q()
        if request.user.is_super_admin or request.user.is_senior_it:
            verification_filter |= Q(status__code="ready-for-it-verification")
        if request.user.is_super_admin:
            verification_filter |= Q(status__code="ready-for-verification")
        elif request.user.is_director and request.user.division_id:
            verification_filter |= Q(
                status__code="ready-for-verification",
                requesting_division_id=request.user.division_id,
            )
        else:
            verification_filter |= Q(status__code="ready-for-verification", requester=request.user)
        tickets = tickets.filter(verification_filter)
    elif scope == "overdue":
        from django.utils import timezone
        tickets = tickets.filter(deadline__lt=timezone.now()).exclude(status__kind__in=["RESOLVED", "CLOSED"])
    context = {
        "tickets": tickets, "q": q, "selected_status": status, "selected_priority": priority, "scope": scope,
        "statuses": WorkflowStatus.objects.filter(is_active=True), "priorities": TicketPriority.objects.filter(is_active=True),
    }
    return render(request, "tickets/ticket_list.html", context)


@login_required
def kanban_board(request):
    tickets = visible_tickets_for(request.user)
    q = request.GET.get("q", "").strip()
    division = request.GET.get("division", "")
    priority = request.GET.get("priority", "")
    if q:
        tickets = tickets.filter(Q(ticket_number__icontains=q) | Q(title__icontains=q))
    if division:
        tickets = tickets.filter(requesting_division__code=division)
    if priority:
        tickets = tickets.filter(priority__code=priority)
    tickets = list(tickets.prefetch_related("status__transitions_from__allowed_roles"))
    columns = [
        {"name": "New", "target": "new", "codes": {"new"}, "tone": "slate"},
        {"name": "Under review", "target": "under-review", "codes": {"under-review", "need-more-information", "validated"}, "tone": "violet"},
        {"name": "Assigned", "target": "assigned", "codes": {"assigned"}, "tone": "blue"},
        {"name": "In progress", "target": "in-progress", "codes": {"in-progress", "reopened", "waiting-for-requester", "waiting-for-meeting"}, "tone": "cyan"},
        {"name": "Blocked", "target": "blocked", "codes": {"blocked"}, "tone": "red"},
        {"name": "IT verification", "target": "ready-for-it-verification", "codes": {"ready-for-it-verification"}, "tone": "violet"},
        {"name": "Requester verification", "target": "ready-for-verification", "codes": {"ready-for-verification", "verification-failed"}, "tone": "orange"},
        {"name": "Completed", "target": "completed", "codes": {"completed", "closed", "invalid", "cancelled"}, "tone": "green"},
    ]
    for ticket in tickets:
        ticket.allowed_kanban_codes = list(_available_statuses(request.user, ticket).values_list("code", flat=True))
    for column in columns:
        column["tickets"] = [ticket for ticket in tickets if ticket.status.code in column["codes"]]
    from core.models import Division
    return render(request, "tickets/kanban.html", {
        "columns": columns, "q": q, "selected_division": division, "selected_priority": priority,
        "divisions": Division.objects.filter(is_active=True), "priorities": TicketPriority.objects.filter(is_active=True),
    })


@login_required
def kanban_move(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    ticket = _ticket_or_404(request.user, request.POST.get("ticket", ""))
    target = get_object_or_404(WorkflowStatus, code=request.POST.get("to_status", ""), is_active=True)
    if not _available_statuses(request.user, ticket).filter(pk=target.pk).exists():
        return JsonResponse({"error": "This workflow step requires a dedicated review, assignment, or verification action."}, status=403)
    comment = request.POST.get("comment", "")
    try:
        transition_ticket(ticket=ticket, to_status=target, actor=request.user, comment=comment, request=request)
    except ValidationError as exc:
        return JsonResponse({"error": _error_message(exc), "requires_comment": "reason" in _error_message(exc).lower()}, status=400)
    except PermissionDenied:
        return JsonResponse({"error": "You are not permitted to make this status change."}, status=403)
    return JsonResponse({"ok": True, "status": target.name, "status_code": target.code, "color": target.color})


@login_required
def ticket_create(request):
    form = TicketCreateForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            ticket = create_ticket(form=form, user=request.user, files=form.cleaned_data["attachments"], request=request)
        except ValidationError as exc:
            form.add_error(None, exc)
            return render(request, "tickets/ticket_form.html", {"form": form})
        if ticket.current_assignee:
            messages.success(request, f"{ticket.ticket_number} was created and assigned to {ticket.current_assignee.full_name}.")
        else:
            messages.success(request, f"{ticket.ticket_number} was created and sent to IT intake.")
        return redirect("ticket_detail", number=ticket.ticket_number)
    return render(request, "tickets/ticket_form.html", {"form": form})


def _available_statuses(user, ticket):
    # Review, assignment, and verification must use their dedicated services so
    # their mandatory decision records cannot be bypassed through a generic POST.
    if ticket.status.code in {
        "new", "under-review", "validated", "ready-for-it-verification",
        "ready-for-verification", "verification-failed",
    }:
        return WorkflowStatus.objects.none()
    transitions = StatusTransition.objects.filter(from_status=ticket.status, is_active=True)
    assigned_worker = ticket.current_assignee_id == user.pk and ticket.status.code in {
        "assigned", "in-progress", "blocked", "waiting-for-requester",
        "waiting-for-meeting", "reopened",
    }
    if not user.is_super_admin and not assigned_worker:
        if user.role_id:
            transitions = transitions.filter(allowed_roles=user.role)
        else:
            transitions = transitions.none()
    return WorkflowStatus.objects.filter(transitions_to__in=transitions).distinct().order_by("sort_order")


@login_required
def ticket_detail(request, number):
    ticket = _ticket_or_404(request.user, number)
    comments = ticket.comments.select_related("author", "author__division").prefetch_related("attachments")
    if not can_view_internal_comments(request.user):
        comments = comments.filter(visibility="PUBLIC")
    comments = list(comments)
    comments_by_id = {comment.pk: comment for comment in comments}
    history = list(ticket.history.select_related("actor")[:50])
    for event in history:
        event.related_comment = comments_by_id.get(event.new_value.get("comment_id"))
    available_statuses = _available_statuses(request.user, ticket)
    context = {
        "ticket": ticket,
        "comments": comments,
        "history": history,
        "comment_form": CommentForm(user=request.user),
        "review_form": ReviewForm(),
        "assignment_form": AssignmentForm(),
        "transition_form": TransitionForm(queryset=available_statuses),
        "technical_verification_form": TechnicalVerificationForm(),
        "verification_form": VerificationForm(),
        "can_review": can_review_ticket(request.user) and ticket.status.code in {"new", "under-review"},
        "can_assign": can_assign_ticket(request.user) and ticket.status.code in {"validated", "assigned", "in-progress", "reopened"},
        "can_technical_verify": can_technical_verify_ticket(request.user, ticket) and ticket.status.code == "ready-for-it-verification",
        "can_verify": can_verify_ticket(request.user, ticket) and ticket.status.code == "ready-for-verification",
        "has_transitions": available_statuses.exists(),
        "active_assignment": ticket.assignments.filter(is_active=True).select_related("assigned_by", "assigned_to").first(),
    }
    return render(request, "tickets/ticket_detail.html", context)


@login_required
def attachment_download(request, pk):
    attachment = get_object_or_404(TicketAttachment.objects.select_related("ticket", "comment"), pk=pk)
    if not visible_tickets_for(request.user).filter(pk=attachment.ticket_id).exists():
        raise Http404
    if attachment.comment and attachment.comment.visibility == "INTERNAL" and not can_view_internal_comments(request.user):
        raise Http404
    response = FileResponse(
        attachment.file.open("rb"), as_attachment=not attachment.is_image,
        filename=attachment.original_name, content_type=attachment.content_type or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def comment_add(request, number):
    if request.method != "POST":
        raise Http404
    ticket = _ticket_or_404(request.user, number)
    form = CommentForm(request.POST, request.FILES, user=request.user)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.ticket = ticket
        comment.author = request.user
        comment.save()
        for uploaded in form.cleaned_data["attachments"]:
            TicketAttachment.objects.create(
                ticket=ticket, comment=comment, file=uploaded, original_name=uploaded.name,
                content_type=getattr(uploaded, "content_type", ""), file_size=uploaded.size, uploaded_by=request.user,
            )
        record_history(
            ticket, request.user, "COMMENT_ADDED",
            f"{form.cleaned_data['visibility'].title()} comment added", request,
            new={"comment_id": comment.pk},
        )
        from communications.models import Notification
        from communications.services import notify_users
        recipients = [ticket.current_assignee, ticket.reviewed_by]
        if form.cleaned_data["visibility"] == "PUBLIC":
            recipients.append(ticket.requester)
            recipients.extend(ticket.watchers.all())
        notify_users(recipients, kind=Notification.Kind.COMMENT, verb=f"commented on {ticket.ticket_number}", actor=request.user, ticket=ticket)
        messages.success(request, "Comment added.")
    else:
        errors = " ".join(message for messages_list in form.errors.values() for message in messages_list)
        messages.error(request, "Please correct the comment: " + errors)
    return redirect("ticket_detail", number=number)


@login_required
def ticket_review(request, number):
    if request.method != "POST":
        raise Http404
    ticket = _ticket_or_404(request.user, number)
    form = ReviewForm(request.POST)
    if form.is_valid():
        try:
            review_ticket(ticket=ticket, actor=request.user, request=request, **form.cleaned_data)
            messages.success(request, "Review decision recorded.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_message(exc))
    return redirect("ticket_detail", number=number)


@login_required
def ticket_assign(request, number):
    if request.method != "POST":
        raise Http404
    ticket = _ticket_or_404(request.user, number)
    form = AssignmentForm(request.POST)
    if form.is_valid():
        try:
            assign_ticket(ticket=ticket, actor=request.user, request=request, **form.cleaned_data)
            messages.success(request, f"Assigned to {form.cleaned_data['assigned_to'].full_name}.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_message(exc))
    else:
        messages.error(request, "Please correct the assignment details.")
    return redirect("ticket_detail", number=number)


@login_required
def ticket_transition(request, number):
    if request.method != "POST":
        raise Http404
    ticket = _ticket_or_404(request.user, number)
    form = TransitionForm(request.POST, queryset=_available_statuses(request.user, ticket))
    if form.is_valid():
        try:
            transition_ticket(ticket=ticket, to_status=form.cleaned_data["to_status"], actor=request.user, comment=form.cleaned_data["comment"], request=request)
            messages.success(request, "Ticket status updated.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_message(exc))
    else:
        messages.error(request, "That status change is not available.")
    return redirect("ticket_detail", number=number)


@login_required
def ticket_verify(request, number):
    if request.method != "POST":
        raise Http404
    ticket = _ticket_or_404(request.user, number)
    form = VerificationForm(request.POST)
    if form.is_valid():
        try:
            verify_ticket(ticket=ticket, actor=request.user, request=request, **form.cleaned_data)
            messages.success(request, "Verification submitted. Thank you.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_message(exc))
    return redirect("ticket_detail", number=number)


@login_required
def ticket_technical_verify(request, number):
    if request.method != "POST":
        raise Http404
    ticket = _ticket_or_404(request.user, number)
    form = TechnicalVerificationForm(request.POST)
    if form.is_valid():
        try:
            technical_verify_ticket(ticket=ticket, actor=request.user, request=request, **form.cleaned_data)
            messages.success(request, "Technical verification decision recorded.")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_message(exc))
    else:
        errors = " ".join(message for errors in form.errors.values() for message in errors)
        messages.error(request, errors or "Please correct the technical verification details.")
    return redirect("ticket_detail", number=number)
