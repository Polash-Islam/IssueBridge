from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .access import can_assign_ticket, can_review_ticket, can_technical_verify_ticket, can_verify_ticket
from .models import (
    StatusTransition, Ticket, TicketAssignment, TicketHistory, TicketNumberSequence,
    TicketReview, TicketTechnicalVerification, TicketVerification, WorkflowStatus,
)


def request_metadata(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip_address = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return {"ip_address": ip_address or None, "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255]}


def record_history(ticket, actor, action, description, request=None, previous=None, new=None):
    metadata = request_metadata(request) if request else {}
    return TicketHistory.objects.create(
        ticket=ticket, actor=actor, action=action, description=description,
        previous_value=previous or {}, new_value=new or {}, **metadata,
    )


@transaction.atomic
def create_ticket(*, form, user, files, request=None):
    division = form.cleaned_data["requesting_division"]
    requester = form.cleaned_data.get("requested_for") or user
    assigned_to = form.cleaned_data.get("assign_to")
    status_code = "assigned" if assigned_to else "new"
    try:
        status = WorkflowStatus.objects.get(code=status_code, is_active=True)
    except WorkflowStatus.DoesNotExist as exc:
        raise ValidationError(
            "Ticket workflow is not configured. Please contact an administrator to restore the workflow statuses."
        ) from exc
    year = timezone.localdate().year
    sequence, _ = TicketNumberSequence.objects.select_for_update().get_or_create(division=division, year=year)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    ticket = form.save(commit=False)
    ticket.ticket_number = f"{division.code}-{year}-{sequence.last_number:04d}"
    ticket.requester = requester
    ticket.identified_by = user
    ticket.status = status
    if assigned_to:
        ticket.current_assignee = assigned_to
        ticket.reviewed_by = user
    ticket.save()
    ticket.watchers.add(requester, user)
    for uploaded in files:
        ticket.attachments.create(
            file=uploaded, original_name=uploaded.name, content_type=getattr(uploaded, "content_type", ""),
            file_size=uploaded.size, uploaded_by=user,
        )
    description = f"Ticket created by {user.full_name}"
    if requester != user:
        description += f" on behalf of {requester.full_name}"
    record_history(
        ticket, user, "TICKET_CREATED", description, request,
        new={"status": status.name, "requester": requester.full_name},
    )
    if files:
        record_history(ticket, user, "FILES_UPLOADED", f"{len(files)} attachment(s) uploaded", request)
    if assigned_to:
        TicketReview.objects.create(
            ticket=ticket, reviewer=user, decision=TicketReview.Decision.VALID,
            reason="Created and directly routed by the Senior IT Consultant.",
        )
        TicketAssignment.objects.create(
            ticket=ticket, assigned_to=assigned_to, assigned_by=user,
            task_description=ticket.description,
        )
        record_history(
            ticket, user, "TICKET_ASSIGNED", f"Assigned directly to {assigned_to.full_name}", request,
            new={"assignee": assigned_to.full_name},
        )
    from accounts.models import User
    from communications.models import Notification
    from communications.services import notify_users
    if assigned_to:
        notify_users(
            [assigned_to], kind=Notification.Kind.ASSIGNED,
            verb=f"assigned {ticket.ticket_number} to you", actor=user, ticket=ticket,
        )
    else:
        intake_users = User.objects.filter(is_active=True, role__code="senior-it-consultant")
        notify_users(intake_users, kind=Notification.Kind.TICKET_CREATED, verb=f"created {ticket.ticket_number}", actor=user, ticket=ticket)
    if requester != user:
        notify_users(
            [requester], kind=Notification.Kind.TICKET_CREATED,
            verb=f"created {ticket.ticket_number} on your behalf", actor=user, ticket=ticket,
        )
    return ticket


def _role_can_transition(user, transition):
    if user.is_super_admin:
        return True
    if not user.role_id:
        return False
    return transition.allowed_roles.filter(pk=user.role_id).exists()


@transaction.atomic
def transition_ticket(*, ticket, to_status, actor, comment="", request=None):
    transition = StatusTransition.objects.filter(
        from_status=ticket.status, to_status=to_status, is_active=True
    ).prefetch_related("allowed_roles").first()
    execution_statuses = {
        "assigned", "in-progress", "blocked", "waiting-for-requester",
        "waiting-for-meeting", "reopened",
    }
    assigned_worker = (
        ticket.current_assignee_id == actor.pk and ticket.status.code in execution_statuses
    )
    if not transition or (not _role_can_transition(actor, transition) and not assigned_worker):
        raise PermissionDenied("You are not permitted to make this status change.")
    if actor.role_code == "officer" and ticket.status.code in execution_statuses and ticket.current_assignee_id != actor.pk:
        raise PermissionDenied("Only the assigned IT Officer can update this task.")
    if transition.requires_comment and not comment.strip():
        raise ValidationError("A reason is required for this status change.")
    if to_status.code in {"assigned", "in-progress"} and not ticket.current_assignee_id:
        raise ValidationError("Assign a responsible person before starting work.")
    previous = ticket.status
    ticket.status = to_status
    if to_status.code in {"completed", "closed"}:
        ticket.completed_at = timezone.now()
    elif previous.code in {"completed", "closed"}:
        ticket.completed_at = None
    ticket.save(update_fields=["status", "completed_at", "updated_at"])
    if comment.strip():
        ticket.comments.create(author=actor, body=comment.strip(), visibility="PUBLIC")
    record_history(
        ticket, actor, "STATUS_CHANGED", f"Status changed from {previous.name} to {to_status.name}", request,
        previous={"status": previous.name}, new={"status": to_status.name, "reason": comment.strip()},
    )
    from communications.models import Notification
    from communications.services import notify_users
    if to_status.code == "ready-for-it-verification":
        from accounts.models import User
        recipients = list(User.objects.filter(is_active=True, role__code="senior-it-consultant"))
    elif to_status.code == "ready-for-verification":
        recipients = [ticket.requester]
    elif previous.code == "ready-for-it-verification" and to_status.code == "in-progress":
        recipients = [ticket.current_assignee]
    else:
        recipients = [ticket.requester, ticket.current_assignee]
    notify_users(
        recipients, kind=Notification.Kind.STATUS,
        verb=f"moved {ticket.ticket_number} to {to_status.name}", actor=actor, ticket=ticket,
    )
    return ticket


@transaction.atomic
def review_ticket(*, ticket, actor, decision, reason, request=None):
    if not can_review_ticket(actor):
        raise PermissionDenied
    if decision != TicketReview.Decision.VALID and not reason.strip():
        raise ValidationError("Please provide a reason for this review decision.")
    mapping = {
        TicketReview.Decision.VALID: "validated",
        TicketReview.Decision.NEED_INFO: "need-more-information",
        TicketReview.Decision.INVALID: "invalid",
        TicketReview.Decision.DUPLICATE: "invalid",
        TicketReview.Decision.RESOLVED: "completed",
        TicketReview.Decision.NOT_IT: "invalid",
    }
    target = WorkflowStatus.objects.get(code=mapping[decision])
    if ticket.status.code == "new":
        under_review = WorkflowStatus.objects.get(code="under-review")
        transition_ticket(ticket=ticket, to_status=under_review, actor=actor, request=request)
    transition_ticket(ticket=ticket, to_status=target, actor=actor, comment=reason, request=request)
    ticket.reviewed_by = actor
    ticket.save(update_fields=["reviewed_by", "updated_at"])
    return TicketReview.objects.create(ticket=ticket, reviewer=actor, decision=decision, reason=reason)


@transaction.atomic
def assign_ticket(*, ticket, actor, assigned_to, task_description, technical_instructions="", expected_output="", additional_notes="", deadline=None, request=None):
    if not can_assign_ticket(actor):
        raise PermissionDenied
    if not assigned_to.is_active:
        raise ValidationError("Tickets can only be assigned to active users.")
    TicketAssignment.objects.filter(ticket=ticket, is_active=True).update(is_active=False, ended_at=timezone.now())
    old_assignee = ticket.current_assignee
    assignment = TicketAssignment.objects.create(
        ticket=ticket, assigned_to=assigned_to, assigned_by=actor, task_description=task_description,
        technical_instructions=technical_instructions, expected_output=expected_output,
        additional_notes=additional_notes, deadline=deadline,
    )
    ticket.current_assignee = assigned_to
    ticket.deadline = deadline
    ticket.save(update_fields=["current_assignee", "deadline", "updated_at"])
    if ticket.status.code == "validated":
        transition_ticket(ticket=ticket, to_status=WorkflowStatus.objects.get(code="assigned"), actor=actor, request=request)
    record_history(
        ticket, actor, "TICKET_ASSIGNED", f"Assigned to {assigned_to.full_name}", request,
        previous={"assignee": old_assignee.full_name if old_assignee else None},
        new={"assignee": assigned_to.full_name, "deadline": deadline.isoformat() if deadline else None},
    )
    from communications.models import Notification
    from communications.services import notify_users
    notify_users(
        [assigned_to], kind=Notification.Kind.ASSIGNED,
        verb=f"assigned {ticket.ticket_number} to you", actor=actor, ticket=ticket,
    )
    return assignment


@transaction.atomic
def verify_ticket(*, ticket, actor, decision, reason="", request=None):
    if not can_verify_ticket(actor, ticket) or ticket.status.code != "ready-for-verification":
        raise PermissionDenied
    if decision == TicketVerification.Decision.FAILED and not reason.strip():
        raise ValidationError("Explain what problem still exists so IT can continue the work.")
    verification = TicketVerification.objects.create(ticket=ticket, verified_by=actor, decision=decision, reason=reason)
    target_code = "completed" if decision == TicketVerification.Decision.VERIFIED else "verification-failed"
    target = WorkflowStatus.objects.get(code=target_code)
    transition_ticket(ticket=ticket, to_status=target, actor=actor, comment=reason, request=request)
    if decision == TicketVerification.Decision.FAILED:
        transition_ticket(ticket=ticket, to_status=WorkflowStatus.objects.get(code="reopened"), actor=actor, request=request)
    record_history(ticket, actor, "VERIFICATION_SUBMITTED", verification.get_decision_display(), request, new={"decision": decision, "reason": reason})
    from communications.models import Notification
    from communications.services import notify_users
    notify_users(
        [ticket.current_assignee, ticket.reviewed_by],
        kind=Notification.Kind.REOPENED if decision == TicketVerification.Decision.FAILED else Notification.Kind.VERIFICATION,
        verb=f"submitted verification for {ticket.ticket_number}: {verification.get_decision_display()}",
        actor=actor, ticket=ticket,
    )
    return verification


@transaction.atomic
def technical_verify_ticket(*, ticket, actor, decision, reason="", request=None):
    if not can_technical_verify_ticket(actor, ticket) or ticket.status.code != "ready-for-it-verification":
        raise PermissionDenied
    if decision == TicketTechnicalVerification.Decision.RETURNED and not reason.strip():
        raise ValidationError("Explain what the responsible person must correct before resubmitting.")
    verification = TicketTechnicalVerification.objects.create(
        ticket=ticket, verified_by=actor, decision=decision, reason=reason,
    )
    target_code = "ready-for-verification" if decision == TicketTechnicalVerification.Decision.APPROVED else "in-progress"
    transition_ticket(
        ticket=ticket, to_status=WorkflowStatus.objects.get(code=target_code), actor=actor,
        comment=reason or "Technical work reviewed and approved by the Senior IT Consultant.", request=request,
    )
    record_history(
        ticket, actor, "TECHNICAL_VERIFICATION", verification.get_decision_display(), request,
        new={"decision": decision, "reason": reason},
    )
    return verification
