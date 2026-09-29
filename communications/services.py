from django.db import transaction
from django.utils import timezone

from .models import Meeting, MeetingHistory, MeetingParticipant, MeetingSequence, Notification


def notify_users(users, *, kind, verb, actor=None, ticket=None, meeting=None, approval_request=None):
    seen = set()
    notifications = []
    for user in users:
        if not user or not user.is_active or user.pk == getattr(actor, "pk", None) or user.pk in seen:
            continue
        seen.add(user.pk)
        notifications.append(Notification(
            recipient=user, actor=actor, kind=kind, verb=verb, ticket=ticket, meeting=meeting,
            approval_request=approval_request,
        ))
    if notifications:
        Notification.objects.bulk_create(notifications)
    return notifications


@transaction.atomic
def create_meeting(*, form, user):
    year = timezone.localdate().year
    sequence, _ = MeetingSequence.objects.select_for_update().get_or_create(year=year)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    meeting = form.save(commit=False)
    meeting.reference = f"MTG-{year}-{sequence.last_number:04d}"
    meeting.requested_by = user
    meeting.organizer = user
    meeting.save()
    participants = list(form.cleaned_data["participants"])
    if user not in participants:
        participants.append(user)
    MeetingParticipant.objects.bulk_create([
        MeetingParticipant(
            meeting=meeting, user=participant,
            response=MeetingParticipant.Response.ACCEPTED if participant == user else MeetingParticipant.Response.PENDING,
            responded_at=timezone.now() if participant == user else None,
        ) for participant in participants
    ])
    MeetingHistory.objects.create(meeting=meeting, actor=user, action="REQUESTED", description=f"Meeting requested by {user.full_name}")
    notify_users(
        participants, kind=Notification.Kind.MEETING,
        verb=f"invited you to {meeting.title}", actor=user, meeting=meeting,
    )
    return meeting


def record_meeting_action(meeting, actor, action, description):
    return MeetingHistory.objects.create(meeting=meeting, actor=actor, action=action, description=description)
