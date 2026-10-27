from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .access import can_assign_ticket, can_review_ticket, can_technical_verify_ticket, can_verify_ticket, is_ticket_intake_user
from .models import (
    StatusTransition, Ticket, TicketAssignment, TicketHistory, TicketNumberSequence,
    TicketIntakeRoute, TicketRecipient, TicketReview, TicketTechnicalVerification, TicketVerification, WorkflowStatus,
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
    requester = user
    division = form.requesting_division
    request_type = form.cleaned_data["request_type"]
    direct_recipients = list(form.cleaned_data.get("recipients", []))
    assigned_to = form.cleaned_data.get("assign_to") if request_type == Ticket.RequestType.IT else None
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
    ticket.request_type = request_type
    if assigned_to:
        ticket.current_assignee = assigned_to
        ticket.reviewed_by = user
    ticket.save()
    ticket.watchers.add(requester, user)
    if request_type == Ticket.RequestType.DIRECT:
        TicketRecipient.objects.bulk_create([
            TicketRecipient(ticket=ticket, user=recipient)
            for recipient in direct_recipients
        ])
    intake_route = None
    if request_type == Ticket.RequestType.IT:
        intake_route = TicketIntakeRoute.objects.filter(
            division__code="IT",
        ).prefetch_related("selected_users").first()
    if request_type == Ticket.RequestType.IT and not assigned_to and intake_route:
        intake_users = list(intake_route.selected_users.filter(is_active=True))
        if intake_users:
            ticket.watchers.add(*intake_users)
    for uploaded in files:
        ticket.attachments.create(
            file=uploaded, original_name=uploaded.name, content_type=getattr(uploaded, "content_type", ""),
            file_size=uploaded.size, uploaded_by=user,
        )
    description = f"Ticket created by {user.full_name}"
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
    if request_type == Ticket.RequestType.DIRECT:
        notify_users(
            direct_recipients, kind=Notification.Kind.TICKET_CREATED,
            verb=f"requested your approval for {ticket.ticket_number}", actor=user, ticket=ticket,
        )
    elif assigned_to:
        notify_users(
            [assigned_to], kind=Notification.Kind.ASSIGNED,
            verb=f"assigned {ticket.ticket_number} to you", actor=user, ticket=ticket,
        )
    else:
        if intake_route:
            intake_users = list(intake_route.selected_users.filter(is_active=True))
        else:
            intake_users = User.objects.filter(
                is_active=True, role__is_division_director=True,
            ).filter(
                Q(division__code="IT") | Q(division__name__iexact="IT"),
            )
        if not intake_users:
            intake_users = User.objects.filter(is_active=True).filter(
                Q(is_superuser=True) | Q(role__code__in=["super-admin", "senior-it-consultant"]),
            )
        notify_users(intake_users, kind=Notification.Kind.TICKET_CREATED, verb=f"created {ticket.ticket_number}", actor=user, ticket=ticket)
    return ticket


@transaction.atomic
def respond_to_direct_request(*, ticket, actor, action, deadline=None, reason="", note="", request=None):
    if ticket.request_type != Ticket.RequestType.DIRECT:
        raise PermissionDenied("This action is only available for direct requests.")
    recipient = TicketRecipient.objects.select_for_update().filter(
        ticket=ticket, user=actor,
    ).first()
    if not recipient:
        raise PermissionDenied("Only selected recipients can respond to this request.")
    if recipient.decision in {TicketRecipient.Decision.APPROVED, TicketRecipient.Decision.DECLINED}:
        raise ValidationError("You have already submitted your final decision.")

    responses = list(TicketRecipient.objects.select_for_update().filter(ticket=ticket))
    if any(item.decision == TicketRecipient.Decision.DECLINED for item in responses) or all(
        item.decision == TicketRecipient.Decision.APPROVED for item in responses
    ):
        raise ValidationError("This direct request has already reached a final decision.")
    if action not in {
        "APPROVE", "DECLINE", "DISCUSS", "MEETING",
    }:
        raise ValidationError("Choose a valid response.")
    if action == "APPROVE" and (not deadline or deadline <= timezone.now()):
        raise ValidationError("Choose a future deadline when approving.")
    if action == "DECLINE" and not reason.strip():
        raise ValidationError("A reason is required when declining.")

    decision_by_action = {
        "APPROVE": TicketRecipient.Decision.APPROVED,
        "DECLINE": TicketRecipient.Decision.DECLINED,
        "DISCUSS": TicketRecipient.Decision.DISCUSSION,
        "MEETING": TicketRecipient.Decision.MEETING,
    }
    recipient.decision = decision_by_action[action]
    recipient.deadline = deadline if action == "APPROVE" else None
    recipient.reason = reason.strip() if action == "DECLINE" else ""
    recipient.note = note.strip()
    recipient.responded_at = timezone.now()
    recipient.save(update_fields=["decision", "deadline", "reason", "note", "responded_at"])

    if action == "APPROVE":
        description = f"{actor.full_name} approved with a deadline of {deadline:%d %b %Y, %H:%M}"
    elif action == "DECLINE":
        description = f"{actor.full_name} declined: {reason.strip()}"
    elif action == "DISCUSS":
        description = f"{actor.full_name} requested a discussion"
    else:
        description = f"{actor.full_name} requested a meeting"
    record_history(
        ticket, actor, f"DIRECT_REQUEST_{action}", description, request,
        new={"decision": recipient.get_decision_display(), "deadline": deadline.isoformat() if deadline else None,
             "reason": recipient.reason, "note": recipient.note},
    )
    from communications.models import Notification
    from communications.services import notify_users
    notify_users(
        [ticket.requester, *(item.user for item in responses)],
        kind=Notification.Kind.STATUS, verb=f"responded to {ticket.ticket_number}: {description}",
        actor=actor, ticket=ticket,
    )
    return recipient


def _role_can_transition(user, transition):
    if user.is_super_admin:
        return True
    if not user.role_id:
        return False
    return transition.allowed_roles.filter(pk=user.role_id).exists()


def _require_it_ticket(ticket):
    if ticket.request_type != Ticket.RequestType.IT:
        raise PermissionDenied("IT workflow actions are not available for direct requests.")


@transaction.atomic
def transition_ticket(*, ticket, to_status, actor, comment="", request=None):
    _require_it_ticket(ticket)
    transition = StatusTransition.objects.filter(
        from_status=ticket.status, to_status=to_status, is_active=True
    ).prefetch_related("allowed_roles").first()
    execution_statuses = {
        "assigned", "in-progress", "blocked", "waiting-for-requester",
        "waiting-for-meeting", "reopened", "verification-failed",
    }
    assigned_worker = (
        ticket.current_assignee_id == actor.pk and ticket.status.code in execution_statuses
    )
    requester_verification_handoff = (
        assigned_worker and ticket.status.code == "in-progress"
        and to_status.code == "ready-for-verification"
    )
    verification_resume = (
        ticket.status.code == "verification-failed"
        and to_status.code == "in-progress"
        and assigned_worker
    )
    if ticket.status.code in execution_statuses and not assigned_worker:
        raise PermissionDenied("Only the assigned person can update this task's status.")
    intake_transition = is_ticket_intake_user(actor) and (
        (ticket.status.code == "new" and to_status.code == "under-review")
        or (ticket.status.code == "under-review" and to_status.code in {
            "validated", "invalid", "need-more-information", "completed",
        })
        or (ticket.status.code == "validated" and to_status.code == "assigned")
    )
    if (not transition and not requester_verification_handoff and not verification_resume) or (
        transition and not _role_can_transition(actor, transition)
        and not assigned_worker and not intake_transition and not verification_resume
    ):
        raise PermissionDenied("You are not permitted to make this status change.")
    if actor.role_code == "officer" and ticket.status.code in execution_statuses and ticket.current_assignee_id != actor.pk:
        raise PermissionDenied("Only the assigned IT Officer can update this task.")
    if transition and transition.requires_comment and not comment.strip():
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
    _require_it_ticket(ticket)
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
    _require_it_ticket(ticket)
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
def extend_assignment_deadline(*, ticket, actor, new_deadline, request=None):
    _require_it_ticket(ticket)
    assignment = TicketAssignment.objects.select_for_update().filter(
        ticket=ticket, is_active=True,
    ).select_related("assigned_by", "assigned_to").first()
    if not assignment or assignment.assigned_by_id != actor.pk:
        raise PermissionDenied("Only the person who assigned this task can change its deadline.")
    if not ticket.is_overdue:
        raise ValidationError("The deadline can only be changed after it has passed.")
    if new_deadline <= timezone.now():
        raise ValidationError("Choose a new deadline in the future.")

    previous_deadline = ticket.deadline
    assignment.deadline = new_deadline
    assignment.save(update_fields=["deadline"])
    ticket.deadline = new_deadline
    ticket.save(update_fields=["deadline", "updated_at"])
    record_history(
        ticket, actor, "DEADLINE_EXTENDED", f"Deadline changed to {new_deadline:%d %b %Y, %H:%M}", request,
        previous={"deadline": previous_deadline.isoformat() if previous_deadline else None},
        new={"deadline": new_deadline.isoformat()},
    )
    from communications.models import Notification
    from communications.services import notify_users
    notify_users(
        [assignment.assigned_to], kind=Notification.Kind.STATUS,
        verb=f"changed the deadline for {ticket.ticket_number} to {new_deadline:%d %b %Y, %H:%M}",
        actor=actor, ticket=ticket,
    )
    return assignment


@transaction.atomic
def verify_ticket(*, ticket, actor, decision, reason="", request=None):
    _require_it_ticket(ticket)
    if not can_verify_ticket(actor, ticket) or ticket.status.code != "ready-for-verification":
        raise PermissionDenied
    if decision == TicketVerification.Decision.FAILED and not reason.strip():
        raise ValidationError("Explain what problem still exists so IT can continue the work.")
    verification = TicketVerification.objects.create(ticket=ticket, verified_by=actor, decision=decision, reason=reason)
    target_code = "completed" if decision == TicketVerification.Decision.VERIFIED else "verification-failed"
    target = WorkflowStatus.objects.get(code=target_code)
    transition_ticket(ticket=ticket, to_status=target, actor=actor, comment=reason, request=request)
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
    _require_it_ticket(ticket)
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
